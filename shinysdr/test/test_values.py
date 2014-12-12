# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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


# pylint: disable=no-member, attribute-defined-outside-init


from __future__ import absolute_import, division

import unittest

from shinysdr.types import Range
from shinysdr.values import ExportedState, BlockCell, CollectionState, LooseCell, Poller, ViewCell, exported_value, setter, unserialize_exported_state


class TestExportedState(unittest.TestCase):
    def test_persistence_basic(self):
        self.object = ValueAndBlockSpecimen(ValueAndBlockSpecimen(ExportedState()))
        self.assertEqual(self.object.state_to_json(), {
            u'value': 0,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })
        self.object.state_from_json({
            u'value': 1,
            u'block': {
                u'value': 2,
                u'block': {},
            },
        })
        self.assertEqual(self.object.state_to_json(), {
            u'value': 1,
            u'block': {
                u'value': 2,
                u'block': {},
            },
        })
    
    # TODO: test persistence error cases like unknown or wrong-typed properties
    
    def test_persistence_args(self):
        self.object = unserialize_exported_state(
            ctor=ValueAndBlockSpecimen,
            kwargs={u'block': ValueAndBlockSpecimen(ExportedState())},
            state={
                u'value': 1,
            })
        self.assertEqual(self.object.state_to_json(), {
            u'value': 1,
            u'block': {
                u'value': 0,
                u'block': {},
            },
        })


class ValueAndBlockSpecimen(ExportedState):
    '''Helper for TestExportedState'''
    def __init__(self, block, value=0):
        self.value = value
        self.block = block
        
    def state_def(self, callback):
        super(ValueAndBlockSpecimen, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'block'))
    
    @exported_value(ctor=float, parameter='value')
    def get_value(self):
        return self.value
    
    @setter
    def set_value(self, value):
        self.value = value


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
    '''Helper for TestDecorator'''
    @exported_value(ctor=float)
    def get_inherited(self):
        return 9


class DecoratorInheritanceSpecimen(DecoratorInheritanceSpecimenSuper):
    '''Helper for TestDecorator'''
    def __init__(self):
        self.rw = 0.0
    
    @exported_value(ctor=Range([(0.0, 10.0)]))
    def get_rw(self):
        return self.rw
    
    @setter
    def set_rw(self, value):
        self.rw = value


class TestBlockCell(unittest.TestCase):
    def setUp(self):
        self.obj_value = ExportedState()
        self.object = BlockCellSpecimen(self.obj_value)
    
    def test_block_cell_value(self):
        cell = self.object.state()['block']
        self.assertEqual(cell.get(), self.obj_value)


class BlockCellSpecimen(ExportedState):
    '''Helper for TestBlockCell'''
    block = None
    
    def __init__(self, block):
        self.block = block
    
    def state_def(self, callback):
        super(BlockCellSpecimen, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'block'))


class TestViewCell(unittest.TestCase):
    def setUp(self):
        self.lc = LooseCell(value=0, key='a', ctor=int)
        self.vc = ViewCell(
            base=self.lc,
            get_transform=lambda x: x + 1,
            set_transform=lambda x: x - 1,
            key='b',
            ctor=int)
    
    def test_get_set(self):
        self.assertEqual(0, self.lc.get())
        self.assertEqual(1, self.vc.get())
        self.vc.set(2)
        self.assertEqual(1, self.lc.get())
        self.assertEqual(2, self.vc.get())
        self.lc.set(3)
        self.assertEqual(3, self.lc.get())
        self.assertEqual(4, self.vc.get())
    
    def test_subscription(self):
        fired = []
        
        def f():
            fired.append(self.vc.get())
        
        self.vc.subscribe(f)
        self.lc.set(1)
        self.assertEqual([2], fired)


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
        '''no state_insert method defined'''
        self.object = CollectionState({}, dynamic=True)
        self.object.state_from_json({'foo': {'fail': True}})
        # throws but exception is caught
        self.assertEqual([], self.object.state().keys())


class InsertFailSpecimen(CollectionState):
    '''Helper for TestStateInsert'''
    def __init__(self):
        self.table = {}
        CollectionState.__init__(self, self.table, dynamic=True)
    
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
    '''Helper for TestCellIdentity'''
    value = 1
    block = None
    
    def __init__(self):
        self.block = ExportedState()
    
    # force worst-case
    def state_is_dynamic(self):
        return True
    
    @exported_value()
    def get_value(self):
        return 9

    def state_def(self, callback):
        super(CellIdentitySpecimen, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'block'))


class TestPoller(unittest.TestCase):
    def setUp(self):
        self.poller = Poller()
        self.cells = PollerCellsSpecimen()
    
    def test_trivial(self):
        cell = self.cells.state()['foo']
        called = [0]
        
        def callback():
            called[0] += 1
        
        sub = self.poller.subscribe(cell, callback)
        self.assertEqual(0, called[0], 'initial')
        self.poller.poll()
        self.assertEqual(0, called[0], 'noop poll')
        self.cells.set_foo('a')
        self.assertEqual(0, called[0], 'after set')
        self.poller.poll()
        self.assertEqual(1, called[0], 'poll after set')
        
        sub.unsubscribe()
        self.cells.set_subscribable('b')
        self.poller.poll()
        self.assertEqual(1, called[0], 'no poll after unsubscribe')
    
    def test_subscription_support(self):
        cell = self.cells.state()['subscribable']
        called = [0]
        
        def callback():
            called[0] += 1
        
        sub = self.poller.subscribe(cell, callback)
        self.assertEqual(0, self.poller._Poller__targets.count_keys(), 'no polling')
        self.assertEqual(0, called[0], 'initial')
        self.cells.set_subscribable('a')
        self.assertEqual(0, called[0], 'after set')
        self.assertEqual('a', self.cells.get_subscribable())
        self.poller.poll()
        self.assertEqual(1, called[0], 'poll after set')
        
        sub.unsubscribe()
        self.cells.set_subscribable('b')
        self.poller.poll()
        self.assertEqual(1, called[0], 'no poll after unsubscribe')


class PollerCellsSpecimen(ExportedState):
    '''Helper for TestPoller'''
    foo = None
    
    def __init__(self):
        self.subscribable = LooseCell(key='subscribable', value='', ctor=str)
    
    def state_def(self, callback):
        super(PollerCellsSpecimen, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(self.subscribable)
    
    # force worst-case
    def state_is_dynamic(self):
        return True
    
    @exported_value()
    def get_foo(self):
        return self.foo

    @setter
    def set_foo(self, value):
        self.foo = value

    def get_subscribable(self):
        return self.subscribable.get()
    
    def set_subscribable(self, value):
        self.subscribable.set(value)
