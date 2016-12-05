# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

# TODO explain better
"""
Type definitions for ShinySDR value cells etc.
"""

from __future__ import absolute_import, division

import bisect
import math

from zope.interface import Interface, implements


# not itself a type in the sense meant here, but the least-wrong-so-far place to put this as it is used by types
class IJsonSerializable(Interface):
    """Value objects which can be serialized as JSON structures.
    
    Only value objects, not things like ExportedState, should implement this interface.
    """
    def to_json(self):
        """Return a JSON representation of this object.
        
        The representation should be a JSON object (dict) which has a key u'type' whose value is a string uniquely identifying the class (loosely speaking) being represented. No well-defined namespace organization has yet been established for these type strings.
        """


def to_value_type(typeoid):
    if isinstance(typeoid, ValueType):
        return typeoid
    elif isinstance(typeoid, type):
        # TODO: Stricten this to only allow a specific set
        return BareType(typeoid)
    else:
        raise TypeError('Don\'t know how to make a ValueType of %r' % (typeoid,))


class ValueType(object):
    """
    A type in the sense of "set of values", plus coercion and other hints.
    """
    implements(IJsonSerializable)
    def to_json(self):
        """See IJsonSerializable."""
        raise NotImplementedError()
    
    def __call__(self, specimen):
        """
        Coerce the specimen to this type.
        
        If the specimen is not of a suitable type, raise TypeError.
        
        If the specimen is of a suitable type but out of range and this type does not choose to make it in range, raise ValueError.
        """
        raise NotImplementedError()
    
    def is_reference(self):
        return False


class BareType(ValueType):
    """
    ValueType wrapper for Python types.
    """
    def __init__(self, python_type):
        self.__python_type = python_type
    
    def __cmp__(self, other):
        if not isinstance(other, BareType):
            return cmp(id(self), id(other))  # dummy
        else:
            return cmp(self.__python_type, other.__python_type)
    
    def __hash__(self):
        return hash(self.__python_type) ^ hash(self.__python_type)

    def to_json(self):
        return bare_type_registry.get(self.__python_type, None)
    
    def __call__(self, specimen):
        return self.__python_type(specimen)


# TODO: Replace this raw object with a proper API
bare_type_registry = {
    bool: u'boolean',
    float: u'float64',
    int: u'integer',
    long: u'integer',
}


class Constant(ValueType):
    """
    A single-valued type.
    """
    
    def __init__(self, value):
        self.__value = value
    
    def to_json(self):
        return {
            u'type': u'constant',
            u'value': self.__value
        }
    
    def __call__(self, specimen):
        return self.__value


class Reference(ValueType):
    def to_json(self):
        return u'block'
    
    def __call__(self, specimen):
        # In the future there might be subtypes which have some criterion for accepting values
        raise TypeError('generic Reference type does not coerce anything')
    
    def is_reference(self):
        return True


class Enum(ValueType):
    """An Enum type accepts any of a fixed set of values.
    
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
            for key, info in values.iteritems()}
    
    def get_table(self):
        return self.__table
    
    def to_json(self):
        return {
            'type': 'enum',
            'table': self.__table,
        }
    
    def __call__(self, specimen):
        specimen = self.__base_type(specimen)
        if self.__strict and specimen not in self.__table:
            raise ValueError('Not a permitted value: ' + repr(specimen))
        return specimen


class EnumRow(object):
    """An EnumRow object provides information about an element of an Enum type, and is also used for similar non-Enum-related purposes.
    
    The label is a 'human-friendly' string to use in place of the enum value. If not specified it defaults to the enum value itself.
    
    The description is a string which provides information left out of the label (what might be presented as a 'tooltip'). It may be omitted (None) or a string.
    
    The sort_key is a string used to order elements for display. If not specified it defaults to the enum value itself.
    
    The label and sort_key default to the enum value itself, and otherwise must be unicode strings.
    The description may be None instead.
    """
    implements(IJsonSerializable)
    
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
    
    def __cmp__(self, other):
        if not isinstance(other, EnumRow):
            return cmp(id(self), id(other))  # dummy
        else:
            return cmp(self.to_json(), other.to_json())
    
    def __hash__(self):
        return hash(self.to_json())
    
    def to_json(self):
        return {
            u'type': u'EnumRow',
            u'label': self.__label,
            u'description': self.__description,
            u'sort_key': self.__sort_key
        }


class Range(ValueType):
    def __init__(self, subranges, strict=True, logarithmic=False, integer=False):
        # TODO validate subranges are sorted
        self.__mins = [min_value for (min_value, max_value) in subranges]
        self.__maxes = [max_value for (min_value, max_value) in subranges]
        self.__strict = strict
        self.__logarithmic = logarithmic
        self.__integer = integer
    
    def to_json(self):
        return {
            'type': 'range',
            'subranges': zip(self.__mins, self.__maxes),
            'logarithmic': self.__logarithmic,
            'integer': self.__integer
        }
    
    def __call__(self, specimen):
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
            # i is now the index of the subrange whose lower endpoint is closest to the specimen.
            
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
        return '%s(%r, strict=%r, logarithmic=%r, integer=%r)' % (type(self).__name__, zip(self.__mins, self.__maxes), self.__strict, self.__logarithmic, self.__integer)
    
    def __eq__(self, other):
        # pylint: disable=unidiomatic-typecheck
        return (
            type(self) == type(other) and
            self.__mins == other.__mins and
            self.__maxes == other.__maxes and
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
        return Range(
            [(mins[i] + offset, maxes[i] + offset) for i in xrange(len(mins))],
            strict=self.__strict,
            logarithmic=self.__logarithmic,
            integer=self.__integer and offset % 1 == 0)
    
    def get_min(self):
        return self.__mins[0]
    
    def get_max(self):
        return self.__maxes[-1]
    
    def get_single_point(self):
        """
        If this Range contains only a single value, return it, else None.
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


class Notice(ValueType):
    def __init__(self, always_visible=False):
        self.__always_visible = always_visible
    
    def to_json(self):
        return {
            'type': 'notice',
            'always_visible': self.__always_visible
        }
    
    def __call__(self, specimen):
        return unicode(specimen)


class Timestamp(ValueType):
    def __init__(self):
        pass
    
    def to_json(self):
        return {
            'type': 'Timestamp'
        }
    
    def __call__(self, specimen):
        return float(specimen)


class BulkDataType(ValueType):
    def __init__(self, info_format, array_format):
        self.__info_format = info_format
        self.__array_format = array_format
    
    def to_json(self):
        return {
            u'type': u'bulk_data',
            u'info_format': self.__info_format,
            u'array_format': self.__array_format,
        }
    
    def get_info_format(self):
        return self.__info_format
    
    def get_array_format(self):
        return self.__array_format
    
    def __call__(self, specimen):
        raise Exception('Coerce not implemented for BulkDataType')
    
    # TODO implement coerce behavior, generally make this more well-defined
