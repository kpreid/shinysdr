# Copyright 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division

from twisted.python import log

from gnuradio import audio
from gnuradio import blocks
from gnuradio import gr

from shinysdr.filters import make_resampler
from shinysdr.types import EnumT


__all__ = []  # appended later


CLIENT_AUDIO_DEVICE = 'client'


class AudioManager(object):
    """
    Manage connecting audio sources (i.e. demodulators) to audio destinations (local devices and network clients represented as message queues).
    
    (This cannot be a hierarchical block, because hierarchical blocks cannot currently have variable numbers of ports.)
    """
    # TODO: This class needs a better name.
    
    def __init__(self, graph, audio_config, stereo=True):
        # for key, audio_device in audio_devices.iteritems():
        #     if key == CLIENT_AUDIO_DEVICE:
        #         raise ValueError('The name %r for an audio device is reserved' % (key,))
        #     if not audio_device.can_transmit():
        #         raise ValueError('Audio device %r is not an output' % (key,))
        if audio_config is not None:
            # quick kludge placeholder -- currently a Device-device can't be stereo so we have a placeholder thing
            # pylint: disable=unpacking-non-sequence
            audio_device_name, audio_sample_rate = audio_config
            audio_devices = {'server': (audio_sample_rate, audio.sink(audio_sample_rate, audio_device_name, False))}
        else:
            audio_devices = {}
        
        self.__audio_devices = audio_devices
        audio_destination_dict = {key: 'Server' or key for key, device in audio_devices.iteritems()}  # temp name till we have proper device objects
        audio_destination_dict[CLIENT_AUDIO_DEVICE] = 'Client'  # TODO reconsider name
        self.__audio_destination_type = EnumT(audio_destination_dict)
        self.__audio_channels = 2 if stereo else 1
        self.__audio_queue_sinks = {}
        self.__audio_buses = {key: BusPlumber(graph, self.__audio_channels) for key in audio_destination_dict}
    
    def get_destination_type(self):
        """
        Return a type object for the available destinations
        """
        return self.__audio_destination_type
    
    def get_default_destination(self):
        return CLIENT_AUDIO_DEVICE

    def add_audio_queue(self, queue, queue_rate):
        """Caller must reconnect flow graph."""
        
        # TODO: place limit on maximum requested sample rate
        self.__audio_queue_sinks[queue] = (queue_rate,
            AudioQueueSink(channels=self.__audio_channels, queue=queue))
    
    def remove_audio_queue(self, queue):
        """Caller must reconnect flow graph."""
        
        del self.__audio_queue_sinks[queue]
    
    def get_channels(self):
        return self.__audio_channels
    
    def validate_destination(self, destination):
        return destination in self.__audio_buses
    
    def reconnecting(self):
        return ReconnectSession(self.__audio_buses, self.__audio_devices, self.__audio_queue_sinks)

    # @exported_value()
    def get_audio_bus_rate(self):
        # TODO: A debugging aid that used to be exported. Make this exported again (not necessarily from this object once we have a proper "system status" view
        return [b.get_current_rate() for b in self.__audio_buses.itervalues()]
    

__all__.append('AudioManager')


class ReconnectSession(object):
    def __init__(self, buses, devices, queue_sinks):
        self.__buses = buses
        self.__devices = devices
        self.__queue_sinks = queue_sinks
        self.__bus_inputs = {bus: [] for bus in buses}
        self.__fallback_bus = buses.keys()[0]
    
    def input(self, block, rate, destination):
        if destination not in self.__bus_inputs:
            log.msg('AudioManager: Invalid audio destination %r' % (destination,))
            destination = self.__fallback_bus
        self.__bus_inputs[destination].append((rate, block))
    
    def finish_bus_connections(self):
        has_useful = False
        for key, bus in self.__buses.iteritems():
            inputs = self.__bus_inputs[key]
            if key == CLIENT_AUDIO_DEVICE:
                outputs = self.__queue_sinks.itervalues()
                noutputs = len(self.__queue_sinks)
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
    Takes an arbitrary number of blocks' float outputs (bus inputs), sums and resamples them, and connects them to an arbitrary number of blocks' inputs (bus outputs).
    
    If there are no outputs, the inputs will go to a null sink. If there are no inputs, the outputs will remain unconnected.
    
    (This cannot be a hierarchical block, because hierarchical blocks cannot currently have variable numbers of ports.)
    """
    def __init__(self, graph, nchannels):
        self.__graph = graph
        self.__channels = xrange(nchannels)
        self.__bus_rate = 0.0
        # TODO: Stop using a cache of resamplers unless we use them in exactly-corresponding fashion; instead use a cache of resampling _filter taps_.
        self.__resampler_cache = {}
    
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
            self.__resampler_cache.clear()
        
        # recreated each time because reusing an add_ff w/ different
        # input counts fails; TODO: report/fix bug
        bus_sums = [blocks.add_ff() for _ in self.__channels]
        
        in_index = 0
        for in_rate, in_block in inputs:
            if in_rate == self.__bus_rate:
                for ch in self.__channels:
                    self.__graph.connect(
                        (in_block, ch),
                        (bus_sums[ch], in_index))
            else:
                for ch in self.__channels:
                    self.__graph.connect(
                        (in_block, ch),
                        # TODO pool these resamplers
                        make_resampler(in_rate, self.__bus_rate),
                        (bus_sums[ch], in_index))
            in_index += 1
        
        if in_index > 0:
            # connect output only if there is at least one input
            if len(outputs) > 0:
                used_resamplers = set()
                for out_rate, out_block in outputs:
                    if out_rate == self.__bus_rate:
                        for ch in self.__channels:
                            self.__graph.connect(bus_sums[ch], (out_block, ch))
                    else:
                        if out_rate not in self.__resampler_cache:
                            # Moderately expensive due to the internals using optfir
                            log.msg('Constructing resampler for audio rate %i' % out_rate)
                            self.__resampler_cache[out_rate] = tuple(
                                make_resampler(self.__bus_rate, out_rate)
                                for _ in self.__channels)
                        resamplers = self.__resampler_cache[out_rate]
                        used_resamplers.add(resamplers)
                        for ch in self.__channels:
                            self.__graph.connect(resamplers[ch], (out_block, ch))
                for resamplers in used_resamplers:
                    for ch in self.__channels:
                        self.__graph.connect(bus_sums[ch], resamplers[ch])
            else:
                # gnuradio requires at least one connected output
                for ch in self.__channels:
                    self.__graph.connect(bus_sums[ch], blocks.null_sink(gr.sizeof_float))


class AudioQueueSink(gr.hier_block2):
    def __init__(self, channels, queue):
        gr.hier_block2.__init__(
            self, 'ShinySDR AudioQueueSink',
            gr.io_signature(channels, channels, gr.sizeof_float),
            gr.io_signature(0, 0, 0),
        )
        sink = blocks.message_sink(
            gr.sizeof_float * channels,
            queue,
            True)
        if channels == 1:
            self.connect((self, 0), sink)
        else:
            interleaver = blocks.streams_to_vector(gr.sizeof_float, channels)
            for ch in xrange(channels):
                self.connect((self, ch), (interleaver, ch))
            self.connect(interleaver, sink)
