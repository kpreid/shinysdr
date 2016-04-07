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

from __future__ import absolute_import, division

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest
from zope.interface import implements  # available via Twisted

from gnuradio import gr

from shinysdr.devices import Device, IRXDriver, ITXDriver
from shinysdr.top import Top
from shinysdr.plugins import simulate
from shinysdr.signals import SignalType
from shinysdr.test.testutil import state_smoke_test
from shinysdr.types import Range
from shinysdr.values import ExportedState


class TestTop(unittest.TestCase):
    def test_state_smoke(self):
        state_smoke_test(Top(devices={'s1': simulate.SimulatedDevice()}))
    
    def test_monitor_source_switch(self):
        freq1 = 1e6
        freq2 = 2e6
        # TODO: Also test signal type switching (not yet supported by SimulatedDevice)
        top = Top(devices={
            's1': simulate.SimulatedDevice(freq=freq1),
            's2': simulate.SimulatedDevice(freq=freq2),
        })
        top.set_source_name('s1')
        self.assertEqual(top.state()['monitor'].get().get_fft_info()[0], freq1)
        top.set_source_name('s2')
        self.assertEqual(top.state()['monitor'].get().get_fft_info()[0], freq2)

    @defer.inlineCallbacks
    def test_monitor_vfo_change(self):
        freq1 = 1e6
        freq2 = 2e6
        dev = simulate.SimulatedDevice(freq=freq1, allow_tuning=True)
        top = Top(devices={'s1': dev})
        self.assertEqual(top.state()['monitor'].get().get_fft_info()[0], freq1)
        dev.set_freq(freq2)
        yield deferLater(the_reactor, 0.1, lambda: None)  # wait for tune delay
        self.assertEqual(top.state()['monitor'].get().get_fft_info()[0], freq2)
        # TODO: Also test value found in data stream

    def test_receiver_source_switch(self):
        """
        Regression test: Switching sources was not updating receiver input frequency.
        """
        freq1 = 1e6
        freq2 = 2e6
        top = Top(devices={
            's1': simulate.SimulatedDevice(freq=freq1),
            's2': simulate.SimulatedDevice(freq=freq2),
        })
        
        (_key, receiver) = top.add_receiver('AM', key='a')
        receiver.set_rec_freq(freq2)
        receiver.set_device_name('s1')
        self.assertFalse(receiver.get_is_valid(), 'receiver initially invalid')
        receiver.set_device_name('s2')
        self.assertTrue(receiver.get_is_valid(), 'receiver now valid')

    def test_receiver_device_default(self):
        """
        Receiver should default to the monitor device, not other receiver's device.
        """
        top = Top(devices={
            's1': simulate.SimulatedDevice(),
            's2': simulate.SimulatedDevice(),
        })
        
        (_key, receiver1) = top.add_receiver('AM', key='a')
        top.set_source_name('s2')
        receiver1.set_device_name('s1')
        (_key, receiver2) = top.add_receiver('AM', key='b')
        self.assertEquals(receiver2.get_device_name(), 's2')
        self.assertEquals(receiver1.get_device_name(), 's1')

    def test_add_unknown_mode(self):
        """
        Specifying an unknown mode should not _fail_.
        """
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)})
        (_key, receiver) = top.add_receiver('NONSENSE', key='a')
        self.assertEqual(receiver.get_mode(), 'AM')
    
    def test_audio_queue_smoke(self):
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)})
        queue = gr.msg_queue()
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_queue(queue, 48000)
        top.remove_audio_queue(queue)
    
    def test_mono(self):
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)}, stereo=False)
        queue = gr.msg_queue()
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_queue(queue, 48000)
        top.remove_audio_queue(queue)
    
    def test_close(self):
        l = set()
        top = Top(devices={'m': Device(
            rx_driver=ShutdownMockDriver(l, 'rx'),
            tx_driver=ShutdownMockDriver(l, 'tx'),
            components={'c': ShutdownMockDriver(l, 'c')})})
        top.close_all_devices()
        # TODO: Add support for closing non-driver components (making this set [rx,tx,c]).
        self.assertEqual(l, set(['rx', 'tx']))
    
    @defer.inlineCallbacks
    def test_auto_retune(self):
        # pylint: disable=no-member
        
        f1 = 50e6  # avoid 100e6 because that's a default a couple of places
        dev = simulate.SimulatedDevice(freq=f1, allow_tuning=True)
        bandwidth = dev.get_rx_driver().get_output_type().get_sample_rate()
        top = Top(devices={'s1': dev})
        (_key, receiver) = top.add_receiver('AM', key='a')
        
        # initial state check
        receiver.set_rec_freq(f1)
        self.assertEqual(dev.get_freq(), f1)
        
        # one "page" up
        f2 = f1 + bandwidth * 3/4
        receiver.set_rec_freq(f2)
        self.assertEqual(dev.get_freq(), f1 + bandwidth)
        
        # must wait for tune_delay, which is 0 for simulated source, or it will look still-valid
        yield deferLater(the_reactor, 0.1, lambda: None)
        
        # one "page" down
        receiver.set_rec_freq(f1)
        self.assertEqual(dev.get_freq(), f1)
        
        yield deferLater(the_reactor, 0.1, lambda: None)
        
        # long hop
        receiver.set_rec_freq(200e6)
        self.assertEqual(dev.get_freq(), 200e6)
        
        # TODO test DC offset gap handling
        # TODO test "set to value it already has" behavior


class ShutdownMockDriver(gr.hier_block2, ExportedState):
    implements(IRXDriver, ITXDriver)

    def __init__(self, dest, key):
        gr.hier_block2.__init__(
            self, self.__class__.__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1))
        self.__dest = dest
        self.__key = key
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=10000)
    
    def get_input_type(self):
        return SignalType(kind='IQ', sample_rate=10000)
    
    def get_tune_delay(self):
        return 0.0
    
    def get_usable_bandwidth(self):
        return Range([(-1, 1)])
    
    def close(self):
        self.__dest.add(self.__key)
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        pass
