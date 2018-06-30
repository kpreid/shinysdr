# -*- coding: utf-8 -*-
# Copyright 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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
Plugin for controlling Elecraft radios.

As of this writing, has only been tested with a KX3 and is known to be missing features for other models.

Designed to be combined with a device supplying I/Q signals from the KX3's “RX I/Q” port.
"""

from __future__ import absolute_import, division, unicode_literals

from collections import defaultdict
import struct

from twisted.internet import defer
from twisted.internet.protocol import Protocol
from twisted.protocols.basic import LineReceiver
from twisted.logger import Logger
from twisted.python.util import sibpath
from twisted.web import static
from zope.interface import Interface, implementer

from shinysdr.devices import Device, IComponent
from shinysdr.interfaces import ClientResourceDef, IHasFrequency
from shinysdr.types import EnumT, NoticeT, RangeT, ReferenceT, to_value_type
from shinysdr.twisted_ext import FactoryWithArgs, SerialPortEndpoint
from shinysdr.values import ExportedState, LooseCell, ViewCell, exported_value


__all__ = []  # appended later


_FREQ_CELL_KEY = 'freq'


# TODO this is named as it is to match the Hamlib plugin; reevaluate what is a good consistent naming scheme.
@defer.inlineCallbacks
def connect_to_rig(reactor, port, baudrate=38400):
    """
    Connect to Elecraft radio over a serial port.
    
    port: Serial port device name.
    baudrate: Serial data rate; must match that set on the radio.
    """
    endpoint = SerialPortEndpoint(port, reactor, baudrate=baudrate)
    factory = FactoryWithArgs.forProtocol(_ElecraftClientProtocol, reactor=reactor)
    protocol = yield endpoint.connect(factory)
    proxy = protocol._proxy()
    
    defer.returnValue(Device(
        vfo_cell=proxy.iq_center_cell(),
        components={'rig': proxy}))


class IElecraftReceiver(Interface):
    """Marker interface for client."""


class IElecraftRadio(Interface):
    """Marker interface for client."""


@implementer(IHasFrequency, IElecraftReceiver)
class _ElecraftReceiver(ExportedState):
    def __init__(self, protocol, is_sub):
        self.__protocol = protocol
        self.__is_sub = is_sub
    
    def state_def(self):
        """overrides ExportedState"""
        for d in super(_ElecraftReceiver, self).state_def():
            yield d
        for d in _st.install_cells(self, self.__protocol, is_sub=self.__is_sub):
            yield d


@implementer(IComponent, IElecraftRadio)
class _ElecraftRadio(ExportedState):
    # TODO: Tell protocol to do no/less polling when nobody is looking.
    
    def __init__(self, protocol):
        self.__protocol = protocol
        self.__rx_main = _ElecraftReceiver(protocol, False)
        self.__rx_sub = _ElecraftReceiver(protocol, True)
        self.__init_center_cell()
    
    def __init_center_cell(self):
        base_freq_cell = self.__rx_main.state()[_FREQ_CELL_KEY]
        mode_cell = self.__rx_main.state()['MD']
        sidetone_cell = self.state()['CW']
        submode_cell = self.state()['DT']
        iq_offset_cell = LooseCell(value=0.0, type=float, writable=True)
        
        self.__iq_center_cell = ViewCell(
                base=base_freq_cell,
                get_transform=lambda x: x + iq_offset_cell.get(),
                set_transform=lambda x: x - iq_offset_cell.get(),
                type=base_freq_cell.type(),  # runtime variable...
                writable=True,
                persists=base_freq_cell.metadata().persists)
        
        def changed_iq(_value=None):
            # TODO this is KX3-specific
            mode = mode_cell.get()
            if mode == 'CW':
                iq_offset = sidetone_cell.get()
            elif mode == 'CW-REV':
                iq_offset = -sidetone_cell.get()
            elif mode == 'AM' or mode == 'FM':
                iq_offset = 11000.0
            elif mode == 'DATA' or mode == 'DATA-REV':
                submode = submode_cell.get()
                if submode == 0:  # "DATA A", SSB with less processing
                    iq_offset = 0.0  # ???
                elif submode == 1:  # "AFSK A", SSB with RTTY style filter
                    iq_offset = 0.0  # ???
                elif submode == 2:  # "FSK D", RTTY
                    iq_offset = 900.0
                elif submode == 3:  # "PSK D", PSK31
                    iq_offset = 1000.0  # I think so...
                else:
                    iq_offset = 0  # fallback
                if mode == 'DATA-REV':
                    iq_offset = -iq_offset
            else:  # USB, LSB, other
                iq_offset = 0.0
            iq_offset_cell.set(iq_offset)
            self.__iq_center_cell.changed_transform()
        
        # TODO bad practice
        mode_cell._subscribe_immediate(changed_iq)
        sidetone_cell._subscribe_immediate(changed_iq)
        submode_cell._subscribe_immediate(changed_iq)
        changed_iq()
    
    def state_def(self):
        """overrides ExportedState"""
        for d in super(_ElecraftRadio, self).state_def():
            yield d
        for d in _st.install_cells(self, self.__protocol, is_sub=None):
            yield d
    
    def close(self):
        """implements IComponent"""
        self.__protocol.transport.loseConnection()
    
    def iq_center_cell(self):
        """Made available for Device creation; not a well-thought-out interface."""
        return self.__iq_center_cell
    
    def get_direct_protocol(self):
        """For experimental use only."""
        return self.__protocol
    
    @exported_value(type=NoticeT(always_visible=False), changes='continuous')  # TODO better changes
    def get_errors(self):
        error = self.__protocol.get_communication_error()
        if not error:
            return u''
        elif error == u'not_responding':
            return u'Radio not responding.'
        elif error == u'bad_data':
            return u'Bad data from radio.'
        else:
            return unicode(error)
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_rx_main(self):
        return self.__rx_main
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_rx_sub(self):
        return self.__rx_sub


_mode_strings = [None, 'LSB', 'USB', 'CW', 'FM', 'AM', 'DATA', 'CW-REV', None, 'DATA-REV']


def _decode_mode(text):
    try:
        s = _mode_strings[int(text)]
        if s is None:
            return text
        return s
    except ValueError:
        return text
    except IndexError:
        return text


def _format_command(cmd, argstr, is_sub=False):
    return cmd + ('$' if is_sub else '') + argstr + ';'


class _ElecraftClientProtocol(Protocol):
    __log = Logger()
    
    def __init__(self, reactor):
        self.__reactor = reactor
        self.__line_receiver = LineReceiver()
        self.__line_receiver.delimiter = b';'
        self.__line_receiver.lineReceived = self.__lineReceived
        self.__communication_error = u'not_responding'
        
        self.__explicit_waits = defaultdict(list)
        
        # set up dummy initial state
        self.__scheduled_poll = reactor.callLater(0, lambda: None)
        self.__scheduled_poll.cancel()
        
        # Set up proxy.
        # Do this last because the proxy fetches metadata from us so we should be otherwise fully initialized.
        self.__proxy_obj = _ElecraftRadio(self)
    
    def connectionMade(self):
        """overrides Protocol"""
        self.__reinitialize()
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        """overrides Protocol"""
        if self.__scheduled_poll.active():
            self.__scheduled_poll.cancel()
        self.__communication_error = u'serial_gone'
    
    def get_communication_error(self):
        return self.__communication_error
    
    def dataReceived(self, data):
        """overrides Protocol"""
        self.__line_receiver.dataReceived(data)
    
    def send_command(self, cmd_text):
        """Send a raw command.
        
        The text must include its trailing semicolon.
        
        If wait=True, return a Deferred.
        """
        if isinstance(cmd_text, unicode):
            cmd_text = cmd_text.encode('us-ascii')  # TODO: correct choice of encoding
        assert cmd_text == b'' or cmd_text.endswith(b';')
        self.transport.write(cmd_text)
    
    def get(self, name):
        """TODO explain
        
        Note that this may wait too little time, if the same command is already in flight.
        """
        d = defer.Deferred()
        self.__explicit_waits[name].append(d)
        self.send_command(name + ';')
        return d
    
    def __reinitialize(self):
        # TODO: Use ID, K3, and OM commands to confirm identity and customize
        self.transport.write(
            b'AI2;'  # Auto-Info Mode 2; notification of any change (delayed)
            b'K31;')  # enable extended response, important for FW command
        self.request_all()  # also triggers polling cycle
    
    def __schedule_timeout(self):
        if self.__scheduled_poll.active():
            self.__scheduled_poll.cancel()
        self.__scheduled_poll = self.__reactor.callLater(1, self.__poll_doubtful)
    
    def __schedule_got_response(self):
        if self.__scheduled_poll.active():
            self.__scheduled_poll.cancel()
        self.__scheduled_poll = self.__reactor.callLater(0.04, self.__poll_fast_reactive)
    
    def request_all(self):
        self.transport.write(
            b'IF;'
            b'AG;AG$;AN;AP;BN;BN$;BW;BW$;CP;CW;DV;ES;FA;FB;FI;FR;FT;GT;IS;KS;'
            b'LK;LK$;LN;MC;MD;MD$;MG;ML;NB;NB$;PA;PA$;PC;RA;RA$;RG;RG$;SB;SQ;'
            b'SQ$;VX;XF;XF$;')
        # If we don't get a response, this fires
        self.__schedule_timeout()
    
    def __poll_doubtful(self):
        """If this method is called then we didn't get a prompt response."""
        self.__communication_error = 'not_responding'
        self.transport.write(b'FA;')
        self.__schedule_timeout()
    
    def __poll_fast_reactive(self):
        """Normal polling activity."""
        # Get FA (VFO A frequency) so we respond fast.
        # Get BN (band) because if we find out we changed bands we need to update band-dependent things.
        # Get MD (mode) because on KX3, A/B button does not report changes
        self.transport.write(b'FA;BN;MD;MD$;')
        self.__schedule_timeout()
    
    def __lineReceived(self, line):
        line = line.lstrip('\x00')  # nulls are sometimes sent on power-on
        self.__log.debug('Elecraft client: received {line!r}', line=line)
        if '\x00' in line:
            # Bad data that may be received during radio power-on
            return
        elif line == '?':
            # busy indication; nothing to do about it as yet
            pass
        else:
            try:
                cmd = line[:2]
                sub = len(line) > 2 and line[2] == '$'
                cmd_sub = cmd + ('$' if sub else '')
                data = line[(3 if sub else 2):]
                
                handler = _st.dispatch(cmd)
                if handler is not None:
                    handler(data, sub, self._update)
                else:
                    self.__log.warn('Elecraft client: unrecognized message {cmd!r} in {line!r}', cmd=cmd, line=line)
                
                if cmd_sub in self.__explicit_waits:
                    waits = self.__explicit_waits[cmd_sub]
                    del self.__explicit_waits[cmd_sub]
                    for d in waits:
                        self.__reactor.callLater(0, d.callback, data)
            except ValueError:  # bad digits or whatever
                self.__log.failure('Elecraft client: error while parsing message {line!r}', line=line)
                self.__communication_error = 'bad_data'
                return  # don't consider as OK, but don't reinit either
        
        if not self.__communication_error:
            # communication is still OK
            self.__schedule_got_response()
        else:
            self.__communication_error = None
            # If there was a communication error, we might be out of sync, so resync and also start up normal polling.
            self.__reinitialize()
    
    def _update(self, key, value, sub=False):
        """Handle a received value update."""
        # TODO less poking at internals, more explicit
        cell = self.__proxy_obj.state().get(key)
        if not cell:
            cell = (self.__proxy_obj.get_rx_sub() if sub else self.__proxy_obj.get_rx_main()).state().get(key)
        
        if cell:
            old_value = cell.get()
            cell.set_internal(value)
        else:
            # just don't crash
            self.__log.warn('Elecraft client: missing cell for state {key!r}', key=key)
        
        if key == 'band' and value != old_value:
            # Band change! Check the things we don't get prompt or any notifications for.
            self.request_all()
    
    def _proxy(self):
        """for use by connect_to_rig"""
        return self.__proxy_obj


class Syntax(object):
    """A mapping between strings and parsed values."""
    # TODO: See if this is useful to other external-protocol implementations and factor it out if so.
    def parse(self, text):
        raise NotImplementedError()

    def format(self, value):
        raise NotImplementedError()
    
    def default_type(self):
        return to_value_type(object)


class FormatAndCoerceSyntax(Syntax):
    def __init__(self, type_obj, formatstr, default_value):
        self.__formatstr = formatstr
        self.__default_value = default_value
        self.__type_obj = type_obj
        
    def parse(self, text):
        return self.__type_obj(text)

    def format(self, value):
        return self.__formatstr.format(value)
    
    def default_value(self):
        return self.__default_value
    
    def default_type(self):
        return to_value_type(self.__type_obj)


class BooleanSyntax(Syntax):
    def parse(self, text):
        return bool(int(text))
        
    def format(self, value):
        return str(int(value))
    
    def default_value(self):
        return False
    
    def default_type(self):
        return to_value_type(bool)


class IntSyntax(Syntax):
    def __init__(self, digits, lower=None, upper=None):
        self.__type = RangeT([(lower or 0, upper or (10 ** digits) - 1)], integer=True)
        self.__formatstr = '{:0' + str(digits) + '}'
    
    def parse(self, text):
        return int(text)
        
    def format(self, value):
        return self.__formatstr.format(value)
    
    def default_value(self):
        return 0
    
    def default_type(self):
        return self.__type


class ScaledIntSyntax(Syntax):
    def __init__(self, digits, scale):
        self.__type = RangeT([(0, (10 ** digits) - 1 * scale)], integer=False)
        self.__formatstr = '{:0' + str(digits) + '}'
        self.__scale = scale
    
    def parse(self, text):
        return float(text) * self.__scale
        
    def format(self, value):
        return self.__formatstr.format(value / self.__scale)
    
    def default_value(self):
        return 0
    
    def default_type(self):
        return self.__type


class EnumSyntax(Syntax):
    def __init__(self, *args, **kwargs):
        self.__type = EnumT(*args, **kwargs)
    
    def parse(self, text):
        return unicode(text)
    
    def format(self, value):
        return str(self.__type(value))
    
    def default_value(self):
        return ''
    
    def default_type(self):
        return self.__type


class ModeSyntax(Syntax):
    __mode_strings = [None, 'LSB', 'USB', 'CW', 'FM', 'AM', 'DATA', 'CW-REV', None, 'DATA-REV']

    def parse(self, text):
        try:
            s = self.__mode_strings[int(text)]
            if s is None:
                return text
            return s
        except ValueError:
            return text
        except IndexError:
            return text
    
    def format(self, value):
        try:
            return '{:01}'.format(self.__mode_strings.index(value))
        except IndexError:
            raise ValueError('unsupported mode: ' + repr(value))
    
    def default_value(self):
        return ''
    
    def default_type(self):
        return EnumT({k: k for k in self.__mode_strings})


s_boolean = BooleanSyntax()
s_mode = ModeSyntax()


class _Row(object):
    def __init__(self, command_name, syntax, s=False, get_only=False, label=None, type=None):
        # pylint: disable=redefined-builtin
        self.__command_name = command_name
        self.__syntax = syntax
        self.__has_sub = s
        self.__cell_kwargs = dict(
            value=syntax.default_value(),
            type=type or syntax.default_type(),
            writable=not get_only,
            persists=False,
            label=label)
    
    def commands(self):
        return {self.__command_name: self.__parse}
    
    def __parse(self, data, sub, update):
        update(self.__command_name, self.__syntax.parse(data), sub=sub)
    
    def make_cell(self, protocol, is_sub):
        key = self.__command_name
        
        def send(value):
            protocol.send_command(_format_command(
                key,
                self.__syntax.format(value),
                is_sub=is_sub))
        
        if self.__has_sub == (is_sub is not None):
            return key, LooseCell(
                post_hook=send,
                **self.__cell_kwargs)
        else:
            return None


class _NonCommandRow(object):
    def __init__(self, state_key, value_type, default_value, has_sub=False, label=None, type=None):
        # pylint: disable=redefined-builtin
        self.__has_sub = has_sub
        self.__key = state_key
        self.__cell_kwargs = dict(
            value=default_value,
            type=value_type,
            writable=False,
            persists=False,
            label=label)
    
    def commands(self):
        return {}
    
    def make_cell(self, protocol, is_sub):
        if self.__has_sub == (is_sub is not None):
            return self.__key, LooseCell(**self.__cell_kwargs)
        else:
            return None


class _UnusedCommand(object):
    def __init__(self, command_name):
        self.__command_name = command_name
    
    def commands(self):
        return {self.__command_name: self.__parse}
    
    def __parse(self, data, sub, update):
        pass
    
    def make_cell(self, protocol, is_sub):
        return None


class _VFORow(object):
    __syntax = IntSyntax(11)
    
    def commands(self):
        return {
            'FA': self.__parser(False),
            'FB': self.__parser(True)
        }
    
    def __parser(self, is_actually_sub):
        def parse(data, sub, update):
            update(_FREQ_CELL_KEY, self.__syntax.parse(data), sub=is_actually_sub)
        
        return parse
    
    def make_cell(self, protocol, is_sub):
        cmd = 'FB' if is_sub else 'FA'
        
        def send_vfo(value):
            protocol.send_command(_format_command(
                cmd,
                self.__syntax.format(value)))
        
        if is_sub is not None:
            return _FREQ_CELL_KEY, LooseCell(
                value=0,
                type=self.__syntax.default_type(),
                writable=True,
                persists=False,
                post_hook=send_vfo)
        else:
            return None


class _IFRow(object):
    """The IF command, which requires special splitting."""
    
    __IF_STRUCT = struct.Struct('!11s 5x 5s s s 3x s s s s s s s 2x')
    
    def __init__(self):
        pass
        
    def commands(self):
        return {'IF': self.__parse_IF}
    
    def __parse_IF(self, data, sub, update):
        (freq, rit_offset, rit_on, xit_on, _tx, mode, _vfo_rx, scan, split, _band_changed, data_mode) = self.__IF_STRUCT.unpack_from(data)
        update(_FREQ_CELL_KEY, int(freq))
        update('RO', int(rit_offset))
        update('RT', s_boolean.parse(rit_on))
        update('XT', s_boolean.parse(xit_on))
        update('MD', s_mode.parse(mode))
        # update('FR', int(vfo_rx))
        update('scan', s_boolean.parse(scan))
        update('split', s_boolean.parse(split))  # no other command
        update('DT', int(data_mode))
    
    def make_cell(self, protocol, is_sub):
        return None


class _ElecraftStateTable(object):
    def __init__(self, rows):
        self.__rows = rows
        command_lookup = {}
        for row in rows:
            for cmd, parser in row.commands().iteritems():
                if cmd in command_lookup:
                    raise ValueError('duplicate ' + cmd)
                command_lookup[cmd] = parser
        self.__command_lookup = command_lookup
    
    def dispatch(self, cmd):
        return self.__command_lookup.get(cmd)
    
    def install_cells(self, proxy, protocol, is_sub):
        """
        is_sub: True, False, or None to indicate non-$ fields.
        """
        for row in self.__rows:
            key_and_cell = row.make_cell(protocol, is_sub)
            if key_and_cell is not None:
                yield key_and_cell


_st = _ElecraftStateTable([
    _UnusedCommand('!'),
    _UnusedCommand('@'),
    _Row('AG', IntSyntax(3), s=True, label='AF Gain',  # TODO on KX3 there is no main/sub
        type=RangeT([(0, 60)])),  # docs claim range is to 255, but KX3 actually goes to 60
    _UnusedCommand('AI'),  # only used as explicit SET in protocol layer
    _UnusedCommand('AK'),  # "Internal Use Only"
    _Row('AN', IntSyntax(1, 1, 2), label='Antenna'),  # TODO get client to not show this as a slider
    _Row('AP', s_boolean, label='Audio Peaking Filter'),
    _UnusedCommand('BG'),  # not yet used,
    _Row('BN', IntSyntax(2), s=True, label='Band'),  # TODO enum type
    _UnusedCommand('BR'),  # not used
    _Row('BW', ScaledIntSyntax(4, 10), s=True, label='Bandwidth'),
    _Row('CP', IntSyntax(3, 0, 40), label='Compression'),
    _Row('CW', ScaledIntSyntax(2, 10), get_only=True, label='CW Sidetone Pitch',
        type=RangeT([(300, 800)], integer=True)),
    _UnusedCommand('DB'),  # not used
    _UnusedCommand('DL'),  # SET only, not used
    _UnusedCommand('DN'),  # SET only, not used
    _UnusedCommand('DS'),  # not yet used -- TODO might be useful for polling
    _Row('DT', IntSyntax(1, 0, 3), label='DATA Sub-Mode'),  # TODO enum type
    _Row('DV', s_boolean, label='Diversity'),
    _UnusedCommand('EL'),  # TODO start using this (error logging; needs parser support)
    _Row('ES', s_boolean, label='ESSB'),
    _VFORow(),  # handles FA and FB
    _Row('FI', IntSyntax(4), get_only=True, label='IF Center'),  # TODO value translation, and treat as K3 only
    _UnusedCommand('FR'),  # RX VFO. not yet used, is complicated, K2-specialized
    _Row('FT', EnumSyntax({'0': 'A', '1': 'B'}), label='TX VFO'),
    _UnusedCommand('FW'),  # deprecated for not-K2, is complicated.
    _Row('GT', EnumSyntax({'002': 'Fast', '004': 'Slow'}), label='AGC'),  # TODO handle K2 case
    _UnusedCommand('IC'),  # not used
    _UnusedCommand('ID'),  # not yet used
    _UnusedCommand('IO'),  # "Internal Use Only"
    _IFRow(),
    _Row('IS', FormatAndCoerceSyntax(int, ' {:04}', 0), label='IF Shift'),  # TODO on KX3 main/sub have separate settings but only main applies and there is no $ -- need special polling
    _UnusedCommand('K2'),
    _UnusedCommand('K3'),  # TODO use it to detect radio type
    _Row('KS', IntSyntax(3, 8, 50), label='Keyer Speed WPM'),  # TODO put units in type once we can
    _UnusedCommand('KY'),  # not yet used
    _Row('LK', s_boolean, s=True, label='VFO Lock'),
    _Row('LN', s_boolean, label='Link VFOs'),  # TODO enable as K3 only
    _Row('MC', IntSyntax(3, 0, 196), label='Memory #'),  # TODO get client to not show this as a slider
    _Row('MD', s_mode, s=True, label='Mode'),
    _Row('MG', IntSyntax(3, 0, 60), label='Mic Gain'),
    _Row('ML', IntSyntax(3, 0, 60), label='Monitor Level'),
    _UnusedCommand('MN'),  # menu access -- might be useful later
    _UnusedCommand('MP'),  # ditto
    _UnusedCommand('MQ'),  # ditto
    _Row('NB', s_boolean, s=True, label='Noise Blanker On'),
    # TODO NL requires special handling
    # OM requires special handling
    _Row('PA', s_boolean, s=True, label='RX Preamp'),
    _Row('PC', IntSyntax(3, 0, 110), label='TX Power Set'),  # note NOT using "K2 extended" format
    _Row('PO', ScaledIntSyntax(3, 0.1), get_only=True, label='TX Power Actual'),  # not yet handling "QRO mode"
    _UnusedCommand('PS'),  # power off -- not used
    _Row('RA', FormatAndCoerceSyntax(bool, ' {02}', False), s=True, label='RX Attenuator'),
    _UnusedCommand('RC'),
    _UnusedCommand('RD'),
    _Row('RG', IntSyntax(3, 190, 250), s=True, label='RF Gain'),  # TODO value translation, non-KX3 version
    _Row('RO', FormatAndCoerceSyntax(int, '{:+04}', 0), label='RIT/XIT'),
    _Row('RT', s_boolean, label='RIT On'),
    _UnusedCommand('RU'),
    _UnusedCommand('RV'),  # not used
    _UnusedCommand('RX'),  # not yet used
    _Row('SB', s_boolean, label='Sub RX/Dual Watch'),  # TODO: Use transceiver-specific name
    _UnusedCommand('SD'),  # not yet used
    _UnusedCommand('SM'),  # not yet used
    _Row('SQ', IntSyntax(3, 0, 29), s=True, label='Squelch'),
    _UnusedCommand('SW'),  # not yet used
    _UnusedCommand('TB'),  # not yet used
    _UnusedCommand('TQ'),  # not yet used
    _UnusedCommand('TX'),  # not yet used
    _UnusedCommand('UP'),  # not used
    _Row('VX', EnumSyntax({'0': 'On', '1': 'Off'}), get_only=True, s=True, label='VOX'),  # note is per-mode
    _Row('XF', IntSyntax(1), get_only=True, s=True, label='XFIL'),
    _Row('XT', s_boolean, label='XIT On'),
    
    # Non-command state
    _NonCommandRow('scan', bool, False),
    _NonCommandRow('split', bool, False),
])


_plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(sibpath(__file__, b'client')),
    load_js_path=b'elecraft.js')
