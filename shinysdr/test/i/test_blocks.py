# Copyright 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division, unicode_literals

from twisted.trial import unittest

from gnuradio import blocks
from gnuradio import gr
from gnuradio.fft import window as windows

from shinysdr.i.blocks import Context, MonitorSink, RecursiveLockBlockMixin
from shinysdr.signals import SignalType


class TestMonitorSink(unittest.TestCase):
    def setUp(self):
        self.tb = RLTB()
        self.context = Context(self.tb)
    
    def make(self, kind='IQ'):
        signal_type = SignalType(kind=kind, sample_rate=1000)
        m = MonitorSink(
            context=self.context,
            signal_type=signal_type)
        self.tb.connect(blocks.null_source(signal_type.get_itemsize()), m)
        return m

    def test_smoke_complex(self):
        self.make('IQ')
        self.tb.start()
        self.tb.stop()
        self.tb.wait()

    def test_smoke_real(self):
        self.make('MONO')
        self.tb.start()
        self.tb.stop()
        self.tb.wait()
    
    def test_smoke_change_window(self):
        m = self.make()
        self.tb.start()
        m.set_window_type(windows.WIN_FLATTOP)
        self.tb.stop()
        self.tb.wait()


class RLTB(gr.top_block, RecursiveLockBlockMixin):
    pass
