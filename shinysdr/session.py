# Copyright 2015 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division

from shinysdr.values import ExportedState


class Session(ExportedState):
    def __init__(self, receive_flowgraph):
        self.__receive_flowgraph = receive_flowgraph

    def state_def(self, callback):
        super(Session, self).state_def(callback)
        rxfs = self.__receive_flowgraph.state()
        callback(rxfs['monitor'])
        callback(rxfs['sources'])
        callback(rxfs['source'])
        callback(rxfs['receivers'])
        callback(rxfs['accessories'])
        callback(rxfs['shared_objects'])
        callback(rxfs['source_name'])
        callback(rxfs['clip_warning'])
        
    def add_audio_queue(self, queue, queue_rate):
        return self.__receive_flowgraph.add_audio_queue(queue, queue_rate)
    
    def remove_audio_queue(self, queue):
        return self.__receive_flowgraph.remove_audio_queue(queue)
    
    def get_audio_queue_channels(self):
        return self.__receive_flowgraph.get_audio_queue_channels()
    
