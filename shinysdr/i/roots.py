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

import base64
import os

import six

from zope.interface import Interface

from shinysdr.values import CellDict, CollectionState


__all__ = []  # appended later


class CapTable(object):
    def __init__(self, unserializer):
        self.__forward = CellDict(dynamic=True)
        # self.__reverse = {}
        self.__collection = _CapTableCollection(self)
        self.__ps = _CapTablePersistenceShim(self, unserializer=unserializer)
    
    def add(self, target, cap=None, slug=''):
        target = IEntryPoint(target)
        # if target in self.__reverse:
        #     actual_cap = self.__reverse[target]
        #     if cap is not None and cap != actual_cap:
        #         # TODO we may want to allow this eventually ...
        #         raise KeyError('Cannot insert one object with two caps')
        #     return actual_cap
        if cap is None:
            cap = generate_cap(slug=slug)
        self.__forward[cap] = target
        return cap
    
    def items(self):
        # TODO rethink this interface
        # note that this exposes a "during iteration, cannot delete" condition
        for cap, target in six.iteritems(self.__forward):
            if not target.entry_point_is_deleted():
                yield cap, target
    
    def garbage_collect(self):
        # TODO rethink this
        delete = []
        for cap, target in six.iteritems(self.__forward):
            if target.entry_point_is_deleted():
                delete.append(cap)
        for cap in delete:
            del self.__forward[cap]
    
    def as_unenumerable_collection(self):
        return self.__collection
    
    def as_persistable(self):
        # note that this doesn't do the prompt deletion thing
        return self.__ps
    
    def _get_cap_dict(self):
        # for use by facets in this module only
        return self.__forward
    
    def _get_entry(self, cap):
        # for use by facets in this module only
        if cap not in self.__forward:
            return None
        target = self.__forward[cap]
        if target.entry_point_is_deleted():
            return None
        return target


__all__.append('CapTable')


class IEntryPoint(Interface):
    def get_type():
        """Returns type for persistence... TODO explain or replace this."""
    
    def entry_point_is_deleted():
        """Returns whether this entry point's existence is to be hidden and, when CapTable.garbage_collect is called, removed."""


__all__.append('IEntryPoint')


class _CapTablePersistenceShim(CollectionState):
    def __init__(self, cap_table, unserializer):
        self.__cap_table = cap_table
        self.__unserializer = unserializer
        CollectionState.__init__(self, cap_table._get_cap_dict())
    
    def state_insert(self, key, desc):
        o = self.__unserializer(desc)
        self.__cap_table._get_cap_dict()[key] = o


class _CapTableCollection(object):
    def __init__(self, cap_table):
        self.__get_entry = cap_table._get_entry
    
    def __contains__(self, key):
        # sanity check: if we get bytes instead, something is broken
        if not isinstance(key, six.text_type):
            raise TypeError('caps must be unicode')
        return self.__get_entry(key) is not None
    
    def __getitem__(self, key):
        # sanity check: if we get bytes instead, something is broken
        if not isinstance(key, six.text_type):
            raise TypeError('caps must be unicode')
        target = self.__get_entry(key)
        if target is None:
            raise KeyError('cap not found')
        else:
            return target


def generate_cap(slug=''):
    cap = unicode(base64.urlsafe_b64encode(os.urandom(128 // 8)).replace('=', ''))
    if slug:
        cap = slug + '-' + cap
    return cap


__all__.append('generate_cap')
