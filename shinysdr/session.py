# Copyright 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

# TODO: Now that this module has AppRoot in it, it is misnamed.

from __future__ import absolute_import, division

import os
import sys

from twisted.internet import reactor as the_reactor  # TODO fix

from shinysdr.top import Top
from shinysdr.values import Command, ExportedState, exported_block


class AppRoot(ExportedState):
    def __init__(self, devices, audio_config, features):
        self.__receive_flowgraph = Top(
            devices=devices,
            audio_config=audio_config,
            features=features)
        # TODO: only one session while we sort out other things
        self.__session = Session(
            receive_flowgraph=self.__receive_flowgraph,
            features=features)
    
    @exported_block()
    def get_receive_flowgraph(self):  # TODO needs to go away
        return self.__receive_flowgraph
    
    @exported_block(persists=True)
    def get_devices(self):
        """Return all existant devices.
        
        This exists only for persistence purposes.
        """
        return self.__receive_flowgraph.get_sources()
    
    # TODO: should become something more like 'create new session'
    def get_session(self):
        return self.__session
    
    def close_all_devices(self):
        self.__receive_flowgraph.close_all_devices()


class Session(ExportedState):
    def __init__(self, receive_flowgraph, features):
        self.__receive_flowgraph = receive_flowgraph
        self.__enable_reboot = features['reboot']
    
    def state_def(self, callback):
        super(Session, self).state_def(callback)
        rxfs = self.__receive_flowgraph.state()
        callback(rxfs['monitor'])
        callback(rxfs['sources'])
        callback(rxfs['source'])
        callback(rxfs['receivers'])
        callback(rxfs['accessories'])
        callback(rxfs['telemetry_store'])
        callback(rxfs['source_name'])
        callback(rxfs['clip_warning'])
        if self.__enable_reboot:
            # TODO kludge
            callback(Command(self, 'reboot', self.reboot))
            callback(Command(self, 'kill', self.kill))
        
    
    def add_audio_queue(self, queue, queue_rate):
        return self.__receive_flowgraph.add_audio_queue(queue, queue_rate)
    
    def remove_audio_queue(self, queue):
        return self.__receive_flowgraph.remove_audio_queue(queue)
    
    def get_audio_queue_channels(self):
        return self.__receive_flowgraph.get_audio_queue_channels()
        
    # TODO: reboot and kill don't belong here, neither the interface nor the implementation.
    def reboot(self):
        # Note that this will immediately kill us and so we will never ack the client invocation -- which we're doing as a deliberate indication of our temporary death.
        # TODO: Do better preservation of options, path, python executable, etc.
        os.execlp('python', 'python', '-m', 'shinysdr.main', *sys.argv[1:])
    
    def kill(self):
        # pylint: disable=no-member
        the_reactor.stop()
