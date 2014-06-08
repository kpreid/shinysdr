#!/usr/bin/env python

# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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


'''
Config interface.

The "public" operations on these objects are used by configuration files to specify configuration. The "private" operations are then used by main to implement the configuration.
'''


from __future__ import absolute_import, division

import base64
import os
import warnings

from twisted.internet import defer
from twisted.python import log

# Note that gnuradio-dependent modules are loaded lazily, to avoid the startup time if all we're going to do is give a usage message
from shinysdr.db import DatabaseModel, database_from_csv, databases_from_directory


__all__ = [
	'Config',
	'make_default_config'
]


class Config(object):
	def __init__(self, reactor):
		# public config elements
		self.sources = _ConfigDict(self)
		self.databases = _ConfigDbs(self, reactor)
		self.accessories = _ConfigAccessories(self)

		# might be wanted
		self.reactor = reactor
		
		# these are to be read by main
		self._state_filename = None
		self._service_makers = []
		
		# private
		self.__waiting = []
		self.__finished = False
	
	@defer.inlineCallbacks
	def _wait_and_validate(self):
		yield defer.gatherResults(self.__waiting)
		
		self.__finished = True
		if len(self._service_makers) == 0:
			warnings.warn('No network service defined!')
	
	def _not_finished(self):
		if self.__finished:
			raise Exception('Too late to modify configuration')
	
	def wait_for(self, deferred):
		'''Wait for the provided Deferred before assuming the configuration to be finished.'''
		self._not_finished()
		self.__waiting.append(defer.maybeDeferred(lambda: deferred))
	
	def persist_to_file(self, filename):
		self._not_finished()
		self._state_filename = str(filename)

	def serve_web(self, http_endpoint, ws_endpoint, root_cap='%(root_cap)s', title=u'ShinySDR'):
		self._not_finished()
		# TODO: See if we're reinventing bits of Twisted service stuff here
		
		def make_service(top, note_dirty):
			import shinysdr.web as lazy_web
			return lazy_web.WebService(
				reactor=self.reactor,
				top=top,
				note_dirty=note_dirty,
				read_only_dbs=self.databases._get_read_only_databases(),
				writable_db=self.databases._get_writable_database(),
				http_endpoint=http_endpoint,
				ws_endpoint=ws_endpoint,
				root_cap=root_cap,
				title=title)
		
		self._service_makers.append(make_service)

	def serve_ghpsdr(self):
		self._not_finished()
		# TODO: Alternate services should be provided using getPlugins rather than hardcoded
		def make_service(top, note_dirty):
			import shinysdr.plugins.ghpsdr as lazy_ghpsdr
			return lazy_ghpsdr.DspserverService(top, note_dirty, 'tcp:8000')
		
		self._service_makers.append(make_service)


class _ConfigDict(object):
	def __init__(self, config):
		self._values = {}
		self._config = config

	def add(self, key, value):
		self._config._not_finished()
		key = unicode(key)
		if key in self._values:
			raise KeyError('Key %r already present' % (key,))
		self._values[key] = value


class _ConfigAccessories(_ConfigDict):
	def add(self, key, value):
		self._config._not_finished()
		import shinysdr.values as lazy_values
		
		if key in self._values:
			raise KeyError('Accessory key %r already present' % (key,))
		
		def f(r):
			self._values[key] = r
		
		self._values[key] = lazy_values.nullExportedState
		defer.maybeDeferred(lambda: value).addCallback(f)


class _ConfigDbs(object):
	__read_only_databases = None
	__writable_db = None
	
	def __init__(self, config, reactor):
		self._config = config
		self.__reactor = reactor
	
	def add_directory(self, path):
		self._config._not_finished()
		path = str(path)
		if self.__read_only_databases is not None:
			raise Exception('Multiple database directories are not yet supported.')
		self.__read_only_databases, path_diagnostics = databases_from_directory(self.__reactor, path)
		for d in path_diagnostics:
			log.msg('%s: %s' % d)

	def add_writable_database(self, path):
		self._config._not_finished()
		path = str(path)
		if self.__writable_db is not None:
			raise Exception('Multiple writable databases are not yet supported.')
		self.__writable_db, diagnostics = database_from_csv(self.__reactor, path, writable=True)
		for d in diagnostics:
			log.msg('%s: %s' % (path, d))
	
	def _get_writable_database(self):
		if self.__writable_db is None:
			# TODO temporary stub till the client takes more configurability -- we should omit the writable db rather than having an unbacked one
			self.__writable_db = DatabaseModel(None, [], writable=True)
		return self.__writable_db
	
	def _get_read_only_databases(self):
		if self.__read_only_databases is None:
			self.__read_only_databases = {}
		return self.__read_only_databases


def make_default_config():
	return '''\
import shinysdr.plugins.osmosdr
import shinysdr.plugins.simulate

# OsmoSDR generic device source; handles USRP, RTL-SDR, FunCube
# Dongle, HackRF, etc.
# If desired, add sample_rate=<n> parameter.
# Use shinysdr.plugins.osmosdr.OsmoSDRProfile to set more parameters
# to make the best use of your specific hardware's capabilities.
config.sources.add(u'osmo', shinysdr.plugins.osmosdr.OsmoSDRSource(''))

# For hardware which uses a sound-card as its ADC or appears as an
# audio device.
config.sources.add(u'audio', shinysdr.source.AudioSource(''))

# Locally generated RF signals for test purposes.
config.sources.add(u'sim', shinysdr.plugins.simulate.SimulatedSource())

config.persist_to_file('state.json')

config.databases.add_directory('dbs/')

config.serve_web(
	# These are in Twisted endpoint description syntax:
	# <http://twistedmatrix.com/documents/current/api/twisted.internet.endpoints.html#serverFromString>
	# Note: ws_endpoint must currently be 1 greater than http_endpoint; if one
	# is SSL then both must be. These restrictions will be relaxed later.
	http_endpoint='tcp:8100',
	ws_endpoint='tcp:8101',

	# A secret placed in the URL as simple access control. Does not
	# provide any real security unless using HTTPS. The default value
	# in this file has been automatically generated from 128 random bits.
	# Set to None to not use any secret.
	root_cap='%(root_cap)s'
	
	# Page title / station name
	title='ShinySDR')
''' % {'root_cap': base64.urlsafe_b64encode(os.urandom(128 // 8)).replace('=', '')}
