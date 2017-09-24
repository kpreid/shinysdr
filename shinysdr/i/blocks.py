# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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
GNU Radio flowgraph blocks for use by ShinySDR.

This module is not an external API and not guaranteed to have a stable
interface.
"""

from __future__ import absolute_import, division, unicode_literals

import array
import math
import os

from zope.interface import Interface, implementer

from gnuradio import gr
from gnuradio import blocks
from gnuradio.fft import fft_vfc, fft_vcc, window as windows

from shinysdr.filters import make_resampler
from shinysdr.math import to_dB
from shinysdr.signals import SignalType
from shinysdr.types import BulkDataT, RangeT
from shinysdr import units
from shinysdr.values import ExportedState, LooseCell, StreamCell, exported_value, setter


class RecursiveLockBlockMixin(object):
    """
    For top blocks needing recursive locking and/or a notification to restart parts.
    """
    __lock_count = 0
    
    def _recursive_lock_hook(self):
        """To override."""
    
    def _recursive_lock(self):
        # gnuradio uses a non-recursive lock, which is not adequate for our purposes because we want to make changes locally or globally without worrying about having a single lock entry point
        if self.__lock_count == 0:
            self.lock()
            self._recursive_lock_hook()
        self.__lock_count += 1

    def _recursive_unlock(self):
        self.__lock_count -= 1
        if self.__lock_count == 0:
            self.unlock()


class Context(object):
    """
    Client facet for RecursiveLockBlockMixin.
    """
    def __init__(self, top):
        self.__top = top
    
    def lock(self):
        self.__top._recursive_lock()
    
    def unlock(self):
        self.__top._recursive_unlock()


# TODO: This function is used by plugins. Put it in an appropriate module.
def make_sink_to_process_stdin(process, itemsize=gr.sizeof_char):
    """Given a twisted Process, connect a sink to its stdin."""
    fd_owned_by_twisted = process.pipes[0].fileno()  # TODO: More public way to do this?
    fd_owned_by_sink = os.dup(fd_owned_by_twisted)
    process.closeStdin()
    return blocks.file_descriptor_sink(itemsize, fd_owned_by_sink)


class _NoContext(object):
    def lock(self):
        pass
    
    def unlock(self):
        pass


class MessageDistributorSink(gr.hier_block2):
    """Like gnuradio.blocks.message_sink, but copies its messages to a dynamic set of queues and saves the most recent item.
    
    Never blocks."""
    def __init__(self, itemsize, context, migrate=None, notify=None):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, itemsize),
            gr.io_signature(0, 0, 0),
        )
        self.__itemsize = itemsize
        self.__context = _NoContext()
        self.__peek = blocks.probe_signal_vb(itemsize)
        self.__subscriptions = {}
        self.__notify = None
        
        self.connect(self, self.__peek)
        
        if migrate is not None:
            assert isinstance(migrate, MessageDistributorSink)  # sanity check
            for queue in migrate.__subscriptions.keys():
                migrate.unsubscribe(queue)
                self.subscribe(queue)
        
        # set now, not earlier, so as not to trigger anything while migrating
        self.__context = context
        self.__notify = notify

    def get(self):
        # probe_signal gives us vector of 0..255 whereas queue messages give str. Reformat to be consistent with messages.
        return array.array('B', self.__peek.level()).tostring()
    
    def get_subscription_count(self):
        return len(self.__subscriptions)
    
    def subscribe(self, queue):
        assert queue not in self.__subscriptions
        sink = blocks.message_sink(self.__itemsize, queue, True)
        self.__subscriptions[queue] = sink
        try:
            self.__context.lock()
            self.connect(self, sink)
        finally:
            self.__context.unlock()
        if self.__notify:
            self.__notify()
    
    def unsubscribe(self, queue):
        sink = self.__subscriptions[queue]
        del self.__subscriptions[queue]
        try:
            self.__context.lock()
            self.disconnect(self, sink)
        finally:
            self.__context.unlock()
        if self.__notify:
            self.__notify()


_maximum_fft_rate = 500


class _OverlappedStreamToVector(gr.hier_block2):
    """
    Block which is like gnuradio.blocks.stream_to_vector, but generates vectors which are overlapping segments of the input, multiplying the overall number of samples by a specified factor.
    """
    
    # A disadvantage of our implementation strategy is that, because blocks.interleave does, we will always generate output vectors in bursts (of size = factor) rather than smoothly.
    
    def __init__(self, size, factor, itemsize=gr.sizeof_gr_complex):
        """
        size: (int) vector size (FFT size) of next block
        factor: (int) output will have this many more samples than input
        
        If size is not divisible by factor, then the output will necessarily have jitter.
        """
        size = int(size)
        factor = int(factor)
        # assert size % factor == 0
        offset = size // factor

        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, itemsize),
            gr.io_signature(1, 1, itemsize * size),
        )
        
        if factor == 1:
            # No duplication needed; simplify flowgraph
            self.connect(self, blocks.stream_to_vector(itemsize, size), self)
        else:
            interleave = blocks.interleave(itemsize * size)
            self.connect(interleave, self)
        
            for i in xrange(0, factor):
                self.connect(
                    self,
                    blocks.delay(itemsize, (factor - 1 - i) * offset),
                    blocks.stream_to_vector(itemsize, size),
                    (interleave, i))


class IMonitor(Interface):
    """Marker interface for client UI.
    
    Note that this is also implemented on the client for the local audio monitor.
    """


@implementer(IMonitor)
class MonitorSink(gr.hier_block2, ExportedState):
    """Convenience wrapper around all the bits and pieces to display the signal spectrum to the client.
    
    The units of the FFT output are dB power/Hz (power spectral density) relative to unit amplitude (i.e. dBFS assuming the source clips at +/-1). Note this is different from the standard logpwrfft result of power _per bin_, which would be undesirably dependent on the sample rate and bin size.
    """
    def __init__(self,
            signal_type=None,
            enable_scope=False,
            freq_resolution=4096,
            time_length=2048,
            frame_rate=30.0,
            input_center_freq=0.0,
            paused=False,
            context=None):
        assert isinstance(signal_type, SignalType)
        assert context is not None
        
        itemsize = signal_type.get_itemsize()
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, itemsize),
            gr.io_signature(0, 0, 0),
        )
        
        # constant parameters
        self.__power_offset = 40  # TODO autoset or controllable
        self.__itemsize = itemsize
        self.__context = context
        self.__enable_scope = enable_scope
        
        # settable parameters
        self.__signal_type = signal_type
        self.__freq_resolution = int(freq_resolution)
        self.__time_length = int(time_length)
        self.__frame_rate = float(frame_rate)
        self.__input_center_freq = float(input_center_freq)
        self.__paused = bool(paused)
        
        self.__interested_cell = LooseCell(type=bool, value=False, writable=False, persists=False)
        
        # stuff created by __do_connect
        self.__gate = None
        self.__fft_sink = None
        self.__scope_sink = None
        self.__frame_dec = None
        self.__frame_rate_to_decimation_conversion = 0.0
        
        self.__do_connect()
    
    def state_def(self):
        for d in super(MonitorSink, self).state_def():
            yield d
        # TODO make this possible to be decorator style
        yield 'fft', StreamCell(self, 'fft',
            type=BulkDataT(array_format='b', info_format='dff'),
            label='Spectrum')
        yield 'scope', StreamCell(self, 'scope',
            type=BulkDataT(array_format='f', info_format='d'),
            label='Scope')

    def __do_connect(self):
        itemsize = self.__itemsize
        
        if self.__signal_type.is_analytic():
            input_length = self.__freq_resolution
            output_length = self.__freq_resolution
            self.__after_fft = None
        else:
            # use vector_to_streams to cut the output in half and discard the redundant part
            input_length = self.__freq_resolution * 2
            output_length = self.__freq_resolution
            self.__after_fft = blocks.vector_to_streams(itemsize=output_length * gr.sizeof_float, nstreams=2)
        
        sample_rate = self.__signal_type.get_sample_rate()
        overlap_factor = int(math.ceil(_maximum_fft_rate * input_length / sample_rate))
        # sanity limit -- OverlapGimmick is not free
        overlap_factor = min(16, overlap_factor)
        
        self.__frame_rate_to_decimation_conversion = sample_rate * overlap_factor / input_length
        
        self.__gate = blocks.copy(itemsize)
        self.__gate.set_enabled(not self.__paused)
        
        overlapper = _OverlappedStreamToVector(
            size=input_length,
            factor=overlap_factor,
            itemsize=itemsize)
        
        self.__frame_dec = blocks.keep_one_in_n(
            itemsize=itemsize * input_length,
            n=int(round(self.__frame_rate_to_decimation_conversion / self.__frame_rate)))
        
        # the actual FFT logic, which is similar to GR's logpwrfft_c
        window = windows.blackmanharris(input_length)
        window_power = sum(x * x for x in window)
        # TODO: use fft_vfc when applicable
        fft_block = (fft_vcc if itemsize == gr.sizeof_gr_complex else fft_vfc)(
            fft_size=input_length,
            forward=True,
            window=window)
        mag_squared = blocks.complex_to_mag_squared(input_length)
        logarithmizer = blocks.nlog10_ff(
            n=10,  # the "deci" in "decibel"
            vlen=input_length,
            k=(
                -to_dB(window_power) +  # compensate for window
                -to_dB(sample_rate) +  # convert from power-per-sample to power-per-Hz
                self.__power_offset  # offset for packing into bytes
            ))
        
        # It would make slightly more sense to use unsigned chars, but blocks.float_to_uchar does not support vlen.
        self.__fft_converter = blocks.float_to_char(vlen=self.__freq_resolution, scale=1.0)
        
        self.__fft_sink = MessageDistributorSink(
            itemsize=output_length * gr.sizeof_char,
            context=self.__context,
            migrate=self.__fft_sink,
            notify=self.__update_interested)
    
        self.__scope_sink = MessageDistributorSink(
            itemsize=self.__time_length * gr.sizeof_gr_complex,
            context=self.__context,
            migrate=self.__scope_sink,
            notify=self.__update_interested)
        scope_chunker = blocks.stream_to_vector_decimator(
            item_size=gr.sizeof_gr_complex,
            sample_rate=sample_rate,
            vec_rate=self.__frame_rate,  # TODO doesn't need to be coupled
            vec_len=self.__time_length)

        # connect everything
        self.__context.lock()
        try:
            self.disconnect_all()
            self.connect(
                self,
                self.__gate,
                overlapper,
                self.__frame_dec,
                fft_block,
                mag_squared,
                logarithmizer)
            if self.__after_fft is not None:
                self.connect(logarithmizer, self.__after_fft)
                self.connect(self.__after_fft, self.__fft_converter, self.__fft_sink)
                self.connect((self.__after_fft, 1), blocks.null_sink(gr.sizeof_float * self.__freq_resolution))
            else:
                self.connect(logarithmizer, self.__fft_converter, self.__fft_sink)
            if self.__enable_scope:
                self.connect(
                    self.__gate,
                    scope_chunker,
                    self.__scope_sink)
        finally:
            self.__context.unlock()
    
    # non-exported
    def get_interested_cell(self):
        return self.__interested_cell
    
    def __update_interested(self):
        self.__interested_cell.set_internal(not self.__paused and (
            self.__fft_sink.get_subscription_count() > 0 or
            self.__scope_sink.get_subscription_count() > 0))
    
    @exported_value(type=SignalType, changes='explicit')
    def get_signal_type(self):
        return self.__signal_type
    
    # non-exported
    def set_signal_type(self, value):
        # TODO: don't rebuild if the rate did not change and the spectrum-sidedness of the type did not change
        assert self.__signal_type.compatible_items(value)
        self.__signal_type = value
        self.__do_connect()
        self.state_changed('signal_type')
    
    # non-exported
    def set_input_center_freq(self, value):
        self.__input_center_freq = float(value) 
    
    @exported_value(
        type=RangeT([(2, 4096)], logarithmic=True, integer=True),
        changes='this_setter',
        label='Resolution',
        description='Frequency domain resolution; number of FFT bins.')
    def get_freq_resolution(self):
        return self.__freq_resolution

    @setter
    def set_freq_resolution(self, freq_resolution):
        self.__freq_resolution = freq_resolution
        self.__do_connect()

    @exported_value(type=RangeT([(1, 4096)], logarithmic=True, integer=True), changes='this_setter')
    def get_time_length(self):
        return self.__time_length

    @setter
    def set_time_length(self, value):
        self.__time_length = value
        self.__do_connect()

    @exported_value(
        type=RangeT([(1, _maximum_fft_rate)],
            unit=units.Hz,
            logarithmic=True,
            integer=False),
        changes='this_setter',
        label='Rate',
        description='Number of FFT frames per second.')
    def get_frame_rate(self):
        return self.__frame_rate

    @setter
    def set_frame_rate(self, value):
        n = int(round(self.__frame_rate_to_decimation_conversion / value))
        self.__frame_dec.set_n(n)
        # derive effective value by calculating inverse
        self.__frame_rate = self.__frame_rate_to_decimation_conversion / n
    
    @exported_value(type=bool, changes='this_setter', label='Pause')
    def get_paused(self):
        return self.__paused

    @setter
    def set_paused(self, value):
        self.__paused = value
        self.__gate.set_enabled(not value)
        self.__update_interested()

    # exported via state_def
    def get_fft_info(self):
        return (self.__input_center_freq, self.__signal_type.get_sample_rate(), self.__power_offset)
    
    def get_fft_distributor(self):
        return self.__fft_sink
    
    # exported via state_def
    def get_scope_info(self):
        return (self.__signal_type.get_sample_rate(),)
    
    def get_scope_distributor(self):
        return self.__scope_sink


# this is in shinysdr.i.blocks rather than shinysdr.filters because I don't consider it public (yet?)
class VectorResampler(gr.hier_block2):
    def __init__(self, in_rate, out_rate, vlen, complex=False):
        # pylint: disable=redefined-builtin
        vitemsize = gr.sizeof_gr_complex if complex else gr.sizeof_float
        itemsize = vitemsize * vlen
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, itemsize),
            gr.io_signature(1, 1, itemsize))

        if vlen == 1:
            self.connect(self, make_resampler(in_rate, out_rate, complex=complex), self)
        else:
            splitter = blocks.vector_to_streams(vitemsize, vlen)
            joiner = blocks.streams_to_vector(vitemsize, vlen)
            self.connect(self, splitter)
            for ch in xrange(vlen):
                self.connect(
                    (splitter, ch),
                    make_resampler(in_rate, out_rate, complex=complex),
                    (joiner, ch))
            self.connect(joiner, self)
