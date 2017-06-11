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

from __future__ import absolute_import, division, unicode_literals

from twisted.trial import unittest
from zope.interface import implementer

from shinysdr.i.roots import CapTable, IEntryPoint
from shinysdr.values import ExportedState, exported_value, unserialize_exported_state


class TestCapTable(unittest.TestCase):
    def setUp(self):
        self.t = CapTable(self.__unserializer)
    
    def __unserializer(self, state):
        return unserialize_exported_state(BaseEntryPointStub, state)
    
    def test_slug(self):
        cap = self.t.add(BaseEntryPointStub(), slug='foo')
        self.assertSubstring('foo-', cap)
    
    def test_persistence(self):
        stub = BaseEntryPointStub()
        cap = self.t.add(stub)
        state = self.t.as_persistable().state_to_json()
        self.tearDown()
        self.setUp()
        self.t.as_persistable().state_from_json(state)
        self.assertEqual(stub.get_serial_number(), self.t.as_unenumerable_collection()[cap].get_serial_number())
    
    def test_deletion(self):
        stub = DeletableStub()
        cap = self.t.add(stub)
        self.assertTrue(cap in self.t.as_unenumerable_collection())
        
        # hidden when deleted flag is set
        stub.set_deleted(True)
        self.assertFalse(cap in self.t.as_unenumerable_collection())
        
        # but not actually removed (to avoid iterate/delete conflicts)
        stub.set_deleted(False)
        self.assertTrue(cap in self.t.as_unenumerable_collection())
        
        # and actually removed after a garbage_collect
        stub.set_deleted(True)
        self.t.garbage_collect()
        stub.set_deleted(False)
        self.assertFalse(cap in self.t.as_unenumerable_collection())


# pylint: disable=global-statement
# We need unique identifiers that are persistable, otherwise just fresh objects would do.
_counter = 0


@implementer(IEntryPoint)
class BaseEntryPointStub(ExportedState):
    def __init__(self, serial_number=None):
        global _counter
        if serial_number is None:
            serial_number = _counter
            _counter += 1
        self.__serial_number = serial_number
    
    def get_type(self):
        return 'footype'
    
    def get_entry_point_slug(self):
        return ''
    
    def entry_point_is_deleted(self):
        return False
    
    def entry_point_what_to_do(self):
        raise NotImplementedError()
    
    @exported_value(type=int, persists=True, parameter='serial_number', changes='never')
    def get_serial_number(self):
        return self.__serial_number


class DeletableStub(BaseEntryPointStub):
    __deleted = False
    
    def set_deleted(self, value):
        self.__deleted = value
    
    def entry_point_is_deleted(self):
        return self.__deleted
    
    def entry_point_what_to_do(self):
        raise NotImplementedError()
