# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division

import math
import os

from zope.interface import Interface, implements

from gnuradio import gr
from gnuradio import blocks
from gnuradio.fft import logpwrfft

from shinysdr.math import to_dB
from shinysdr.signals import SignalType
from shinysdr.types import BulkDataType, Range
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
        return self.__peek.level()
    
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


class _OverlapGimmick(gr.hier_block2):
    """
    Pure flowgraph kludge to cause a logpwrfft block to perform overlapped FFTs.
    
    The more correct solution would be to replace stream_to_vector_decimator (used inside of logpwrfft) with a block which takes arbitrarily-spaced vector chunks of the input rather than chunking and then decimating in terms of whole chunks. The cost of doing this instead is more scheduling steps and more data copies.
    
    To adjust for the data rate, the logpwrfft block's sample rate parameter must be multiplied by the factor parameter of this block; or equivalently, the frame rate must be divided by it.
    """
    
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
            gr.io_signature(1, 1, itemsize),
        )
        
        if factor == 1:
            # No duplication needed; simplify flowgraph
            # GR refused to connect self to self, so insert a dummy block
            self.connect(self, blocks.copy(itemsize), self)
        else:
            interleave = blocks.interleave(itemsize * size)
            self.connect(
                interleave,
                blocks.vector_to_stream(itemsize, size),
                self)
        
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


class MonitorSink(gr.hier_block2, ExportedState):
    """Convenience wrapper around all the bits and pieces to display the signal spectrum to the client.
    
    The units of the FFT output are dB power/Hz (power spectral density) relative to unit amplitude (i.e. dBFS assuming the source clips at +/-1). Note this is different from the standard logpwrfft result of power _per bin_, which would be undesirably dependent on the sample rate and bin size.
    """
    implements(IMonitor)
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
        
        self.__interested_cell = LooseCell(key='interested', type=bool, value=False, writable=False, persists=False)
        
        # blocks
        self.__gate = None
        self.__fft_sink = None
        self.__scope_sink = None
        self.__scope_chunker = None
        self.__before_fft = None
        self.__logpwrfft = None
        self.__overlapper = None
        
        self.__rebuild()
        self.__connect()
    
    def state_def(self, callback):
        super(MonitorSink, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(StreamCell(self, 'fft',
            type=BulkDataType(array_format='b', info_format='dff'),
            label='Spectrum'))
        callback(StreamCell(self, 'scope',
            type=BulkDataType(array_format='f', info_format='d'),
            label='Scope'))

    def __rebuild(self):
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
        
        self.__gate = blocks.copy(gr.sizeof_gr_complex)
        self.__gate.set_enabled(not self.__paused)
        
        self.__fft_sink = MessageDistributorSink(
            itemsize=output_length * gr.sizeof_char,
            context=self.__context,
            migrate=self.__fft_sink,
            notify=self.__update_interested)
        self.__overlapper = _OverlapGimmick(
            size=input_length,
            factor=overlap_factor,
            itemsize=self.__itemsize)
        
        # Adjusts units so displayed level is independent of resolution and sample rate. Also throw in the packing offset
        compensation = to_dB(input_length / sample_rate) + self.__power_offset
        # TODO: Consider not using the logpwrfft block
        
        self.__logpwrfft = logpwrfft.logpwrfft_c(
            sample_rate=sample_rate * overlap_factor,
            fft_size=input_length,
            ref_scale=10.0 ** (-compensation / 20.0) * 2,  # not actually using this as a reference scale value but avoiding needing to use a separate add operation to apply the unit change -- this expression is the inverse of what logpwrfft does internally
            frame_rate=self.__frame_rate,
            avg_alpha=1.0,
            average=False)
        # It would make slightly more sense to use unsigned chars, but blocks.float_to_uchar does not support vlen.
        self.__fft_converter = blocks.float_to_char(vlen=self.__freq_resolution, scale=1.0)
    
        self.__scope_sink = MessageDistributorSink(
            itemsize=self.__time_length * gr.sizeof_gr_complex,
            context=self.__context,
            migrate=self.__scope_sink,
            notify=self.__update_interested)
        self.__scope_chunker = blocks.stream_to_vector_decimator(
            item_size=gr.sizeof_gr_complex,
            sample_rate=sample_rate,
            vec_rate=self.__frame_rate,  # TODO doesn't need to be coupled
            vec_len=self.__time_length)

    def __connect(self):
        self.__context.lock()
        try:
            self.disconnect_all()
            self.connect(
                self,
                self.__gate,
                self.__overlapper,
                self.__logpwrfft)
            if self.__after_fft is not None:
                self.connect(self.__logpwrfft, self.__after_fft)
                self.connect(self.__after_fft, self.__fft_converter, self.__fft_sink)
                self.connect((self.__after_fft, 1), blocks.null_sink(gr.sizeof_float * self.__freq_resolution))
            else:
                self.connect(self.__logpwrfft, self.__fft_converter, self.__fft_sink)
            if self.__enable_scope:
                self.connect(
                    self.__gate,
                    self.__scope_chunker,
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
        self.__rebuild()
        self.__connect()
        self.state_changed('signal_type')
    
    # non-exported
    def set_input_center_freq(self, value):
        self.__input_center_freq = float(value) 
    
    @exported_value(
        type=Range([(2, 4096)], logarithmic=True, integer=True),
        changes='this_setter',
        label='Resolution',
        description='Frequency domain resolution; number of FFT bins.')
    def get_freq_resolution(self):
        return self.__freq_resolution

    @setter
    def set_freq_resolution(self, freq_resolution):
        self.__freq_resolution = freq_resolution
        self.__rebuild()
        self.__connect()

    @exported_value(type=Range([(1, 4096)], logarithmic=True, integer=True), changes='this_setter')
    def get_time_length(self):
        return self.__time_length

    @setter
    def set_time_length(self, value):
        self.__time_length = value
        self.__rebuild()
        self.__connect()

    @exported_value(
        type=Range([(1, _maximum_fft_rate)],
        logarithmic=True, integer=False),
        changes='this_setter',
        label='Rate',
        description='Number of FFT frames per second.')
    def get_frame_rate(self):
        return self.__frame_rate

    @setter
    def set_frame_rate(self, value):
        self.__logpwrfft.set_vec_rate(float(value))
        self.__frame_rate = self.__logpwrfft.frame_rate()
    
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
