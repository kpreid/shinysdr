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

from twisted.trial import unittest

from osmosdr import range_t, meta_range_t
from shinysdr.plugins.osmosdr import convert_osmosdr_range


class TestOsmoSDRRange(unittest.TestCase):
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
			[(min, max) for (min, max, _) in range_argses],
			myrange.type_to_json()['subranges'])
