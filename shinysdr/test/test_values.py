# -*- coding: utf-8 -*-
# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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

import six

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest

import numpy

from shinysdr.test.testutil import CellSubscriptionTester, LoopbackInterestTracker, LogTester
from shinysdr.types import BulkDataElement, BulkDataT, EnumRow, RangeT, ReferenceT, to_value_type
from shinysdr.values import CellDict, CollectionState, ElementSinkCell, ExportedState, LooseCell, PollingCell, StringSinkCell, ViewCell, command, exported_value, nullExportedState, setter, unserialize_exported_state


class TestExportedState(unittest.TestCase):
    def test_persistence_basic(self):
        o = ValueAndBlockSpecimen(ValueAndBlockSpecimen(ExportedState()))
        self.assertEqual(o.state_to_json(), {
            u'value': 0,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        o.state_from_json({
            u'value': 1,
            u'block': {
                u'value': 2,
                u'block': {},
            },
        })
        self.assertEqual(o.state_to_json(), {
            u'value': 1,
            u'block': {
                u'value': 2,
                u'block': {},
            },
        })
    
    def test_persistence_unknown_key(self):
        class Nada(ExportedState):
            def __repr__(self):
                return '<Nada>'  # no address
        
        log_tester = LogTester()
        o = Nada()
        o.state_from_json({
            u'irrelevant': 1,
        }, log=log_tester.log)
        log_tester.check(dict(text='Discarding nonexistent state <Nada>.irrelevant = 1'))
        self.assertEqual(o.state_to_json(), {})
    
    def test_persistence_bad_value(self):
        class Splodey(ExportedState):
            def __repr__(self):
                return '<Splodey>'  # no address
            
            @exported_value(changes='this_setter')
            def get_foo(self):
                return 'fixed'
            
            @setter
            def set_foo(self, value):
                raise ValueError('boom')
        
        log_tester = LogTester()
        o = Splodey()
        o.state_from_json({
            u'foo': 1,
        }, log=log_tester.log)
        log_tester.check(dict(text='Discarding erroneous state <Splodey>.foo = 1'))
    
    def test_persistence_args(self):
        o = unserialize_exported_state(
            ctor=ValueAndBlockSpecimen,
            kwargs={u'block': ValueAndBlockSpecimen(ExportedState())},
            state={
                u'value': 1,
            })
        self.assertEqual(o.state_to_json(), {
            u'value': 1,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
    
    # see TestCell for other subscription cases
    def test_subscription_this_setter(self):
        o = ValueAndBlockSpecimen()
        st = CellSubscriptionTester(o.state()['value'], interest_tracking=False)
        o.set_value(1)
        st.expect_now(1)
        st.unsubscribe()
        o.set_value(2)
        st.advance()  # check for unwanted callbacks


class ValueAndBlockSpecimen(ExportedState):
    """Helper for TestExportedState"""
    def __init__(self, block=nullExportedState, value=0):
        self.__value = value
        self.__block = block
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_block(self):
        return self.__block
    
    @exported_value(type=float, parameter='value', changes='this_setter')
    def get_value(self):
        return self.__value
    
    @setter
    def set_value(self, value):
        self.__value = value


class TestDecoratorInheritance(unittest.TestCase):
    def setUp(self):
        self.object = DecoratorInheritanceSpecimen()
    
    def test_state_with_inheritance(self):
        keys = sorted(self.object.state().keys())
        self.assertEqual(['inherited', 'rw'], keys)
        rw_cell = self.object.state()['rw']
        self.assertEqual(rw_cell.get(), 0.0)
        rw_cell.set(1.0)
        self.assertEqual(rw_cell.get(), 1.0)


class DecoratorInheritanceSpecimenSuper(ExportedState):
    """Helper for TestDecorator"""
    @exported_value(type=float, changes='never')
    def get_inherited(self):
        return 9


class DecoratorInheritanceSpecimen(DecoratorInheritanceSpecimenSuper):
    """Helper for TestDecorator"""
    def __init__(self):
        self.rw = 0.0
    
    @exported_value(type=RangeT([(0.0, 10.0)]), changes='this_setter')
    def get_rw(self):
        return self.rw
    
    @setter
    def set_rw(self, value):
        self.rw = value


class TestBaseCell(unittest.TestCase):
    def test_specify_all_metadata(self):
        # using LooseCell as an arbitrary concrete subclass
        cell = LooseCell(
            value=0,
            type=int,
            persists=False,  # the non-default value
            label='mylabel',
            description='mydescription',
            sort_key='mysortkey')
        self.assertEqual(cell.metadata().value_type, to_value_type(int))
        self.assertEqual(cell.metadata().persists, False)
        self.assertEqual(cell.metadata().naming, EnumRow(
            label='mylabel',
            description='mydescription',
            sort_key='mysortkey'))


class TestPollingCell(unittest.TestCase):
    # TODO write other tests, as appropriate - this is the 'normal' cell type which most other stuff wouldn't work without
    
    def __test_subscription(self, changes):
        o = NoInherentCellSpecimen()
        cell = PollingCell(o, 'value', changes=changes, interest_tracker=LoopbackInterestTracker())
        st = CellSubscriptionTester(cell)
        o.value = 1
        if changes == 'explicit':
            cell.poll_for_change(specific_cell=True)
        st.expect_now(1)
        st.unsubscribe()
        o.value = 2
        st.advance()  # check for unwanted callbacks
    
    # TODO: These subscription tests will require adjustment as the different 'changes' policies get actually implemented.
    
    def test_subscription_never(self):
        o = NoInherentCellSpecimen()
        cell = PollingCell(o, 'value', changes='never', interest_tracker=LoopbackInterestTracker())
        st = CellSubscriptionTester(cell, interest_tracking=False)
        o.value = 1
        st.advance()  # expected no callback even if we lie
    
    def test_subscription_continuous(self):
        self.__test_subscription('continuous')
    
    def test_subscription_explicit(self):
        self.__test_subscription('explicit')
    
    # this_setter is handled in TestExportedState because it involves the decorators
    
    def test_metadata_explicit(self):
        cell = PollingCell(
            target=NoInherentCellSpecimen(),
            key='value',
            changes='never',
            label='foo',
            description='bar',
            sort_key='baz')
        self.assertEqual(cell.metadata().naming, EnumRow(
            label='foo',
            description='bar',
            sort_key='baz'))
    
    def test_metadata_default(self):
        cell = PollingCell(
            target=NoInherentCellSpecimen(),
            key='value',
            changes='never')
        self.assertEqual(cell.metadata().naming, EnumRow(
            label='value',
            sort_key='value'))
    
    def test_repr(self):
        cell = PollingCell(
            target=NoInherentCellSpecimen(),
            key='value',
            changes='never')
        self.assertEqual(repr(cell), '<PollingCell <NoInherentCellSpecimen repr>.value>')


class NoInherentCellSpecimen(object):
    def __init__(self):
        self.value = 0
    
    def get_value(self):
        return self.value
    
    def __repr__(self):
        return '<NoInherentCellSpecimen repr>'


# TODO: BlockCell no longer exists, but this test still tests something; rename appropriately
class TestBlockCell(unittest.TestCase):
    def setUp(self):
        self.obj_value = ExportedState()
        self.object = BlockCellSpecimen(self.obj_value)
    
    def test_block_cell_value(self):
        cell = self.object.state()['block']
        self.assertEqual(cell.get(), self.obj_value)
    
    def test_subscription(self):
        o = BlockCellSpecimen(self.obj_value)
        st = CellSubscriptionTester(o.state()['block'], interest_tracking=False)
        new = ExportedState()
        o.replace_block(new)
        st.expect_now(new)
        st.unsubscribe()
        o.replace_block(self.obj_value)
        st.advance()  # check for unwanted callbacks


class BlockCellSpecimen(ExportedState):
    """Helper for TestBlockCell"""
    block = None
    
    def __init__(self, block):
        self.__block = block
    
    @exported_value(type=ReferenceT(), changes='explicit')
    def get_block(self):
        return self.__block
    
    def replace_block(self, block):
        self.__block = block
        self.state_changed('block')


class TestGRSinkCell(unittest.TestCase):
    # for lint
    cell = None
    sink = None
    dtype = None
    
    def setUp(self):
        self.info_value = 1000
        
        def info_getter():
            self.info_value += 1
            return (self.info_value,)
        
        self.info_getter = info_getter
    
    def setUpForBulkData(self):
        self.cell = ElementSinkCell(
            info_getter=self.info_getter,
            type=BulkDataT(array_format='f', info_format='d'),
            interest_tracker=LoopbackInterestTracker())
        self.dtype = numpy.uint8
        self.sink = self.cell.create_sink_internal(self.dtype)
    
    def setUpForUnicodeString(self):
        self.cell = StringSinkCell(
            encoding='utf-8',
            interest_tracker=LoopbackInterestTracker())
        self.dtype = numpy.uint8
        self.sink = self.cell.create_sink_internal(self.dtype)
    
    def inject_bytes(self, bytestr):
        # calling implementation of sink block to not have to set up a flowgraph
        self.sink.work([numpy.frombuffer(bytestr, dtype=self.dtype)], [])
        
        # We wait because StringSinkCell uses reactor.callFromThread. We've skipped setting up the GNU Radio block thread, but it doesn't know that (and Clock does not support callFromThread).
        return deferLater(the_reactor, 0.0, lambda: None)
    
    @defer.inlineCallbacks
    def test_element_get_not_mutated(self):
        self.setUpForBulkData()
        gotten = self.cell.get()
        self.assertEqual(gotten, [])
        yield self.inject_bytes(b'ab')
        self.assertEqual(self.cell.get(), [
            BulkDataElement(data=b'a', info=(1001,)),
            BulkDataElement(data=b'b', info=(1001,))
        ])
        self.assertEqual(gotten, [])  # not mutating list
    
    @defer.inlineCallbacks
    def test_element_delta_subscriber(self):
        self.setUpForBulkData()
        st = CellSubscriptionTester(self.cell, delta=True)
        yield self.inject_bytes(b'ab')
        st.expect_now([
            BulkDataElement(data=b'a', info=(1001,)),
            BulkDataElement(data=b'b', info=(1001,))
        ], kind='append')
        st.unsubscribe()
        yield self.inject_bytes(b'ignored')
        st.advance()
    
    @defer.inlineCallbacks
    def test_element_plain_subscriber(self):
        self.setUpForBulkData()
        st = CellSubscriptionTester(self.cell, delta=False)
        yield self.inject_bytes(b'ab')
        st.expect_now([
            BulkDataElement(data=b'a', info=(1001,)),
            BulkDataElement(data=b'b', info=(1001,))
        ], kind='value')
        st.unsubscribe()
        yield self.inject_bytes(b'ignored')
        st.advance()
    
    @defer.inlineCallbacks
    def test_string_get(self):
        self.setUpForUnicodeString()
        gotten = self.cell.get()
        self.assertTrue(isinstance(gotten, six.text_type))
        self.assertEqual(gotten, u'')
        yield self.inject_bytes('abç'.encode('utf-8'))
        gotten = self.cell.get()
        self.assertTrue(isinstance(gotten, six.text_type))
        self.assertEqual(gotten, 'abç')
        
        # now append some more to test the buffer
        yield self.inject_bytes('deƒ'.encode('utf-8'))
        self.assertEqual(self.cell.get(), 'abçdeƒ')
    
    @defer.inlineCallbacks
    def test_string_coding_error(self):
        self.setUpForUnicodeString()
        yield self.inject_bytes(b'ab\xFF')
        self.assertEqual(self.cell.get(), 'ab\uFFFD')
    
    @defer.inlineCallbacks
    def test_string_delta_subscriber(self):
        self.setUpForUnicodeString()
        st = CellSubscriptionTester(self.cell, delta=True)
        yield self.inject_bytes('abç'.encode('utf-8'))
        st.expect_now('abç', kind='append')
        st.unsubscribe()
        yield self.inject_bytes(b'ignored')
        st.advance()
    
    @defer.inlineCallbacks
    def test_string_plain_subscriber(self):
        self.setUpForUnicodeString()
        st = CellSubscriptionTester(self.cell, delta=False)
        yield self.inject_bytes('abç'.encode('utf-8'))
        st.expect_now('abç')
        yield self.inject_bytes('deƒ'.encode('utf-8'))
        
        # TODO: This is not the correct result; it should match get().
        # Poller currently does not deal with attaching simple subscribers correctly
        st.expect_now('deƒ')


class TestLooseCell(unittest.TestCase):
    def setUp(self):
        self.lc = LooseCell(
            value=0,
            type=int,
            writable=True,
            interest_tracker=LoopbackInterestTracker())
    
    def test_get_set(self):
        self.assertEqual(0, self.lc.get())
        self.lc.set(1)
        self.assertEqual(1, self.lc.get())
        self.lc.set(2.1)
        self.assertEqual(2, self.lc.get())
    
    def test_subscription(self):
        st = CellSubscriptionTester(self.lc)
        self.lc.set(1)
        st.expect_now(1)
        st.unsubscribe()
        self.lc.set(2)
        st.advance()  # check for unwanted callbacks
    
    def test_repr(self):
        if six.PY2:
            self.assertEqual(repr(self.lc), '<LooseCell PythonT(<type \'int\'>) 0>')
        else:
            self.assertEqual(repr(self.lc), '<LooseCell PythonT(<class \'int\'>) 0>')
    
    def test_default_writability(self):
        self.assertFalse(LooseCell(value=0, type=int).isWritable())
    
    def test_not_writable(self):
        self.lc = LooseCell(value=0, type=int, writable=False)
        self.assertRaises(Exception, lambda:
            self.lc.set(1))
        self.assertEqual(self.lc.get(), 0)


class TestViewCell(unittest.TestCase):
    def setUp(self):
        self.lc = LooseCell(value=0, type=RangeT([(-100, 100)]), writable=True)
        self.delta = 1
        self.vc = ViewCell(
            base=self.lc,
            get_transform=lambda x: x + self.delta,
            set_transform=lambda x: x - self.delta,
            type=int,
            writable=True,
            interest_tracker=LoopbackInterestTracker())
    
    # TODO: Add tests for behavior when the transform is not perfectly one-to-one (such as due to floating-point error).
    
    # TODO: Test propagation of interest
    
    def test_get_set(self):
        self.assertEqual(0, self.lc.get())
        self.assertEqual(1, self.vc.get())
        self.vc.set(2)
        self.assertEqual(1, self.lc.get())
        self.assertEqual(2, self.vc.get())
        self.lc.set(3)
        self.assertEqual(3, self.lc.get())
        self.assertEqual(4, self.vc.get())
        
        self.delta = 10
        self.vc.changed_transform()
        self.assertEqual(3, self.lc.get())
        self.assertEqual(13, self.vc.get())
    
    def test_subscription(self):
        st = CellSubscriptionTester(self.vc)
        
        self.lc.set(1)
        st.expect_now(2)
        
        self.delta = 10
        self.vc.changed_transform()
        self.assertEqual(1, self.lc.get())
        st.expect_now(11)
        st.unsubscribe()
        self.lc.set(2)
        st.advance()
    
    def test_coerced_base_value(self):
        self.vc.set(999)  # out of base cell's range, gets clamped
        self.assertEqual(100 + self.delta, self.vc.get())
    
    # TODO: Test what happens when the base cell is not writable
    # ...or if it raises an unexpected error on set()


class TestCommandCell(unittest.TestCase):
    def setUp(self):
        self.specimen = DecoratorCommandSpecimen()
    
    def test_call_method(self):
        self.assertEqual(0, self.specimen.count)
        r = self.specimen.cmd()
        self.assertEqual(None, r)
        self.assertEqual(1, self.specimen.count)
    
    def test_call_cell(self):
        self.assertEqual(0, self.specimen.count)
        self.specimen.state()['cmd'].set(None)  # TODO: Stop overloading 'set' to mean 'invoke'
        self.assertEqual(1, self.specimen.count)
    
    def test_metadata_explicit(self):
        cell = self.specimen.state()['cmd']
        self.assertEqual(cell.metadata().naming, EnumRow(
            label='Do the thing',
            sort_key='cmd'))
    
    def test_metadata_default(self):
        cell = self.specimen.state()['unlabeled']
        self.assertEqual(cell.metadata().naming, EnumRow(
            label='unlabeled',
            sort_key='unlabeled'))


class DecoratorCommandSpecimen(ExportedState):
    def __init__(self):
        self.count = 0
    
    @command(label='Do the thing')
    def cmd(self):
        self.count += 1
    
    @command()
    def unlabeled(self):
        pass


class TestStateInsert(unittest.TestCase):
    object = None
    
    def test_success(self):
        self.object = InsertFailSpecimen()
        self.object.state_from_json({'foo': {'fail': False}})
        self.assertEqual(['foo'], list(self.object.state().keys()))
    
    def test_failure(self):
        self.object = InsertFailSpecimen()
        self.object.state_from_json({'foo': {'fail': True}})
        # throws but exception is caught -- TODO: Test logging
        self.assertEqual([], list(self.object.state().keys()))
        self.flushLoggedErrors(ValueError)
    
    def test_undefined(self):
        """no state_insert method defined"""
        self.object = CollectionState(CellDict(dynamic=True))
        self.object.state_from_json({'foo': {'fail': True}})
        # throws but exception is caught -- TODO: Test logging
        self.assertEqual([], list(self.object.state().keys()))
        self.flushLoggedErrors(ValueError)


class InsertFailSpecimen(CollectionState):
    """Helper for TestStateInsert"""
    def __init__(self):
        self.table = CellDict(dynamic=True)
        CollectionState.__init__(self, self.table)
    
    def state_insert(self, key, desc):
        if desc['fail']:
            raise ValueError('Should be handled')
        else:
            self.table[key] = ExportedState()
            self.table[key].state_from_json(desc)


class TestCellIdentity(unittest.TestCase):
    def setUp(self):
        self.object = CellIdentitySpecimen()

    def assertConsistent(self, f):
        self.assertEqual(f(), f())
        self.assertEqual(f().__hash__(), f().__hash__())

    def test_value_cell(self):
        self.assertConsistent(lambda: self.object.state()['value'])
            
    def test_block_cell(self):
        self.assertConsistent(lambda: self.object.state()['block'])


class CellIdentitySpecimen(ExportedState):
    """Helper for TestCellIdentity"""
    __value = 1
    
    def __init__(self):
        self.__block = ExportedState()
    
    # force worst-case
    def state_is_dynamic(self):
        return True
    
    @exported_value(changes='never')
    def get_value(self):
        return 9

    @exported_value(type=ReferenceT(), changes='never')
    def get_block(self):
        return self.__block
