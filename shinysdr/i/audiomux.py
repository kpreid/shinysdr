# Copyright 2015, 2016, 2018 Kevin Reid and the ShinySDR contributors
#
# This file is part of ShinySDR.
# 
# ShinySDR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# ShinySDR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

"""
GR blocks and such supporting receiver audio delivery.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import six

from twisted.internet import reactor as the_reactor
from twisted.logger import Logger

from gnuradio import blocks
from gnuradio import gr
import numpy

from shinysdr.i.blocks import ReactorSink, VectorResampler
from shinysdr.types import EnumT

try:
    # pylint: disable=ungrouped-imports
    from gnuradio import audio as gr_audio
except ImportError:
    # It is possible to have a GNU Radio compiled without gr-audio, so we want to be able to proceed without it. Server audio mode will break inelegantly.
    audio = 'UNAVAILABLE'


__all__ = []  # appended later


CLIENT_AUDIO_DEVICE = 'client'


class AudioManager(object):
    """
    Manage connecting audio sources (i.e. demodulators) to audio destinations (local devices and network clients represented as functions that accept binary buffers of samples).
    
    (This cannot be a hierarchical block, because hierarchical blocks cannot currently have variable numbers of ports.)
    """
    # TODO: This class needs a better name.
    
    __logger = Logger()
    
    def __init__(self, graph, audio_config, stereo=True):
        # for key, audio_device in six.iteritems(audio_devices):
        #     if key == CLIENT_AUDIO_DEVICE:
        #         raise ValueError('The name %r for an audio device is reserved' % (key,))
        #     if not audio_device.can_transmit():
        #         raise ValueError('Audio device %r is not an output' % (key,))
        if audio_config is not None:
            # quick kludge placeholder -- currently a Device-device can't be stereo so we have a placeholder thing
            # pylint: disable=unpacking-non-sequence
            audio_device_name, audio_sample_rate = audio_config
            audio_devices = {
                'server': (audio_sample_rate, VectorAudioSink(
                    audio_sample_rate, audio_device_name, channels=(2 if stereo else 1), ok_to_block=False))}
        else:
            audio_devices = {}
        
        self.__audio_devices = audio_devices
        audio_destination_dict = {key: 'Server' or key for key, device in six.iteritems(audio_devices)}  # temp name till we have proper device objects
        audio_destination_dict[CLIENT_AUDIO_DEVICE] = 'Client'  # TODO reconsider name
        self.__audio_destination_type = EnumT(audio_destination_dict)
        self.__audio_channels = 2 if stereo else 1
        self.__audio_sinks = {}
        self.__audio_buses = {key: BusPlumber(graph, self.__audio_channels) for key in audio_destination_dict}
    
    def get_destination_type(self):
        """
        Return a type object for the available destinations
        """
        return self.__audio_destination_type
    
    def get_default_destination(self):
        return CLIENT_AUDIO_DEVICE

    def add_audio_callback(self, callback, sample_rate):
        """Caller must reconnect flow graph."""
        
        if not 1 <= sample_rate <= 192000:
            # TODO: This sanity check is also enforced in the UI entry point; arrange for a common definition of the limits
            raise ValueError('Sample rate out of range')
        self.__audio_sinks[callback] = (
            sample_rate,
            ReactorSink(
                numpy_type=numpy.dtype((numpy.float32, self.__audio_channels)),
                callback=lambda array: callback(array.tobytes()),
                reactor=the_reactor)
        )
    
    def remove_audio_callback(self, callback):
        """Caller must reconnect flow graph."""
        
        del self.__audio_sinks[callback]
    
    def get_channels(self):
        return self.__audio_channels
    
    def validate_destination(self, destination):
        return destination in self.__audio_buses
    
    def reconnecting(self):
        return ReconnectSession(self.__audio_buses, self.__audio_devices, self.__audio_sinks, self.__logger)

    # @exported_value()
    def get_audio_bus_rate(self):
        # TODO: A debugging aid that used to be exported. Make this exported again (not necessarily from this object once we have a proper "system status" view
        return [b.get_current_rate() for b in six.itervalues(self.__audio_buses)]
    

__all__.append('AudioManager')


class ReconnectSession(object):
    def __init__(self, buses, devices, audio_sinks, log):
        self.__buses = buses
        self.__devices = devices
        self.__audio_sinks = audio_sinks
        self.__log = log
        self.__bus_inputs = {bus: [] for bus in buses}
        self.__fallback_bus = list(buses.keys())[0]
    
    def input(self, block, rate, destination):
        if destination not in self.__bus_inputs:
            self.__log.error('Invalid audio destination {audio_destination!r}', audio_destination=destination)
            destination = self.__fallback_bus
        self.__bus_inputs[destination].append((rate, block))
    
    def finish_bus_connections(self):
        has_useful = False
        for key, bus in six.iteritems(self.__buses):
            inputs = self.__bus_inputs[key]
            if key == CLIENT_AUDIO_DEVICE:
                outputs = six.itervalues(self.__audio_sinks)
                noutputs = len(self.__audio_sinks)
            else:
                outputs = [self.__devices[key]]
                noutputs = 1
            if len(inputs) > 0 and noutputs > 0:
                has_useful = True
            bus.connect(
                inputs=inputs,
                outputs=outputs)
        return has_useful


class BusPlumber(object):
    """
    Takes an arbitrary number of blocks' float or pair-of-float (stereo) outputs (bus inputs), sums and resamples them, and connects them to an arbitrary number of blocks' inputs (bus outputs).
    
    If there are no outputs, the inputs will go to a null sink. If there are no inputs, the outputs will remain unconnected.
    
    (This cannot be a hierarchical block, because hierarchical blocks cannot currently have variable numbers of ports.)
    """
    def __init__(self, graph, nchannels):
        self.__graph = graph
        self.__nchannels = nchannels
        self.__channels = six.moves.range(nchannels)
        self.__bus_rate = 0.0
    
    def get_current_rate(self):
        return self.__bus_rate
    
    def connect(self, inputs, outputs):
        """
        Make all new connections (graph.disconnect_all() must have been done) between inputs and outputs.
        
        inputs and outputs must be iterables of (sample_rate, block) tuples.
        """
        inputs = list(inputs)
        outputs = list(outputs)
        
        # Determine bus rate.
        # The bus obviously does not need to be higher than the rate of any bus input, because that would be extraneous data. It also does not need to be higher than the rate of any bus output, because no output has use for the information.
        max_in_rate = max((rate for rate, _ in inputs)) if len(inputs) > 0 else 0.0
        max_out_rate = max((rate for rate, _ in outputs)) if len(outputs) > 0 else 0.0
        new_bus_rate = min(max_out_rate, max_in_rate)
        if new_bus_rate == 0.0:
            # There are either no inputs or no outputs. Use the other side's rate so we have a well-defined value.
            new_bus_rate = max(max_out_rate, max_in_rate)
        if new_bus_rate == 0.0:
            # There are both no inputs and no outputs. No point in not keeping the old rate (and its resampler cache).
            new_bus_rate = self.__bus_rate
        elif new_bus_rate != self.__bus_rate:
            self.__bus_rate = new_bus_rate
        
        # recreated each time because reusing an add_ff w/ different
        # input counts fails; TODO: report/fix bug
        bus_sum = blocks.add_ff(vlen=self.__nchannels)
        
        in_index = 0
        for in_rate, in_block in inputs:
            self.__connect_maybe_with_resampler(in_block, in_rate, self.__bus_rate, (bus_sum, in_index))
            in_index += 1
        
        if in_index > 0:
            # connect output only if there is at least one input
            if len(outputs) > 0:
                resampler_table = {}
                for out_rate, out_block in outputs:
                    self.__connect_maybe_with_resampler(bus_sum, self.__bus_rate, out_rate, out_block, resampler_table=resampler_table)
            else:
                # gnuradio requires at least one connected output
                self.__graph.connect(bus_sum, blocks.null_sink(gr.sizeof_float * self.__nchannels))
    
    def __connect_maybe_with_resampler(self, in_endpoint, in_rate, out_rate, out_endpoint, resampler_table=None):
        """Connect in_endpoint, a source of vectors of size self.__nchannels, to out_endpoint, inserting per-channel resamplers if needed.
        
        If resampler_table (a dict) is provided then it is used to record resamplers already created that can be shared. in_endpoint and in_rate are assumed to be the same."""
        if in_rate == out_rate:
            self.__graph.connect(in_endpoint, out_endpoint)
        else:
            if resampler_table is not None and out_rate in resampler_table:
                self.__graph.connect(resampler_table[out_rate], out_endpoint)
            else:
                resampler = VectorResampler(in_rate, out_rate, vlen=self.__nchannels)
                self.__graph.connect(in_endpoint, resampler, out_endpoint)
                if resampler_table is not None:
                    resampler_table[out_rate] = resampler


class VectorAudioSink(gr.hier_block2):
    """Like gnuradio.audio.sink, but takes vectors instead of multiple input ports."""
    def __init__(self, sample_rate, device_name, channels, ok_to_block=False):
        assert channels > 0
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float * channels),
            gr.io_signature(0, 0, 0))
        sink = gr_audio.sink(sample_rate, device_name, ok_to_block=ok_to_block)
        if channels > 1:
            splitter = blocks.vector_to_streams(gr.sizeof_float, channels)
            self.connect(self, splitter)
            for ch in six.moves.range(channels):
                self.connect((splitter, ch), (sink, ch))
        else:
            self.connect(self, sink)
