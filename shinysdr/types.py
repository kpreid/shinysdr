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

"""
Type definitions for ShinySDR value cells etc.

See docs for ValueType in this module for more information.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import array
import bisect
from collections import namedtuple
import math
import struct

import six

from zope.interface import Interface, implementer

from shinysdr.i.json import IJsonSerializable  # reexport
from shinysdr import units


__all__ = [
    'IJsonSerializable',  # reexport
]  # also appended later


def to_value_type(typeoid):
    if isinstance(typeoid, ValueType):
        return typeoid
    elif isinstance(typeoid, type):
        # TODO: Stricten this to only allow a specific set
        return PythonT(typeoid)
    else:
        raise TypeError('Don\'t know how to make a ValueType of %r' % (typeoid,))


__all__.append('to_value_type')


@implementer(IJsonSerializable)
class ValueType(object):
    """A type in the sense of "set of (permitted) values", plus coercion and hints about interpretation of the value.
    
    ValueTypes are used by shinysdr.values.BaseCell objects to define the kind of values the cell may take on.
    
    A type may be called with a value to coerce or reject the value.
    
    A Python type object may be converted to a ValueType using the to_value_type function.
    
    Conventionally, concrete subclasses of ValueType should be referred to with names like "RangeT" and their instances (actual types) like "range_t". This is in order to avoid ambiguity with naming a type versus a value of that type, given that there are also classes of types so that the normal capital/lowercase convention is not sufficient.
    """
    def to_json(self):
        """See IJsonSerializable."""
        raise NotImplementedError()
    
    def __call__(self, specimen):
        """Coerce the specimen to this type.
        
        If the specimen is not of a suitable type, raise TypeError.
        
        If the specimen is of a suitable type but out of range and this type does not choose to make it in range, raise ValueError.
        """
        raise NotImplementedError()
    
    def is_reference(self):
        return False
    
    def create_buffer(self, history_length):
        """Create and return an IDeltaBuffer suitable for values of this type.
        
        Returns None if the type does not support appending.
        
        history_length is an integer; the units depend on the type.
        """
        return None


__all__.append('ValueType')


# TODO: this is like IDeltaSubscriber but can't declare it; move code to shinysdr.interfaces so it can
class IDeltaBuffer(Interface):
    # pylint: disable=arguments-differ, signature-differs
    def get():
        """Return the current value."""

    def __call__(value):
        """Replace the current value."""
    
    def append(patch):
        """Append to the current value."""
    
    def prepend(patch):
        """Prepend to the current value."""


class PythonT(ValueType):
    """ValueType wrapper for Python types."""
    def __init__(self, python_type):
        self.__python_type = python_type
    
    def __eq__(self, other):
        return isinstance(other, PythonT) and self.__python_type == other.__python_type
    
    def __hash__(self):
        return hash(self.__python_type) ^ hash(self.__python_type)
    
    def __repr__(self):
        return '{0}({1})'.format(
            type(self).__name__,
            self.__python_type)
        
    def to_json(self):
        return python_type_registry.get(self.__python_type, None)
    
    def __call__(self, specimen):
        return self.__python_type(specimen)
    
    def create_buffer(self, history_length):
        if issubclass(self.__python_type, basestring):
            return _StringDeltaBuffer(self.__python_type(), history_length=history_length)
        else:
            return None


# TODO: Replace this raw object with a proper API
python_type_registry = {
    bool: u'boolean',
    float: u'float64',
    int: u'integer',
    long: u'integer',
    unicode: u'string',
}


__all__.append('python_type_registry')


@implementer(IDeltaBuffer)
class _StringDeltaBuffer(object):
    def __init__(self, value, history_length):
        self.__history_length = history_length
        self.__value = value
        self.__is_truncated = False
    
    def get(self):
        return self.__value

    def __call__(self, value):
        self.__is_truncated = False
        self.__truncate_and_update(value)
    
    def append(self, patch):
        self.__truncate_and_update(self.__value + patch)
    
    def prepend(self, patch):
        if self.__is_truncated:
            return
        self.__truncate_and_update(patch + self.__value)
    
    def __truncate_and_update(self, untruncated):
        self.__value = untruncated[-self.__history_length:]
        self.__is_truncated = self.__is_truncated or len(untruncated) > self.__history_length


class ConstantT(ValueType):
    """
    A single-valued type.
    """
    
    def __init__(self, value):
        self.__value = value
    
    def to_json(self):
        return {
            u'type': u'ConstantT',
            u'value': self.__value
        }
    
    def __call__(self, specimen):
        return self.__value


__all__.append('ConstantT')


class ReferenceT(ValueType):
    # TODO document
    def to_json(self):
        return u'reference'
    
    def __call__(self, specimen):
        # In the future there might be subtypes which have some criterion for accepting values
        raise TypeError('generic ReferenceT type does not coerce anything')
    
    def is_reference(self):
        return True


__all__.append('ReferenceT')


class EnumT(ValueType):
    """Type which accepts any of a fixed set of values.
    
    The values are normally Unicode strings but may be another type.
    The values may have metadata such as description text different from the value itself.
    """
    def __init__(self, values, strict=True, base_type=unicode):
        """values: dict of {value: metadata}.
        
        The metadata may be an EnumRow object, or a unicode string which will be used as the short description.
        
        If strict is False, then values not in the enum will be allowed, but they will still be coerced by base_type.
        """
        self.__strict = bool(strict)
        self.__base_type = base_type = to_value_type(base_type)
        self.__table = {
            base_type(key): EnumRow(info, associated_key=key)
            for key, info in six.iteritems(values)}
    
    def get_table(self):
        return self.__table
    
    def to_json(self):
        return {
            'type': 'EnumT',
            'table': self.__table,
        }
    
    def __call__(self, specimen):
        specimen = self.__base_type(specimen)
        if self.__strict and specimen not in self.__table:
            raise ValueError('Not a permitted value: ' + repr(specimen))
        return specimen


__all__.append('EnumT')


@implementer(IJsonSerializable)
class EnumRow(object):
    """An EnumRow object provides information about an element of an EnumT, and is also used for similar non-EnumT-related purposes.
    
    The label is a 'human-friendly' string to use in place of the enum value. If not specified it defaults to the enum value itself.
    
    The description is a string which provides information left out of the label (what might be presented as a 'tooltip'). It may be omitted (None) or a string.
    
    The sort_key is a string used to order elements for display. If not specified it defaults to the enum value itself.
    
    The label and sort_key default to the enum value itself, and otherwise must be unicode strings.
    The description may be None instead.
    """
    # TODO this complicated init needs more tests
    def __init__(self, enum_row_or_string=None, label=None, description=None, sort_key=None, associated_key=None):
        if isinstance(enum_row_or_string, EnumRow):
            if label is None:
                label = enum_row_or_string.__label
            if description is None:
                description = enum_row_or_string.__description
            if sort_key is None:
                sort_key = enum_row_or_string.__sort_key
        else:
            if label is None:
                label = unicode(enum_row_or_string) if enum_row_or_string else None
        
        self.__label = (
            unicode(label) if label is not None else
            unicode(enum_row_or_string) if enum_row_or_string is not None else
            associated_key)
        self.__description = (
            unicode(description) if description is not None else None)
        self.__sort_key = (
            unicode(sort_key) if sort_key is not None else
            unicode(associated_key) if associated_key is not None
            else associated_key)
    
    def __eq__(self, other):
        return isinstance(other, EnumRow) and self.to_json() == other.to_json()
    
    def __hash__(self):
        return hash(self.to_json())
    
    def __repr__(self):
        return u'EnumRow(label={0[label]!r}, description={0[description]!r}, sort_key={0[sort_key]!r})'.format(self.to_json())
    
    def to_json(self):
        return {
            u'type': u'EnumRow',
            u'label': self.__label,
            u'description': self.__description,
            u'sort_key': self.__sort_key
        }


__all__.append('EnumRow')


class QuantityT(ValueType):
    """Type for a quantity, that is, a number with associated units.
    
    To express a quantity with a limited range, use RangeT instead.
    """
    def __init__(self, unit=units.none, base_type=float):
        assert isinstance(unit, units.Unit)
        self.__unit = unit
        self.__base_type = to_value_type(base_type)
    
    def to_json(self):
        return {
            'type': 'QuantityT',
            'unit': self.__unit,
            'base_type': self.__base_type
        }
    
    def __call__(self, specimen):
        return self.__base_type(specimen)


__all__.append(QuantityT)


class RangeT(ValueType):
    """Type for an integer or float value with a (possibly non-contiguous) range of permitted or recommended values.
    
    If a number outside of the range is provided and the type is strict, it is coerced to the nearest value which lies inside the range.
    """
    def __init__(self, subranges, unit=units.none, strict=True, logarithmic=False, integer=False):
        """
        subranges: Array of nonoverlapping (inclusive lower bound, inclusive upper bound) in increasing order.
        strict: If false, numbers outside the subranges are permitted.
        logarithmic: Whether UI for specifying the value should operate on a logarithmic scale.
        integer: Whether the numbers should be of integer type after coercion.
        """
        assert isinstance(unit, units.Unit)

        # check that subranges are sorted and nonoverlapping
        mins = []
        maxes = []
        for i, (min_value, max_value) in enumerate(subranges):
            if not min_value <= max_value:
                raise ValueError('Invalid RangeT: subranges[{}] has min {} < max {}'.format(i, min_value, max_value))
            if maxes and not maxes[-1] < min_value:
                raise ValueError('Invalid RangeT: subranges[{}] has min {} below previous max {}'.format(i, min_value, maxes[-1]))
            mins.append(min_value)
            maxes.append(max_value)
        if not mins:
            raise ValueError('Invalid RangeT: no subranges given')
        
        self.__unit = unit
        self.__mins = mins
        self.__maxes = maxes
        self.__strict = strict
        self.__logarithmic = logarithmic
        self.__integer = integer
    
    def to_json(self):
        return {
            'type': 'RangeT',
            'subranges': zip(self.__mins, self.__maxes),
            'unit': self.__unit,
            'logarithmic': self.__logarithmic,
            'integer': self.__integer
        }
    
    def __call__(self, specimen, range_round_direction=0):
        specimen = float(specimen)
        
        if self.__integer:
            if self.__logarithmic:
                # We may eventually want other log base options; currently only 2
                if specimen <= 0:
                    specimen = self.__mins[0]
                specimen = 2 ** int(round(math.log(specimen, 2)))
            else:
                specimen = int(round(specimen))
        
        if self.__strict:
            mins = self.__mins
            maxes = self.__maxes
            
            i = bisect.bisect_right(mins, specimen) - 1
            if i < 0: i = 0
            # i is now the index of the subrange whose lower endpoint is closest to but not exceeding the specimen.
            
            if range_round_direction < 0:
                pass
            elif range_round_direction > 0:
                # Round to upper range rather than lower one, if we're not already in range.
                if i < len(mins) - 1 and specimen > maxes[i]:
                    i = i + 1
            else:
                # Round to nearest range instead of lower one.
                if i < len(mins) - 1 and mins[i + 1] - specimen < specimen - maxes[i]:
                    i = i + 1
            
            # Clamp to chosen range.
            if specimen < mins[i]:
                specimen = mins[i]
            elif specimen > maxes[i]:
                specimen = maxes[i]
        
        return specimen
    
    def __repr__(self):
        return '{0}({1[subranges]!r}, unit={1[unit]}, strict={strict!r}, logarithmic={1[logarithmic]!r}, integer={1[integer]!r})'.format(
            type(self).__name__,
            self.to_json(),
            strict=self.__strict)
    
    def __eq__(self, other):
        # pylint: disable=unidiomatic-typecheck
        return (
            type(self) == type(other) and
            self.__mins == other.__mins and
            self.__maxes == other.__maxes and
            self.__unit == other.__unit and
            self.__strict == other.__strict and
            self.__logarithmic == other.__logarithmic and
            self.__integer == other.__integer
        )
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    __hash__ = None
    
    def shifted_by(self, offset):
        mins = self.__mins
        maxes = self.__maxes
        return RangeT(
            [(mins[i] + offset, maxes[i] + offset) for i in six.moves.range(len(mins))],
            unit=self.__unit,
            strict=self.__strict,
            logarithmic=self.__logarithmic,
            integer=self.__integer and offset % 1 == 0)
    
    def get_min(self):
        return self.__mins[0]
    
    def get_max(self):
        return self.__maxes[-1]
    
    def get_single_point(self):
        """
        If this RangeT contains only a single value, return it, else None.
        """
        if len(self.__mins) != 1:
            return None
        else:
            a = self.__mins[0]
            b = self.__maxes[0]
            if a == b:
                return a
            else:
                return None


__all__.append('RangeT')


class NoticeT(ValueType):
    """Type for strings which are warnings or errors.
    
    The empty string should be used for "no error at this time".
    """
    def __init__(self, always_visible=False):
        self.__always_visible = always_visible
    
    def to_json(self):
        return {
            'type': 'NoticeT',
            'always_visible': self.__always_visible
        }
    
    def __call__(self, specimen):
        return unicode(specimen)


__all__.append('NoticeT')


class TimestampT(ValueType):
    """Type for seconds-since-epoch time values which are meaningfully displayed in relative-to-the-current-time form."""
    def __init__(self):
        pass
    
    def to_json(self):
        return {
            'type': 'TimestampT'
        }
    
    def __call__(self, specimen):
        return float(specimen)


__all__.append('TimestampT')


# TODO: This module otherwise contains only types and related, not the value implementations. Relocate once a proper place exists for it _and_ BulkDataT.
@implementer(IJsonSerializable)
class BulkDataElement(namedtuple('BulkDataElement', [
    'info',
    'data',
])):
    def to_json(self):
        unpacker = array.array(b'b')
        unpacker.fromstring(self.data)
        return [self.info, unpacker.tolist()]


__all__.append('BulkDataElement')


class BulkDataT(ValueType):
    """Type for arrays of BulkDataElement objects which, particularly, are delivered to the client in efficient binary form rather than JSON."""
    def __init__(self, info_format, array_format):
        # TODO: Document the format parameters
        self.__info_format = info_format
        # str() is for Python 2.7.6 compatibility (array.array requires a str rather than unicode string)
        self.__array_format = str(array_format)
    
    def to_json(self):
        return {
            u'type': u'BulkDataT',
            u'info_format': self.__info_format,
            u'array_format': self.__array_format,
        }
    
    def get_info_format(self):
        return self.__info_format
    
    def get_array_format(self):
        return self.__array_format
    
    def pack(self, value):
        return struct.pack(self.get_info_format(), *value.info) + value.data
    
    def __call__(self, specimen):
        raise Exception('Coerce not implemented for BulkDataT')
    
    # TODO implement coerce behavior, generally make this more well-defined
    
    def create_buffer(self, history_length):
        return _BulkDataDeltaBuffer(history_length=history_length)


__all__.append('BulkDataT')


@implementer(IDeltaBuffer)
class _BulkDataDeltaBuffer(object):
    def __init__(self, history_length):
        self.__history_length = history_length
        self.__items = []
        self.__is_truncated = False
    
    def get(self):
        return self.__items[:]  # make copy of list that is mutated

    def __call__(self, value):
        self.__is_truncated = False
        self.__items = value[:]
    
    def append(self, patch):
        self.__items.extend(patch)
        self.__truncate_and_update()
    
    def prepend(self, patch):
        if self.__is_truncated:
            return
        self.__items[:0] = patch
        self.__truncate_and_update()
    
    def __truncate_and_update(self):
        if len(self.__items) > self.__history_length:
            self.__items[:-self.__history_length] = []
            self.__is_truncated = True
