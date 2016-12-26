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

from __future__ import absolute_import, division

import json

from twisted.trial import unittest
from zope.interface import Interface, implements  # available via Twisted

from shinysdr.i.network.base import transform_for_json
# TODO: StateStreamInner is an implementation detail; arrange a better interface to test
from shinysdr.i.network.export_ws import StateStreamInner
from shinysdr.signals import SignalType
from shinysdr.test.testutil import SubscriptionTester
from shinysdr.types import ReferenceT
from shinysdr.values import CellDict, CollectionState, ExportedState, NullExportedState, exported_value, nullExportedState, setter


class StateStreamTestCase(unittest.TestCase):
    object = None  # should be set in subclass setUp
    
    def setUpForObject(self, obj):
        # pylint: disable=attribute-defined-outside-init
        self.object = obj
        self.updates = []
        self.st = SubscriptionTester()
        
        def send(value):
            self.updates.extend(json.loads(value))
        
        self.stream = StateStreamInner(
            send,
            self.object,
            'urlroot',
            subscription_context=self.st.context)
    
    def getUpdates(self):
        # pylint: disable=attribute-defined-outside-init
        
        self.st.advance()
        self.stream._flush()  # warning: implementation poking
        u = self.updates
        self.updates = []
        return u


class TestStateStream(StateStreamTestCase):
    def test_init_and_mutate(self):
        self.setUpForObject(StateSpecimen())
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['register_block', 1, 'urlroot', ['shinysdr.test.i.network.test_export_ws.IFoo']],
            ['register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description()],
            ['value', 1, {'rw': 2}],
            ['value', 0, 1],
        ]))
        self.assertEqual(self.getUpdates(), [])
        self.object.set_rw(2.0)
        self.assertEqual(self.getUpdates(), [
            ['value', 2, self.object.get_rw()],
        ])

    def test_two_references(self):
        """Two references are handled correctly, including not deleting until both are gone."""
        self.setUpForObject(DuplicateReferenceSpecimen())
        self.assertEqual(self.getUpdates(), transform_for_json([
            [u'register_block', 1, u'urlroot', []],
            [u'register_cell', 2, u'urlroot/foo', self.object.state()['foo'].description()],
            [u'register_block', 3, u'urlroot/foo', [u'shinysdr.values.INull']],
            [u'value', 3, {}],
            [u'value', 2, 3],
            [u'register_cell', 4, u'urlroot/bar', self.object.state()['bar'].description()],
            [u'value', 4, 3],
            [u'value', 1, {u'bar': 4, u'foo': 2}],
            [u'value', 0, 1],
        ]))
        replacement = NullExportedState()
        # becomes distinct
        self.object.bar = replacement
        self.object.state_changed()
        self.assertEqual(self.getUpdates(), [
            [u'register_block', 5, u'urlroot/bar', [u'shinysdr.values.INull']],
            [u'value', 5, {}],
            [u'value', 4, 5]
        ])
        # old value should be deleted
        self.object.foo = replacement
        self.object.state_changed()
        self.assertEqual(self.getUpdates(), [
            [u'value', 2, 5],
            [u'delete', 3]
        ])
    
    def test_collection_delete(self):
        d = CellDict({'a': ExportedState()}, dynamic=True)
        self.setUpForObject(CollectionState(d))
        
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['register_block', 1, 'urlroot', []],
            ['register_cell', 2, 'urlroot/a', self.object.state()['a'].description()],
            ['register_block', 3, 'urlroot/a', []],
            ['value', 3, {}],
            ['value', 2, 3],
            ['value', 1, {'a': 2}],
            ['value', 0, 1],
        ]))
        self.assertEqual(self.getUpdates(), [])
        del d['a']
        self.assertEqual(self.getUpdates(), [
            ['value', 1, {}],
            ['delete', 2],
            ['delete', 3],
        ])
    
    def test_send_set_normal(self):
        self.setUpForObject(StateSpecimen())
        self.assertIn(
            transform_for_json(['register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description()]),
            self.getUpdates())
        self.stream.dataReceived(json.dumps(['set', 2, 100.0, 1234]))
        self.assertEqual(self.getUpdates(), [
            ['value', 2, 100.0],
            ['done', 1234],
        ])
        self.stream.dataReceived(json.dumps(['set', 2, 100.0, 1234]))
        self.assertEqual(self.getUpdates(), [
            # don't see any value message
            ['done', 1234],
        ])
    
    def test_send_set_wrong_target(self):
        # Raised exception will be logged safely by the wrappper.
        # TODO: Instead of raising, report the error associated with the connection somehow
        self.setUpForObject(StateSpecimen())
        self.assertIn(
            transform_for_json(['register_block', 1, 'urlroot', ['shinysdr.test.i.network.test_export_ws.IFoo']]),
            self.getUpdates())
        self.assertRaises(Exception, lambda:  # TODO more specific error
            self.stream.dataReceived(json.dumps(['set', 1, 100.0, 1234])))
        self.assertEqual(self.getUpdates(), [])
    
    def test_send_set_unknown_target(self):
        # Raised exception will be logged safely by the wrappper.
        # TODO: Instead of raising, report the error associated with the connection somehow
        self.setUpForObject(StateSpecimen())
        self.getUpdates()
        self.assertRaises(KeyError, lambda:
            self.stream.dataReceived(json.dumps(['set', 99999, 100.0, 1234])))
        self.assertEqual(self.getUpdates(), [])


class IFoo(Interface):
    pass


class StateSpecimen(ExportedState):
    """Helper for TestStateStream"""
    implements(IFoo)

    def __init__(self):
        self.rw = 1.0
    
    @exported_value(type=float, changes='this_setter')
    def get_rw(self):
        return self.rw
    
    @setter
    def set_rw(self, value):
        self.rw = value


class DuplicateReferenceSpecimen(ExportedState):
    """Helper for TestStateStream"""

    def __init__(self):
        self.foo = self.bar = nullExportedState
    
    @exported_value(type=ReferenceT(), changes='explicit')
    def get_foo(self):
        return self.foo
    
    @exported_value(type=ReferenceT(), changes='explicit')
    def get_bar(self):
        return self.bar


class TestSerialization(StateStreamTestCase):
    # TODO we should probably do this more directly
    def test_signal_type(self):
        self.setUpForObject(SerializationSpecimen())
        self.getUpdates()  # ignore initialization
        self.object.st = SignalType(kind='USB', sample_rate=1234.0)
        self.object.state_changed()
        self.assertEqual(self.getUpdates(), [
            ['value', 2, {
                u'type': u'SignalType',
                u'kind': u'USB',
                u'sample_rate': 1234.0
            }],
        ])


class SerializationSpecimen(ExportedState):
    """Helper for TestStateStream"""
    implements(IFoo)

    def __init__(self):
        self.st = None
    
    @exported_value(type=SignalType, changes='explicit')
    def get_st(self):
        return self.st
