# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.types import Constant, Enum, EnumRow, Range


def _testType(self, type_obj, good, bad):
    for case in good:
        if isinstance(case, tuple):
            input_value, output_value = case
        else:
            input_value = case
            output_value = case
        self.assertEqual(type_obj(input_value), output_value, msg='for input %r' % (input_value,))
    for value in bad:
        # pylint: disable=cell-var-from-loop
        self.assertRaises(ValueError, lambda: type_obj(value))


class TestConstant(unittest.TestCase):
    longMessage = True
    
    def test_serial(self):
        self.assertEqual({u'type': u'constant', u'value': 1}, Constant(1).type_to_json())
    
    def test_run(self):
        _testType(self,
            Constant(1),
            [1, 1.0, (None, 1), ('foo', 1)],
            [])

class TestEnum(unittest.TestCase):
    longMessage = True
    
    def test_strict(self):
        _testType(self,
            Enum({u'a': u'a', u'b': u'b'}, strict=True),
            [(u'a', u'a'), ('a', u'a')],
            [u'c', 999])

    def test_strict_by_default(self):
        _testType(self,
            Enum({u'a': u'a', u'b': u'b'}),
            [(u'a', u'a'), ('a', u'a')],
            [u'c', 999])

    def test_lenient(self):
        _testType(self,
            Enum({u'a': u'a', u'b': u'b'}, strict=False),
            [(u'a', u'a'), ('a', u'a'), u'c', (999, u'999')],
            [])
    
    def test_values(self):
        enum = Enum({u'a': u'adesc'})
        self.assertEquals(enum.get_table(),
            {u'a': EnumRow(u'adesc', associated_key=u'a')})
    
    def test_metadata_simple(self):
        self.assertEquals(self.__row(u'desc').to_json(),
            {
                u'label': u'desc',
                u'description': None,
                u'sort_key': u'key',
            })
    
    def test_metadata_partial(self):
        self.assertEquals(self.__row(EnumRow(label='a')).to_json(),
            {
                u'label': u'a',
                u'description': None,
                u'sort_key': u'key',
            })
    
    def test_metadata_explicit(self):
        self.assertEquals(self.__row(EnumRow(label='a', description='b', sort_key='c')).to_json(),
            {
                u'label': u'a',
                u'description': u'b',
                u'sort_key': u'c',
            })
    
    def __row(self, row):
        return Enum({u'key': row}).get_table()[u'key']


class TestRange(unittest.TestCase):
    longMessage = True
    
    def test_discrete(self):
        _testType(self,
            Range([(1, 1), (2, 3), (5, 5)], strict=True, integer=False),
            [(0, 1), 1, (1.49, 1), (1.50, 1), (1.51, 2), 2, 2.5, 3, (4, 3), (4.1, 5), 5, (6, 5)],
            [])

    def test_log_integer(self):
        _testType(self,
            Range([(1, 32)], strict=True, logarithmic=True, integer=True),
            [(0, 1), 1, 2, 4, 32, (2.0, 2), (2.5, 2), (3.5, 4), (33, 32)],
            [])

    def test_shifted_float(self):
        _testType(self,
            Range([(3, 4)], strict=True, logarithmic=False, integer=False).shifted_by(-3),
            [(-0.5, 0), 0, 0.25, 1, (1.5, 1)],
            [])

    def test_shifted_integer(self):
        _testType(self,
            Range([(3, 4)], strict=True, logarithmic=False, integer=True).shifted_by(-3),
            [(-0.5, 0), 0, (0.25, 0), 1, (1.5, 1)],
            [])

    def test_repr(self):
        self.assertEqual('Range([(1, 2), (3, 4)], strict=True, logarithmic=False, integer=False)',
                         repr(Range([(1, 2), (3, 4)])))
        self.assertEqual('Range([(1, 2), (3, 4)], strict=False, logarithmic=False, integer=False)',
                         repr(Range([(1, 2), (3, 4)], strict=False)))
        self.assertEqual('Range([(1, 2), (3, 4)], strict=True, logarithmic=True, integer=False)',
                         repr(Range([(1, 2), (3, 4)], logarithmic=True)))
        self.assertEqual('Range([(1, 2), (3, 4)], strict=True, logarithmic=False, integer=True)',
                         repr(Range([(1, 2), (3, 4)], integer=True)))

    def test_equal(self):
        self.assertEqual(Range([(1, 2), (3, 4)]),
                         Range([(1, 2), (3, 4)]))
        self.assertEqual(Range([(1, 2), (3, 4)], integer=True, logarithmic=True),
                         Range([(1, 2), (3, 4)], integer=True, logarithmic=True))
        self.assertNotEqual(Range([(1, 2), (3, 4)]),
                            Range([(0, 2), (3, 4)]))
        self.assertNotEqual(Range([(1, 2)]),
                            Range([(1, 2)], integer=True))
        self.assertNotEqual(Range([(1, 2)]),
                            Range([(1, 2)], logarithmic=True))
        self.assertNotEqual(Range([(1, 2)]),
                            Range([(1, 2)], strict=False))
        