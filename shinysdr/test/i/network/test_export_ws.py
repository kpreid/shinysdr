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

from __future__ import absolute_import, division, print_function, unicode_literals

import json

import six

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import Clock, deferLater
from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
from zope.interface import Interface, implementer

import numpy

from shinysdr.i.json import transform_for_json
# TODO: StateStreamInner is an implementation detail; arrange a better interface to test
from shinysdr.i.network.export_ws import StateStreamInner, OurStreamProtocol
from shinysdr.i.roots import CapTable, IEntryPoint
from shinysdr.signals import SignalType
from shinysdr.test.testutil import Cells, SubscriptionTester
from shinysdr.types import BulkDataT, ReferenceT
from shinysdr.values import CellDict, CollectionState, ExportedState, ElementSinkCell, NullExportedState, StringSinkCell, SubscriptionContext, exported_value, nullExportedState, setter


class StateStreamTestCase(unittest.TestCase):
    object = None  # should be set in subclass setUp
    
    def setUpForObject(self, obj):
        # pylint: disable=attribute-defined-outside-init
        self.object = obj
        self.updates = []
        self.st = SubscriptionTester()
        
        def send(value):
            if isinstance(value, six.text_type):
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
    maxDiff = 4000
    
    def test_init_and_mutate(self):
        self.setUpForObject(StateSpecimen())
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['register_block', 1, 'urlroot', ['shinysdr.test.i.network.test_export_ws.IFoo']],
            ['register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description(), 1.0],
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
            [u'register_cell', 2, u'urlroot/foo', self.object.state()['foo'].description(), None],
            [u'register_block', 3, u'urlroot/foo', [u'shinysdr.values.INull']],
            [u'value', 3, {}],
            [u'value', 2, 3],
            [u'register_cell', 4, u'urlroot/bar', self.object.state()['bar'].description(), None],
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
            ['register_cell', 2, 'urlroot/a', self.object.state()['a'].description(), None],
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
            transform_for_json(['register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description(), 1.0]),
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
    
    @defer.inlineCallbacks
    def test_bulk_data(self):
        self.setUpForObject(BulkDataSpecimen())
        cell = self.object.state()['s']
        yield _append_to_sink_cell(cell, b'ab')
        
        description = cell.description()
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['register_block', 1, 'urlroot', []],
            ['register_cell', 2, 'urlroot/s', description, []],
            ['value', 1, {'s': 2}],
            ['value', 0, 1],
            ['actually_binary', b'\x02\x00\x00\x00\x01a'],
            ['actually_binary', b'\x02\x00\x00\x00\x01b'],
        ]))
        yield _append_to_sink_cell(cell, b'cd')
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['actually_binary', b'\x02\x00\x00\x00\x02c'],
            ['actually_binary', b'\x02\x00\x00\x00\x02d'],
        ]))
    
    @defer.inlineCallbacks
    def test_value_patch(self):
        cell = StringSinkCell(encoding='us-ascii')
        yield _append_to_sink_cell(cell, b'ab')
        self.setUpForObject(Cells({
            's': cell
        }))
        self.st.advance()
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['register_block', 1, 'urlroot', []],
            ['register_cell', 2, 'urlroot/s', cell.description(), 'ab'],
            ['value', 1, {'s': 2}],
            ['value', 0, 1],
        ]))
        yield _append_to_sink_cell(cell, b'cd')
        self.st.advance()
        self.assertEqual(self.getUpdates(), transform_for_json([
            ['value_append', 2, 'cd'],
        ]))


def _append_to_sink_cell(cell, bytestr):
    # TODO: this is too much poking internals for this high level test; make a temp flowgraph instead
    cell.create_sink_internal(numpy.uint8).work([numpy.frombuffer(bytestr, dtype=numpy.uint8)], [])
    return deferLater(the_reactor, 0.0, lambda: None)


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


class BulkDataSpecimen(ExportedState):
    """Helper for TestStateStream"""
    
    def __init__(self):
        self.info_value = 0
    
    def state_def(self):
        def info_getter():
            self.info_value += 1
            return (self.info_value,)
        yield 's', ElementSinkCell(
            info_getter=info_getter,
            type=BulkDataT('b', 'b'))


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


_FAKE_SAMPLES = b'\x00\x01\xFE\xFF'


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
    
    def tearDown(self):
        # It used to be if we don't do this cleanup we get a deadlock, probably because of the blocking audio queue thread that doesn't exist any more. But it's good practice to exercise cleanup in tests anyway.
        self.protocol.connectionLost(None)
    
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
    
    @defer.inlineCallbacks
    def test_audio(self):
        self.begin('/foo/audio?rate=1')
        self.clock.advance(1)
        yield deferLater(the_reactor, 0.0, lambda: None)
        self.assertEqual(self.transport.messages(), [
            {
                u'signal_type': {
                    u'type': u'SignalType',
                    u'kind': u'MONO',
                    u'sample_rate': 1.0
                },
                u'type': u'audio_stream_metadata'
            },
            _FAKE_SAMPLES,
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
        return [json.loads(m) if isinstance(m, six.text_type) else m for m in self.__messages]


@implementer(IEntryPoint)
class EntryPointStub(ExportedState):
    def get_type(self):
        raise NotImplementedError

    def entry_point_is_deleted(self):
        return False
    
    def add_audio_callback(self, callback, sample_rate):
        deferLater(the_reactor, 0.0, lambda: callback(_FAKE_SAMPLES))
    
    def remove_audio_callback(self, callback):
        pass
        
    def get_audio_callback_channels(self):
        return 1
