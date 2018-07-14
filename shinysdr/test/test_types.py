# -*- coding: utf-8 -*-
# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

import six

from twisted.trial import unittest

from shinysdr.types import BulkDataElement, BulkDataT, ConstantT, EnumT, EnumRow, RangeT, to_value_type
from shinysdr import units


def _test_coerce_cases(self, type_obj, good, bad):
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


class TestPythonT(unittest.TestCase):
    def test_coerce_unicode(self):
        """Coercion behavior is inherited from the Python type's __call__."""
        if six.PY2:
            _test_coerce_cases(self,
                to_value_type(six.text_type),
                good=[
                    '', 
                    'hello world',
                    '↑',
                    (None, 'None'),
                    (b'x', 'x'),
                    (1, '1'),
                    ([], '[]'),
                ],
                bad=[
                    b'\xFF',  # encoding failure
                ])
        else:
            _test_coerce_cases(self,
                to_value_type(six.text_type),
                good=[
                    '', 
                    'hello world',
                    '↑',
                    (None, 'None'),
                    (b'x', "b'x'"),
                    (b'\xFF', "b'\\xff'"),
                    (1, '1'),
                    ([], '[]'),
                ],
                bad=[])
    
    def test_string_buffer_append_and_truncate(self):
        # TODO: add more tests
        buf = to_value_type(six.text_type).create_buffer(history_length=5)
        buf.append('aa')
        buf.append('bb')
        self.assertEqual(buf.get(), 'aabb')
        buf.append('cc')
        self.assertEqual(buf.get(), 'abbcc')


class TestConstantT(unittest.TestCase):
    longMessage = True
    
    def test_serial(self):
        self.assertEqual({u'type': u'ConstantT', u'value': 1}, ConstantT(1).to_json())
    
    def test_run(self):
        _test_coerce_cases(self,
            ConstantT(1),
            [1, 1.0, (None, 1), ('foo', 1)],
            [])


class TestEnumT(unittest.TestCase):
    longMessage = True
    
    def test_strict(self):
        _test_coerce_cases(self,
            EnumT({u'a': u'a', u'b': u'b'}, strict=True),
            [(u'a', u'a'), ('a', u'a')],
            [u'c', 999])

    def test_strict_by_default(self):
        _test_coerce_cases(self,
            EnumT({u'a': u'a', u'b': u'b'}),
            [(u'a', u'a'), ('a', u'a')],
            [u'c', 999])

    def test_lenient(self):
        _test_coerce_cases(self,
            EnumT({u'a': u'a', u'b': u'b'}, strict=False),
            [(u'a', u'a'), ('a', u'a'), u'c', (999, u'999')],
            [])
    
    def test_values(self):
        enum = EnumT({u'a': u'adesc'})
        self.assertEquals(
            enum.get_table(),
            {u'a': EnumRow(u'adesc', associated_key=u'a')})
    
    def test_metadata_simple(self):
        self.assertEquals(
            self.__row(u'desc').to_json(),
            {
                u'type': u'EnumRow',
                u'label': u'desc',
                u'description': None,
                u'sort_key': u'key',
            })
    
    def test_metadata_partial(self):
        self.assertEquals(
            self.__row(EnumRow(label='a')).to_json(),
            {
                u'type': u'EnumRow',
                u'label': u'a',
                u'description': None,
                u'sort_key': u'key',
            })
    
    def test_metadata_explicit(self):
        self.assertEquals(
            self.__row(EnumRow(label='a', description='b', sort_key='c')).to_json(),
            {
                u'type': u'EnumRow',
                u'label': u'a',
                u'description': u'b',
                u'sort_key': u'c',
            })
    
    def test_metadata_empty_label(self):
        self.assertEquals(
            self.__row(EnumRow(label='')).to_json(),
            {
                u'type': u'EnumRow',
                u'label': u'',
                u'description': None,
                u'sort_key': u'key',
            })
    
    def __row(self, row):
        return EnumT({u'key': row}).get_table()[u'key']


class TestRangeT(unittest.TestCase):
    longMessage = True
    
    def test_construction(self):
        self.assertRaises(ValueError, lambda: RangeT([]))
        self.assertRaises(ValueError, lambda: RangeT([(2, 1)]))
        self.assertRaises(ValueError, lambda: RangeT([(1, 2), (2, 3)]))
    
    def test_discrete(self):
        _test_coerce_cases(self,
            RangeT([(1, 1), (2, 3), (5, 5)], strict=True, integer=False),
            [(0, 1), 1, (1.49, 1), (1.50, 1), (1.51, 2), 2, 2.5, 3, (4, 3), (4.1, 5), 5, (6, 5)],
            [])

    def test_log_integer(self):
        _test_coerce_cases(self,
            RangeT([(1, 32)], strict=True, logarithmic=True, integer=True),
            [(0, 1), 1, 2, 4, 32, (2.0, 2), (2.5, 2), (3.5, 4), (33, 32)],
            [])

    def test_shifted_float(self):
        _test_coerce_cases(self,
            RangeT([(3, 4)], strict=True, logarithmic=False, integer=False).shifted_by(-3),
            [(-0.5, 0), 0, 0.25, 1, (1.5, 1)],
            [])

    def test_shifted_integer(self):
        _test_coerce_cases(self,
            RangeT([(3, 4)], strict=True, logarithmic=False, integer=True).shifted_by(-3),
            [(-0.5, 0), 0, (0.25, 0), 1, (1.5, 1)],
            [])

    def test_rounding_at_ends_single(self):
        self.assertEqual(RangeT([[1, 3]])(0, range_round_direction=-1), 1)
        self.assertEqual(RangeT([[1, 3]])(2, range_round_direction=-1), 2)
        self.assertEqual(RangeT([[1, 3]])(4, range_round_direction=-1), 3)
        self.assertEqual(RangeT([[1, 3]])(0, range_round_direction=+1), 1)
        self.assertEqual(RangeT([[1, 3]])(2, range_round_direction=+1), 2)
        self.assertEqual(RangeT([[1, 3]])(4, range_round_direction=+1), 3)
    
    def test_rounding_in_gap(self):
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.4, range_round_direction=0), 2)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.4, range_round_direction=-1), 2)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.4, range_round_direction=+1), 3)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.6, range_round_direction=-1), 2)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.6, range_round_direction=+1), 3)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(2.6, range_round_direction=0), 3)
    
    def test_rounding_at_ends_split(self):
        self.assertEqual(RangeT([[1, 2], [3, 4]])(0, range_round_direction=0), 1)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(0, range_round_direction=-1), 1)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(0, range_round_direction=+1), 1)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(5, range_round_direction=0), 4)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(5, range_round_direction=-1), 4)
        self.assertEqual(RangeT([[1, 2], [3, 4]])(5, range_round_direction=+1), 4)
    
    def test_repr(self):
        self.assertEqual('RangeT([(1, 2), (3, 4)], unit=, strict=True, logarithmic=False, integer=False)',
                         repr(RangeT([(1, 2), (3, 4)])))
        self.assertEqual('RangeT([(1, 2), (3, 4)], unit=dB, strict=True, logarithmic=False, integer=False)',
                         repr(RangeT([(1, 2), (3, 4)], unit=units.dB)))
        self.assertEqual('RangeT([(1, 2), (3, 4)], unit=, strict=False, logarithmic=False, integer=False)',
                         repr(RangeT([(1, 2), (3, 4)], strict=False)))
        self.assertEqual('RangeT([(1, 2), (3, 4)], unit=, strict=True, logarithmic=True, integer=False)',
                         repr(RangeT([(1, 2), (3, 4)], logarithmic=True)))
        self.assertEqual('RangeT([(1, 2), (3, 4)], unit=, strict=True, logarithmic=False, integer=True)',
                         repr(RangeT([(1, 2), (3, 4)], integer=True)))

    def test_equal(self):
        self.assertEqual(RangeT([(1, 2), (3, 4)]),
                         RangeT([(1, 2), (3, 4)]))
        self.assertEqual(RangeT([(1, 2), (3, 4)], integer=True, logarithmic=True),
                         RangeT([(1, 2), (3, 4)], integer=True, logarithmic=True))
        self.assertNotEqual(RangeT([(1, 2), (3, 4)]),
                            RangeT([(0, 2), (3, 4)]))
        self.assertNotEqual(RangeT([(1, 2)]),
                            RangeT([(1, 2)], integer=True))
        self.assertNotEqual(RangeT([(1, 2)]),
                            RangeT([(1, 2)], logarithmic=True))
        self.assertNotEqual(RangeT([(1, 2)]),
                            RangeT([(1, 2)], strict=False))


class TestBulkData(unittest.TestCase):
    def test_element_serialization(self):
        self.assertEqual(
            BulkDataElement(info=(123,), data=b'\xFF').to_json(),
            [(123,), [-1]])
    
    def test_buffer_append_and_truncate(self):
        # TODO: add more tests
        buf = BulkDataT('', '').create_buffer(history_length=2)
        buf.append([BulkDataElement(info=(), data=b'\x01')])
        buf.append([BulkDataElement(info=(), data=b'\x02')])
        self.assertEqual(buf.get(), [
            BulkDataElement(info=(), data=b'\x01'),
            BulkDataElement(info=(), data=b'\x02')])
        buf.append([BulkDataElement(info=(), data=b'\x03')])
        self.assertEqual(buf.get(), [
            BulkDataElement(info=(), data=b'\x02'),
            BulkDataElement(info=(), data=b'\x03')])
