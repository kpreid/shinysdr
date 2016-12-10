# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

import os.path
import shutil
import tempfile

#from twisted.internet import defer
from twisted.internet.task import Clock
from twisted.trial import unittest

from shinysdr.i.persistence import _PERSISTENCE_DELAY, PersistenceFileGlue, PersistenceChangeDetector
from shinysdr.test.testutil import SubscriptionTester
from shinysdr.values import ExportedState, Reference, exported_value, nullExportedState, setter


class TestPersistenceFileGlue(unittest.TestCase):
    def setUp(self):
        self.__clock = Clock()
        self.__temp_dir = tempfile.mkdtemp(prefix='shinysdr_test_persistence_tmp')
        self.__state_name = os.path.join(self.__temp_dir, 'state')
        self.__reset()
    
    def tearDown(self):
        shutil.rmtree(self.__temp_dir)
    
    def __reset(self):
        """Recreate the object for write-then-read tests."""
        self.__root = ValueAndBlockSpecimen()
    
    def __start(self, **kwargs):
        return PersistenceFileGlue(
            reactor=self.__clock,
            root_object=self.__root,
            filename=self.__state_name,
            **kwargs)
    
    def test_no_defaults(self):
        self.__start()
        # It would be surprising if this assertion failed; this test is mainly just to test the initialization succeeds
        self.assertEqual(self.__root.get_value(), 0)
    
    def test_defaults(self):
        self.__start(get_defaults=lambda _: {u'value': 1})
        self.assertEqual(self.__root.get_value(), 1)

    def test_persistence(self):
        """Test that state persists."""
        self.__start()
        self.assertEqual(self.__root.get_value(), 0)  # check initial assumption
        self.__root.set_value(1)
        self.__clock.advance(0.01)  # let change detector detect change
        self.__clock.advance(_PERSISTENCE_DELAY + 0.01)
        self.__reset()
        self.__start()
        self.assertEqual(self.__root.get_value(), 1)  # check persistence


class TestPersistenceChangeDetector(unittest.TestCase):
    def setUp(self):
        self.st = SubscriptionTester()
        self.o = ValueAndBlockSpecimen(ValueAndBlockSpecimen(ExportedState()))
        self.calls = 0
        self.d = PersistenceChangeDetector(self.o, self.__callback, subscription_context=self.st.context)
    
    def __callback(self):
        self.calls += 1
    
    def test_1(self):
        self.assertEqual(self.d.get(), {
            u'value': 0,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        self.assertEqual(0, self.calls)
        self.o.set_value(1)
        self.assertEqual(0, self.calls)
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.set_value(2)
        self.st.advance()
        self.assertEqual(1, self.calls) # only fires once
        self.assertEqual(self.d.get(), {
            u'value': 2,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.get_block().set_value(3)  # pylint: disable=no-member
        self.st.advance()
        self.assertEqual(2, self.calls)
        self.assertEqual(self.d.get(), {
            u'value': 2,
            u'block': {
                u'value': 3,
                u'block': {},
            },
        })


class ValueAndBlockSpecimen(ExportedState):
    def __init__(self, block=nullExportedState, value=0):
        self.__value = value
        self.__block = block
    
    @exported_value(type=Reference(), changes='never')
    def get_block(self):
        return self.__block
    
    @exported_value(type=float, parameter='value', changes='this_setter')
    def get_value(self):
        return self.__value
    
    @setter
    def set_value(self, value):
        self.__value = value
