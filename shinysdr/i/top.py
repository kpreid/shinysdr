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

from __future__ import absolute_import, division

import math
import time

from twisted.internet import reactor
from twisted.python import log
from zope.interface import implements  # available via Twisted

from gnuradio import blocks
from gnuradio import gr

from shinysdr.i.audiomux import AudioManager
from shinysdr.i.blocks import MonitorSink, RecursiveLockBlockMixin, Context
from shinysdr.i.poller import the_subscription_context
from shinysdr.i.receiver import Receiver
from shinysdr.math import LazyRateCalculator
from shinysdr.signals import SignalType
from shinysdr.telemetry import TelemetryStore
from shinysdr.types import Enum, Notice
from shinysdr.values import ExportedState, CollectionState, exported_block, exported_value, setter, IWritableCollection, unserialize_exported_state


class ReceiverCollection(CollectionState):
    implements(IWritableCollection)
    
    def __init__(self, table, top):
        CollectionState.__init__(self, table, dynamic=True)
        self.__top = top
    
    def state_insert(self, key, desc):
        self.__top.add_receiver(mode=desc['mode'], key=key, state=desc)
    
    def create_child(self, desc):
        (key, receiver) = self.__top.add_receiver(desc['mode'])
        receiver.state_from_json(desc)
        return key
        
    def delete_child(self, key):
        self.__top.delete_receiver(key)


# TODO: Figure out how to stop having to 'declare' this here and in config.py
_stub_features = {'stereo': True}


class Top(gr.top_block, ExportedState, RecursiveLockBlockMixin):

    def __init__(self, devices={}, audio_config=None, features=_stub_features):
        # pylint: disable=dangerous-default-value
        if len(devices) <= 0:
            raise ValueError('Must have at least one RF device')
        
        gr.top_block.__init__(self, "SDR top block")
        self.__running = False  # duplicate of GR state we can't reach, see __start_or_stop
        self.__has_a_useful_receiver = False

        # Configuration
        # TODO: device refactoring: Remove vestigial 'accessories'
        self._sources = {k: d for k, d in devices.iteritems() if d.can_receive()}
        self._accessories = accessories = {k: d for k, d in devices.iteritems() if not d.can_receive()}
        self.source_name = self._sources.keys()[0]  # arbitrary valid initial value
        self.__rx_device_type = Enum({k: v.get_name() or k for (k, v) in self._sources.iteritems()})
        
        # Audio early setup
        self.__audio_manager = AudioManager(  # must be before contexts
            graph=self,
            audio_config=audio_config,
            stereo=features['stereo'])

        # Blocks etc.
        # TODO: device refactoring: remove 'source' concept (which is currently a device)
        # TODO: remove legacy no-underscore names, maybe get rid of self.source
        self.source = None
        self.__monitor_rx_driver = None
        self.monitor = MonitorSink(
            signal_type=SignalType(sample_rate=10000, kind='IQ'),  # dummy value will be updated in _do_connect
            context=Context(self))
        self.monitor.get_interested_cell().subscribe2(lambda value: self.__start_or_stop_later, the_subscription_context)
        self.__clip_probe = MaxProbe()
        
        # Receiver blocks (multiple, eventually)
        self._receivers = {}
        self._receiver_valid = {}
        
        # collections
        # TODO: No longer necessary to have these non-underscore names
        self.sources = CollectionState(self._sources)
        self.receivers = ReceiverCollection(self._receivers, self)
        self.accessories = CollectionState(accessories)
        self.__telemetry_store = TelemetryStore()
        
        # Flags, other state
        self.__needs_reconnect = [u'initialization']
        self.__in_reconnect = False
        self.receiver_key_counter = 0
        self.receiver_default_state = {}
        self.__cpu_calculator = LazyRateCalculator(lambda: time.clock())
        
        # Initialization
        
        def hookup_vfo_callback(k, d):  # function so as to not close over loop variable
            d.get_vfo_cell().subscribe2(lambda value: self.__device_vfo_callback(k), the_subscription_context)
        
        for k, d in devices.iteritems():
            hookup_vfo_callback(k, d)
        
        self._do_connect()

    def add_receiver(self, mode, key=None, state=None):
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
            
        combined_state = defaults.copy()
        for do_not_use_default in ['device_name', 'freq_linked_to_device']:
            if do_not_use_default in combined_state:
                del combined_state[do_not_use_default]
        if state is not None:
            combined_state.update(state)
        
        facet = ContextForReceiver(self, key)
        receiver = unserialize_exported_state(Receiver, kwargs=dict(
            mode=mode,
            audio_channels=self.__audio_manager.get_channels(),
            device_name=self.source_name,
            audio_destination=self.__audio_manager.get_default_destination(),  # TODO match others
            context=facet,
        ), state=combined_state)
        facet._receiver = receiver
        self._receivers[key] = receiver
        self._receiver_valid[key] = False
        
        self.__needs_reconnect.append(u'added receiver ' + key)
        self._do_connect()

        # until _enabled, the facet ignores any reconnect/rebuild-triggering callbacks
        facet._enabled = True
        
        return (key, receiver)

    def delete_receiver(self, key):
        assert key in self._receivers
        receiver = self._receivers[key]
        
        # save defaults for use if about to become empty
        if len(self._receivers) == 1:
            self.receiver_default_state = receiver.state_to_json()
        
        del self._receivers[key]
        del self._receiver_valid[key]
        self.__needs_reconnect.append(u'removed receiver ' + key)
        self._do_connect()

    # TODO move these methods to a facet of AudioManager
    def add_audio_queue(self, queue, queue_rate):
        self.__audio_manager.add_audio_queue(queue, queue_rate)
        self.__needs_reconnect.append(u'added audio queue')
        self._do_connect()
        self.__start_or_stop()
    
    def remove_audio_queue(self, queue):
        self.__audio_manager.remove_audio_queue(queue)
        self.__start_or_stop()
        self.__needs_reconnect.append(u'removed audio queue')
        self._do_connect()
    
    def get_audio_queue_channels(self):
        """
        Return the number of channels (which will be 1 or 2) in audio queue outputs.
        """
        return self.__audio_manager.get_channels()

    def _do_connect(self):
        """Do all reconfiguration operations in the proper order."""

        if self.__in_reconnect:
            raise Exception('reentrant reconnect or _do_connect crashed')
        self.__in_reconnect = True
        
        t0 = time.time()
        if self.source is not self._sources[self.source_name]:
            log.msg('Flow graph: Switching RF device to %s' % (self.source_name))
            self.__needs_reconnect.append(u'switched device')

            this_source = self._sources[self.source_name]
            
            self.source = this_source
            self.state_changed('source')
            self.__monitor_rx_driver = this_source.get_rx_driver()
            monitor_signal_type = self.__monitor_rx_driver.get_output_type()
            self.monitor.set_signal_type(monitor_signal_type)
            self.monitor.set_input_center_freq(this_source.get_freq())
            self.__clip_probe.set_window_and_reconnect(0.5 * monitor_signal_type.get_sample_rate())
        
        if self.__needs_reconnect:
            log.msg(u'Flow graph: Rebuilding connections because: %s' % (', '.join(self.__needs_reconnect),))
            self.__needs_reconnect = []
            
            self._recursive_lock()
            self.disconnect_all()
            
            self.connect(
                self.__monitor_rx_driver,
                self.monitor)
            self.connect(
                self.__monitor_rx_driver,
                self.__clip_probe)

            # Filter receivers
            audio_rs = self.__audio_manager.reconnecting()
            n_valid_receivers = 0
            has_non_audio_receiver = False
            for key, receiver in self._receivers.iteritems():
                self._receiver_valid[key] = receiver.get_is_valid()
                if not self._receiver_valid[key]:
                    continue
                if not self.__audio_manager.validate_destination(receiver.get_audio_destination()):
                    log.err('Flow graph: receiver audio destination %r is not available' % (receiver.get_audio_destination(),))
                    continue
                n_valid_receivers += 1
                if n_valid_receivers > 6:
                    # Sanity-check to avoid burning arbitrary resources
                    # TODO: less arbitrary constant; communicate this restriction to client
                    log.err('Flow graph: Refusing to connect more than 6 receivers')
                    break
                self.connect(self._sources[receiver.get_device_name()].get_rx_driver(), receiver)
                receiver_output_type = receiver.get_output_type()
                if receiver_output_type.get_sample_rate() <= 0:
                    # Demodulator has no output, but receiver has a dummy output, so connect it to something to satisfy flow graph structure.
                    for ch in xrange(0, self.__audio_manager.get_channels()):
                        self.connect((receiver, ch), blocks.null_sink(gr.sizeof_float))
                    # Note that we have a non-audio receiver which may be useful even if there is no audio output
                    has_non_audio_receiver = True
                else:
                    assert receiver_output_type.get_kind() == 'STEREO'
                    audio_rs.input(receiver, receiver_output_type.get_sample_rate(), receiver.get_audio_destination())
            
            self.__has_a_useful_receiver = audio_rs.finish_bus_connections() or \
                has_non_audio_receiver
            
            self._recursive_unlock()
            # (this is in an if block but it can't not execute if anything else did)
            log.msg('Flow graph: ...done reconnecting (%i ms).' % ((time.time() - t0) * 1000,))
            
            self.__start_or_stop_later()
        
        self.__in_reconnect = False

    def __device_vfo_callback(self, device_key):
        reactor.callLater(
            self._sources[device_key].get_rx_driver().get_tune_delay(),
            self.__device_vfo_changed,
            device_key)

    def __device_vfo_changed(self, device_key):
        device = self._sources[device_key]
        freq = device.get_freq()
        if self.source is device:
            self.monitor.set_input_center_freq(freq)
        for rec_key, receiver in self._receivers.iteritems():
            if receiver.get_device_name() == device_key:
                receiver.changed_device_freq()
                self._update_receiver_validity(rec_key)
            # TODO: If multiple receivers change validity we'll do redundant reconnects in this loop; avoid that.

    def _update_receiver_validity(self, key):
        receiver = self._receivers[key]
        if receiver.get_is_valid() != self._receiver_valid[key]:
            self.__needs_reconnect.append(u'receiver %s validity changed' % (key,))
            self._do_connect()
    
    @exported_block(changes='never')
    def get_monitor(self):
        return self.monitor
    
    @exported_block(persists=False, changes='never')
    def get_sources(self):
        return self.sources
    
    @exported_block(persists=False, changes='explicit')
    def get_source(self):
        return self.source  # TODO no need for this now...?
    
    @exported_block(changes='never')
    def get_receivers(self):
        return self.receivers
    
    @exported_block(persists=False, changes='never')
    def get_accessories(self):
        return self.accessories
    
    @exported_block(changes='never')
    def get_telemetry_store(self):
        return self.__telemetry_store
    
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
        # TODO: Improve start/stop conditions:
        #
        # * run if a client is watching an audio-having receiver's cell-based outputs (e.g. VOR) but not listening to audio
        #
        # * don't run if no client is watching a pure telemetry receiver
        #   (maybe a user preference since having a history when you connect is useful)
        #
        # Both of these refinements require becoming aware of cell subscriptions.
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
        """Close all devices in preparation for a clean shutdown.
        
        Makes this top block unusable"""
        for device in self._sources.itervalues():
            device.close()
        for device in self._accessories.itervalues():
            device.close()
        self.stop()
        self.wait()

    @exported_value(type_fn=lambda self: self.__rx_device_type, changes='this_setter')
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
    
    @exported_value(type=Notice(always_visible=False), changes='continuous')
    def get_clip_warning(self):
        level = self.__clip_probe.level()
        # We assume that our sample source's absolute limits on I and Q values are the range -1.0 to 1.0. This is a square region; therefore the magnitude observed can be up to sqrt(2) = 1.414 above this, allowing us some opportunity to measure the amount of excess, and also to detect clipping even if the device doesn't produce exactly +-1.0 valus.
        if level >= 1.0:
            return u'Input amplitude too high (%.2f \u2265 1.0). Reduce gain.' % math.sqrt(level)
        else:
            return u''
    
    # TODO: This becomes useless w/ Session fix
    @exported_value(type=float, changes='continuous')
    def get_cpu_use(self):
        return round(self.__cpu_calculator.get(), 2)
    
    def _get_rx_device_type(self):
        """for ContextForReceiver only"""
        return self.__rx_device_type
    
    def _get_audio_destination_type(self):
        """for ContextForReceiver only"""
        return self.__audio_manager.get_destination_type()
    
    def _trigger_reconnect(self, reason):
        self.__needs_reconnect.append(reason)
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
        self._receiver = None  # assigned outside

    def get_device(self, device_key):
        return self.__top._sources[device_key]

    def get_rx_device_type(self):
        return self.__top._get_rx_device_type()

    def get_audio_destination_type(self):
        return self.__top._get_audio_destination_type()

    def revalidate(self, tuning):
        if not self._enabled: return

        # TODO: Lots of the below logic probably ought to replace the current receiver.get_is_valid.
        # TODO: Be aware of receiver bandwidth.

        receiver = self._receiver
        device = self.__top._sources[receiver.get_device_name()]
        usable_bandwidth_range = device.get_rx_driver().get_usable_bandwidth()
        needed_freq = receiver.get_rec_freq()
        current_device_freq = device.get_freq()

        def validate_by_range(rec_freq, dev_freq):
            rel_freq = rec_freq - dev_freq
            return usable_bandwidth_range(rel_freq) == rel_freq

        # TODO: can't do this because it horribly breaks drag-tuning
        #if tuning and not validate_by_range(needed_freq, current_device_freq):
        # we need to check the range as well as receiver.get_is_valid because receiver.get_is_valid uses the tune_delay delayed frequency which may not be up to date
        if tuning and not receiver.get_is_valid() and not validate_by_range(needed_freq, current_device_freq):
            # TODO need 0Hz-gimmick logic
            direction = 1 if needed_freq > current_device_freq else -1
            usable_bandwidth_step = usable_bandwidth_range.get_max() - usable_bandwidth_range.get_min()

            page_size = usable_bandwidth_step
            paged_freq = device.get_freq() + direction * page_size
            if validate_by_range(needed_freq, paged_freq):
                freq = paged_freq
                print '--- page', device.get_freq(), direction * page_size, freq
            else:
                # need a long step
                # TODO need avoid-DC-offset logic
                freq = needed_freq
                print '--- jump', device.get_freq(), freq

            # TODO write justification here that this won't be dangerously reentrant
            device.set_freq(freq)
            # TODO: It would also make sense to switch sources here, if the receiver is more-in-range for the other source.
            
            # No need to _update_receiver_validity here because tuning will do that with fewer reconnects.
        else:
            self.__top._update_receiver_validity(self._key)

    def changed_needed_connections(self, reason):
        if self._enabled:
            self.__top._trigger_reconnect(u'receiver %s: %s' % (self._key, reason))
    
    def output_message(self, message):
        self.__top.get_telemetry_store().receive(message)


class MaxProbe(gr.hier_block2):
    """
    A probe whose level is the maximum magnitude-squared occurring within the specified window of samples.
    """
    def __init__(self, window=10000):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(0, 0, 0))
        self.__sink = None  # quiet pylint
        self.set_window_and_reconnect(window)
    
    def level(self):
        # pylint: disable=method-hidden
        # overridden in instances
        raise Exception('This placeholder should never get called')
    
    def set_window_and_reconnect(self, window):
        """
        Must be called while the flowgraph is locked already.
        """
        # Use a power-of-2 window size to satisfy gnuradio allocation alignment without going overboard.
        window = int(2 ** math.floor(math.log(window, 2)))
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
    """not quite base 26, actually, because it has no true zero digit"""
    if x < 26:
        return 'abcdefghijklmnopqrstuvwxyz'[x]
    else:
        return base26(x // 26 - 1) + base26(x % 26)
