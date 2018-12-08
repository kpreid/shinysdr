# Copyright 2016, 2017 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys

from zope.interface import implementer

from shinysdr.devices import Device, IComponent
from shinysdr.values import ExportedState, command


__all__ = ['Rebooter']


def Rebooter(reactor):
    return Device(components={'rebooter': _RebooterComponent(reactor)})


@implementer(IComponent)
class _RebooterComponent(ExportedState):
    def __init__(self, reactor):
        self.__reactor = reactor
    
    def close(self):
        """implements IComponent"""
    
    @command(label='Restart server')
    def reboot(self):
        # Note that this will immediately kill us and so we will never ack the client invocation -- which we're doing as a deliberate indication of our temporary death.
        # TODO: Do better preservation of interpreter options, etc.
        os.execlp(sys.executable or 'python', 'python',
            '-m', 'shinysdr.main', *sys.argv[1:])
    
    @command(label='Kill server')
    def kill(self):
        # pylint: disable=no-member
        self.__reactor.stop()
