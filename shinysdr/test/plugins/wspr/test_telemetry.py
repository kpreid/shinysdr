# Copyright 2017 Phil Frost <indigo@bitglue.com>
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

from __future__ import absolute_import, division, unicode_literals

from twisted.trial import unittest

from zope.interface.verify import verifyObject

from shinysdr.telemetry import ITelemetryMessage, ITelemetryObject
from shinysdr.plugins.wspr.telemetry import WSPRSpot, WSPRStation, IWSPRStation, grid_to_lat_long


class TestWSPRSpot(unittest.TestCase):
    def test_interface(self):
        spot = WSPRSpot(None, None, None, None, None, None, None, None)
        verifyObject(ITelemetryMessage, spot)


class TestWSPRStation(unittest.TestCase):
    def setUp(self):
        self.station = WSPRStation(None)

    def test_interface(self):
        verifyObject(ITelemetryObject, self.station)
        verifyObject(IWSPRStation, self.station)

    def test_expiry(self):
        """Stations expire 30 minutes after the last spot."""
        t = 13987317.3
        spot = WSPRSpot(t, None, None, None, None, None, None, None)
        self.station.receive(spot)
        expiry = self.station.get_object_expiry()
        self.assertIsInstance(expiry, float)
        self.assertEqual(expiry, t + 30 * 60)

        t += 600
        spot = WSPRSpot(t, None, None, None, None, None, None, None)
        self.station.receive(spot)
        expiry = self.station.get_object_expiry()
        self.assertEqual(expiry, t + 30 * 60)


class TestGridToLatLon(unittest.TestCase):
    def assertLatLongAlmostEqual(self, grid, (lat_b, lon_b)):
        lat_a, lon_a = grid_to_lat_long(grid)
        self.assertAlmostEqual(lat_a, lat_b)
        self.assertAlmostEqual(lon_a, lon_b)

    def test_valid_squares(self):
        self.assertLatLongAlmostEqual('AA00', (-89.5, -179))
        self.assertLatLongAlmostEqual('RR99', (89.5, 179))
        self.assertLatLongAlmostEqual('EN82', (42.5, -83))

    def test_valid_subsquares(self):
        self.assertLatLongAlmostEqual('AA00aa', (-90 + 2.5 / 60 / 2, -180 + 5 / 60 / 2))
        self.assertLatLongAlmostEqual('RR99xx', (90 - 2.5 / 60 / 2, 180 - 5 / 60 / 2))
        self.assertLatLongAlmostEqual('EN82fo', (42 + (14.5 * 2.5) / 60, -84 + (5.5 * 5) / 60))

    def test_case_insensitive(self):
        self.assertLatLongAlmostEqual('en82FO', (42 + (14.5 * 2.5) / 60, -84 + (5.5 * 5) / 60))

    def test_invalid_grids(self):
        self.assertRaises(ValueError, grid_to_lat_long, '1')
        self.assertRaises(ValueError, grid_to_lat_long, 'AA0')
        self.assertRaises(ValueError, grid_to_lat_long, 'AA00a')
        self.assertRaises(ValueError, grid_to_lat_long, 'AA0z')
        self.assertRaises(ValueError, grid_to_lat_long, 'AA00aaa')
