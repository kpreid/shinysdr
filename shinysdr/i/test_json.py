# Copyright 2018 Kevin Reid and the ShinySDR contributors
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

from collections import namedtuple

from twisted.trial import unittest

from shinysdr.i.json import serialize, transform_for_json


SomeNamedTuple = namedtuple('SomeNamedTuple', ['x', 'y'])


class TestSerialize(unittest.TestCase):
    def test_smoke(self):
        self.assertEqual('"foo"', serialize('foo'))


class TestTransformForJson(unittest.TestCase):
    def test_default(self):
        value = {'things': [1, '2', None, True, False]}
        self.assertEqual(transform_for_json(value), value)

    def test_tuple(self):
        """Test that the namedtuple special case does not affect regular tuples, other than by turning them into lists."""
        self.assertEqual(transform_for_json((1, (2, 3))), [1, [2, 3]])

    def test_namedtuple(self):
        self.assertEqual(
            transform_for_json([SomeNamedTuple([1], SomeNamedTuple(2, 3))]),
            [{'x': [1], 'y': {'x': 2, 'y': 3}}])
