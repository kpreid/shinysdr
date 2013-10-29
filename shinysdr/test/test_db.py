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
from twisted.web import client
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
				u'freq': 1e6,
				u'mode': u'',
				u'label': u'a',
				u'notes': u'',
			}])


class TestDBWeb(unittest.TestCase):
	def setUp(self):
		dbResource = db.DatabaseResource(os.path.join(os.path.dirname(__file__), 'test_db_data.csv'))
		self.port = reactor.listenTCP(0, server.Site(dbResource), interface="127.0.0.1")
	
	def tearDown(self):
		return self.port.stopListening()
	
	def __url(self, path):
		return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
	
	def test_response(self):
		def callback(s):
			j = json.loads(s)
			self.assertEqual(j, [
				{
					u'type': u'channel',
					u'freq': 10e6,
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
				},
			])
		return client.getPage(self.__url('/')).addCallback(callback)

