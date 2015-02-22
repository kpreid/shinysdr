# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

from gnuradio import gr

from shinysdr.top import Top
from shinysdr.plugins import simulate


class TestTop(unittest.TestCase):
    def test_source_switch_update(self):
        '''
        Regression test: Switching sources was not updating receiver input frequency.
        '''
        freq = 1e6
        top = Top(devices={
            's1': simulate.SimulatedDevice(freq=0),
            's2': simulate.SimulatedDevice(freq=freq),
        })
        top.set_source_name('s1')
        self.assertEqual(top.monitor.get_fft_info()[0], 0)
        
        (_key, receiver) = top.add_receiver('AM', key='a')
        receiver.set_rec_freq(freq)
        self.assertFalse(receiver.get_is_valid())
        
        top.set_source_name('s2')
        # TODO: instead of top.monitor, should go through state interface
        self.assertEqual(top.monitor.get_fft_info()[0], freq)
        self.assertTrue(receiver.get_is_valid())

    def test_add_unknown_mode(self):
        '''
        Specifying an unknown mode should not _fail_.
        '''
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)})
        (_key, receiver) = top.add_receiver('NONSENSE', key='a')
        self.assertEqual(receiver.get_mode(), 'AM')
    
    def test_audio_queue_smoke(self):
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)})
        queue = gr.msg_queue()
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_queue(queue, 48000)
        top.remove_audio_queue(queue)
    
    def test_mono(self):
        top = Top(devices={'s1': simulate.SimulatedDevice(freq=0)}, stereo=False)
        queue = gr.msg_queue()
        (_key, _receiver) = top.add_receiver('AM', key='a')
        top.add_audio_queue(queue, 48000)
        top.remove_audio_queue(queue)
