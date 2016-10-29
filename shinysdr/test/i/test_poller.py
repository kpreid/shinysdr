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
from shinysdr.values import ExportedState, LooseCell, exported_value, setter


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
        
        # pylint: disable=no-member
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
    """Helper for TestPoller"""
    foo = None
    
    def __init__(self):
        self.subscribable = LooseCell(key='subscribable', value='', type=str)
    
    def state_def(self, callback):
        super(PollerCellsSpecimen, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(self.subscribable)
    
    # force worst-case
    def state_is_dynamic(self):
        return True
    
    @exported_value(changes='continuous', persists=False)
    def get_foo(self):
        return self.foo

    @setter
    def set_foo(self, value):
        self.foo = value

    def get_subscribable(self):
        return self.subscribable.get()
    
    def set_subscribable(self, value):
        self.subscribable.set(value)
