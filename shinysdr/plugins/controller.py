# Copyright 2016, 2018 Kevin Reid and the ShinySDR contributors
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
Plugin for user-defined arbitrary commands.

It connects to something (such as a serial port) and sends arbitrary strings defined in configuration in response to user input.
"""
# TODO: Write user documentation for this device. Maybe think about making it easier to configure first.

from __future__ import absolute_import, division, print_function, unicode_literals

import functools

import six

from twisted.internet.protocol import Factory, Protocol
from twisted.protocols.basic import LineReceiver
from zope.interface import implementer, Interface

from shinysdr.devices import Device, IComponent
from shinysdr.types import to_value_type
from shinysdr.values import Command as CommandCell, ExportedState, LooseCell


__all__ = []  # appended later


def Controller(reactor, key='controller', endpoint=None, elements=None, encoding='US-ASCII'):
    """Create a controller device.
  
    key: Component ID. TODO point at device merging documentation once it exists
    endpoint: Endpoint to connect to (such as a shinysdr.twisted_ext.SerialPortEndpoint).
    elements: List of elements (objects which define commands to send).
    encoding: Character encoding to use when Unicode text is given.
    """
    return Device(components={six.text_type(key): _ControllerProxy(
        reactor=reactor,
        endpoint=endpoint,
        elements=elements or [],
        encoding=encoding)})


__all__.append('Controller')


class IElement(Interface):
    def _install_cells(callback, send, encoding):
        pass


@implementer(IElement)
class Command(object):
    """Defines a command to send a single string."""
    def __init__(self, label, text):
        """label: Name the user sees.
        text: What is sent when the command is triggered.
        """
        if not isinstance(text, six.string_types):
            raise TypeError('Command text must be string, not %s: %r' % (type(text), text))
        self.__label = label
        self.__text = text
    
    def _cells(self, send, encoding):
        if isinstance(self.__text, six.text_type):
            text = self.__text.encode(encoding)
        else:
            text = self.__text
        # TODO: Autogenerate unique keys instead of requiring the label to be unique.
        yield self.__label, CommandCell(functools.partial(send, text),
            label=self.__label)


__all__.append('Command')


@implementer(IElement)
class Selector(object):
    """Defines a cell whose value is the text to send.
    
    Typically the cell's type would be an EnumT.
    """
    
    def __init__(self, name, type):
        # pylint: disable=redefined-builtin
        self.__name = name
        self.__type = to_value_type(type)
    
    def _cells(self, send, encoding):
        # TODO: Autogenerate unique keys instead of requiring __name to be unique.
        yield self.__name, LooseCell(
            type=self.__type,
            value=u'',
            writable=True,
            persists=True,
            post_hook=lambda value: send(six.text_type(value).encode(encoding)),
            label=self.__name)


__all__.append('Selector')


@implementer(IComponent)
class _ControllerProxy(ExportedState):
    def __init__(self, reactor, endpoint, elements, encoding):
        self.__reactor = reactor
        self.__elements = elements
        self.__encoding = encoding
        
        # ClientService (which does reconnecting) is only since 16.1 and we currently want to support 13.2 due to MacPorts and Debian versions
        # cs = ClientService(endpoint, Factory.forProtocol(_ControllerProtocol))
        # cs.startService()
        factory = Factory.forProtocol(_ControllerProtocol)
        self.__protocol = None
        endpoint.connect(factory).addCallback(self.__got_protocol)
    
    def state_def(self):
        for d in super(_ControllerProxy, self).state_def():
            yield d
        for element in self.__elements:
            for d in IElement(element)._cells(self.__send, self.__encoding):
                yield d
    
    def close(self):
        # TODO: This is used for testing and is not actually called by Device.close. Device.close needs to be extended to support notifying components of close.
        if self.__protocol:
            self.__protocol.transport.loseConnection()
    
    def __got_protocol(self, protocol):
        self.__protocol = protocol
    
    def __send(self, cmd):
        self.__protocol.send(cmd)


class _ControllerProtocol(Protocol):
    def __init__(self):
        self.__line_receiver = LineReceiver()
        self.__line_receiver.delimiter = b';'
        self.__line_receiver.lineReceived = self.__lineReceived
    
    def connectionMade(self):
        """overrides Protocol"""
        # TODO: Report success
    
    def connectionLost(self, reason=None):
        """overrides Protocol"""
        # TODO: Report loss to user
    
    def dataReceived(self, data):
        """overrides Protocol"""
        self.__line_receiver.dataReceived(data)
    
    def __lineReceived(self, line):
        print(line)
    
    def send(self, cmd):
        self.transport.write(cmd)
