# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

import unittest

from shinysdr.blocks import MultistageChannelFilter


class TestMultistageChannelFilter(unittest.TestCase):
	def test_settings(self):
		# TODO: Test filter functionality; this only tests that the operations work
		filt = MultistageChannelFilter(input_rate=32000000, output_rate=16000, cutoff_freq=3000, transition_width=1200)
		filt.set_cutoff_freq(2900)
		filt.set_transition_width(1000)
		filt.set_center_freq(10000)
		self.assertEqual(2900, filt.get_cutoff_freq())
		self.assertEqual(1000, filt.get_transition_width())
		self.assertEqual(10000, filt.get_center_freq())

	def test_float_rates(self):
		# Either float or int rates should be accepted
		# TODO: Test filter functionality; this only tests that the operations work
		MultistageChannelFilter(input_rate=32000000.0, output_rate=16000.0, cutoff_freq=3000, transition_width=1200)
