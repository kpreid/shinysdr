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

from __future__ import absolute_import, division

from twisted.trial import unittest

from gnuradio import blocks
from gnuradio import gr

from shinysdr.i.audiomux import AudioManager


class TestAudioManager(unittest.TestCase):
    def setUp(self):
        self.tb = gr.top_block()
        self.p = AudioManager(
            graph=self.tb,
            audio_config=None,
            stereo=False)

    def test_smoke(self):
        rs = self.p.reconnecting()
        rs.input(ConnectionCanarySource(self.tb), 10000, 'client')
        rs.finish_bus_connections()
        self.tb.start()
        self.tb.stop()
        self.tb.wait()

    def test_wrong_dest_name(self):
        """
        Shouldn't fail to construct a valid flow graph, despite the bad name.
        """
        rs = self.p.reconnecting()
        rs.input(ConnectionCanarySource(self.tb), 10000, 'bogusname')
        rs.finish_bus_connections()
        self.tb.start()
        self.tb.stop()
        self.tb.wait()


def ConnectionCanarySource(graph):
    """
    Set up a partial graph to detect its output not being connected
    """
    source = blocks.vector_source_f([])
    copy = blocks.copy(gr.sizeof_float)
    graph.connect(source, copy)
    return copy
