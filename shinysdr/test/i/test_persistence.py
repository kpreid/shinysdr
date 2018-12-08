# Copyright 2014, 2015, 2016, 2018 Kevin Reid and the ShinySDR contributors
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

import os.path

import six

from twisted.internet.task import Clock
from twisted.trial import unittest

from shinysdr.i.persistence import PersistenceFileGlue, PersistenceChangeDetector
from shinysdr.test.testutil import Files, SubscriptionTester
from shinysdr.values import ExportedState, ReferenceT, exported_value, nullExportedState, setter


class TestPersistenceFileGlue(unittest.TestCase):
    def setUp(self):
        self.__clock = Clock()
        self.__files = Files({})
        self.__state_name = os.path.join(self.__files.dir, 'state')
        self.__reset()
    
    def tearDown(self):
        self.assertFalse(self.__clock.getDelayedCalls())
        self.__files.close()
    
    def __reset(self):
        """Recreate the object for write-then-read tests."""
        self.__root = ValueAndBlockSpecimen(value='initial')
    
    def __start(self,
            get_defaults=lambda _: {'value': 'default'},
            **kwargs):
        return PersistenceFileGlue(
            reactor=self.__clock,
            root_object=self.__root,
            filename=self.__state_name,
            get_defaults=get_defaults,
            **kwargs)
    
    def test_no_defaults(self):
        self.__start(get_defaults=lambda _: {})
        # It would be surprising if this assertion failed; this test is mainly just to test the initialization succeeds
        self.assertEqual(self.__root.get_value(), 'initial')
    
    def test_defaults(self):
        self.__start()
        self.assertEqual(self.__root.get_value(), 'default')

    def test_no_persistence(self):
        self.__state_name = None
        self.__start()
        self.assertEqual(self.__root.get_value(), 'default')

    def test_persistence(self):
        """Test that state persists."""
        pfg = self.__start()
        self.__root.set_value('set')
        advance_until(self.__clock, pfg.sync(), limit=2)
        self.__reset()
        self.__start()
        self.assertEqual(self.__root.get_value(), 'set')  # check persistence
    
    def test_delay_is_present(self):
        """Test that persistence isn't immediate."""
        pfg = self.__start()
        self.__root.set_value('set')
        self.__reset()
        self.__start()
        self.assertEqual(self.__root.get_value(), 'default')  # change not persisted
        advance_until(self.__clock, pfg.sync(), limit=2)  # clean up clock for tearDown check
    
    def test_broken_state_recovery(self):
        pfg = self.__start()
        self.__root.set_value(ObjectWhichCannotBePersisted())
        try:
            advance_until(self.__clock, pfg.sync(), limit=2)
        except TypeError:  # expected error
            pass
        self.__reset()
        self.__start()
        # now we should be back to the default value
        self.assertEqual(self.__root.get_value(), 'default')
    
    def test_unparseable_file_recovery(self):
        self.__files.create({self.__state_name: ''})  # empty file is bad JSON
        self.__start()
        self.assertEqual(self.__root.get_value(), 'default')
        self.flushLoggedErrors(ValueError)
    
    # TODO: Add a test that multiple changes don't trigger multiple writes -- needs a reasonable design for a hook to observe the write.


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
            'value': 'initial',
            'block': {
                'value': 'initial',
                'block': {},
            },
        })
        self.assertEqual(0, self.calls)
        self.o.set_value('one')
        self.assertEqual(0, self.calls)
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.set_value('two')
        self.st.advance()
        self.assertEqual(1, self.calls)  # only fires once
        self.assertEqual(self.d.get(), {
            u'value': 'two',
            u'block': {
                u'value': 'initial',
                u'block': {},
            },
        })
        self.st.advance()
        self.assertEqual(1, self.calls)
        self.o.get_block().set_value('three')  # pylint: disable=no-member
        self.st.advance()
        self.assertEqual(2, self.calls)
        self.assertEqual(self.d.get(), {
            u'value': 'two',
            u'block': {
                u'value': 'three',
                u'block': {},
            },
        })


class ValueAndBlockSpecimen(ExportedState):
    def __init__(self, block=nullExportedState, value='initial'):
        self.__value = value
        self.__block = block
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_block(self):
        return self.__block
    
    @exported_value(type=six.text_type, parameter='value', changes='this_setter')
    def get_value(self):
        return self.__value
    
    @setter
    def set_value(self, value):
        self.__value = value


class ObjectWhichCannotBePersisted(object):
    pass


def advance_until(clock, d, limit=10, timestep=0.001):
    ret = []
    err = []
    d.addCallbacks(ret.append, err.append)
    for _ in six.moves.range(limit):
        if ret:
            return ret[0]
        elif err:
            raise err[0]
        else:
            clock.advance(timestep)
    raise Exception('advance_until ran out')
