# -*- coding: utf-8 -*-
# Copyright 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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

from twisted.trial import unittest

from gnuradio import blocks

# Note: not testing _ConstantVFOCell, it's just a useful utility
from shinysdr.devices import _ConstantVFOCell, AudioDevice, Device, FrequencyShift, IDevice, PositionedDevice, _coerce_channel_mapping, find_audio_rx_names, merge_devices
from shinysdr.testutil import DeviceTestCase, StubComponent, StubRXDriver, StubTXDriver, state_smoke_test
from shinysdr.types import RangeT
from shinysdr.values import LooseCell, nullExportedState


class TestDevice(unittest.TestCase):
    def test_state_smoke_empty(self):
        state_smoke_test(Device())
        
    def test_state_smoke_full(self):
        state_smoke_test(Device(
            name=u'x',
            rx_driver=StubRXDriver(),
            tx_driver=StubTXDriver(),
            vfo_cell=_ConstantVFOCell(1),
            components={'c': StubComponent()}))
    
    def test_name(self):
        self.assertEqual(u'x', Device(name='x').get_name())
        self.assertEqual(None, Device().get_name())
    
    def test_close(self):
        log = set()
        Device(
            rx_driver=_ShutdownDetectorRX(log, 'rx'),
            tx_driver=_ShutdownDetectorTX(log, 'tx'),
            components={'c': _ShutdownDetector(log, 'c')}
        ).close()
        self.assertEqual(log, set(['rx', 'tx', 'c']))
    
    def test_rx_absent(self):
        d = Device()
        self.assertEqual(False, d.can_receive())
        self.assertEqual(nullExportedState, d.get_rx_driver())
    
    def test_rx_present(self):
        rxd = StubRXDriver()
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
        d = Device(rx_driver=StubRXDriver())
        d.set_transmitting(True)
        d.set_transmitting(False)
    
    def test_tx_mode_actual(self):
        log = []
        txd = _TestTXDriver(log)
        d = Device(rx_driver=StubRXDriver(), tx_driver=txd)
        
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
            Device(components={'a': StubComponent()}),
            Device(components={'b': StubComponent()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().iterkeys()), ['a', 'b'])

    def test_components_conflict(self):
        d = merge_devices([
            Device(components={'a': StubComponent()}),
            Device(components={'a': StubComponent()})
        ])
        self.assertEqual(d, IDevice(d))
        self.assertEqual(sorted(d.get_components_dict().iterkeys()), ['0-a', '1-a'])

    def test_vfos(self):
        d = merge_devices([
            Device(vfo_cell=_ConstantVFOCell(1)),
            Device(vfo_cell=LooseCell(value=0, type=RangeT([(10, 20)]), writable=True))
        ])
        self.assertTrue(d.get_vfo_cell().isWritable())
        # TODO more testing


class TestAudioDevice2ChTo1(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice2ChTo1, self).setUpFor(
            device=AudioDevice('', channel_mapping=1,
                _module=_AudioModuleStub({'': 2})))

    # Test methods provided by DeviceTestCase


class TestAudioDevice2ChTo2(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice2ChTo2, self).setUpFor(
            device=AudioDevice('', channel_mapping='IQ',
                _module=_AudioModuleStub({'': 2})))

    # Test methods provided by DeviceTestCase


class TestAudioDevice1ChTo2(DeviceTestCase):
    def setUp(self):
        super(TestAudioDevice1ChTo2, self).setUpFor(
            device=AudioDevice('', channel_mapping='IQ',
                _module=_AudioModuleStub({'': 1})))

    # Test methods provided by DeviceTestCase


class TestFindAudioRxNames(unittest.TestCase):
    def test_normal(self):
        # TODO: This test will have to change once we actually support enumerating audio devices
        self.assertEqual([''],
            find_audio_rx_names(_module=_AudioModuleStub({'': 2})))
    
    def test_none(self):
        self.assertEqual([],
            find_audio_rx_names(_module=_AudioModuleStub({})))


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


class _TestTXDriver(StubTXDriver):
    def __init__(self, log):
        super(_TestTXDriver, self).__init__()
        self.log = log
    
    def set_transmitting(self, value, midpoint_hook):
        self.log.append((value, midpoint_hook))


class _ShutdownDetector(StubComponent):
    def __init__(self, dest, key):
        super(_ShutdownDetector, self).__init__()
        self.__dest = dest
        self.__key = key
    
    def close(self):
        self.__dest.add(self.__key)


class _ShutdownDetectorRX(_ShutdownDetector, StubRXDriver):
    pass


class _ShutdownDetectorTX(_ShutdownDetector, StubTXDriver):
    pass


class _AudioModuleStub(object):
    """Stub to substitute for the gnuradio.audio module which does not talk to actual hardware.
    """
    
    def __init__(self, names):
        """
        names: dict mapping from device name to number of channels in source block
        """
        self.__names = names
    
    def source(self, sampling_rate, device_name, ok_to_block=True):
        if device_name not in self.__names:
            # unfortunately RuntimeError is the error gnuradio raises
            raise RuntimeError('_AudioModuleStub has no audio device {!r}'.format(device_name))
        noutputs = self.__names[device_name]
        # An arbitrary block that has the same output signature as the intended audio source. The tests we are doing do not ever run the flow graph, so the blocks do not need to have their inputs satisfied. We cannot use a custom hier block because hier blocks do not support variable numbers of outputs.
        if noutputs == 1:
            return blocks.vector_source_f([1])
        elif noutputs == 2:
            return blocks.complex_to_float()
        else:
            raise NotImplementedError('noutputs={!r}'.format(noutputs))
    
    def sink(self, sampling_rate, device_name, ok_to_block=True):
        raise NotImplementedError()
