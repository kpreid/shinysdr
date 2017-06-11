# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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
This module contains utilities building on the Twisted framework
-- things that could plausibly be part of Twisted itself but we
had to write ourselves.
"""

from __future__ import absolute_import, division

import subprocess

from twisted.internet import defer
from twisted.internet.interfaces import ILoggingContext, IStreamClientEndpoint
from twisted.internet.protocol import Factory
from twisted.internet.serialport import SerialPort
from zope.interface import implementer

__all__ = []  # appended later


def fork_deferred(d):
    """Returns a new Deferred which fires at the same time d does.
    
    The difference between this and just using d is that d is not affected by
    the outcome of any callbacks or errbacks added to the returned Deferred.
    """
    # TODO: It might be better to replace uses of this with a Promise
    # abstraction (a source of arbitrarily many 'forked Deferreds'.
    
    def callback(v):
        d2.callback(v)
        return v
    
    def errback(f):
        d2.errback(f)
        f.trap()  # always fail
    
    d2 = defer.Deferred()
    d.addCallbacks(callback, errback)
    return d2


__all__.append('fork_deferred')


def test_subprocess(args, substring, shell=False):
    """Check the stdout or stderr of the specified command for a specified string."""
    # TODO: establish resource and output size limits
    # TODO: Use Twisted subprocess facilities instead to avoid possible conflicts
    try:
        output = subprocess.check_output(
            args=args,
            shell=shell,
            stderr=subprocess.STDOUT)
        return substring in output
    except OSError:
        return False
    except subprocess.CalledProcessError:
        return False


__all__.append('test_subprocess')


@implementer(ILoggingContext)
class FactoryWithArgs(Factory):
    """A Factory which passes constant arguments to construct a Protocol.
    
    Use as FactoryWithArgs.forProtocol(protocol_class, *args, **kwargs).
    """
    def __init__(self, *args, **kwargs):
        self.__args = args
        self.__kwargs = kwargs
    
    def buildProtocol(self, addr):
        """overrides Factory"""
        p = self.protocol(*self.__args, **self.__kwargs)
        p.factory = self
        return p
    
    def logPrefix(self):
        """implements ILoggingContext"""
        # We're not doing the _getLogPrefix thing as seen in Twisted because both things here are class objects and not going to themselves provide ILoggingContext.
        return '%s (%s)' % (self.protocol.__name__, self.__class__.__name__)


__all__.append('FactoryWithArgs')


@implementer(IStreamClientEndpoint)
class SerialPortEndpoint(object):
    """Endpoint for connecting to a serial port."""
    def __init__(self, port, reactor, **serial_kwargs):
        self.__port = port
        self.__reactor = reactor
        self.__serial_kwargs = serial_kwargs
  
    def connect(self, protocol_factory):
        protocol = protocol_factory.buildProtocol(None)
        SerialPort(protocol, self.__port, self.__reactor, **self.__serial_kwargs)
        return defer.succeed(protocol)


__all__.append('SerialPortEndpoint')
