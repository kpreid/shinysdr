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
import os
import os.path
import shutil
import StringIO
import tempfile

from gnuradio import blocks
from gnuradio import gr

from twisted.internet import reactor as the_reactor
from twisted.internet import defer
from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.internet.protocol import Protocol
from twisted.internet.task import Clock
from twisted.logger import Logger, formatEvent
from twisted.test.proto_helpers import StringTransport
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
from shinysdr.values import ExportedState, InterestTracker, IDeltaSubscriber, ISubscription, SubscriptionContext, nullExportedState


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
    def __init__(self, cell, delta=False, interest_tracking=True):
        SubscriptionTester.__init__(self)
        self.cell = cell
        self.__interest_tracking = interest_tracking
        
        self.expected = []
        self.seen = []
        self.unsubscribed = False
        
        if interest_tracking and not isinstance(cell.interest_tracker, LoopbackInterestTracker):
            raise Exception('cell\'s interest_tracker must be a LoopbackInterestTracker or interest testing must be disabled')
        
        if delta:
            self.__subscriber = _DeltaSubscriber(self)
        else:
            self.__subscriber = _DeltaSubscriber(self).__call__
        
        gotten_value = cell.get()
        if interest_tracking and cell.interest_tracker.interested:
            raise Exception('interested true too soon')
        initial_value, self.subscription = cell.subscribe2(self.__subscriber, self.context)
        if interest_tracking and not cell.interest_tracker.interested:
            raise Exception('interested did not become true')
        verifyObject(ISubscription, self.subscription)
        if initial_value != gotten_value:
            raise Exception('claimed initial value {!r} did not match current get() value {!r}; this is not prohibited but likely a mistake if it occurs in tests'
                .format(initial_value, gotten_value))
        
        if len(self.seen) > 0:
            raise Exception('unexpected callback on subscription from {!r}, with value {!r}'.format(self.cell, self.seen[0]))
    
    def _log_subscriber_call(self, kind, value):
        if self.unsubscribed:
            raise Exception('unexpected subscription callback after unsubscribe from {!r}, with value {!r}'.format(self.cell, value))
        # TODO distinguish kinds
        self.seen.append((kind, value))
    
    def expect_now(self, expected_value, kind='value'):
        if len(self.seen) > len(self.expected):
            actual_value = self.seen[len(self.expected)]
            raise Exception('too-soon callback from {!r}; saw {!r}'.format(self.cell, actual_value))
        self.advance()
        self.should_have_seen(expected_value, kind=kind)
    
    def should_have_seen(self, expected_value, kind='value'):
        expected_kind_and_value = kind, expected_value
        i = len(self.expected)
        self.expected.append(expected_value)
        if len(self.seen) < len(self.expected):
            raise Exception('no subscription callback from {!r}; expected {!r}'.format(self.cell, expected_value))
        actual_kind_and_value = self.seen[i]
        if actual_kind_and_value != expected_kind_and_value:
            raise Exception('expected {!r} from {!r}; saw {!r}'.format(expected_kind_and_value, self.cell, actual_kind_and_value))
    
    def unsubscribe(self):
        assert not self.unsubscribed
        self.subscription.unsubscribe()
        self.unsubscribed = True
        if self.__interest_tracking and self.cell.interest_tracker.interested:
            raise Exception('interested did not become false')


class LoopbackInterestTracker(InterestTracker):
    """Kludge for CellSubscriptionTester's convenience."""
    
    interested = False
    
    def __init__(self):
        InterestTracker.__init__(self, self.__set)
    
    def __set(self, interested):
        self.interested = interested


@implementer(IDeltaSubscriber)
class _DeltaSubscriber(object):
    def __init__(self, subscription_tester):
        self.__subscription_tester = subscription_tester
    
    def __call__(self, value):
        self.__subscription_tester._log_subscriber_call('value', value)
    
    def append(self, patch):
        self.__subscription_tester._log_subscriber_call('append', patch)
    
    def prepend(self, patch):
        self.__subscription_tester._log_subscriber_call('prepend', patch)


class Cells(ExportedState):
    """Helper to create an ExportedState of arbitrary non-dynamic shape."""
    def __init__(self, cells):
        self.__cells = cells
    
    def state_def(self):
        for kv in self.__cells.iteritems():
            yield kv

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
        
    def setUpFor(self, mode, demod_class=None, state=None, skip_if_unavailable=False):
        # pylint: disable=attribute-defined-outside-init
        if state is None:
            state = {}
        mode_def = lookup_mode(mode, include_unavailable=True)
        if mode_def and not mode_def.available and skip_if_unavailable:
            raise unittest.SkipTest('mode {!r} marked unavailable'.format(mode))
        if mode_def is not None and demod_class is None:
            demod_class = mode_def.demod_class
        if demod_class is None:
            if mode_def is None:
                raise Exception('Mode {!r} not registered'.format(mode))
            else:
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
    # This is nearly an alias for http_request but reads better
    return http_request(reactor, url, method='GET', accept=accept)


def http_post_json(reactor, url, value):
    # in principle this could be streaming if we had a pipe-thing to glue between json.dump and FileBodyProducer, but it isn't worth building that for tests
    return http_request(reactor, url,
        method='POST',
        body=json.dumps(value),
        more_headers={'Content-Type': 'application/json'})


def http_request(reactor, url, method, body=None, accept=None, more_headers=None):
    agent = client.Agent(reactor)
    headers = Headers()
    if accept is not None:
        headers.addRawHeader('Accept', str(accept))
    if more_headers:
        for k, v in more_headers.iteritems():
            headers.addRawHeader(str(k), str(v))
    d = agent.request(
        method=str(method),
        uri=str(url),
        headers=headers,
        bodyProducer=client.FileBodyProducer(StringIO.StringIO(str(body))) if body else None)
    return _handle_agent_response(d)


def _handle_agent_response(d):
    def callback(response):
        finished = defer.Deferred()
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
        self.data = b''

    def dataReceived(self, data):
        self.data += data
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        self.finished.callback(self.data)


def assert_http_resource_properties(test_case, url):
    """Common properties all HTTP resources should have."""
    def callback((response, data)):
        # If this fails, we probably made a mistake
        test_case.assertNotEqual(response.code, http.NOT_FOUND)
        
        csp = response.headers.getRawHeaders(b'Content-Security-Policy')
        test_case.assertEqual(1, len(csp))
        test_case.assertEqual(
            [
                b"default-src 'self' 'unsafe-inline'",
                b"connect-src 'self' ws://*:* wss://*:*",
                b"img-src 'self' data: blob:",
                b"media-src http: https: file: blob:",
                b"object-src 'none'",
                b"base-uri 'self'",
            ],
            csp[0].split(b';'))
        test_case.assertEqual([b'no-referrer'], response.headers.getRawHeaders(b'Referrer-Policy'))
        test_case.assertEqual([b'nosniff'], response.headers.getRawHeaders(b'X-Content-Type-Options'))
        
        content_type = response.headers.getRawHeaders(b'Content-Type')[0]
        if content_type == 'application/json':
            json.loads(data)  # raises error if it doesn't parse
        elif content_type.startswith('text/html'):
            test_case.assertRegex(content_type, r'(?i)text/html;\s*charset=utf-8')
            test_case.assertRegex(data, br'(?i)<!doctype html>')
        elif content_type in ('application/javascript', 'text/javascript'):
            pass
        else:
            raise Exception('Don\'t know what content type checking to do', data[0], content_type)
    
    return http_get(the_reactor, url).addCallback(callback)


# --- Miscellaneous ---


class Files(object):
    """Creates files described from a data structure in a managed temporary directory.
    
    The data structure consists of dicts for directories and strings for files.
    """
    def __init__(self, desc):
        self.dir = tempfile.mkdtemp(prefix='shinysdr_test_config_tmp')
        self.create(desc)
    
    def create(self, desc):
        self.__create(self.dir + '/.', desc)
    
    def close(self):
        shutil.rmtree(self.dir)
    
    def __create(self, path, desc):
        assert path.startswith(self.dir + '/')
        assert not os.path.exists(path) or os.path.isdir(path)
        if isinstance(desc, basestring):
            with open(path, 'w') as f:
                f.write(desc)
        elif isinstance(desc, dict):
            if not os.path.exists(path):
                os.mkdir(path)
            for k, d in desc.iteritems():
                self.__create(os.path.join(path, k), d)
        else:
            raise TypeError('don\'t know what to do with {!r} at {!r}'.format(desc, path))


class LogTester(object):
    """Helper for making assertions about what was logged to a twisted.logging.Logger."""
    def __init__(self):
        self.log = Logger(observer=self.__add_event)
        self.logged = []
        
    def __add_event(self, event):
        self.logged.append(_LogEventTester(event))
    
    def check(self, *expected_messages):
        if len(self.logged) != len(expected_messages):
            raise AssertionError('Expected {} log messages but saw {} {!r}'.format(
                len(expected_messages), len(self.logged), self.logged))
        for actual, expected in zip(self.logged, expected_messages):
            actual.check(**expected)


class _LogEventTester(object):
    def __init__(self, event):
        self.event = event
    
    def check(self, **features):
        for key, expected_value in features.iteritems():
            if key == 'text':
                text = formatEvent(self.event)
                if text != expected_value:
                    raise AssertionError('Expected log event to look like\n{!r}\nbut was\n{!r}\n{!r}'.format(
                        expected_value, text, self.event))
            else:
                if self.event[key] != expected_value:
                    raise AssertionError('Expected log event to have {!r}: {!r} but was \n{!r}'.format(
                        key, expected_value, self.event))
    
    def __repr__(self):
        return '<LogEventTester {!r}>'.format(self.event)


@implementer(IStreamClientEndpoint)
class StringTransportEndpoint(object):
    """Endpoint for a fresh StringTransport. Intended for tests."""
    def __init__(self):
        self.string_transport = StringTransport()
    
    def connect(self, protocol_factory):
        protocol = protocol_factory.buildProtocol(None)
        protocol.makeConnection(self.string_transport)
        return defer.succeed(protocol)
