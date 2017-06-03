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

from __future__ import absolute_import, division

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest
from zope.interface import implements  # available via Twisted

from gnuradio import gr

from shinysdr.devices import Device, IComponent, merge_devices
from shinysdr.i.top import Top
from shinysdr.plugins import simulate
from shinysdr.signals import SignalType
from shinysdr.test.testutil import StubRXDriver, state_smoke_test
from shinysdr.types import RangeT
from shinysdr.values import ExportedState, LooseCell


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
        top = Top(
            devices={'s1': simulate.SimulatedDevice(freq=0)},
            features={'stereo': False})
        queue = gr.msg_queue()
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_queue(queue, 48000)
        top.remove_audio_queue(queue)
    
    def test_close(self):
        l = []
        top = Top(devices={'m':
            merge_devices([
                simulate.SimulatedDevice(),
                Device(components={'c': _DeviceShutdownDetector(l)})])})
        top.close_all_devices()
        self.assertEqual(l, ['close'])
    
    @defer.inlineCallbacks
    def test_monitor_interest(self):
        queue = gr.msg_queue()
        top = Top(devices={'s1': simulate.SimulatedDevice()})
        self.assertFalse(top._Top__running)
        top.get_monitor().get_fft_distributor().subscribe(queue)
        yield deferLater(the_reactor, 0.1, lambda: None)
        self.assertTrue(top._Top__running)
        top.get_monitor().get_fft_distributor().unsubscribe(queue)
        yield deferLater(the_reactor, 0.1, lambda: None)
        self.assertFalse(top._Top__running)


class TestRetuning(unittest.TestCase):
    """Tests of automatic device tuning behavior."""
    def setUp(self):
        f1 = self.f1 = 50e6  # avoid 100e6 because that's a default a couple of places
        self.dev = _RetuningTestDevice(f1, False)
        self.bandwidth = self.dev.get_rx_driver().get_output_type().get_sample_rate()
        top = Top(devices={'s1': self.dev})
        (_key, self.receiver) = top.add_receiver('AM', key='a')
        
        self.receiver.set_rec_freq(f1)

        # sanity check
        self.assertEqual(self.dev.get_freq(), f1)
    
    @defer.inlineCallbacks
    def __do_test(self, rec_freq, expected_dev_freq):
        self.receiver.set_rec_freq(rec_freq)
        self.assertEqual(self.dev.get_freq(), expected_dev_freq)
        
        # allow for tune_delay (which is 0 for SimulatedDevice) so receiver validity is updated
        yield deferLater(the_reactor, 0.1, lambda: None)
        
        self.assertTrue(self.receiver.get_is_valid())
    
    def test_one_page_up(self):
        return self.__do_test(
            self.f1 + self.bandwidth * 3 / 4,
            self.f1 + self.bandwidth)
    
    def test_one_page_down(self):
        return self.__do_test(
            self.f1 - self.bandwidth * 3 / 4,
            self.f1 - self.bandwidth)
    
    def test_long_jump(self):
        return self.__do_test(
            200e6,
            200e6)
    
    # TODO test DC offset gap handling
    # TODO test "set to value it already has" behavior


def _RetuningTestDevice(freq, has_dc_offset):
    return Device(
        rx_driver=_RetuningTestRXDriver(has_dc_offset),
        vfo_cell=LooseCell(
            key='freq',
            value=freq,
            type=RangeT([(-1e9, 1e9)]),  # TODO kludge magic numbers
            writable=True,
            persists=False))


class _RetuningTestRXDriver(StubRXDriver):
    def __init__(self, has_dc_offset):
        super(_RetuningTestRXDriver, self).__init__()
        rate = 200e3
        self.__signal_type = SignalType(kind='IQ', sample_rate=rate)
        halfrate = rate / 2
        if has_dc_offset:
            self.__usable_bandwidth = RangeT([(-halfrate, 1), (1, halfrate)])
        else:
            self.__usable_bandwidth = RangeT([(-halfrate, halfrate)])
    
    def get_output_type(self):
        return self.__signal_type
    
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth


class _DeviceShutdownDetector(ExportedState):
    implements(IComponent)

    def __init__(self, dest):
        super(_DeviceShutdownDetector, self).__init__()
        self.__dest = dest
        
    def close(self):
        self.__dest.append('close')
