# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

from collections import defaultdict
import math
import time

from twisted.internet import reactor
from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import audio
from gnuradio import blocks
from gnuradio import gr

from shinysdr.types import Enum, Notice
from shinysdr.values import ExportedState, CollectionState, exported_value, setter, BlockCell, IWritableCollection
from shinysdr.blocks import make_resampler, MonitorSink, RecursiveLockBlockMixin, Context
from shinysdr.receiver import Receiver
from shinysdr.signals import SignalType


CLIENT_AUDIO_DEVICE = 'client'


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

    def __init__(self, devices={}, audio_config=None, stereo=True):
        if not len(devices) > 0:
            raise ValueError('Must have at least one RF device')
        #for key, audio_device in audio_devices.iteritems():
        #    if key == CLIENT_AUDIO_DEVICE:
        #        raise ValueError('The name %r for an audio device is reserved' % (key,))
        #    if not audio_device.can_transmit():
        #        raise ValueError('Audio device %r is not an output' % (key,))
        if audio_config is not None:
            # quick kludge placeholder -- currently a Device-device can't be stereo so we have a placeholder thing
            # pylint: disable=unpacking-non-sequence
            audio_device_name, audio_sample_rate = audio_config
            audio_devices = {'server': (audio_sample_rate, audio.sink(audio_sample_rate, audio_device_name, False))}
        else:
            audio_devices = {}
        
        gr.top_block.__init__(self, "SDR top block")
        self.__running = False  # duplicate of GR state we can't reach, see __start_or_stop
        self.__has_a_useful_receiver = False

        # Configuration
        # TODO: device refactoring: Remove vestigial 'accessories'
        self._sources = {k: d for k, d in devices.iteritems() if d.can_receive()}
        self._accessories = accessories = {k: d for k, d in devices.iteritems() if not d.can_receive()}
        self.source_name = self._sources.keys()[0]  # arbitrary valid initial value
        
        # Audio early setup
        self.__audio_devices = audio_devices  # must be before contexts

        # Blocks etc.
        # TODO: device refactoring: remove 'source' concept (which is currently a device)
        self.source = None
        self.__rx_driver = None
        self.__source_tune_subscription = None
        self.monitor = MonitorSink(
            signal_type=SignalType(sample_rate=10000, kind='IQ'),  # dummy value will be updated in _do_connect
            context=Context(self))
        self.monitor.get_interested_cell().subscribe(self.__start_or_stop_later)
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
        audio_destination_dict = {key: 'Server' or key for key, device in audio_devices.iteritems()}  # temp name till we have proper device objects
        audio_destination_dict[CLIENT_AUDIO_DEVICE] = 'Client'  # TODO reconsider name
        self.__audio_destination_type = Enum(audio_destination_dict, strict=True)
        self.__audio_channels = 2 if stereo else 1
        self.audio_queue_sinks = {}
        self.__audio_buses = {key: BusPlumber(self, self.__audio_channels) for key in audio_destination_dict}
        
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

            # Filter receivers
            bus_inputs = defaultdict(lambda: [])
            n_valid_receivers = 0
            for key, receiver in self._receivers.iteritems():
                self._receiver_valid[key] = receiver.get_is_valid()
                if not self._receiver_valid[key]:
                    continue
                if receiver.get_audio_destination() not in self.__audio_buses:
                    log.err('Flow graph: receiver audio destination %r is not available' % (receiver.get_audio_destination(),))
                n_valid_receivers += 1
                if n_valid_receivers > 6:
                    # Sanity-check to avoid burning arbitrary resources
                    # TODO: less arbitrary constant; communicate this restriction to client
                    log.err('Flow graph: Refusing to connect more than 6 receivers')
                    break
                self.connect(self.__rx_driver, receiver)
                rrate = receiver.get_output_type().get_sample_rate()
                bus_inputs[receiver.get_audio_destination()].append((rrate, receiver))
            
            self.__has_a_useful_receiver = False
            for key, bus in self.__audio_buses.iteritems():
                inputs = bus_inputs[key]
                if key == CLIENT_AUDIO_DEVICE:
                    outputs = self.audio_queue_sinks.itervalues()
                    noutputs = len(self.audio_queue_sinks)
                else:
                    outputs = [self.__audio_devices[key]]
                    noutputs = 1
                if len(inputs) > 0 and noutputs > 0:
                    self.__has_a_useful_receiver = True
                bus.connect(
                    inputs=inputs,
                    outputs=outputs)
            
            self._recursive_unlock()
            log.msg('Flow graph: ...done reconnecting.')
            
            self.__start_or_stop()

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

    def __start_or_stop(self):
        # TODO: We should also run if any of:
        #   there are any data-logging receivers (e.g. APRS, ADS-B)
        #       (requires becoming aware of no-audio receivers)
        #   a client is watching a receiver's cell-based outputs (e.g. VOR)
        #       (requires becoming aware of cell subscriptions)
        should_run = (
            self.__has_a_useful_receiver
            or self.monitor.get_interested_cell().get())
        if should_run != self.__running:
            if should_run:
                self.start()
            else:
                self.stop()
                self.wait()

    def __start_or_stop_later(self):
        reactor.callLater(0, self.__start_or_stop)

    def close_all_devices(self):
        '''Close all devices in preparation for a clean shutdown.
        
        Makes this top block unusable'''
        for device in self._sources.itervalues():
            device.close()
        for device in self._accessories.itervalues():
            device.close()
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
            audio_destination=CLIENT_AUDIO_DEVICE,  # TODO match others
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

    @exported_value()
    def get_audio_bus_rate(self):
        '''
        Not visible externally; for diagnostic purposes only.
        '''
        return [b.get_current_rate() for b in self.__audio_buses.itervalues()]
    
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
    
    def _get_audio_destination_type(self):
        '''for ContextForReceiver only'''
        return self.__audio_destination_type
    
    def _trigger_reconnect(self):
        self.__needs_reconnect = True
        self._do_connect()
    
    def _recursive_lock_hook(self):
        for source in self._sources.itervalues():
            source.notify_reconnecting_or_restarting()
        #for audio_device in self.__audio_devices.itervalues():
        #    audio_device.notify_reconnecting_or_restarting()


class ContextForReceiver(Context):
    def __init__(self, top, key):
        Context.__init__(self, top)
        self.__top = top
        self._key = key
        self._enabled = False  # assigned outside

    def get_audio_destination_type(self):
        return self.__top._get_audio_destination_type()

    def revalidate(self):
        if self._enabled:
            self.__top._update_receiver_validity(self._key)

    def changed_output_type_or_destination(self):
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


class BusPlumber(object):
    '''
    Takes an arbitrary number of blocks' float outputs (bus inputs), sums and resamples them, and connects them to an arbitrary number of blocks' inputs (bus outputs).
    
    If there are no outputs, the inputs will go to a null sink. If there are no inputs, the outputs will remain unconnected.
    
    (This cannot be a hierarchical block, because hierarchical blocks cannot currently have variable numbers of ports.)
    '''
    def __init__(self, graph, nchannels):
        self.__graph = graph
        self.__channels = xrange(nchannels)
        self.__bus_rate = 0.0
        # TODO: Stop using a cache of resamplers unless we use them in exactly-corresponding fashion; instead use a cache of resampling _filter taps_.
        self.__resampler_cache = {}
    
    def get_current_rate(self):
        return self.__bus_rate
    
    def connect(self, inputs, outputs):
        '''
        Make all new connections (graph.disconnect_all() must have been done) between inputs and outputs.
        
        inputs and outputs must be iterables of (sample_rate, block) tuples.
        '''
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
                            log.msg('Flow graph: Constructing resampler for audio rate %i' % out_rate)
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
