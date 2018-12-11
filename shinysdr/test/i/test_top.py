# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

import six

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest
from zope.interface import implementer  # available via Twisted

from shinysdr.devices import Device, IComponent, merge_devices
from shinysdr.i.poller import the_subscription_context
from shinysdr.i.top import Top
from shinysdr.plugins.simulate import SimulatedDeviceForTest
from shinysdr.signals import SignalType
from shinysdr.test.testutil import StubRXDriver, state_smoke_test
from shinysdr.types import RangeT
from shinysdr.values import ExportedState, LooseCell


class TestTop(unittest.TestCase):
    def test_state_smoke(self):
        state_smoke_test(Top(devices={'s1': SimulatedDeviceForTest()}))
    
    def test_monitor_source_switch(self):
        freq1 = 1e6
        freq2 = 2e6
        # TODO: Also test signal type switching (not yet supported by SimulatedDeviceForTest)
        top = Top(devices={
            's1': SimulatedDeviceForTest(freq=freq1),
            's2': SimulatedDeviceForTest(freq=freq2),
        })
        # TODO: using get_fft_info is digging into the implementation
        top.set_source_name('s1')
        self.assertEqual(top.state()['monitor'].get()._get_fft_info()[0], freq1)
        top.set_source_name('s2')
        self.assertEqual(top.state()['monitor'].get()._get_fft_info()[0], freq2)

    @defer.inlineCallbacks
    def test_monitor_vfo_change(self):
        freq1 = 1e6
        freq2 = 2e6
        dev = SimulatedDeviceForTest(freq=freq1, allow_tuning=True)
        top = Top(devices={'s1': dev})
        # TODO: using get_fft_info is digging into the implementation
        self.assertEqual(top.state()['monitor'].get()._get_fft_info()[0], freq1)
        dev.set_freq(freq2)
        yield deferLater(the_reactor, 0.1, lambda: None)  # wait for tune delay
        self.assertEqual(top.state()['monitor'].get()._get_fft_info()[0], freq2)
        # TODO: Also test value found in data stream

    def test_receiver_source_switch(self):
        """
        Regression test: Switching sources was not updating receiver input frequency.
        """
        freq1 = 1e6
        freq2 = 2e6
        top = Top(devices={
            's1': SimulatedDeviceForTest(freq=freq1),
            's2': SimulatedDeviceForTest(freq=freq2),
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
            's1': SimulatedDeviceForTest(),
            's2': SimulatedDeviceForTest(),
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
        top = Top(devices={'s1': SimulatedDeviceForTest(freq=0)})
        (_key, receiver) = top.add_receiver('NONSENSE', key='a')
        self.assertEqual(receiver.get_mode(), 'AM')
    
    def test_audio_callback_smoke(self):
        def callback(data):
            pass
        top = Top(devices={'s1': SimulatedDeviceForTest(freq=0)})
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_callback(callback, 48000)
        top.remove_audio_callback(callback)
    
    def test_mono(self):
        def callback(data):
            pass
        top = Top(
            devices={'s1': SimulatedDeviceForTest(freq=0)},
            features={'stereo': False})
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_callback(callback, 48000)
        top.remove_audio_callback(callback)
    
    def test_close(self):
        log = []
        top = Top(devices={'m':
            merge_devices([
                SimulatedDeviceForTest(),
                Device(components={'c': _DeviceShutdownDetector(log)})])})
        top.close_all_devices()
        self.assertEqual(log, ['close'])
    
    @defer.inlineCallbacks
    def test_monitor_interest(self):
        top = Top(devices={'s1': SimulatedDeviceForTest()})
        self.assertFalse(top._Top__running)
        _, subscription = top.get_monitor().state()['fft'].subscribe2(lambda v: None, the_subscription_context)
        try:
            yield deferLater(the_reactor, 0.1, lambda: None)
            self.assertTrue(top._Top__running)
        finally:
            subscription.unsubscribe()
        yield deferLater(the_reactor, 0.1, lambda: None)
        self.assertFalse(top._Top__running)


class TestRetuning(unittest.TestCase):
    __OFFSET_SMALL = 1.0
    __OFFSET_LARGE = 1000.0
    
    """Tests of automatic device tuning behavior."""
    def setUp(self):
        f1 = self.f1 = 50e6  # avoid 100e6 because that's a default a couple of places
        self.devs = {
            'clean': _RetuningTestDevice(f1, -1.0),
            'offset_small': _RetuningTestDevice(f1, self.__OFFSET_SMALL),
            'offset_large': _RetuningTestDevice(f1, self.__OFFSET_LARGE),
        }
        self.bandwidth = self.devs['clean'].get_rx_driver().get_output_type().get_sample_rate()
        top = Top(devices=self.devs)
        (_key, self.receiver) = top.add_receiver('AM', key='a')

        # initial state sanity check
        for d in six.itervalues(self.devs):
            self.assertEqual(d.get_freq(), f1)
    
    @defer.inlineCallbacks
    def __do_test(self, device_name, rec_freq, expected_dev_freq):
        self.receiver.set_device_name(device_name)
        self.receiver.set_rec_freq(rec_freq)
        self.assertEqual(self.devs[device_name].get_freq(), expected_dev_freq)
        
        # allow for tune_delay (which is 0 for _RetuningTestDevice) so receiver validity is updated
        yield deferLater(the_reactor, 0.1, lambda: None)
        
        self.assertTrue(self.receiver.get_is_valid())
    
    def test_one_page_up(self):
        return self.__do_test('clean',
            self.f1 + self.bandwidth * 3 / 4,
            self.f1 + self.bandwidth)
    
    def test_one_page_down(self):
        return self.__do_test('clean',
            self.f1 - self.bandwidth * 3 / 4,
            self.f1 - self.bandwidth)
    
    def test_jump(self):
        return self.__do_test('clean',
            200e6,
            200e6)
    
    def test_jump_dc_avoidance_am(self):
        shape = self.receiver.get_demodulator().get_band_shape()
        # Note: sign of offset doesn't matter, but the implementation prefers this one.
        return self.__do_test('offset_small',
            200e6,
            200e6 - self.__OFFSET_SMALL + shape.stop_low)
    
    def test_jump_dc_offset_small_usb(self):
        # Expect no offset because USB's filter lies above the exclusion
        self.receiver.set_mode('USB')
        return self.__do_test('offset_small',
            200e6,
            200e6)
    
    def test_jump_dc_offset_small_lsb(self):
        # Expect no offset because LSB's filter lies below the exclusion
        self.receiver.set_mode('LSB')
        return self.__do_test('offset_small',
            200e6,
            200e6)
    
    def test_jump_dc_offset_large_usb(self):
        self.receiver.set_mode('USB')
        shape = self.receiver.get_demodulator().get_band_shape()
        return self.__do_test('offset_large',
            200e6,
            200e6 - self.__OFFSET_LARGE + shape.stop_low)
    
    def test_jump_dc_offset_large_lsb(self):
        self.receiver.set_mode('LSB')
        shape = self.receiver.get_demodulator().get_band_shape()
        return self.__do_test('offset_large',
            200e6,
            200e6 + self.__OFFSET_LARGE + shape.stop_high)
    
    # TODO test "set to value it already has" behavior


def _RetuningTestDevice(freq, has_dc_offset):
    return Device(
        rx_driver=_RetuningTestRXDriver(has_dc_offset),
        vfo_cell=LooseCell(
            value=freq,
            type=RangeT([(-1e9, 1e9)]),  # TODO kludge magic numbers
            writable=True,
            persists=False))


class _RetuningTestRXDriver(StubRXDriver):
    def __init__(self, offset_radius):
        super(_RetuningTestRXDriver, self).__init__()
        rate = 200e3
        self.__signal_type = SignalType(kind='IQ', sample_rate=rate)
        halfrate = rate / 2
        if offset_radius > 0:
            self.__usable_bandwidth = RangeT([(-halfrate, -offset_radius), (offset_radius, halfrate)])
        else:
            self.__usable_bandwidth = RangeT([(-halfrate, halfrate)])
    
    def get_output_type(self):
        return self.__signal_type
    
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth


@implementer(IComponent)
class _DeviceShutdownDetector(ExportedState):
    def __init__(self, log):
        super(_DeviceShutdownDetector, self).__init__()
        self.__log = log
        
    def close(self):
        self.__log.append('close')
    
    def attach_context(self, device_context):
        """implements IComponent"""
