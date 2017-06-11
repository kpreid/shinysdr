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
import StringIO

from gnuradio import blocks
from gnuradio import gr

from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol
from twisted.internet.task import Clock
from twisted.trial import unittest
from twisted.web import client
from twisted.web import http
from twisted.web.http_headers import Headers
from zope.interface import implementer
from zope.interface.verify import verifyObject

from shinysdr.devices import Device, IComponent, IRXDriver, ITXDriver
from shinysdr.grc import DemodulatorAdapter
from shinysdr.i.modes import lookup_mode
from shinysdr.i.poller import Poller
from shinysdr.interfaces import IDemodulator
from shinysdr.signals import SignalType
from shinysdr.types import RangeT
from shinysdr.values import ExportedState, SubscriptionContext, nullExportedState


# --- Values/types/state test utilities


def state_smoke_test(value):
    """Retrieve every value in the given ExportedState instance and its children."""
    assert isinstance(value, ExportedState)
    for cell in value.state().itervalues():
        value = cell.get()
        if cell.type().is_reference():
            state_smoke_test(value)


class SubscriptionTester(object):
    """Manages a mock SubscriptionContext."""
    def __init__(self):
        self.__clock = Clock()
        self.context = SubscriptionContext(
            reactor=self.__clock,
            poller=Poller())
    
    def advance(self):
        # support both 'real' subscriptions and poller subscriptions
        self.__clock.advance(1)
        self.context.poller.poll_all()


class CellSubscriptionTester(SubscriptionTester):
    """Subscribes to a single cell and checks the subscription's behavior."""
    def __init__(self, cell):
        SubscriptionTester.__init__(self)
        self.cell = cell
        self.expected = []
        self.seen = []
        self.subscription = cell.subscribe2(self.__callback, self.context)
        if not self.subscription:
            raise Exception('missing subscription object')
        self.unsubscribed = False
    
    def __callback(self, value):
        if self.unsubscribed:
            raise Exception('unexpected subscription callback after unsubscribe from {!r}, with value {!r}'.format(self.cell, value))
        self.seen.append(value)
    
    def expect_now(self, expected_value):
        if len(self.seen) > len(self.expected):
            actual_value = self.seen[len(self.expected)]
            raise Exception('too-soon callback from {!r}; saw {!r}'.format(self.cell, actual_value))
        self.advance()
        self.should_have_seen(expected_value)
    
    def should_have_seen(self, expected_value):
        i = len(self.expected)
        self.expected.append(expected_value)
        if len(self.seen) < len(self.expected):
            raise Exception('no subscription callback from {!r}; expected {!r}'.format(self.cell, expected_value))
        actual_value = self.seen[i]
        if actual_value != expected_value:
            raise Exception('expected {!r} from {!r}; saw {!r}'.format(expected_value, self.cell, actual_value))
    
    def unsubscribe(self):
        assert not self.unsubscribed
        self.subscription.unsubscribe()
        self.unsubscribed = True


# --- Radio test utilities ---


class DeviceTestCase(unittest.TestCase):
    def setUp(self):
        # pylint: disable=unidiomatic-typecheck
        self.__noop = type(self) is DeviceTestCase
        if not hasattr(self, 'device') and not self.__noop:
            raise Exception('No device specified for DeviceTestCase')
        
    def setUpFor(self, device):
        # pylint: disable=attribute-defined-outside-init
        self.device = device
        DeviceTestCase.setUp(self)  # neither super nor self call
    
    def tearDown(self):
        if self.__noop: return
        self.device.close()
    
    def test_smoke(self):
        if self.__noop: return
        self.assertIsInstance(self.device, Device)
        # also tests close() by way of tearDown
    
    def test_rx_implements(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        verifyObject(IRXDriver, rx_driver)
    
    def test_rx_output_type(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        t = rx_driver.get_output_type()
        self.assertIsInstance(t, SignalType)
        self.assertTrue(t.get_sample_rate() > 0)
        self.assertEquals(t.get_itemsize(), gr.sizeof_gr_complex)  # float not supported yet
    
    def test_rx_tune_delay(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        self.assertIsInstance(rx_driver.get_tune_delay(), float)
    
    def test_rx_usable_bandwidth(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        self.assertIsInstance(rx_driver.get_usable_bandwidth(), RangeT)
    
    def test_rx_notify(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        # No specific expectations, but it shouldn't throw.
        rx_driver.notify_reconnecting_or_restarting()
    
    def test_tx_implements(self):
        if self.__noop: return
        tx_driver = self.device.get_tx_driver()
        if tx_driver is nullExportedState: return
        verifyObject(ITXDriver, tx_driver)
    
    def test_tx_input_type(self):
        if self.__noop: return
        tx_driver = self.device.get_tx_driver()
        if tx_driver is nullExportedState: return
        t = tx_driver.get_input_type()
        self.assertIsInstance(t, SignalType)
        self.assertTrue(t.get_sample_rate() > 0)
        self.assertEquals(t.get_itemsize(), gr.sizeof_gr_complex)  # float not supported yet
    
    def test_tx_notify(self):
        if self.__noop: return
        tx_driver = self.device.get_tx_driver()
        if tx_driver is nullExportedState: return
        # No specific expectations, but it shouldn't throw.
        tx_driver.notify_reconnecting_or_restarting()
    
    def test_tx_set_transmitting(self):
        if self.__noop: return
        tx_driver = self.device.get_tx_driver()
        if tx_driver is nullExportedState: return
        
        nhook = [0]
        
        def midpoint_hook():
            nhook[0] += 1
        
        # hook is always called exactly once
        tx_driver.set_transmitting(True, midpoint_hook)
        self.assertEqual(nhook, 1)
        tx_driver.set_transmitting(True, midpoint_hook)
        self.assertEqual(nhook, 2)
        tx_driver.set_transmitting(False, midpoint_hook)
        self.assertEqual(nhook, 3)
        tx_driver.set_transmitting(False, midpoint_hook)
        self.assertEqual(nhook, 4)


class DemodulatorTestCase(unittest.TestCase):
    """
    Set up an environment for testing a demodulator and do some fundamental tests.
    """

    def setUp(self):
        # pylint: disable=unidiomatic-typecheck
        self.__noop = type(self) is DemodulatorTestCase
        if not hasattr(self, 'demodulator') and not self.__noop:
            raise Exception('No demodulator specified for DemodulatorTestCase')
        
    def setUpFor(self, mode, demod_class=None, state=None):
        # pylint: disable=attribute-defined-outside-init
        if state is None:
            state = {}
        mode_def = lookup_mode(mode)
        if mode_def is not None and demod_class is None:
            demod_class = mode_def.demod_class
        if demod_class is None:
            raise Exception('Demodulator not registered for mode {!r}'.format(mode))
        
        # Wire up top block. We don't actually want to inspect the signal processing; we just want to see if GR has a complaint about the flow graph connectivity.
        self.__top = gr.top_block()
        self.__adapter = DemodulatorAdapter(
            mode=mode,
            demod_class=demod_class,
            input_rate=100000,
            output_rate=22050,
            quiet=True)
        self.demodulator = self.__adapter.get_demodulator()
        self.__top.connect(
            blocks.vector_source_c([]),
            (self.__adapter, 0),
            blocks.null_sink(gr.sizeof_float))
        self.__top.connect(
            (self.__adapter, 1),
            blocks.null_sink(gr.sizeof_float))
        
        DemodulatorTestCase.setUp(self)  # neither super nor self call
    
    def tearDown(self):
        if self.__noop: return
        self.__top.stop()
        self.__top.wait()
    
    def test_implements(self):
        if self.__noop: return
        verifyObject(IDemodulator, self.demodulator)
    
    def test_state(self):
        if self.__noop: return
        state_smoke_test(self.demodulator)


@implementer(IComponent)
class StubComponent(ExportedState):
    """Minimal implementation of IComponent."""
    def close():
        pass


@implementer(IRXDriver)
class StubRXDriver(gr.hier_block2, ExportedState):
    """Minimal implementation of IRXDriver."""
    __signal_type = SignalType(kind='IQ', sample_rate=10000)
    __usable_bandwidth = RangeT([(-1e9, 1e9)])  # TODO magic numbers

    def __init__(self):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex))
        self.connect(blocks.vector_source_c([]), self)
    
    def get_output_type(self):
        return self.__signal_type

    def get_tune_delay(self):
        return 0.0
    
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth
    
    def close(self):
        pass
    
    def notify_reconnecting_or_restarting(self):
        pass


@implementer(ITXDriver)
class StubTXDriver(gr.hier_block2, ExportedState):
    """Minimal implementation of ITXDriver."""
    __signal_type = SignalType(kind='IQ', sample_rate=10000)
    
    def __init__(self):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(0, 0, 0))
        self.connect(self, blocks.null_sink(gr.sizeof_gr_complex))
    
    def get_input_type(self):
        return self.__signal_type

    def get_tune_delay(self):
        return 0.0
    
    def close(self):
        pass
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        pass


# --- HTTP test utilities ---


def http_get(reactor, url, accept=None):
    agent = client.Agent(reactor)
    headers = Headers()
    if accept is not None:
        headers.addRawHeader('Accept', str(accept))
    d = agent.request('GET', url, headers=headers)
    return _handle_agent_response(d)


def http_post(reactor, url, value):
    agent = client.Agent(reactor)
    d = agent.request('POST', url,
        headers=client.Headers({'Content-Type': ['application/json']}),
        # in principle this could be streaming if we had a pipe-thing to glue between json.dump and FileBodyProducer
        bodyProducer=client.FileBodyProducer(StringIO.StringIO(json.dumps(value))))
    return _handle_agent_response(d)


def _handle_agent_response(d):
    def callback(response):
        finished = Deferred()
        if response.code == http.NO_CONTENT:
            # TODO: properly get whether there is a body from the response
            # this is a special case because with no content deliverBody never signals connectionLost
            finished.callback((response, None))
        else:
            response.deliverBody(_Accumulator(finished))
            finished.addCallback(lambda data: (response, data))
        return finished
    d.addCallback(callback)
    return d


class _Accumulator(Protocol):
    # TODO eliminate this boilerplate
    def __init__(self, finished):
        self.finished = finished
        self.data = ''

    def dataReceived(self, data):
        self.data += data
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        self.finished.callback(self.data)
