# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

from twisted.internet.task import Clock
from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
from zope.interface import Interface, implementer

from gnuradio import gr

from shinysdr.i.json import transform_for_json
# TODO: StateStreamInner is an implementation detail; arrange a better interface to test
from shinysdr.i.network.export_ws import StateStreamInner, OurStreamProtocol
from shinysdr.i.roots import CapTable, IEntryPoint
from shinysdr.signals import SignalType
from shinysdr.test.testutil import SubscriptionTester
from shinysdr.types import BulkDataT, ReferenceT
from shinysdr.values import CellDict, CollectionState, ExportedState, NullExportedState, StreamCell, SubscriptionContext, exported_value, nullExportedState, setter


class StateStreamTestCase(unittest.TestCase):
    object = None  # should be set in subclass setUp
    
    def setUpForObject(self, obj):
        # pylint: disable=attribute-defined-outside-init
        self.object = obj
        self.updates = []
        self.st = SubscriptionTester()
        
        def send(value):
            if isinstance(value, unicode):
                self.updates.extend(json.loads(value))
            elif isinstance(value, bytes):
                self.updates.append(['actually_binary', value])
        
        self.stream = StateStreamInner(
            send,
            self.object,
            'urlroot',
            subscription_context=self.st.context)
    
    def getUpdates(self):
        # pylint: disable=attribute-defined-outside-init
        
        self.st.advance()
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
    
    def test_stream_cell(self):
        self.setUpForObject(StreamCellSpecimen())
        self.assertEqual(self.getUpdates(), transform_for_json([
            [u'register_block', 1, u'urlroot', []],
            [u'register_cell', 2, u'urlroot/s', self.object.state()['s'].description()],
            [u'value', 1, {u's': 2}],
            [u'value', 0, 1],
        ]))
        self.object.queue.insert_tail(gr.message().make_from_string('qu', 0, 1, len('qu')))
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['actually_binary', b'\x02\x00\x00\x00q'],
            ['actually_binary', b'\x02\x00\x00\x00u'],
        ]))


class IFoo(Interface):
    pass


@implementer(IFoo)
class StateSpecimen(ExportedState):
    """Helper for TestStateStream"""

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


class StreamCellSpecimen(ExportedState):
    """Helper for TestStateStream"""
    
    def __init__(self):
        self.queue = None
    
    def state_def(self):
        yield 's', StreamCell(self, 's', type=BulkDataT('', 'b'))
    
    def get_s_distributor(self):
        return self  # shortcut
    
    def get_s_info(self):
        return ()
    
    def subscribe(self, queue):
        # acting as distributor
        self.queue = queue
    
    def unsubscribe(self, queue):
        # acting as distributor
        assert self.queue == queue
        self.queue = None
    
    def get(self):
        # acting as distributor
        return u'gotten'


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


@implementer(IFoo)
class SerializationSpecimen(ExportedState):
    """Helper for TestStateStream"""

    def __init__(self):
        self.st = None
    
    @exported_value(type=SignalType, changes='explicit')
    def get_st(self):
        return self.st


class TestOurStreamProtocol(unittest.TestCase):
    def setUp(self):
        cap_table = CapTable(unserializer=None)
        cap_table.add(EntryPointStub(), cap=u'foo')
        self.clock = Clock()
        self.transport = FakeWebSocketTransport()
        self.protocol = OurStreamProtocol(
            caps=cap_table.as_unenumerable_collection(),
            subscription_context=SubscriptionContext(reactor=self.clock, poller=None))
        self.protocol.transport = self.transport
    
    def begin(self, url):
        self.transport.location = bytes(url)
        self.protocol.dataReceived(b'{}')
    
    def test_dispatch(self):
        self.begin('/foo/radio')
        self.clock.advance(1)
        self.assertEqual(self.transport.messages(), [
            [  # batch
                ['register_block', 1, u'/foo/radio', ['shinysdr.i.roots.IEntryPoint']],
                [u'value', 1, {}],
                ['value', 0, 1],
            ],
        ])


class FakeWebSocketTransport(object):
    def __init__(self):
        self.__messages = []
        # faking up stuff!!!
        self.location = None
        self.transport = StringTransport()
        self.transport.dataBuffer = []
    
    def write(self, data):
        self.__messages.append(data)
    
    def messages(self):
        # assuming no binary messages for now
        return [json.loads(m) for m in self.__messages]


@implementer(IEntryPoint)
class EntryPointStub(ExportedState):
    def get_type(self):
        raise NotImplementedError

    def entry_point_is_deleted(self):
        return False
