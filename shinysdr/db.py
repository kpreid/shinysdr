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

import cgi
import csv
import json
import os.path
import urllib


class DatabasesResource(resource.Resource):
	isLeaf = False
	
	def __init__(self, path):
		resource.Resource.__init__(self)
		self.putChild('', _DbsIndexResource(self))
		self.names = []
		for name in os.listdir(path):
			if name.endswith('.csv'):
				self.putChild(name, DatabaseResource(os.path.join(path, name)))
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
	
	def __init__(self, path):
		resource.Resource.__init__(self)
		with open(path, 'rb') as csvfile:
			database = _parse_csv_file(csvfile)
		self.putChild('', _DbIndexResource(database))


class _DbIndexResource(resource.Resource):
	isLeaf = True
	defaultContentType = 'application/json'
	
	def __init__(self, db):
		resource.Resource.__init__(self)
		self.db = db
	
	def render_GET(self, request):
		return json.dumps(self.db)


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
			record[u'freq'] = _parse_freq(freq_str)
		# extension of format: location
		if csvrec.get('Latitude', '') != '' and csvrec.get('Longitude', '') != '':
			record[u'location'] = [float(csvrec['Latitude']), float(csvrec['Longitude'])]
		db.append(record)
	return db


def _parse_freq(freq_str):
	return 1e6 * float(freq_str)
