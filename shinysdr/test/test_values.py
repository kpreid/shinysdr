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

import unittest

from shinysdr.i.poller import Poller
from shinysdr.test.testutil import CellSubscriptionTester
from shinysdr.types import Range
from shinysdr.values import Cell, CellDict, CollectionState, ExportedState, LooseCell, ViewCell, command, exported_block, exported_value, nullExportedState, setter, unserialize_exported_state


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
    
    # TODO: test persistence error cases like unknown or wrong-typed properties
    
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
        st = CellSubscriptionTester(o.state()['value'])
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
    
    @exported_block(changes='never')
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
        keys = self.object.state().keys()
        keys.sort()
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
    
    @exported_value(type=Range([(0.0, 10.0)]), changes='this_setter')
    def get_rw(self):
        return self.rw
    
    @setter
    def set_rw(self, value):
        self.rw = value


class TestCell(unittest.TestCase):
    # TODO write other tests, as appropriate - this is the 'normal' cell type which most other stuff wouldn't work without
    
    def __test_subscription(self, changes):
        o = NoInherentCellSpecimen()
        cell = Cell(o, 'value', changes=changes)
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
        cell = Cell(o, 'value', changes='never')
        st = CellSubscriptionTester(cell)
        o.value = 1
        st.advance()  # expected no callback even if we lie
    
    def test_subscription_continuous(self):
        self.__test_subscription('continuous')
    
    def test_subscription_explicit(self):
        self.__test_subscription('explicit')
    
    # this_setter is handled in TestExportedState because it involves the decorators


class NoInherentCellSpecimen(object):
    def __init__(self):
        self.value = 0
    
    def get_value(self):
        return self.value


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
        st = CellSubscriptionTester(o.state()['block'])
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
    
    @exported_block(changes='explicit')
    def get_block(self):
        return self.__block
    
    def replace_block(self, block):
        self.__block = block
        self.state_changed('block')


class TestLooseCell(unittest.TestCase):
    def setUp(self):
        self.lc = LooseCell(value=0, key='a', type=int)
    
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


class TestViewCell(unittest.TestCase):
    def setUp(self):
        self.lc = LooseCell(value=0, key='a', type=int)
        self.delta = 1
        self.vc = ViewCell(
            base=self.lc,
            get_transform=lambda x: x + self.delta,
            set_transform=lambda x: x - self.delta,
            key='b',
            type=int)
    
    # TODO: Add tests for behavior when the transform is not perfectly one-to-one (such as due to floating-point error).
    
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


class TestCommandCell(unittest.TestCase):
    def setUp(self):
        self.specimen = DecoratorCommandSpecimen()
    
    def test_method(self):
        self.assertEqual(0, self.specimen.count)
        r = self.specimen.cmd()
        self.assertEqual(None, r)
        self.assertEqual(1, self.specimen.count)
    
    def test_cell(self):
        self.assertEqual(0, self.specimen.count)
        self.specimen.state()['cmd'].set(None)  # TODO: Stop overloading 'set' to mean 'invoke'
        self.assertEqual(1, self.specimen.count)


class DecoratorCommandSpecimen(ExportedState):
    def __init__(self):
        self.count = 0
    
    @command()
    def cmd(self):
        self.count += 1


class TestStateInsert(unittest.TestCase):
    object = None
    
    def test_success(self):
        self.object = InsertFailSpecimen()
        self.object.state_from_json({'foo': {'fail': False}})
        self.assertEqual(['foo'], self.object.state().keys())
    
    def test_failure(self):
        self.object = InsertFailSpecimen()
        self.object.state_from_json({'foo': {'fail': True}})
        # throws but exception is caught
        self.assertEqual([], self.object.state().keys())
    
    def test_undefined(self):
        """no state_insert method defined"""
        self.object = CollectionState(CellDict(dynamic=True))
        self.object.state_from_json({'foo': {'fail': True}})
        # throws but exception is caught
        self.assertEqual([], self.object.state().keys())


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

    @exported_block(changes='never')
    def get_block(self):
        return self.__block
