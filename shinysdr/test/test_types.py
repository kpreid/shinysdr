# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.types import Enum, Range


def _testType(self, type_obj, good, bad):
	for value in good:
		if isinstance(value, tuple):
			input, output = value
			self.assertEqual(type_obj(input), output)
		else:
			self.assertEqual(type_obj(value), value)
	for value in bad:
		self.assertRaises(ValueError, lambda: type_obj(value))


class TestTypes(unittest.TestCase):
	def test_Enum_strict(self):
		_testType(self,
			Enum({u'a': u'a', u'b': u'b'}, strict=True),
			[(u'a', u'a'), ('a', u'a')],
			[u'c', 999])

	def test_Enum_lenient(self):
		_testType(self,
			Enum({u'a': u'a', u'b': u'b'}, strict=False),
			[(u'a', u'a'), ('a', u'a'), u'c', (999, u'999')],
			[])

	def test_Range_log_integer(self):
		_testType(self,
			Range([(1, 32)], strict=True, logarithmic=True, integer=True),
			[(0, 1), 1, 2, 4, 32, (2.0, 2), (2.5, 2), (3.5, 4), (33, 32)],
			[])

	def test_Range_shifted_float(self):
		_testType(self,
			Range([(3, 4)], strict=True, logarithmic=False, integer=False).shifted_by(-3),
			[(-0.5, 0), 0, 0.25, 1, (1.5, 1)],
			[])

	def test_Range_shifted_integer(self):
		_testType(self,
			Range([(3, 4)], strict=True, logarithmic=False, integer=True).shifted_by(-3),
			[(-0.5, 0), 0, (0.25, 0), 1, (1.5, 1)],
			[])
