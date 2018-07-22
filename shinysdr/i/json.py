# Copyright 2013, 2014, 2015, 2016, 2018 Kevin Reid <kpreid@switchb.org>
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

"""Customized JSON serialization for persistence and networking."""

from __future__ import absolute_import, division, print_function, unicode_literals

import json

import six

from zope.interface import Interface


# not itself a type in the sense meant here, but the least-wrong-so-far place to put this as it is used by types
# This should be referenced from external code as shinysdr.types.IJsonSerializable.
class IJsonSerializable(Interface):
    """Value objects which can be serialized as JSON structures.
    
    Only value objects, not things like ExportedState, should implement this interface.
    """
    def to_json(self):
        """Return a JSON representation of this object.
        
        The representation should be a JSON object (dict) which has a key u'type' whose value is a string uniquely identifying the class (loosely speaking) being represented. No well-defined namespace organization has yet been established for these type strings.
        """


# JSONEncoder configured for ShinySDR API use.
# Do not use this directly; use serialize() instead.
_json_encoder_for_serial = json.JSONEncoder(
    ensure_ascii=False,
    check_circular=False,
    allow_nan=True,
    sort_keys=True,
    separators=(',', ':'))


def serialize(obj):
    """JSON-encode values for clients, both HTTP and state stream WebSocket."""
    structure = transform_for_json(obj)
    # Python 2's JSONEncoder is not 100% consistent about which type of string it returns when ensure_ascii is false
    return unicode(_json_encoder_for_serial.encode(structure))


def transform_for_json(obj):
    """Replaces serializable objects in a data structure with JSON-compatible representations.

    Use serialize() to produce a JSON string instead of this, unless this is what you need."""
    # Cannot implement this using the default hook in JSONEncoder because we want to override the behavior for namedtuples (normally treated as tuples), which cannot be done otherwise.
    if IJsonSerializable.providedBy(obj):
        return transform_for_json(obj.to_json())
    elif isinstance(obj, tuple) and hasattr(obj, '_asdict'):  # namedtuple
        # TODO: Consider replreplacing all uses of this generic namedtuple handling with IJsonSerializable now that we have that.
        return {k: transform_for_json(v) for k, v in six.iteritems(obj._asdict())}
    elif isinstance(obj, dict):
        return {k: transform_for_json(v) for k, v in six.iteritems(obj)}
    elif isinstance(obj, (list, tuple)):
        return [transform_for_json(v) for v in obj]
    else:
        return obj
