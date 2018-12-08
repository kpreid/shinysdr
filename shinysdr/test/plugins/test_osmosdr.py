# Copyright 2013, 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

from shinysdr.test.testutil import DeviceTestCase
from shinysdr.types import RangeT

# If gr-osmosdr itself is not available, skip the tests, don't fail in loading.
try:
    from osmosdr import range_t, meta_range_t
    _unavailability = None
except ImportError as e:
    _unavailability = e

if not _unavailability:
    # pylint: disable=ungrouped-imports
    from shinysdr.plugins.osmosdr import OsmoSDRDevice, OsmoSDRProfile, convert_osmosdr_range, profile_from_device_string


class TestOsmoSDRDeviceCore(DeviceTestCase):
    def setUp(self):
        if _unavailability:
            raise unittest.SkipTest(_unavailability)
        super(TestOsmoSDRDeviceCore, self).setUpFor(
            device=OsmoSDRDevice('file=/dev/null,rate=100000,freq=0'))

    # Test methods provided by DeviceTestCase


# TODO: Find out if any of the device types supported by osmosdr.sink has a dummy/loopback mode, and if it does, use that to test OsmoSDRTXDriver.


class TestOsmoSDRDeviceMisc(unittest.TestCase):
    # pylint: disable=no-member
    
    def setUp(self):
        if _unavailability:
            raise unittest.SkipTest(_unavailability)
    
    def test_initial_zero_freq(self):
        # 100 MHz is a default we use
        self.assertEqual(100e6,
            OsmoSDRDevice('file=/dev/null,rate=100000,freq=0')
            .get_freq())

    def test_initial_nonzero_freq(self):
        self.assertEqual(21000,
            OsmoSDRDevice('file=/dev/null,rate=100000,freq=21000')
            .get_freq())

    def test_bandwidth_contiguous(self):
        self.assertEqual(RangeT([(-30000.0, 30000.0)]),
            OsmoSDRDevice('file=/dev/null,rate=80000', profile=OsmoSDRProfile(
                dc_offset=False))
            .get_rx_driver().get_usable_bandwidth())

    def test_bandwidth_discontiguous(self):
        self.assertEqual(RangeT([(-30000.0, -1.0), (1.0, 30000.0)]),
            OsmoSDRDevice('file=/dev/null,rate=80000', profile=OsmoSDRProfile(
                dc_offset=True))
            .get_rx_driver().get_usable_bandwidth())

    def test_bandwidth_default(self):
        self.assertEqual(RangeT([(-30000.0, 30000.0)]),
            OsmoSDRDevice('file=/dev/null,rate=80000')
            .get_rx_driver().get_usable_bandwidth())


class TestOsmoSDRProfile(unittest.TestCase):
    def setUp(self):
        if _unavailability:
            raise unittest.SkipTest(_unavailability)
    
    def test_inference(self):
        # TODO: This test shouldn't be repeating the tune_delay values from the code.
        self.assertEqual(
            OsmoSDRProfile(),
            profile_from_device_string(b''))
        # Strictly speaking, RTL devices may have DC offsets, but current production uses the R820T or similar tuners, which do not, so this is a reasonable default.
        self.assertEqual(
            OsmoSDRProfile(agc=True, dc_cancel=False, dc_offset=False, tune_delay=0.13),
            profile_from_device_string(b'rtl=0'))
        self.assertEqual(
            OsmoSDRProfile(tx=True, agc=False, dc_cancel=False, dc_offset=True, tune_delay=0.045),
            profile_from_device_string(b'hackrf=0'))
        self.assertEqual(
            OsmoSDRProfile(agc=False, dc_cancel=False, dc_offset=False, tune_delay=0.0),
            profile_from_device_string(b'file=foo.bin'))
    
    def test_parser(self):
        self.assertEqual(False, profile_from_device_string(b'testarg=\',hackrf\',rtl').dc_offset)
        self.assertEqual(True, profile_from_device_string(b'testarg=\',rtl\',hackrf').dc_offset)


class TestOsmoSDRRange(unittest.TestCase):
    def setUp(self):
        if _unavailability:
            raise unittest.SkipTest(_unavailability)
    
    def test_convert_simple(self):
        self.do_convert_test([(1, 2, 0)])

    def test_convert_stepped(self):
        self.do_convert_test([(1, 2, 1)])

    def test_convert_point(self):
        self.do_convert_test([(1, 1, 0)])
    
    def test_convert_gapped(self):
        self.do_convert_test([(0, 0, 0), (1, 2, 0)])
    
    def do_convert_test(self, range_argses):
        orange = meta_range_t()
        for range_args in range_argses:
            orange.push_back(range_t(*range_args))
        myrange = convert_osmosdr_range(orange)
        self.assertEqual(
            [(min_val, max_val) for (min_val, max_val, _) in range_argses],
            myrange.to_json()['subranges'])
