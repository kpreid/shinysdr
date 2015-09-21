# Copyright 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

from twisted.trial import unittest
from zope.interface import implements  # available via Twisted

# Note: not testing _ConstantVFOCell, it's just a useful utility
from shinysdr.devices import _ConstantVFOCell, AudioDevice, Device, FrequencyShift, IDevice, IRXDriver, ITXDriver, PositionedDevice, merge_devices
from shinysdr.signals import SignalType
from shinysdr.test.testutil import DeviceTestCase
from shinysdr.types import Range
from shinysdr.values import ExportedState, LooseCell, nullExportedState


class TestDevice(unittest.TestCase):
    def test_name(self):
        self.assertEqual(u'x', Device(name='x').get_name())
        self.assertEqual(None, Device().get_name())
    
    def test_rx_absent(self):
        d = Device()
        self.assertEqual(False, d.can_receive())
        self.assertEqual(nullExportedState, d.get_rx_driver())
    
    def test_rx_present(self):
        rxd = _TestRXDriver()
        d = Device(rx_driver=rxd)
        self.assertEqual(True, d.can_receive())
        self.assertEqual(rxd, d.get_rx_driver())
    
    def test_tx_absent(self):
        d = Device()
        self.assertEqual(False, d.can_receive())
        self.assertEqual(nullExportedState, d.get_tx_driver())
    
    def test_tx_present(self):
        txd = _TestTXDriver([])
        d = Device(tx_driver=txd)
        self.assertEqual(True, d.can_transmit())
        self.assertEqual(txd, d.get_tx_driver())
    
    def test_tx_mode_noop(self):
        '''
        With no TX driver, set_transmitting is a noop.
        
        This was chosen as the most robust handling of the erroneous operation.
        '''
        d = Device(rx_driver=_TestRXDriver())
        d.set_transmitting(True)
        d.set_transmitting(False)
    
    def test_tx_mode_actual(self):
        log = []
        txd = _TestTXDriver(log)
        d = Device(rx_driver=_TestRXDriver(), tx_driver=txd)
        def midpoint_hook():
            log.append('H')
        # Either TX driver receives the hook (!= case) or the hook is called directly (== case)
        d.set_transmitting(True, midpoint_hook)
        self.assertEqual(log, [(True, midpoint_hook)])
        d.set_transmitting(True, midpoint_hook)
        self.assertEqual(log, [(True, midpoint_hook), 'H'])
        d.set_transmitting(False, midpoint_hook)
        self.assertEqual(log, [(True, midpoint_hook), 'H', (False, midpoint_hook)])
        d.set_transmitting(False, midpoint_hook)
        self.assertEqual(log, [(True, midpoint_hook), 'H', (False, midpoint_hook), 'H'])
    
    # TODO VFO tests
    # TODO components tests
    # close() is tested in test_top


class _TestRXDriver(ExportedState):
    implements(IRXDriver)
    
    def get_output_type(self):
        return SignalType('IQ', 1)

    def get_tune_delay(self):
        return 0.0

    def get_usable_bandwidth(self):
        return Range([(-1, 1)])
    
    def notify_reconnecting_or_restarting(self):
        pass


class _TestTXDriver(ExportedState):
    implements(ITXDriver)
    
    def __init__(self, log):
        self.log = log
    
    def get_input_type(self):
        return SignalType('IQ', 1)
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        self.log.append((value, midpoint_hook))


class TestMergeDevices(unittest.TestCase):
    def test_name(self):
        self.assertEqual('a', merge_devices([Device(), Device(name='a')]).get_name())
        self.assertEqual('a', merge_devices([Device(name='a'), Device()]).get_name())
        self.assertEqual('a+b', merge_devices([Device(name='a'), Device(name='b')]).get_name())

    def test_components_disjoint(self):
        d = merge_devices([
            Device(components={'a': ExportedState()}),
            Device(components={'b': ExportedState()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().keys()), ['a', 'b'])

    def test_components_conflict(self):
        d = merge_devices([
            Device(components={'a': ExportedState()}),
            Device(components={'a': ExportedState()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().keys()), ['0-a', '1-a'])

    def test_vfos(self):
        d = merge_devices([
            Device(vfo_cell=_ConstantVFOCell(1)),
            Device(vfo_cell=LooseCell(key='freq', value=0, type=Range([(10, 20)]), writable=True))
        ])
        self.assertTrue(d.get_vfo_cell().isWritable())
        # TODO more testing


class TestAudioDevice(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice, self).setUpFor(
            device=AudioDevice(''))

    # Test methods provided by DeviceTestCase


class TestFrequencyShift(DeviceTestCase):
    def setUp(self):
        super(TestFrequencyShift, self).setUpFor(
            device=FrequencyShift(100.0))

    # Test methods provided by DeviceTestCase


class TestPositionedDevice(DeviceTestCase):
    def setUp(self):
        super(TestPositionedDevice, self).setUpFor(
            device=PositionedDevice(10.0, 20.0))

    # Test methods provided by DeviceTestCase

