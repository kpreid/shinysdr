# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.signals import no_signal, SignalType


class TestSignalType(unittest.TestCase):
    def test_validation(self):
        self.assertRaises(TypeError, lambda: SignalType(kind='NONE', sample_rate=None))
        self.assertRaises(ValueError, lambda: SignalType(kind='NONE', sample_rate=0.1))
        self.assertRaises(ValueError, lambda: SignalType(kind='FOO', sample_rate=1.0))
        self.assertRaises(ValueError, lambda: SignalType(kind='IQ', sample_rate=-1.0))
        self.assertRaises(ValueError, lambda: SignalType(kind='IQ', sample_rate=0.0))
    
    def test_constants(self):
        self.assertEquals(
            no_signal,
            SignalType(kind='NONE', sample_rate=0))
    
    def test_eq(self):
        self.assertEquals(
            no_signal,
            no_signal)
        self.assertEquals(
            SignalType(kind='IQ', sample_rate=1),
            SignalType(kind='IQ', sample_rate=1))
        self.assertNotEquals(
            no_signal,
            SignalType(kind='IQ', sample_rate=1))
        self.assertNotEquals(
            SignalType(kind='IQ', sample_rate=1),
            SignalType(kind='IQ', sample_rate=2))
        self.assertNotEquals(
            SignalType(kind='USB', sample_rate=1),
            SignalType(kind='LSB', sample_rate=1))
    
    def test_sample_rate(self):
        self.assertIsInstance(SignalType(kind='IQ', sample_rate=1).get_sample_rate(), float)
        self.assertIsInstance(no_signal.get_sample_rate(), float)
        self.assertEquals(123, SignalType(kind='IQ', sample_rate=123).get_sample_rate())
        self.assertEquals(0, no_signal.get_sample_rate())
    
    def test_compatibility(self):
        def c(a, b):
            return a.compatible_items(b)
        
        self.assertTrue(c(
            SignalType(kind='IQ', sample_rate=1),
            SignalType(kind='IQ', sample_rate=2)))
        self.assertFalse(c(
            SignalType(kind='IQ', sample_rate=1),
            SignalType(kind='MONO', sample_rate=1)))
