# Copyright 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division, unicode_literals

from zope.interface import implementer

from shinysdr.i.roots import IEntryPoint
from shinysdr.i.top import Top
from shinysdr.types import ReferenceT
from shinysdr.values import ExportedState, exported_value


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
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_receive_flowgraph(self):  # TODO needs to go away
        return self.__receive_flowgraph
    
    @exported_value(type=ReferenceT(), persists=True, changes='never')
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


@implementer(IEntryPoint)
class Session(ExportedState):
    def __init__(self, receive_flowgraph, features):
        self.__receive_flowgraph = receive_flowgraph
    
    def state_def(self):
        for d in super(Session, self).state_def():
            yield d
        rxfs = self.__receive_flowgraph.state()
        for name in [
            'monitor',
            'sources',
            'source',
            'receivers',
            'accessories',
            'telemetry_store',
            'source_name',
            'clip_warning'
        ]:
            yield name, rxfs[name]

    def get_type(self):
        """implements IEntryPoint"""
        # TODO stub for multisession refactoring
        raise NotImplementedError()
    
    def entry_point_is_deleted(self):
        """implements IEntryPoint"""
        # TODO stub for multisession refactoring
        return False
    
    def add_audio_queue(self, queue, queue_rate):
        return self.__receive_flowgraph.add_audio_queue(queue, queue_rate)
    
    def remove_audio_queue(self, queue):
        return self.__receive_flowgraph.remove_audio_queue(queue)
    
    def get_audio_queue_channels(self):
        return self.__receive_flowgraph.get_audio_queue_channels()
