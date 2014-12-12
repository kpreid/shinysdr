#!/usr/bin/env python

# Copyright 20134 Kevin Reid <kpreid@switchb.org>
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

'''
Benchmark for MultistageChannelFilter.
'''

from __future__ import absolute_import, division

import time

from gnuradio import blocks
from gnuradio import gr

from shinysdr.blocks import MultistageChannelFilter


def test_one_filter(**kwargs):
    print '------ %s -------' % (kwargs,)
    f = MultistageChannelFilter(**kwargs)
    
    size = 10000000
    
    top = gr.top_block()
    top.connect(
        blocks.vector_source_c([5] * size),
        f,
        blocks.null_sink(gr.sizeof_gr_complex))
        
    print f.explain()
    
    t0 = time.clock()
    top.start()
    top.wait()
    top.stop()
    t1 = time.clock()

    print size, 'samples processed in', t1 - t0, 'CPU-seconds'


if __name__ == '__main__':
    # like SSB
    test_one_filter(input_rate=3200000, output_rate=8000, cutoff_freq=3000, transition_width=1200)
    
    # like WFM
    test_one_filter(input_rate=2400000, output_rate=240000, cutoff_freq=80000, transition_width=20000)
    
    # requires non-decimation resampling
    test_one_filter(input_rate=1000000, output_rate=48000, cutoff_freq=5000, transition_width=1000)
