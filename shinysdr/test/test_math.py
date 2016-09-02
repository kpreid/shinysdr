# Copyright 2014, 2016 Kevin Reid <kpreid@switchb.org>
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

from math import pi

from twisted.trial import unittest

import shinysdr.math as smath


class TestFactorize(unittest.TestCase):
    longMessages = True
    
    def test_error(self):
        self.assertRaises(ValueError, lambda: smath.factorize(0))
    
    def test_cases(self):
        self.assertEqual(smath.factorize(1), [])
        self.assertEqual(smath.factorize(2), [2])
        self.assertEqual(smath.factorize(3), [3])
        self.assertEqual(smath.factorize(4), [2, 2])
        self.assertEqual(smath.factorize(5), [5])
        self.assertEqual(smath.factorize(6), [2, 3])
        self.assertEqual(smath.factorize(7), [7])
        self.assertEqual(smath.factorize(8), [2, 2, 2])
        self.assertEqual(smath.factorize(9), [3, 3])
        self.assertEqual(smath.factorize(48000), [2] * 7 + [3] + [5] * 3)


class TestSmallFactorAtLeast(unittest.TestCase):
    longMessages = True
    
    def test_exact(self):
        self.assertEqual(smath.small_factor_at_least(100, 9), 10)
        self.assertEqual(smath.small_factor_at_least(100, 10), 10)
        self.assertEqual(smath.small_factor_at_least(100, 11), 20)
    
    def test_approx(self):
        self.assertEqual(smath.small_factor_at_least(100, 9, _force_approx=True), 25)
        self.assertEqual(smath.small_factor_at_least(100, 10, _force_approx=True), 10)
        self.assertEqual(smath.small_factor_at_least(100, 11, _force_approx=True), 25)


class TestSphericalMath(unittest.TestCase):
    def test_geodesic_distance(self):
        self.assertApproximates(
            smath.geodesic_distance((0, 0), (0, 180)),
            smath._EARTH_MEAN_RADIUS_METERS * pi,
            1e-8)
        self.assertApproximates(
            smath.geodesic_distance((0, 0), (0, 90)),
            smath._EARTH_MEAN_RADIUS_METERS * pi / 2,
            1e-8)
