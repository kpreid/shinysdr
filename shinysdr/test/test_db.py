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

import json
import os.path
import StringIO

from twisted.trial import unittest
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol
from twisted.web import client
from twisted.web import http
from twisted.web import server

from shinysdr import db


class TestCSV(unittest.TestCase):
	def __parse(self, s):
		return db._parse_csv_file(StringIO.StringIO(s))
	
	def test_short_line(self):
		self.assertEqual(
			self.__parse('Frequency,Name,Comment\n1,a'),
			[{
				u'type': u'channel',
				u'lowerFreq': 1e6,
				u'upperFreq': 1e6,
				u'mode': u'',
				u'label': u'a',
				u'notes': u'',
				u'location': None
			}])

class TestDBWeb(unittest.TestCase):
	test_data_json = [
		{
			u'type': u'channel',
			u'lowerFreq': 10e6,
			u'upperFreq': 10e6,
			u'mode': u'AM',
			u'label': u'name',
			u'notes': u'comment',
			u'location': [0, 90],
		},
		{
			u'type': u'band',
			u'lowerFreq': 10e6,
			u'upperFreq': 20e6,
			u'mode': u'AM',
			u'label': u'bandname',
			u'notes': u'comment',
			u'location': None,
		},
	]
	
	def setUp(self):
		dbResource = db.DatabaseResource(self.test_data_json)
		self.port = reactor.listenTCP(0, server.Site(dbResource), interface="127.0.0.1")
	
	def tearDown(self):
		return self.port.stopListening()
	
	def __url(self, path):
		return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
	
	def test_response(self):
		def callback(s):
			j = json.loads(s)
			self.assertEqual(j, self.test_data_json)
		return client.getPage(self.__url('/')).addCallback(callback)

	def test_update_good(self):
		new_record = {
			u'type': u'channel',
			u'lowerFreq': 20e6,
			u'upperFreq': 20e6,
		}
		index = 0
		modified = self.test_data_json[:]
		modified[index] = new_record

		d = post(self.__url('/' + str(index)), {
			'old': self.test_data_json[index],
			'new': new_record
		})

		def proceed((response, data)):
			if response.code >= 300:
				print data
			self.assertEqual(response.code, http.NO_CONTENT)
			def check(s):
				j = json.loads(s)
				self.assertEqual(j, modified)
			return client.getPage(self.__url('/')).addCallback(check)
		d.addCallback(proceed)
		return d

	def test_create(self):
		new_record = {
			u'type': u'channel',
			u'freq': 20e6,
		}

		d = post(self.__url('/'), {
			'new': new_record
		})

		def proceed((response, data)):
			if response.code >= 300:
				print data
			self.assertEqual(response.code, http.CREATED)
			url = 'ONLYONE'.join(response.headers.getRawHeaders('Location'))
			self.assertEqual(url, self.__url('/2'))  # URL of new entry
			def check(s):
				j = json.loads(s)
				self.assertEqual(j[-1], new_record)
			return client.getPage(self.__url('/')).addCallback(check)
		d.addCallback(proceed)
		return d


def post(url, value):
	agent = client.Agent(reactor)
	d = agent.request('POST', url,
		headers=client.Headers({'Content-Type': ['application/json']}),
		# in principle this could be streaming if we had a pipe-thing to glue between json.dump and FileBodyProducer
		bodyProducer=client.FileBodyProducer(StringIO.StringIO(json.dumps(value))))
	def callback(response):
		finished = Deferred()
		if response.code == http.NO_CONTENT:
			# TODO: properly get whether there is a body from the response
			# this is a special case because with no content deliverBody never signals connectionLost
			finished.callback((response, None))
		else:
			response.deliverBody(Accumulator(finished))
			finished.addCallback(lambda data: (response, data))
		return finished
	d.addCallback(callback)
	return d


class Accumulator(Protocol):
	# TODO eliminate this boilerplate
	def __init__(self, finished):
		self.finished = finished
		self.data = ''

	def dataReceived(self, chunk):
		self.data += chunk
	
	def connectionLost(self, reason):
		self.finished.callback(self.data)
