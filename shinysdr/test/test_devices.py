# -*- coding: utf-8 -*-
# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from gnuradio import gr

# Note: not testing _ConstantVFOCell, it's just a useful utility
from shinysdr.devices import _ConstantVFOCell, AudioDevice, Device, FrequencyShift, IComponent, IDevice, IRXDriver, ITXDriver, PositionedDevice, _coerce_channel_mapping, merge_devices
from shinysdr.signals import SignalType
from shinysdr.test.testutil import DeviceTestCase
from shinysdr.types import RangeT
from shinysdr.values import ExportedState, LooseCell, nullExportedState


class TestDevice(unittest.TestCase):
    def test_name(self):
        self.assertEqual(u'x', Device(name='x').get_name())
        self.assertEqual(None, Device().get_name())
    
    def test_close(self):
        l = set()
        Device(
            rx_driver=_ShutdownDetector(l, 'rx'),
            tx_driver=_ShutdownDetector(l, 'tx'),
            components={'c': _ShutdownDetector(l, 'c')}
        ).close()
        self.assertEqual(l, set(['rx', 'tx', 'c']))
    
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
        """
        With no TX driver, set_transmitting is a noop.
        
        This was chosen as the most robust handling of the erroneous operation.
        """
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


class TestMergeDevices(unittest.TestCase):
    def test_name(self):
        self.assertEqual('a', merge_devices([Device(), Device(name='a')]).get_name())
        self.assertEqual('a', merge_devices([Device(name='a'), Device()]).get_name())
        self.assertEqual('a+b', merge_devices([Device(name='a'), Device(name='b')]).get_name())

    def test_components_disjoint(self):
        d = merge_devices([
            Device(components={'a': _StubComponent()}),
            Device(components={'b': _StubComponent()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().iterkeys()), ['a', 'b'])

    def test_components_conflict(self):
        d = merge_devices([
            Device(components={'a': _StubComponent()}),
            Device(components={'a': _StubComponent()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().iterkeys()), ['0-a', '1-a'])

    def test_vfos(self):
        d = merge_devices([
            Device(vfo_cell=_ConstantVFOCell(1)),
            Device(vfo_cell=LooseCell(key='freq', value=0, type=RangeT([(10, 20)]), writable=True))
        ])
        self.assertTrue(d.get_vfo_cell().isWritable())
        # TODO more testing


class TestAudioDevice1Ch(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice1Ch, self).setUpFor(
            device=AudioDevice('', channel_mapping=1))

    # Test methods provided by DeviceTestCase


class TestAudioDevice2Ch(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice2Ch, self).setUpFor(
            device=AudioDevice('', channel_mapping='IQ'))

    # Test methods provided by DeviceTestCase


class TestAudioDeviceChannels(unittest.TestCase):
    """Tests for _coerce_channel_mapping.
    
    This is an internal helper for AudioDevice, but it is complex and it would be impractical to test otherwise, as the test would constitute checking for the expected signal from an AudioDevice."""
    def test_one_channel_shorthand(self):
        self.assertEqual(_coerce_channel_mapping(1), [[1]])
        self.assertEqual(_coerce_channel_mapping(2), [[0, 1]])
        self.assertEqual(_coerce_channel_mapping(3), [[0, 0, 1]])
    
    def test_iq_shorthand(self):
        self.assertEqual(_coerce_channel_mapping('IQ'), [[1, 0], [0, 1]])
        self.assertEqual(_coerce_channel_mapping('QI'), [[0, 1], [1, 0]])
    
    def test_default(self):
        self.assertEqual(_coerce_channel_mapping(None),
                         _coerce_channel_mapping('IQ'))
    
    def test_matrix(self):
        self.assertEqual(_coerce_channel_mapping([[1], [2]]), [[1], [2]])
        self.assertEqual(_coerce_channel_mapping([[1, 2], [3, 4]]), [[1, 2], [3, 4]])
        self.assertEqual(_coerce_channel_mapping([[1, 2, 3], [4, 5, 6]]), [[1, 2, 3], [4, 5, 6]])
    
    def test_bad_type(self):
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping('foo'))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping(object()))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([object()]))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([[0], [object()]]))
    
    def test_bad_size(self):
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping(0))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([]))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([[]]))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([[], []]))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([[1, 2], []]))
        self.assertRaises(TypeError, lambda: _coerce_channel_mapping([[1], [2, 3]]))


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


class _TestRXDriver(ExportedState):
    implements(IRXDriver)
    
    def get_output_type(self):
        return SignalType('IQ', 1)

    def get_tune_delay(self):
        return 0.0

    def get_usable_bandwidth(self):
        return RangeT([(-1, 1)])
    
    def close(self):
        pass
    
    def notify_reconnecting_or_restarting(self):
        pass


class _TestTXDriver(ExportedState):
    implements(ITXDriver)
    
    def __init__(self, log):
        self.log = log
    
    def get_input_type(self):
        return SignalType('IQ', 1)
    
    def close(self):
        pass
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        self.log.append((value, midpoint_hook))


class _StubComponent(ExportedState):
    implements(IComponent)
    
    def close(self):
        pass


class _ShutdownDetector(gr.hier_block2, ExportedState):
    implements(IComponent, IRXDriver, ITXDriver)

    def __init__(self, dest, key):
        gr.hier_block2.__init__(
            self, type(self).__name__,
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
        return RangeT([(-1, 1)])
    
    def close(self):
        self.__dest.add(self.__key)
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        pass
