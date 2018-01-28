# -*- coding: utf-8 -*-
# Copyright 2018 Kevin Reid and the ShinySDR contributors
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

from gnuradio.blocks import vector_source_i, vector_sink_i

from twisted.internet import defer
from twisted.internet.task import Clock
from twisted.trial import unittest
from zope.interface import implementer

from shinysdr.i.depgraph import BlockFitting, IFitting, IFittingFactory, Plumber, _RepeatingAsyncTask


class TestPlumberDirect(unittest.TestCase):
    """Tests of Plumber interacting with stub objects without GR.
    
    These tests do not exercise the interaction with GR but they more closely check the interaction between Plumber and IFitting.
    """
    
    def setUp(self):
        self.clock = Clock()
        self.p = Plumber(self.clock)
    
    def test_just_one(self):
        log = []
        self.p.add_explicit_candidate(MockFittingFactory('f1', log.append))
        self.clock.advance(1)
        self.assertEqual(log, ['f1 construct', 'f1 open'])
    
    def test_simple_dependencies(self):
        log = []
        f1 = MockFittingFactory('f1', log.append)
        f2 = MockFittingFactory('f2', log.append)
        f3 = MockFittingFactory('f3', log.append, [f1, f2])
        self.p.add_explicit_candidate(f3)
        self.clock.advance(1)
        self.assertEqual(set(log), {
            # TODO: assert with specific ordering constraints instead of arbitrary
            'f3 construct',
            'f1 construct',
            'f2 construct',
            'f1 open',
            'f3 open',
            'f2 open',
        })
    
    def test_change_dependencies(self):
        log = []
        f1a = MockFittingFactory('f1a', log.append)
        f1b = MockFittingFactory('f1b', log.append)
        f2 = MockFittingFactory('f2', log.append, [f1a])
        self.p.add_explicit_candidate(f2)
        self.clock.advance(1)
        self.assertEqual(set(log), {
            'f2 construct',
            'f1a construct',
            'f2 open',
            'f1a open',
        })
        log[:] = []
        f2.deps = [f1b]
        f2.remote_rebuild_me()
        self.clock.advance(1)
        self.assertEqual(set(log), {
            'f2 construct',
            'f1b construct',
            'f1a close',
            'f2 close',
            'f1b open',
            'f2 open',
        })


class TestPlumberWithGR(unittest.TestCase):
    """Tests of Plumber specifically working with GR blocks."""
    
    def setUp(self):
        self.clock = Clock()
        self.p = Plumber(self.clock)
    
    def test_trivial_connection(self):
        a = GRSourceFactory([10, 20, 30, 40])
        b = GRSinkFactory(a)
        self.p.add_explicit_candidate(b)
        self.clock.advance(1)
        self.p.wait_and_resume()
        self.assertEqual(b.block.data(), (10, 20, 30, 40))
    
    def test_change_requested_input(self):
        # setup
        a1 = GRSourceFactory([10])
        a2 = GRSourceFactory([20])
        b = GRSinkFactory(a1)
        self.p.add_explicit_candidate(b)
        
        # first run
        self.clock.advance(1)
        self.p.wait_and_resume()
        
        # swap inputs
        b.change_input_to(a2)
        
        # second run
        self.clock.advance(1)
        self.p.wait_and_resume()
        
        self.assertEqual(b.block.data(), (10, 20))


@implementer(IFittingFactory)
class GRSourceFactory(object):
    def __init__(self, data):
        self.data = data
        self.block = vector_source_i(self.data)
        self.seen_context = None
    
    def __call__(self, fitting_context):
        self.seen_context = fitting_context
        return defer.succeed(BlockFitting(
            fitting_context=fitting_context,
            block=self.block))


@implementer(IFittingFactory)
class GRSinkFactory(object):
    def __init__(self, input_ff):
        self.__input = IFittingFactory(input_ff)
        self.block = vector_sink_i()
        self.seen_context = None
    
    def __call__(self, fitting_context):
        self.seen_context = fitting_context
        return defer.succeed(BlockFitting(
            fitting_context=fitting_context,
            block=self.block,
            input_ff=self.__input))
    
    def change_input_to(self, input_ff):
        self.__input = IFittingFactory(input_ff)
        self.seen_context.rebuild_me()
    
    def swap_block(self):
        self.block = vector_sink_i()
        self.seen_context.rebuild_me()


class TestRepeatingAsyncTask(unittest.TestCase):
    # _RepeatingAsyncTask is strictly internal, but hairy enough we would like to test it separately.
    
    def setUp(self):
        self.clock = Clock()
    
    def tearDown(self):
        self.flushLoggedErrors(self.DummyException)
    
    def test_simple_repeat(self):
        calls = []
        
        def f():
            calls.append(1)
        
        rat = _RepeatingAsyncTask(self.clock, f)
        rat.start()
        self.assertEqual(calls, [])
        self.clock.advance(1)
        self.assertEqual(calls, [1])
        rat.start()
        self.clock.advance(1)
        self.assertEqual(calls, [1, 1])
    
    def test_failure_ok(self):
        # pylint: disable=unreachable
        # TODO: This test causes unhandled errors that cause random later tests to fail and is therefore disabled. Figure out how to make it polite.
        raise unittest.SkipTest()
        
        calls = []
        
        def f():
            calls.append(1)
            raise self.DummyException()
        
        rat = _RepeatingAsyncTask(self.clock, f)
        rat.start()
        self.assertEqual(calls, [])
        self.clock.advance(1)
        self.assertEqual(calls, [1])
        rat.start()
        self.clock.advance(1)
        self.assertEqual(calls, [1, 1])
    
    # TODO: Test start() called in middle of task
    # TODO: Test explicit lack of overlap
    # TODO: Test return value of start()
    
    class DummyException(Exception):
        pass


@implementer(IFittingFactory)
class MockFittingFactory(object):
    def __init__(self, label, log_fn=lambda: None, deps=None):
        self.label = label
        self.log_fn = log_fn
        self.deps = deps or []
        self.instance_serial = 0
        self.instances = []
    
    def __repr__(self):
        return 'FF({})'.format(self.label)
    
    def __call__(self, fitting_context):
        self.instance_serial += 1
        fitting = MockFitting(fitting_context, self, self.instance_serial)
        self.instances.append(fitting)
        return fitting
    
    def remote_rebuild_me(self):
        for fitting in self.instances:
            fitting.fitting_context.rebuild_me()


@implementer(IFitting)
class MockFitting(object):
    def __init__(self, fitting_context, mock_fitting_factory, serial):
        self.serial = serial
        self.ff = mock_fitting_factory
        self.fitting_context = fitting_context
        self.ff.log_fn(self.ff.label + ' construct')
    
    def __repr__(self):
        return 'F({} #{})'.format(self.ff.label, self.serial)
    
    def open(self):
        self.ff.log_fn(self.ff.label + ' open')
    
    def close(self):
        self.ff.log_fn(self.ff.label + ' close')
        
    def deps(self):
        return self.ff.deps


# TODO temp debug
# import sys
# from twisted.logger import Logger, STDLibLogObserver, globalLogBeginner, textFileLogObserver
# globalLogBeginner.beginLoggingTo([textFileLogObserver(sys.stderr)])


# t = TestPlumber()
# t.setUp()
# t.test_trivial_connection()
