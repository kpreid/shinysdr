# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=dangerous-default-value, no-method-argument, no-init, method-hidden
# (the default values in question are not mutated)
# (pylint is confused by interfaces)
# (method-hidden: done on purpose)

from __future__ import absolute_import, division

import math
import time

from twisted.internet import reactor
from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import blocks
from gnuradio import gr

from shinysdr.types import Enum, Notice
from shinysdr.values import ExportedState, CollectionState, exported_value, setter, BlockCell, IWritableCollection
from shinysdr.blocks import make_resampler, MonitorSink, RecursiveLockBlockMixin, Context
from shinysdr.receiver import Receiver
from shinysdr.signals import SignalType


class ReceiverCollection(CollectionState):
    implements(IWritableCollection)
    
    def __init__(self, table, top):
        CollectionState.__init__(self, table, dynamic=True)
        self.__top = top
    
    def state_insert(self, key, desc):
        (key, receiver) = self.__top.add_receiver(desc['mode'], key=key)
        receiver.state_from_json(desc)
    
    def create_child(self, desc):
        (key, receiver) = self.__top.add_receiver(desc['mode'])
        receiver.state_from_json(desc)
        return key
        
    def delete_child(self, key):
        self.__top.delete_receiver(key)


class Top(gr.top_block, ExportedState, RecursiveLockBlockMixin):

    def __init__(self, devices={}, stereo=True):
        gr.top_block.__init__(self, "SDR top block")
        self.__unpaused = True  # user state
        self.__running = False  # actually started

        # Configuration
        # TODO: device refactoring: Remove vestigial 'accessories'
        self._sources = {k: d for k, d in devices.iteritems() if d.can_receive()}
        accessories = {k: d for k, d in devices.iteritems() if not d.can_receive()}
        self.source_name = self._sources.keys()[0]  # arbitrary valid initial value

        # Blocks etc.
        # TODO: device refactoring: remove 'source' concept (which is currently a device)
        self.source = None
        self.__rx_driver = None
        self.__source_tune_subscription = None
        self.monitor = MonitorSink(
            signal_type=SignalType(sample_rate=10000, kind='IQ'),  # dummy value will be updated in _do_connect
            context=Context(self))
        self.__clip_probe = MaxProbe()
        
        # Receiver blocks (multiple, eventually)
        self._receivers = {}
        self._receiver_valid = {}
        
        self.__shared_objects = {}
        
        # kludge for using collection like block - TODO: better architecture
        self.sources = CollectionState(self._sources)
        self.receivers = ReceiverCollection(self._receivers, self)
        self.accessories = CollectionState(accessories)
        # TODO: better name than "shared objects"
        self.shared_objects = CollectionState(self.__shared_objects, dynamic=True)
        
        # Audio stream bits
        self.__audio_channels = 2 if stereo else 1
        self.audio_resampler_cache = {}
        self.audio_queue_sinks = {}
        self.__audio_bus_rate = 1  # dummy initial value, computed in _do_connect
        
        # Flags, other state
        self.__needs_reconnect = True
        self.input_rate = None
        self.input_freq = None
        self.receiver_key_counter = 0
        self.receiver_default_state = {}
        self.last_wall_time = time.time()
        self.last_cpu_time = time.clock()
        self.last_cpu_use = 0
        
        self._do_connect()

    def add_receiver(self, mode, key=None):
        if len(self._receivers) >= 100:
            # Prevent storage-usage DoS attack
            raise Exception('Refusing to create more than 100 receivers')
        
        if key is not None:
            assert key not in self._receivers
        else:
            while True:
                key = base26(self.receiver_key_counter)
                self.receiver_key_counter += 1
                if key not in self._receivers:
                    break
        
        if len(self._receivers) > 0:
            arbitrary = self._receivers.itervalues().next()
            defaults = arbitrary.state_to_json()
        else:
            defaults = self.receiver_default_state
        
        receiver = self._make_receiver(mode, defaults, key)
        
        self._receivers[key] = receiver
        self._receiver_valid[key] = False
        
        self.__needs_reconnect = True
        self._do_connect()
        
        return (key, receiver)

    def delete_receiver(self, key):
        assert key in self._receivers
        receiver = self._receivers[key]
        
        # save defaults for use if about to become empty
        if len(self._receivers) == 1:
            self.receiver_default_state = receiver.state_to_json()
        
        del self._receivers[key]
        del self._receiver_valid[key]
        self.__needs_reconnect = True
        self._do_connect()

    def add_audio_queue(self, queue, queue_rate):
        # TODO: place limit on maximum requested sample rate
        self.audio_queue_sinks[queue] = (queue_rate,
            AudioQueueSink(channels=self.__audio_channels, queue=queue))
        
        self.__needs_reconnect = True
        self._do_connect()
        self.__start_or_stop()
    
    def remove_audio_queue(self, queue):
        del self.audio_queue_sinks[queue]
        
        self.__start_or_stop()
        self.__needs_reconnect = True
        self._do_connect()
    
    def get_audio_channels(self):
        '''
        Return the number of channels (which will be 1 or 2) in audio queue outputs.
        '''
        return self.__audio_channels

    def _do_connect(self):
        """Do all reconfiguration operations in the proper order."""
        rate_changed = False
        if self.source is not self._sources[self.source_name]:
            log.msg('Flow graph: Switching RF source')
            self.__needs_reconnect = True

            this_source = self._sources[self.source_name]
            
            def update_input_freqs():
                freq = this_source.get_freq()
                self.input_freq = freq
                self.monitor.set_input_center_freq(freq)
                for receiver in self._receivers.itervalues():
                    receiver.set_input_center_freq(freq)
            
            def tune_hook():
                # Note that in addition to the flow graph delay, the callLater is also needed in order to ensure we don't do our reconfiguration in the middle of the source's own workings.
                reactor.callLater(self.__rx_driver.get_tune_delay(), tune_hook_actual)
            
            def tune_hook_actual():
                if self.source is not this_source:
                    return
                update_input_freqs()
                for key in self._receivers:
                    self._update_receiver_validity(key)
                    # TODO: If multiple receivers change validity we'll do redundant reconnects in this loop; avoid that.
            
            if self.__source_tune_subscription is not None:
                self.__source_tune_subscription.unsubscribe()
            self.__source_tune_subscription = this_source.state()['freq'].subscribe(tune_hook)
            
            self.source = this_source
            self.__rx_driver = this_source.get_rx_driver()
            source_signal_type = self.__rx_driver.get_output_type()
            this_rate = source_signal_type.get_sample_rate()
            rate_changed = self.input_rate != this_rate
            self.input_rate = this_rate
            self.monitor.set_signal_type(source_signal_type)
            self.__clip_probe.set_window_and_reconnect(0.5 * this_rate)
            update_input_freqs()
        
        if rate_changed:
            log.msg('Flow graph: Changing sample rates')
            for receiver in self._receivers.itervalues():
                receiver.set_input_rate(self.input_rate)

        if self.__needs_reconnect:
            log.msg('Flow graph: Rebuilding connections')
            self.__needs_reconnect = False
            
            self._recursive_lock()
            self.disconnect_all()
            
            self.connect(
                self.__rx_driver,
                self.monitor)
            self.connect(
                self.__rx_driver,
                self.__clip_probe)
            
            # Determine audio bus rate.
            # The bus obviously does not need to be higher than the rate of any receiver, because that would be extraneous data. It also does not need to be higher than the rate of any queue, because no queue has use for the information.
            if len(self._receivers) > 0 and len(self.audio_queue_sinks) > 0:
                max_out_rate = max((receiver.get_output_type().get_sample_rate() for receiver in self._receivers.itervalues()))
                max_in_rate = max((queue_rate for (queue_rate, sink) in self.audio_queue_sinks.itervalues()))
                new_bus_rate = min(max_out_rate, max_in_rate)
                if new_bus_rate != self.__audio_bus_rate:
                    self.__audio_bus_rate = new_bus_rate
                    self.audio_resampler_cache.clear()
            
            # recreated each time because reusing an add_ff w/ different
            # input counts fails; TODO: report/fix bug
            audio_sums = [blocks.add_ff() for _ in xrange(self.__audio_channels)]
            
            audio_sum_index = 0
            for key, receiver in self._receivers.iteritems():
                self._receiver_valid[key] = receiver.get_is_valid()
                if self._receiver_valid[key]:
                    if audio_sum_index >= 6:
                        # Sanity-check to avoid burning arbitrary resources
                        # TODO: less arbitrary constant; communicate this restriction to client
                        log.err('Flow graph: Refusing to connect more than 6 receivers')
                        break
                    self.connect(self.__rx_driver, receiver)
                    receiver_rate = receiver.get_output_type().get_sample_rate()
                    if receiver_rate == self.__audio_bus_rate:
                        for ch in xrange(self.__audio_channels):
                            self.connect(
                                (receiver, ch),
                                (audio_sums[ch], audio_sum_index))
                    else:
                        for ch in xrange(self.__audio_channels):
                            self.connect(
                                (receiver, ch),
                                # TODO pool these resamplers
                                make_resampler(receiver_rate, self.__audio_bus_rate),
                                (audio_sums[ch], audio_sum_index))
                    audio_sum_index += 1
            
            if audio_sum_index > 0:
                # connect audio output only if there is at least one input
                if len(self.audio_queue_sinks) > 0:
                    used_resamplers = set()
                    for (queue_rate, sink) in self.audio_queue_sinks.itervalues():
                        if queue_rate == self.__audio_bus_rate:
                            for ch in xrange(self.__audio_channels):
                                self.connect(audio_sums[ch], (sink, ch))
                        else:
                            if queue_rate not in self.audio_resampler_cache:
                                # Moderately expensive due to the internals using optfir
                                log.msg('Flow graph: Constructing resampler for audio rate %i' % queue_rate)
                                self.audio_resampler_cache[queue_rate] = tuple(
                                    make_resampler(self.__audio_bus_rate, queue_rate)
                                    for _ in xrange(self.__audio_channels))
                            resamplers = self.audio_resampler_cache[queue_rate]
                            used_resamplers.add(resamplers)
                            for ch in xrange(self.__audio_channels):
                                self.connect(resamplers[ch], (sink, ch))
                    for resamplers in used_resamplers:
                        for ch in xrange(self.__audio_channels):
                            self.connect(audio_sums[ch], resamplers[ch])
                else:
                    # no stream sinks, gnuradio requires a dummy sink
                    for ch in xrange(self.__audio_channels):
                        self.connect(audio_sums[ch], blocks.null_sink(gr.sizeof_float))
        
            self._recursive_unlock()
            log.msg('Flow graph: ...done reconnecting.')

    def _update_receiver_validity(self, key):
        receiver = self._receivers[key]
        if receiver.get_is_valid() != self._receiver_valid[key]:
            self.__needs_reconnect = True
            self._do_connect()

    def state_def(self, callback):
        super(Top, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'monitor'))
        callback(BlockCell(self, 'sources'))
        callback(BlockCell(self, 'source', persists=False))
        callback(BlockCell(self, 'receivers'))
        callback(BlockCell(self, 'accessories', persists=False))
        callback(BlockCell(self, 'shared_objects'))

    def start(self, **kwargs):
        # trigger reconnect/restart notification
        self._recursive_lock()
        self._recursive_unlock()
        
        super(Top, self).start(**kwargs)
        self.__running = True

    def stop(self):
        super(Top, self).stop()
        self.__running = False

    @exported_value(ctor=bool)
    def get_unpaused(self):
        return self.__unpaused
    
    @setter
    def set_unpaused(self, value):
        self.__unpaused = bool(value)
        self.__start_or_stop()
    
    def __start_or_stop(self):
        # TODO: We should also run if at least one client is watching the spectrum or demodulators' cell-based outputs, but there's no good way to recognize that yet.
        should_run = self.__unpaused and len(self.audio_queue_sinks) > 0
        if should_run != self.__running:
            if should_run:
                self.start()
            else:
                self.stop()
                self.wait()

    @exported_value(ctor_fn=lambda self:
        Enum({k: v.get_name() or k for (k, v) in self._sources.iteritems()}))
    def get_source_name(self):
        return self.source_name
    
    @setter
    def set_source_name(self, value):
        if value == self.source_name:
            return
        if value not in self._sources:
            raise ValueError('Source %r does not exist' % (value,))
        self.source_name = value
        self._do_connect()

    def _make_receiver(self, mode, state, key):
        facet = ContextForReceiver(self, key)
        receiver = Receiver(
            mode=mode,
            input_rate=self.input_rate,
            input_center_freq=self.input_freq,
            audio_channels=self.__audio_channels,
            context=facet,
        )
        receiver.state_from_json(state)
        # until _enabled, ignore any callbacks resulting from the state_from_json initialization
        facet._enabled = True
        return receiver
    
    @exported_value(ctor=Notice(always_visible=False))
    def get_clip_warning(self):
        level = self.__clip_probe.level()
        # We assume that our sample source's absolute limits on I and Q values are the range -1.0 to 1.0. This is a square region; therefore the magnitude observed can be up to sqrt(2) = 1.414 above this, allowing us some opportunity to measure the amount of excess, and also to detect clipping even if the device doesn't produce exactly +-1.0 valus.
        if level >= 1.0:
            return u'Input amplitude too high (%.2f \u2265 1.0). Reduce gain.' % math.sqrt(level)
        else:
            return u''
    
    @exported_value(ctor=int)
    def get_input_rate(self):
        return self.input_rate

    @exported_value(ctor=int)
    def get_audio_bus_rate(self):
        '''
        Not visible externally; for diagnostic purposes only.
        '''
        return self.__audio_bus_rate
    
    @exported_value(ctor=float)
    def get_cpu_use(self):
        cur_wall_time = time.time()
        elapsed_wall = cur_wall_time - self.last_wall_time
        if elapsed_wall > 0.5:
            cur_cpu_time = time.clock()
            elapsed_cpu = cur_cpu_time - self.last_cpu_time
            self.last_wall_time = cur_wall_time
            self.last_cpu_time = cur_cpu_time
            self.last_cpu_use = round(elapsed_cpu / elapsed_wall, 2)
        return self.last_cpu_use
    
    def get_shared_object(self, ctor):
        # TODO: Make shared objects able to persist. This will probably require some kind of up-front registry.
        # TODO: __name__ is a lousy strategy
        key = ctor.__name__
        if key not in self.__shared_objects:
            self.__shared_objects[key] = ctor()
        return self.__shared_objects[key]
    
    def _trigger_reconnect(self):
        self.__needs_reconnect = True
        self._do_connect()
    
    def _recursive_lock_hook(self):
        for source in self._sources.itervalues():
            source.notify_reconnecting_or_restarting()


class ContextForReceiver(Context):
    def __init__(self, top, key):
        Context.__init__(self, top)
        self.__top = top
        self._key = key
        self._enabled = False  # assigned outside

    def revalidate(self):
        if self._enabled:
            self.__top._update_receiver_validity(self._key)

    def changed_output_type(self):
        if self._enabled:
            self.__top._trigger_reconnect()
    
    def get_shared_object(self, ctor):
        return self.__top.get_shared_object(ctor)


class IHasFrequency(Interface):
    # TODO: better module placement for this
    def get_freq():
        pass


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


class MaxProbe(gr.hier_block2):
    '''
    A probe whose level is the maximum magnitude-squared occurring within the specified window of samples.
    '''
    def __init__(self, window=10000):
        gr.hier_block2.__init__(
            self, 'ShinySDR MaxProbe',
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(0, 0, 0),
        )
        self.__sink = None  # quiet pylint
        self.set_window_and_reconnect(window)
    
    def level(self):
        # overridden in instances
        raise Exception('This placeholder should never get called')
    
    def set_window_and_reconnect(self, window):
        '''
        Must be called while the flowgraph is locked already.
        '''
        window = int(window)
        self.disconnect_all()
        self.__sink = blocks.probe_signal_f()
        self.connect(
            self,
            blocks.complex_to_mag_squared(),
            blocks.stream_to_vector(itemsize=gr.sizeof_float, nitems_per_block=window),
            blocks.max_ff(window),
            self.__sink)
        
        # shortcut method implementation
        self.level = self.__sink.level
        


def base26(x):
    '''not quite base 26, actually, because it has no true zero digit'''
    if x < 26:
        return 'abcdefghijklmnopqrstuvwxyz'[x]
    else:
        return base26(x // 26 - 1) + base26(x % 26)
