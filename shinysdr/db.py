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

from twisted.web import resource
from twisted.web import http

import cgi
import csv
import errno
import json
import os.path
import urllib
import warnings


class DatabasesResource(resource.Resource):
	isLeaf = False
	
	def __init__(self, path):
		resource.Resource.__init__(self)
		self.putChild('', _DbsIndexResource(self))
		self.names = []
		try:
			filenames = os.listdir(path)
		except OSError as e:
			warnings.warn('Error opening database directory %r: %r' % (path, e))
			return
		for name in filenames:
			if name.endswith('.csv'):
				with open(os.path.join(path, name), 'rb') as csvfile:
					database = _parse_csv_file(csvfile)
				self.putChild(name, DatabaseResource(database))
				self.names.append(name)


class _DbsIndexResource(resource.Resource):
	isLeaf = True
	defaultContentType = 'text/html'
	
	def __init__(self, dbs_resource):
		resource.Resource.__init__(self)
		self.dbs_resource = dbs_resource
	
	def render_GET(self, request):
		request.write('<html><title>Databases</title><ul>')
		for name in self.dbs_resource.names:
			request.write('<li><a href="%s/">%s</a>' % (cgi.escape(urllib.quote(name, '')), name))
		request.write('</ul>')
		return ''


class DatabaseResource(resource.Resource):
	isLeaf = False
	
	def __init__(self, database):
		resource.Resource.__init__(self)
		def instantiate(i):
			self.putChild(str(i), _RecordResource(database[i]))
		self.putChild('', _DbIndexResource(database, instantiate))
		for i, record in enumerate(database):
			instantiate(i)


class _DbIndexResource(resource.Resource):
	isLeaf = True
	defaultContentType = 'application/json'
	
	def __init__(self, db, instantiate):
		resource.Resource.__init__(self)
		self.__db = db
		self.__instantiate = instantiate
	
	def render_GET(self, request):
		return json.dumps(self.__db)
	
	def render_POST(self, request):
		desc = json.load(request.content)
		record = _normalize_record(desc['new'])
		self.__db.append(record)
		index = len(self.__db) - 1
		self.__instantiate(index)
		url = request.prePathURL() + str(index)
		request.setResponseCode(http.CREATED)
		request.setHeader('Content-Type', 'text/plain')
		request.setHeader('Location', url)
		return url


class _RecordResource(resource.Resource):
	isLeaf = True
	defaultContentType = 'application/json'
	
	def __init__(self, record):
		resource.Resource.__init__(self)
		self.record = record
	
	def render_GET(self, request):
		return json.dumps(self.record)
	
	def render_POST(self, request):
		assert request.getHeader('Content-Type') == 'application/json'
		patch = json.load(request.content)
		old = _normalize_record(patch['old'])
		new = patch['new']
		if old == self.record:
			# TODO check syntax of record
			self.record.clear()
			self.record.update(new)
			request.setResponseCode(http.NO_CONTENT)
			return ''
		else:
			request.setResponseCode(http.CONFLICT)
			request.setHeader('Content-Type', 'text/plain')
			return 'Old values did not match: %r vs %r' % (old, self.record)


def _parse_csv_file(csvfile):
	db = []
	for csvrec in csv.DictReader(csvfile):
		# csv does not deal in unicode itself
		csvrec = {unicode(k, 'utf-8'): unicode(v, 'utf-8')
			for k, v in csvrec.iteritems()
				if v is not None}
		#print csvrec
		if 'Frequency' not in csvrec:
			# TODO: warn properly
			print 'skipping record without frequency'
			continue
		record = {
			u'mode': csvrec.get('Mode', ''),
			u'label': csvrec.get('Name', ''),
			u'notes': csvrec.get('Comment', ''),
		}
		# TODO remove this conflation and add proper 2.5kHz support
		if record['mode'] == u'FM':
			record['mode'] = u'NFM'
		freq_str = csvrec['Frequency']
		if '-' in freq_str:
			# extension of format: bands
			record[u'type'] = u'band'
			record[u'lowerFreq'], record[u'upperFreq'] = map(_parse_freq, freq_str.split('-'))
		else:
			record[u'type'] = u'channel'
			record[u'lowerFreq'] = record[u'upperFreq'] = _parse_freq(freq_str)
		# extension of format: location
		if csvrec.get('Latitude', '') != '' and csvrec.get('Longitude', '') != '':
			record[u'location'] = [float(csvrec['Latitude']), float(csvrec['Longitude'])]
		else:
			record[u'location'] = None
		db.append(record)
	return db


def _parse_freq(freq_str):
	return 1e6 * float(freq_str)


def _normalize_record(record):
	'''Normalize values in a record dict.'''
	# TODO: type/syntax check
	out = {}
	for k, v in record.iteritems():
		# JSON/JS/JSON roundtrip turns integral floats into ints
		if isinstance(v, int):
			v = float(v)
		out[k] = v
	return out
