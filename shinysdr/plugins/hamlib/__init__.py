# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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
Plugin for Hamlib hardware interfaces.

To use this plugin, add something like this to your config file:

import shinysdr.plugins.hamlib
config.devices.add('my-other-radio',
	shinysdr.plugins.hamlib.connect_to_rig(config.reactor,
		options=['-m', '<model ID>', '-r', '<device file name>']))

TODO explain how to link up with soundcard devices
'''

# pylint: disable=no-init
# (no-init is pylint being confused by interfaces)


from __future__ import absolute_import, division

import os.path
import re
import subprocess

from zope.interface import implements, Interface

from twisted.internet import defer
from twisted.internet.error import ConnectionRefusedError
from twisted.internet.protocol import ClientFactory, Protocol
from twisted.internet.task import LoopingCall, deferLater
from twisted.protocols.basic import LineReceiver
from twisted.python import log
from twisted.web import static

from shinysdr.devices import Device
from shinysdr.top import IHasFrequency
from shinysdr.types import Enum, Range
from shinysdr.values import Cell, ExportedState, LooseCell
from shinysdr.web import ClientResourceDef


__all__ = []  # appended later


class IProxy(Interface):
	'''
	Marker interface for hamlib proxies (rig, rotator).
	'''


class IRig(IProxy):
	'''
	Hamlib rig proxy (anything interfaced by rigctld).
	'''


def _forkDeferred(d):
	# No doubt this demonstrates I don't actually know how to program in Twisted
	
	def callback(v):
		d2.callback(v)
		return v
	
	def errback(f):
		d2.errback(f)
		f.trap()  # always fail
	
	d2 = defer.Deferred()
	d.addCallbacks(callback, errback)
	return d2


_modes = Enum({x: x for x in ['USB', 'LSB', 'CW', 'CWR', 'RTTY', 'RTTYR', 'AM', 'FM', 'WFM', 'AMS', 'PKTLSB', 'PKTUSB', 'PKTFM', 'ECSSUSB', 'ECSSLSB', 'FAX', 'SAM', 'SAL', 'SAH', 'DSB']})


_vfos = Enum({'VFOA': 'VFO A', 'VFOB': 'VFO B', 'VFOC': 'VFO C', 'currVFO': 'currVFO', 'VFO': 'VFO', 'MEM': 'MEM', 'Main': 'Main', 'Sub': 'Sub', 'TX': 'TX', 'RX': 'RX'})


_passbands = Range([(0, 0)])


_info = {
	'Frequency': (Range([(0, 9999999999)], integer=True)),
	'Mode': (_modes),
	'Passband': (_passbands),
	'VFO': (_vfos),
	'RIT': (int),
	'XIT': (int),
	'PTT': (bool),
	'DCD': (bool),
	'Rptr Shift': (Enum({'+': '+', '-': '-'})),
	'Rptr Offset': (int),
	'CTCSS Tone': (int),
	'DCS Code': (str),
	'CTCSS Sql': (int),
	'DCS Sql': (str),
	'TX Frequency': (int),
	'TX Mode': (_modes),
	'TX Passband': (_passbands),
	'Split': (bool),
	'TX VFO': (_vfos),
	'Tuning Step': (int),
	'Antenna': (int),
}


_commands = {
	'freq': ['Frequency'],
	'mode': ['Mode', 'Passband'],
	'vfo': ['VFO'],
	'rit': ['RIT'],
	'xit': ['XIT'],
	#'ptt': ['PTT'], # writing disabled until when we're more confident in correct functioning
	'rptr_shift': ['Rptr Shift'],
	'rptr_offs': ['Rptr Offset'],
	'ctcss_tone': ['CTCSS Tone'],
	'dcs_code': ['DCS Code'],
	'ctcss_sql': ['CTCSS Sql'],
	'dcs_sql': ['DCS Sql'],
	'split_freq': ['TX Frequency'],
	'split_mode': ['TX Mode', 'TX Passband'],
	'split_vfo': ['Split', 'TX VFO'],
	'ts': ['Tuning Step'],
	# TODO: describe func, level, parm
	'ant': ['Antenna'],
	'powerstat': ['Power Stat'],
}


_how_to_command = {key: command
	for command, keys in _commands.iteritems()
	for key in keys}


_cap_remap = {
	# TODO: Make this well-founded
	'Ant': ['Antenna'],
	'CTCSS Squelch': ['CTCSS Sql'],
	'CTCSS': ['CTCSS Tone'],
	'DCS Squelch': ['DCS Sql'],
	'DCS': ['DCS Code'],
	'Mode': ['Mode', 'Passband'],
	'Repeater Offset': ['Rptr Offset', 'Rptr Shift'],
	'Split Freq': ['TX Frequency'],
	'Split Mode': ['TX Mode', 'TX Passband'],
	'Split VFO': ['Split', 'TX VFO'],
}


@defer.inlineCallbacks
def connect_to_server(reactor, host='localhost', port=4532):
	connected = defer.Deferred()
	reactor.connectTCP(host, port, _RigctldClientFactory(connected))
	protocol = yield connected
	#print 'top connected ', protocol.transport
	rigObj = _HamlibRig(protocol)
	yield rigObj.sync()  # allow dump_caps round trip
	defer.returnValue(Device(
		vfo_cell=rigObj.state()['freq'],
		components={'rig': rigObj}))


__all__.append('connect_to_server')


@defer.inlineCallbacks
def connect_to_rig(reactor, options=None, port=4532):
	'''
	Start a rigctld process and connect to it.
	
	options: list of rigctld options, e.g. ['-m', '123', '-r', '/dev/ttyUSB0'].
	Do not specify host or port directly.
	'''
	if options is None:
		options = []
	host = '127.0.0.1'
	
	# We use rigctld instead of rigctl, because rigctl will only execute one command at a time and does not have the better-structured response formats.
	# If it were possible, we'd rather connect to rigctld over a pipe or unix-domain socket to avoid port allocation issues.

	# Make sure that there isn't (as best we can check) something using the port already.
	fake_connected = defer.Deferred()
	reactor.connectTCP(host, port, _RigctldClientFactory(fake_connected))
	try:
		yield fake_connected
		raise Exception('Something is already using port %i!' % port)
	except ConnectionRefusedError:
		pass
	
	process = subprocess.Popen(
		args=['/usr/bin/env', 'rigctld', '-T', host, '-t', str(port)] + options,
		stdin=None,
		stdout=None,
		stderr=None,
		close_fds=True)
	
	# Retry connecting with exponential backoff, because the rigctld process won't tell us when it's started listening.
	rig_device = None
	refused = None
	for i in xrange(0, 5):
		try:
			rig_device = yield connect_to_server(reactor, host=host, port=port)
			break
		except ConnectionRefusedError, e:
			refused = e
			yield deferLater(reactor, 0.1 * (2 ** i), lambda: None)
	else:
		raise refused
	
	rig_device.get_components()['rig'].when_closed().addCallback(lambda _: process.kill())
	
	defer.returnValue(rig_device)


__all__.append('connect_to_rig')


class _HamlibRig(ExportedState):
	implements(IRig, IHasFrequency)
	
	def __init__(self, protocol):
		# info from hamlib
		self.__cache = {}
		self.__caps = {}
		self.__levels = []
		
		# keys are same as __cache, values are functions to call with new values from rig
		self._cell_updaters = {}
		
		self.__protocol = protocol
		self.__disconnect_deferred = defer.Deferred()
		protocol._set_rig(self)

		# TODO: If hamlib backend supports "transceive mode", use it in lieu of polling
		self.__poller_slow = LoopingCall(self.__poll_slow)
		self.__poller_fast = LoopingCall(self.__poll_fast)
		self.__poller_slow.start(2.0)
		self.__poller_fast.start(0.2)
		
		protocol.rc_send('dump_caps')
	
	def sync(self):
		return self.__protocol.rc_sync()
	
	def close(self):
		self.__protocol.transport.loseConnection()
		return self.when_closed()
	
	def when_closed(self):
		return _forkDeferred(self.__disconnect_deferred)
	
	def _ehs_get(self, name_in_cmd):
		if name_in_cmd in self.__cache:
			return self.__cache[name_in_cmd]
		else:
			return 0.0
	
	#def __query(self, name_full):
	#	self.__protocol.rc_send('get_' + _info[name_full][0])
	
	def _clientReceived(self, command, key, value):
		if command == 'dump_caps':
			def write(key):
				self.__caps[key] = value
				if key == 'Get level':
					# add to polling info
					for info in value.strip().split(' '):
						match = re.match(r'^(\w+)\([^()]+\)$', info)
						# part in parens is probably min/max/step info, but we don't have any working examples to test against (they are all 0)
						if match:
							self.__levels.append(match.group(1))
						else:
							log.err('Unrecognized level description from rigctld: ' + info)
			
			# remove irregularity
			keymatch = re.match(r'(Can [gs]et )([\w\s,/-]+)', key)
			if keymatch and keymatch.group(2) in _cap_remap:
				for mapped in _cap_remap[keymatch.group(2)]:
					write(keymatch.group(1) + mapped)
			else:
				write(key)
		else:
			self.__update_cache_and_cells(key, value)
	
	def _clientReceivedLevel(self, level_name, value_str):
		self.__update_cache_and_cells(level_name + ' level', value_str)
	
	def __update_cache_and_cells(self, key, value):
		self.__cache[key] = value
		if key in self._cell_updaters:
			self._cell_updaters[key](value)
	
	def _clientConnectionLost(self, reason):
		self.__poller_slow.stop()
		self.__poller_fast.stop()
		self.__disconnect_deferred.callback(None)
	
	def _ehs_set(self, name_full, value):
		if not isinstance(value, str):
			raise TypeError()
		name_in_cmd = _how_to_command[name_full]  # raises if cannot set
		if value != self.__cache[name_full]:
			self.__cache[name_full] = value
			self.__protocol.rc_send('set_' + name_in_cmd + ' ' + ' '.join(
				[self.__cache[arg_name] for arg_name in _commands[name_in_cmd]]))
	
	def state_def(self, callback):
		super(_HamlibRig, self).state_def(callback)
		for name in _info:
			can_get = self.__caps.get('Can get ' + name)
			if can_get is None:
				log.msg('No can-get information for ' + name)
			if can_get != 'Y':
				# TODO: Handle 'E' condition
				continue
			writable = name in _how_to_command and self.__caps.get('Can set ' + name) == 'Y'
			_install_cell(self, name, False, writable, callback, self.__caps)
		for level_name in self.__levels:
			# TODO support writable levels
			_install_cell(self, level_name + ' level', True, False, callback, self.__caps)

	def __poll_fast(self):
		# TODO: Stop if we're getting behind
		p = self.__protocol
		
		# likely to be set by hw controls
		p.rc_send('get_freq')
		p.rc_send('get_mode')
		
		# received signal info
		p.rc_send('get_dcd')
		for level_name in self.__levels:
			p.rc_send('get_level ' + level_name)
	
	def __poll_slow(self):
		# TODO: Stop if we're getting behind
		p = self.__protocol
		
		p.rc_send('get_vfo')
		p.rc_send('get_rit')
		p.rc_send('get_xit')
		p.rc_send('get_ptt')
		p.rc_send('get_rptr_shift')
		p.rc_send('get_rptr_offs')
		p.rc_send('get_ctcss_tone')
		p.rc_send('get_dcs_code')
		p.rc_send('get_split_freq')
		p.rc_send('get_split_mode')
		p.rc_send('get_split_vfo')
		p.rc_send('get_ts')


def _install_cell(self, name, is_level, writable, callback, caps):
	# this is a function for the sake of the closure variables
	
	if name == 'Frequency':
		cell_name = 'freq'  # consistency with our naming scheme elsewhere, also IHasFrequency
	else:
		cell_name = name
	
	if is_level:
		# TODO: Use range info from hamlib if available
		if name == 'STRENGTH level':
			ctor = Range([(-54, 50)], strict=False)
		elif name == 'SWR level':
			ctor = Range([(1, 30)], strict=False)
		elif name == 'RFPOWER level':
			ctor = Range([(0, 100)], strict=False)
		else:
			ctor = Range([(-10, 10)], strict=False)
	elif name == 'Mode' or name == 'TX Mode':
		# kludge
		ctor = Enum({x: x for x in caps['Mode list'].strip().split(' ')})
	elif name == 'VFO' or name == 'TX VFO':
		ctor = Enum({x: x for x in caps['VFO list'].strip().split(' ')})
	else:
		ctor = _info[name]
	
	def updater(strval):
		if ctor is bool:
			value = bool(int(strval))
		else:
			value = ctor(strval)
		cell.set_internal(value)
	
	def actually_write_value(value):
		if ctor is bool:
			self._ehs_set(name, str(int(value)))
		else:
			self._ehs_set(name, str(ctor(value)))
	
	cell = LooseCell(key=cell_name, value='placeholder', ctor=ctor, writable=writable, persists=False, post_hook=actually_write_value)
	self._cell_updaters[name] = updater
	updater(self._ehs_get(name))
	callback(cell)


class _RigctldClientFactory(ClientFactory):
	def __init__(self, connected_deferred):
		self.__connected_deferred = connected_deferred
	
	def buildProtocol(self, addr):
		p = _RigctldClientProtocol(self.__connected_deferred)
		return p

	def clientConnectionFailed(self, connector, reason):
		self.__connected_deferred.errback(reason)


class _RigctldClientProtocol(Protocol):
	def __init__(self, connected_deferred):
		self.__rig_obj = None
		self.__connected_deferred = connected_deferred
		self.__line_receiver = LineReceiver()
		self.__line_receiver.delimiter = '\n'
		self.__line_receiver.lineReceived = self.__lineReceived
		self.__sent = 0
		self.__syncers = []
		self.__receive_cmd = None
		self.__receive_arg = None
	
	def connectionMade(self):
		#print 'connectionMade protocol', self.transport
		self.__connected_deferred.callback(self)
	
	def connectionLost(self, reason):
		#print 'connectionLost protocol'
		if self.__rig_obj is not None:
			self.__rig_obj._clientConnectionLost(reason)
	
	def dataReceived(self, data):
		self.__line_receiver.dataReceived(data)
	
	def __lineReceived(self, line):
		if self.__receive_cmd is None:
			match = re.match(r'^(\w+):\s*(.*)$', line)
			if match is not None:
				# command response starting line
				self.__receive_cmd = match.group(1)
				self.__receive_arg = match.group(2)
				return
			log.err('Unrecognized line (no command active) from rigctld: ' + line)
		else:
			match = re.match(r'^RPRT (.*)$', line)
			if match is not None:
				# command response ending line
				# TODO: Report errors
				self.__receive_cmd = None
				self.__receive_arg = None
				self.__sent -= 1
				# TODO: this is not a proper algorithm; we need to match send point to receive point. This can stall if commands are being sent constantly
				if self.__sent == 0:
					for syncer in self.__syncers:
						syncer.callback(None)
					self.__syncers[:] = []
				return
			if self.__receive_cmd == 'get_level':
				# Should be a level value
				match = re.match(r'^-?\d+\.?\d*$', line)
				if match:
					self.__rig_obj._clientReceivedLevel(self.__receive_arg, line)
					return
			match = re.match(r'^([\w ,/-]+):\s*(.*)$', line)
			if match is not None:
				# Command response
				if self.__rig_obj is not None:
					self.__rig_obj._clientReceived(self.__receive_cmd, match.group(1), match.group(2))
					return
			match = re.match(r'^\t', line)
			if match is not None and self.__receive_cmd == 'dump_caps':
				# Sub-info from dump_caps, not currently used
				return
			match = re.match(r'^Warning--', line)
			if match is not None:
				# Warning from dump_caps, not currently used
				return
			match = re.match(r'^$', line)
			if match is not None:
				return
			log.err('Unrecognized line during ' + self.__receive_cmd + ' from rigctld: ' + line)
	
	def _set_rig(self, rig):
		self.__rig_obj = rig
	
	def rc_sync(self):
		d = defer.Deferred()
		self.__syncers.append(d)
		return d
	
	def rc_send(self, cmd):
		# TODO: assert no newlines for safety
		self.transport.write('+\\' + cmd + '\n')
		self.__sent += 1
	
_plugin_client = ClientResourceDef(
	key=__name__,
	resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
	loadURL='hamlib.js')
