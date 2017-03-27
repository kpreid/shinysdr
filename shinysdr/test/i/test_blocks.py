# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.i.blocks import Context, MonitorSink, RecursiveLockBlockMixin
from shinysdr.signals import SignalType


class TestMonitorSink(unittest.TestCase):
    def setUp(self):
        self.tb = RLTB()
        self.context = Context(self.tb)

    def test_smoke(self):
        m = MonitorSink(
            context=self.context,
            signal_type=SignalType(kind='IQ', sample_rate=1000))
        self.tb.connect(blocks.null_source(gr.sizeof_gr_complex), m)
        self.tb.start()
        self.tb.stop()
        self.tb.wait()


class RLTB(gr.top_block, RecursiveLockBlockMixin):
    pass
