# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=signature-differs
# (signature-differs: twisted is inconsistent about connectionMade/connectionLost)

import json
import StringIO

from gnuradio import gr

from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol
from twisted.trial import unittest
from twisted.web import client
from twisted.web import http
from twisted.web.http_headers import Headers

from shinysdr.devices import Device
from shinysdr.plugins.simulate import SimulatedDevice
from shinysdr.signals import SignalType
from shinysdr.top import Top
from shinysdr.types import Range
from shinysdr.values import nullExportedState


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
        self.assertIsInstance(rx_driver.get_usable_bandwidth(), Range)
    
    def test_rx_notify(self):
        if self.__noop: return
        rx_driver = self.device.get_rx_driver()
        if rx_driver is nullExportedState: return
        # No specific expectations, but it shouldn't throw.
        rx_driver.notify_reconnecting_or_restarting()
    
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


class DemodulatorTester(object):
    '''
    Set up an environment for testing a demodulator.
    '''
    def __init__(self, mode):
        # TODO: Refactor things so that we can take the demod ctor rather than a mode string
        # TODO: Tell the simulated device to have no modulators, or have a simpler dummy source for testing, so we don't waste time on setup
        self.__top = Top(devices={'s1': SimulatedDevice()})
        self.__top.add_receiver(mode, key='a')
        self.__top.start()  # TODO overriding internals
    
    def close(self):
        if self.__top is not None:
            self.__top.stop()
            self.__top = None
    
    def __enter__(self):
        pass
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


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

    def dataReceived(self, chunk):
        self.data += chunk
    
    def connectionLost(self, reason):
        self.finished.callback(self.data)
