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

import numpy
import numpy.testing

from shinysdr.plugins import rtty
#from shinysdr.test.testutil import DemodulatorTester

# disable: mode is disabled so we can't test it
# class TestRTTY(unittest.TestCase):
#     def __make(self):
#     def test_common(self):
#         with DemodulatorTester('RTTY'):
#             pass


class TestRTTYEncoder(unittest.TestCase):
    def setUp(self):
        # self.encoder = rtty.RTTYEncoder()
        pass
    
    def __wrap(self, data_bits):
        out = [0, 0]
        for b in data_bits:
            out.append(b)
            out.append(b)
        out.append(1)
        out.append(1)
        out.append(1)
        return out
    
    def __run_encoder(self, input_chars):
        return rtty._encode_rtty_alloc(
            numpy.array(map(ord, input_chars), dtype=numpy.uint8))
    
    def test_basic(self):
        # pylint: disable=no-member
        # (pylint glitch)
        
        # TODO wrong assert
        numpy.testing.assert_array_equal(self.__run_encoder('QE'), numpy.array(
            self.__wrap([1, 1, 1, 0, 1]) +
            self.__wrap([1, 0, 0, 0, 0]), dtype=numpy.float32))
