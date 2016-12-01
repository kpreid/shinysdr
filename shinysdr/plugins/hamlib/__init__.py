# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

"""
Plugin for Hamlib hardware interfaces.

To use this plugin, add something like this to your config file:

import shinysdr.plugins.hamlib
config.devices.add('my-other-radio',
    shinysdr.plugins.hamlib.connect_to_rig(config.reactor,
        options=['-m', '<model ID>', '-r', '<device file name>']))

TODO explain how to link up with soundcard devices
"""

from __future__ import absolute_import, division

import os.path
import re
import subprocess
import time

from zope.interface import implements, Interface

from twisted.internet import defer
from twisted.internet.error import ConnectionRefusedError
from twisted.internet.protocol import ClientFactory, Protocol
from twisted.internet.task import LoopingCall, deferLater
from twisted.protocols.basic import LineReceiver
from twisted.python import log
from twisted.web import static

from shinysdr.devices import Device, IComponent
from shinysdr.interfaces import ClientResourceDef, IHasFrequency
from shinysdr.twisted_ext import fork_deferred
from shinysdr.types import Enum, Notice, Range
from shinysdr.values import ExportedState, LooseCell, exported_value


__all__ = []  # appended later


class IProxy(Interface):
    """
    Marker interface for hamlib proxies (rig, rotator).
    """


__all__.append('IProxy')


class IRig(IProxy):
    """
    Hamlib rig proxy (anything interfaced by rigctld).
    """


__all__.append('IRig')


class IRotator(IProxy):
    """
    Hamlib rotator proxy (anything interfaced by rotctld).
    """


__all__.append('IRotator')


# Hamlib RPRT error codes
RIG_OK = 0
RIG_EINVAL = -1
RIG_ECONF = -2
RIG_ENOMEM = -3
RIG_ENIMPL = -4
RIG_ETIMEOUT = -5
RIG_EIO = -6
RIG_EINTERNAL = -7
RIG_EPROTO = -7
RIG_ERJCTED = -8
RIG_ETRUNC = -9
RIG_ENAVAIL = -10
RIG_ENTARGET = -11
RIG_BUSERROR = -12
RIG_BUSBUSY = -13
RIG_EARG = -14
RIG_EVFO = -15
RIG_EDOM = -16


_modes = Enum({x: x for x in ['USB', 'LSB', 'CW', 'CWR', 'RTTY', 'RTTYR', 'AM', 'FM', 'WFM', 'AMS', 'PKTLSB', 'PKTUSB', 'PKTFM', 'ECSSUSB', 'ECSSLSB', 'FAX', 'SAM', 'SAL', 'SAH', 'DSB']}, strict=False)


_vfos = Enum({'VFOA': 'VFO A', 'VFOB': 'VFO B', 'VFOC': 'VFO C', 'currVFO': 'currVFO', 'VFO': 'VFO', 'MEM': 'MEM', 'Main': 'Main', 'Sub': 'Sub', 'TX': 'TX', 'RX': 'RX'}, strict=False)


_passbands = Range([(0, 0)])


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
    
    'Position': ['Azimuth', 'Elevation'],
}


@defer.inlineCallbacks
def connect_to_rigctld(reactor, host='localhost', port=4532):
    """
    Connect to an existing rigctld process.
    """
    proxy = yield _connect_to_daemon(
        reactor=reactor,
        host=host,
        port=port,
        server_name='rigctld',
        proxy_ctor=_HamlibRig)
    defer.returnValue(Device(
        vfo_cell=proxy.state()['freq'],
        components={'rig': proxy}))


__all__.append('connect_to_rigctld')


@defer.inlineCallbacks
def connect_to_rotctld(reactor, host='localhost', port=4533):
    """
    Connect to an existing rotctld process.
    """
    proxy = yield _connect_to_daemon(
        reactor=reactor,
        host=host,
        port=port,
        server_name='rotctld',
        proxy_ctor=_HamlibRotator)
    defer.returnValue(Device(
        components={'rotator': proxy}))


__all__.append('connect_to_rotctld')


@defer.inlineCallbacks
def _connect_to_daemon(reactor, host, port, server_name, proxy_ctor):
    connected = defer.Deferred()
    reactor.connectTCP(host, port, _HamlibClientFactory(server_name, connected))
    protocol = yield connected
    proxy = proxy_ctor(protocol)
    yield proxy._ready_deferred  # wait for dump_caps round trip
    defer.returnValue(proxy)


def connect_to_rig(reactor, options=None, port=4532):
    """
    Start a rigctld process and connect to it.
    
    options: list of rigctld options, e.g. ['-m', '123', '-r', '/dev/ttyUSB0'].
    Do not specify host or port in the options.
    
    port: A free port number to use.
    """
    return _connect_to_device(
        reactor=reactor,
        options=options,
        port=port,
        daemon='rigctld',
        connect_func=connect_to_rigctld)


__all__.append('connect_to_rig')


def connect_to_rotator(reactor, options=None, port=4533):
    """
    Start a rotctld process and connect to it.
    
    options: list of rotctld options, e.g. ['-m', '1102', '-r', '/dev/ttyUSB0'].
    Do not specify host or port in the options.
    
    port: A free port number to use.
    """
    return _connect_to_device(
        reactor=reactor,
        options=options,
        port=port,
        daemon='rotctld',
        connect_func=connect_to_rotctld)


__all__.append('connect_to_rotator')


@defer.inlineCallbacks
def _connect_to_device(reactor, options, port, daemon, connect_func):
    if options is None:
        options = []
    host = '127.0.0.1'
    
    # We use rigctld instead of rigctl, because rigctl will only execute one command at a time and does not have the better-structured response formats.
    # If it were possible, we'd rather connect to rigctld over a pipe or unix-domain socket to avoid port allocation issues.

    # Make sure that there isn't (as best we can check) something using the port already.
    fake_connected = defer.Deferred()
    reactor.connectTCP(host, port, _HamlibClientFactory('(probe) %s' % (daemon,), fake_connected))
    try:
        yield fake_connected
        raise Exception('Something is already using port %i!' % port)
    except ConnectionRefusedError:
        pass
    
    process = subprocess.Popen(
        args=['/usr/bin/env', daemon, '-T', host, '-t', str(port)] + options,
        stdin=None,
        stdout=None,
        stderr=None,
        close_fds=True)
    
    # Retry connecting with exponential backoff, because the daemon process won't tell us when it's started listening.
    proxy_device = None
    refused = Exception('this shouldn\'t be raised')
    for i in xrange(0, 5):
        try:
            proxy_device = yield connect_func(
                reactor=reactor,
                host=host,
                port=port)
            break
        except ConnectionRefusedError as e:
            refused = e
            yield deferLater(reactor, 0.1 * (2 ** i), lambda: None)
    else:
        raise refused
    
    # TODO: Sometimes we fail to kill the process because there was a protocol error during the connection stages. Refactor so that doesn't happen.
    for proxy in proxy_device.get_components_dict().itervalues():  # only expect one, but CellDict is minimal for now
        proxy.when_closed().addCallback(lambda _: process.kill())
    
    defer.returnValue(proxy_device)


class _HamlibProxy(ExportedState):
    # pylint: disable=no-member
    """
    Abstract class for objects which export state proxied to a hamlib daemon.
    """
    implements(IComponent, IProxy)
    
    def __init__(self, protocol):
        # info from hamlib
        self.__cache = {}
        self.__caps = {}
        self.__levels = []
        
        # invert command table
        # TODO: we only need to do this once per class, really
        self._how_to_command = {key: command
            for command, keys in self._commands.iteritems()
            for key in keys}
        
        # keys are same as __cache, values are functions to call with new values from rig
        self._cell_updaters = {}
        
        self.__communication_error = False
        self.__last_error = (-1e9, '', 0)
        
        self.__protocol = protocol
        self.__disconnect_deferred = defer.Deferred()
        protocol._set_proxy(self)

        # TODO: If hamlib backend supports "transceive mode", use it in lieu of polling
        self.__poller_slow = LoopingCall(self.__poll_slow)
        self.__poller_fast = LoopingCall(self.__poll_fast)
        self.__poller_slow.start(2.0)
        self.__poller_fast.start(0.2)
        
        self._ready_deferred = protocol.rc_send('dump_caps')
    
    def sync(self):
        # TODO: Replace 'sync' with more specifically meaningful operations
        d = self.__protocol.rc_send(self._dummy_command)
        d.addCallback(lambda _: None)  # ignore result
        return d
    
    def close(self):
        """implements IComponent"""
        self.__protocol.transport.loseConnection()
        return self.when_closed()  # used for tests, not part of IComponent
    
    def when_closed(self):
        return fork_deferred(self.__disconnect_deferred)
    
    def _ehs_get(self, name_in_cmd):
        if name_in_cmd in self.__cache:
            return self.__cache[name_in_cmd]
        else:
            return 0.0
    
    def _clientReceived(self, command, key, value):
        self.__communication_error = False
        
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
                            log.err('Unrecognized level description from %s: %r' % (self._server_name, info))
            
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
    
    def _clientError(self, cmd, error_number):
        if cmd.startswith('get_'):
            # these getter failures are boring, probably us polling something not implemented
            if error_number == RIG_ENIMPL or error_number == RIG_ENTARGET or error_number == RIG_BUSERROR:
                return
            elif error_number == RIG_ETIMEOUT:
                self.__communication_error = True
                return
        self.__last_error = (time.time(), cmd, error_number)
        self.state_changed('errors')
    
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
        name_in_cmd = self._how_to_command[name_full]  # raises if cannot set
        if value != self.__cache[name_full]:
            self.__cache[name_full] = value
            self.__protocol.rc_send(
                'set_' + name_in_cmd,
                ' '.join(self.__cache[arg_name] for arg_name in self._commands[name_in_cmd]))
    
    def state_def(self, callback):
        super(_HamlibProxy, self).state_def(callback)
        for name in self._info:
            can_get = self.__caps.get('Can get ' + name)
            if can_get is None:
                log.msg('No can-get information for ' + name)
            if can_get != 'Y':
                # TODO: Handle 'E' condition
                continue
            writable = name in self._how_to_command and self.__caps.get('Can set ' + name) == 'Y'
            _install_cell(self, name, False, writable, callback, self.__caps)
        for level_name in self.__levels:
            # TODO support writable levels
            _install_cell(self, level_name + ' level', True, False, callback, self.__caps)

    def __poll_fast(self):
        # TODO: Stop if we're getting behind
        p = self.__protocol
        self.poll_fast(p.rc_send)
        for level_name in self.__levels:
            p.rc_send('get_level', level_name)
    
    def __poll_slow(self):
        # TODO: Stop if we're getting behind
        p = self.__protocol
        self.poll_slow(p.rc_send)
    
    @exported_value(type=Notice(always_visible=False), changes='explicit')
    def get_errors(self):
        if self.__communication_error:
            return 'Rig not responding.'
        else:
            (error_time, cmd, error_number) = self.__last_error
            if error_time > time.time() - 10:
                return u'%s: %s' % (cmd, error_number)
            else:
                return u''
    
    def poll_fast(self, send):
        raise NotImplementedError()
    
    def poll_slow(self, send):
        raise NotImplementedError()


def _install_cell(self, name, is_level, writable, callback, caps):
    # this is a function for the sake of the closure variables
    
    if name == 'Frequency':
        cell_name = 'freq'  # consistency with our naming scheme elsewhere, also IHasFrequency
    else:
        cell_name = name
    
    if is_level:
        # TODO: Use range info from hamlib if available
        if name == 'STRENGTH level':
            vtype = Range([(-54, 50)], strict=False)
        elif name == 'SWR level':
            vtype = Range([(1, 30)], strict=False)
        elif name == 'RFPOWER level':
            vtype = Range([(0, 100)], strict=False)
        else:
            vtype = Range([(-10, 10)], strict=False)
    elif name == 'Mode' or name == 'TX Mode':
        # kludge
        vtype = Enum({x: x for x in caps['Mode list'].strip().split(' ')})
    elif name == 'VFO' or name == 'TX VFO':
        vtype = Enum({x: x for x in caps['VFO list'].strip().split(' ')})
    else:
        vtype = self._info[name]
    
    def updater(strval):
        try:
            if vtype is bool:
                value = bool(int(strval))
            else:
                value = vtype(strval)
        except ValueError:
            value = unicode(strval)
        cell.set_internal(value)
    
    def actually_write_value(value):
        if vtype is bool:
            self._ehs_set(name, str(int(value)))
        else:
            self._ehs_set(name, str(vtype(value)))
    
    cell = LooseCell(
        key=cell_name,
        value='placeholder',
        type=vtype,
        writable=writable,
        persists=False,
        post_hook=actually_write_value,
        label=name)  # TODO: supply label values from _info table
    self._cell_updaters[name] = updater
    updater(self._ehs_get(name))
    callback(cell)


class _HamlibRig(_HamlibProxy):
    implements(IRig, IHasFrequency)
    
    _server_name = 'rigctld'
    _dummy_command = 'get_freq'
    
    _info = {
        'Frequency': (Range([(0, 9999999999)], integer=True)),
        'Mode': (_modes),
        'Passband': (_passbands),
        'VFO': (_vfos),
        'RIT': (int),
        'XIT': (int),
        'PTT': (bool),
        'DCD': (bool),
        'Rptr Shift': (Enum({'+': '+', '-': '-', 'None': 'None'}, strict=False)),
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
        # 'ptt': ['PTT'], # writing disabled until when we're more confident in correct functioning
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
    
    def poll_fast(self, send):
        # likely to be set by hw controls
        send('get_freq')
        send('get_mode')
        
        # received signal info
        send('get_dcd')
    
    def poll_slow(self, send):
        send('get_vfo')
        send('get_rit')
        send('get_xit')
        send('get_ptt')
        send('get_rptr_shift')
        send('get_rptr_offs')
        send('get_ctcss_tone')
        send('get_dcs_code')
        send('get_split_freq')
        send('get_split_mode')
        send('get_split_vfo')
        send('get_ts')

class _HamlibRotator(_HamlibProxy):
    implements(IRotator)

    _server_name = 'rotctld'
    _dummy_command = 'get_pos'
    
    # TODO: support imperative commands:
    # move
    # stop
    # park
    # reset
    
    _info = {
        # TODO: Get ranges from dump_caps
        'Azimuth': (Range([(-180, 180)])),
        'Elevation': (Range([(0, 90)])),
    }
    
    _commands = {
        'pos': ['Azimuth', 'Elevation'],
    }
    
    def poll_fast(self, send):
        send('get_pos')
    
    def poll_slow(self, send):
        pass

class _HamlibClientFactory(ClientFactory):
    def __init__(self, server_name, connected_deferred):
        self.__server_name = server_name
        self.__connected_deferred = connected_deferred
    
    def buildProtocol(self, addr):
        p = _HamlibClientProtocol(self.__server_name, self.__connected_deferred)
        return p

    def clientConnectionFailed(self, connector, reason):
        self.__connected_deferred.errback(reason)


class _HamlibClientProtocol(Protocol):
    def __init__(self, server_name, connected_deferred):
        self.__proxy_obj = None
        self.__server_name = server_name
        self.__connected_deferred = connected_deferred
        self.__line_receiver = LineReceiver()
        self.__line_receiver.delimiter = '\n'
        self.__line_receiver.lineReceived = self.__lineReceived
        self.__waiting_for_responses = []
        self.__receive_cmd = None
        self.__receive_arg = None
    
    def connectionMade(self):
        self.__connected_deferred.callback(self)
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        if self.__proxy_obj is not None:
            self.__proxy_obj._clientConnectionLost(reason)
    
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
            log.err('%s client: Unrecognized line (no command active): %r' % (self.__server_name, line))
        else:
            match = re.match(r'^RPRT (-?\d+)$', line)
            if match is not None:
                # command response ending line
                return_code = int(match.group(1))
                
                waiting = self.__waiting_for_responses
                i = 0
                for i, (wait_cmd, wait_deferred) in enumerate(waiting):
                    if self.__receive_cmd != wait_cmd:
                        log.err("%s client: Didn't get a response for command %r before receiving one for command %r" % (self.__server_name, wait_cmd, self.__receive_cmd))
                    else:
                        # TODO: Consider 'parsing' return code more here.
                        if return_code != 0:
                            self.__proxy_obj._clientError(self.__receive_cmd, return_code)
                        wait_deferred.callback(return_code)
                        break
                self.__waiting_for_responses = waiting[i + 1:]
                
                self.__receive_cmd = None
                self.__receive_arg = None
                return
            if self.__receive_cmd == 'get_level':
                # Should be a level value
                match = re.match(r'^-?\d+\.?\d*$', line)
                if match:
                    self.__proxy_obj._clientReceivedLevel(self.__receive_arg, line)
                    return
            match = re.match(r'^([\w ,/-]+):\s*(.*)$', line)
            if match is not None:
                # Command response
                if self.__proxy_obj is not None:
                    self.__proxy_obj._clientReceived(self.__receive_cmd, match.group(1), match.group(2))
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
            log.err('%s client: Unrecognized line during %s: %r' % (self.__server_name, self.__receive_cmd, line))
    
    def _set_proxy(self, proxy):
        self.__proxy_obj = proxy
    
    def rc_send(self, cmd, argstr=''):
        if not re.match(r'^\w+$', cmd):  # no spaces (stuffing args in), no newlines (breaking the command)
            raise ValueError('Syntactically invalid command name %r' % (cmd,))
        if not re.match(r'^[^\r\n]*$', argstr):  # no newlines
            raise ValueError('Syntactically invalid arguments string %r' % (cmd,))
        self.transport.write('+\\' + cmd + ' ' + argstr + '\n')
        d = defer.Deferred()
        self.__waiting_for_responses.append((cmd, d))
        return d

_plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='hamlib.js')
