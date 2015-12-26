# Copyright 2015 Kevin Reid <kpreid@switchb.org>
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

import time

from twisted.internet.task import Clock
from twisted.trial import unittest
from zope.interface import implements

from shinysdr.telemetry import ITelemetryMessage, ITelemetryObject, TelemetryItem, TelemetryStore, Track, empty_track


class TestTrack(unittest.TestCase):
    def test_init_from_partial_json(self):
        self.assertEquals(
            empty_track._replace(
                latitude=TelemetryItem(1, 1000),
                longitude=TelemetryItem(2, 1000)),
            Track({
                u'latitude': {u'value': 1, u'timestamp': 1000},
                u'longitude': {u'value': 2, u'timestamp': 1000},
            }))


class TestTelemetryStore(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clock.advance(1000)
        self.store = TelemetryStore(time_source=self.clock)
    
    def test_new_object(self):
        self.assertEqual([], self.store.state().keys())
        self.store.receive(Msg('foo', 1000))
        self.assertEqual(['foo'], self.store.state().keys())
        obj = self.store.state()['foo'].get()
        self.assertIsInstance(obj, Obj)
    
    def test_receive_called(self):
        self.store.receive(Msg('foo', 1000, 1))
        obj = self.store.state()['foo'].get()
        self.assertEquals(obj.last_msg, 1)
        self.store.receive(Msg('foo', 1000, 2))
        self.assertEquals(obj.last_msg, 2)
    
    def test_drop_old(self):
        self.store.receive(Msg('foo', 1000))
        self.assertEqual(['foo'], self.store.state().keys())
        self.clock.advance(1799.5)
        self.store.receive(Msg('bar', 2799.5))
        self.assertEqual({'bar', 'foo'}, set(self.store.state().keys()))
        self.clock.advance(0.5)
        self.store.receive(Msg('bar', 2800))
        self.assertEqual(['bar'], self.store.state().keys())
    
    def test_become_interesting(self):
        self.store.receive(Msg('foo', 1000, 'boring'))
        self.assertEqual([], self.store.state().keys())
        self.store.receive(Msg('foo', 1001, 'interesting'))
        self.assertEqual(['foo'], self.store.state().keys())
        # 'become boring' is not implemented, so also not tested yet
    
    def test_drop_old_boring(self):
        '''
        Make sure that dropping a boring object doesn't fail.
        '''
        self.store.receive(Msg('foo', 1000, 'boring'))
        self.assertEqual([], self.store.state().keys())
        self.clock.advance(1800)
        self.store.receive(Msg('bar', 2800, 'boring'))
        self.assertEqual([], self.store.state().keys())
    

class Msg(object):
    implements(ITelemetryMessage)
    
    def __init__(self, object_id, timestamp, value='no value'):
        self.__id = object_id
        self.timestamp = timestamp
        self.value = value
    
    def get_object_id(self):
        return self.__id
    
    def get_object_constructor(self):
        return Obj
    

class Obj(object):
    implements(ITelemetryObject)
    
    def __init__(self, object_id):
        self.__id = object_id
        self.last_msg = 'no message'
        self.last_time = None
    
    def receive(self, message):
        self.last_msg = message.value
        self.last_time = message.timestamp
    
    def is_interesting(self):
        return self.last_msg != 'boring'
    
    def get_object_expiry(self):
        return self.last_time + 1800