# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol
from twisted.web import client
from twisted.web import http
from twisted.web.http_headers import Headers

from shinysdr.plugins.simulate import SimulatedDevice
from shinysdr.top import Top


# --- Radio test utilities ---


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
