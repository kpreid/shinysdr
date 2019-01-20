# Copyright 2017, 2018 Kevin Reid and the ShinySDR contributors
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

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.task import deferLater
from twisted.trial import unittest

from gnuradio import blocks
from gnuradio import gr
from gnuradio.fft import window as windows
import numpy

from shinysdr.i.blocks import Context, MonitorSink, ReactorSink, RecursiveLockBlockMixin
from shinysdr.signals import SignalType


class TestReactorSink(unittest.TestCase):
    def setUp(self):
        self.tb = gr.top_block(str('TestReactorSink'))  # py2/3 compatibility -- must be the 'normal' string type in either case
        self.out = []
    
    def callback(self, array):
        self.out.append(array.tolist())
    
    @defer.inlineCallbacks
    def test_bytes(self):
        test_data_bytes = [1, 2, 3, 255]
        self.tb.connect(
            blocks.vector_source_b(test_data_bytes),
            ReactorSink(numpy_type=numpy.uint8, callback=self.callback, reactor=the_reactor))
        self.tb.start()
        self.tb.wait()
        self.tb.stop()
        yield deferLater(the_reactor, 0.0, lambda: None)
        self.assertEqual(self.out, [test_data_bytes])
    
    @defer.inlineCallbacks
    def test_pair_floats(self):
        # This test isn't about complexes, but this is the easiest way to set up the vector source
        test_data_floats = [[1, 2], [3, 4]]
        test_data_complexes = [complex(1, 2), complex(3, 4)]
        self.tb.connect(
            blocks.vector_source_c(test_data_complexes),
            ReactorSink(numpy_type=numpy.dtype((numpy.float32, 2)), callback=self.callback, reactor=the_reactor))
        self.tb.start()
        self.tb.wait()
        self.tb.stop()
        yield deferLater(the_reactor, 0.0, lambda: None)
        self.assertEqual(self.out, [test_data_floats])


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
