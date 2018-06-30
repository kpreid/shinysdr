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

from __future__ import absolute_import, division, unicode_literals

from twisted.trial import unittest

from shinysdr.i.poller import Poller
from shinysdr.test.testutil import LogTester
from shinysdr.values import ExportedState, LooseCell, exported_value, setter


class TestPoller(unittest.TestCase):
    def setUp(self):
        self.log_tester = LogTester()
        self.poller = Poller(log=self.log_tester.log)
    
    def tearDown(self):
        self.flushLoggedErrors(DummyBrokenGetterException)
    
    def test_trivial_direct(self):
        cells = PollerCellsSpecimen()
        cell = cells.state()['foo']
        called = []
        
        def callback(value):
            called.append(value)
        
        sub = self.poller.subscribe(cell, callback, fast=True)
        self.assertEqual([], called, 'initial')
        self.poller.poll(True)
        self.assertEqual([], called, 'noop poll')
        cells.set_foo('a')
        self.assertEqual([], called, 'after set')
        self.poller.poll(True)
        self.assertEqual(['a'], called, 'poll after set')
        
        sub.unsubscribe()
        cells.set_subscribable('b')
        self.poller.poll(True)
        self.assertEqual(['a'], called, 'no poll after unsubscribe')
    
    def test_initially_throwing_getter(self):
        """Check fallback behavior when a cell getter throws."""
        called = []
        
        def callback(value):
            called.append(value)
        
        broken_cell = BrokenGetterSpecimen(True).state()['foo']
        self.poller.subscribe(broken_cell, callback, fast=True)
        self.log_tester.check(dict(log_format='Exception in {cell}.get()', cell=broken_cell))
        
        self.assertEqual(called, [])
        self.poller.poll(True)
        self.assertEqual(called, [])
        
    def test_later_throwing_getter(self):
        called = []
        
        def make_callback(key):
            def callback(value):
                called.append((key, value))
            return callback
        
        bgs = BrokenGetterSpecimen(False)
        not_broken_1 = PollerCellsSpecimen().state()['foo']
        broken_cell = bgs.state()['foo']
        not_broken_2 = PollerCellsSpecimen().state()['foo']
        self.poller.subscribe(not_broken_1, make_callback('1'), fast=True)
        self.poller.subscribe(broken_cell, make_callback('b'), fast=True)
        self.poller.subscribe(not_broken_2, make_callback('2'), fast=True)
        self.assertEqual(called, [])
        bgs.broken = True
        self.log_tester.check()
        self.poller.poll(True)
        self.log_tester.check(dict(log_format='Exception in {cell}.get()', cell=broken_cell))
        self.assertEqual(called, [])
    
    # TODO: test multiple subscription behavior wrt throwing
    # TODO: test interest updates on initial throw


class PollerCellsSpecimen(ExportedState):
    """Helper for TestPoller"""
    foo = None
    
    def __init__(self):
        self.subscribable = LooseCell(value='', type=str, writable=True)
    
    def state_def(self):
        for d in super(PollerCellsSpecimen, self).state_def():
            yield d
        # TODO make this possible to be decorator style
        yield 'subscribable', self.subscribable
    
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


class BrokenGetterSpecimen(ExportedState):
    def __init__(self, initially_broken):
        self.broken = initially_broken
    
    @exported_value(changes='continuous', persists=False)
    def get_foo(self):
        if self.broken:
            raise DummyBrokenGetterException()
        else:
            return 1000


class DummyBrokenGetterException(Exception):
    pass
