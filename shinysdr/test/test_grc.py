# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

from shinysdr import grc
from shinysdr.plugins.basic_demod import AMModulator, NFMDemodulator, UnselectiveAMDemodulator


class TestDemodulatorAdapter(unittest.TestCase):
    def test_stereo_resample(self):
        # AM-unsel is an example of a stereo demodulator
        adapter = grc.DemodulatorAdapter(mode='AM-unsel', input_rate=100000, output_rate=22050)
        self.assertIsInstance(adapter.get_demodulator(), UnselectiveAMDemodulator)
        self.assertNotEqual(adapter.get_demodulator().get_output_type().get_sample_rate(), 22050)
    
    def test_mono_resample(self):
        # NFM is an example of a mono demodulator
        adapter = grc.DemodulatorAdapter(mode='NFM', input_rate=100000, output_rate=22050)
        self.assertIsInstance(adapter.get_demodulator(), NFMDemodulator)
        self.assertNotEqual(adapter.get_demodulator().get_output_type().get_sample_rate(), 22050)
    
    def test_stereo_direct(self):
        adapter = grc.DemodulatorAdapter(mode='AM-unsel', input_rate=100000, output_rate=10000)
        self.assertIsInstance(adapter.get_demodulator(), UnselectiveAMDemodulator)
        self.assertEqual(adapter.get_demodulator().get_output_type().get_sample_rate(), 10000)
    
    def test_mono_direct(self):
        adapter = grc.DemodulatorAdapter(mode='NFM', input_rate=100000, output_rate=10000)
        self.assertIsInstance(adapter.get_demodulator(), NFMDemodulator)
        self.assertEqual(adapter.get_demodulator().get_output_type().get_sample_rate(), 10000)


class TestModulatorAdapter(unittest.TestCase):
    def test_direct(self):
        adapter = grc.ModulatorAdapter(mode='AM', input_rate=10000, output_rate=10000)
        self.assertIsInstance(adapter.get_modulator(), AMModulator)
        self.assertEqual(adapter.get_modulator().get_input_type().get_sample_rate(), 10000)
        self.assertEqual(adapter.get_modulator().get_output_type().get_sample_rate(), 10000)

    def test_resample(self):
        adapter = grc.ModulatorAdapter(mode='AM', input_rate=20000, output_rate=20000)
        self.assertIsInstance(adapter.get_modulator(), AMModulator)
        self.assertNotEqual(adapter.get_modulator().get_input_type().get_sample_rate(), 20000)
        self.assertNotEqual(adapter.get_modulator().get_output_type().get_sample_rate(), 20000)
