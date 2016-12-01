# -*- coding: utf-8 -*-
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

# pylint: disable=no-member
# (no-member: Twisted reactor)

from __future__ import absolute_import, division

from zope.interface import implements

from gnuradio import gr

try:
    from dsd import block_ff as dsd_block_ff
    _available = True
except ImportError:
    _available = False

from shinysdr.filters import make_resampler
from shinysdr.interfaces import ModeDef, IDemodulator
from shinysdr.plugins.basic_demod import NFMDemodulator
from shinysdr.signals import SignalType
from shinysdr.types import EnumRow, Reference
from shinysdr.values import ExportedState, exported_value


_demod_rate = 48000  # hardcoded in gr-dsd


class DSDDemodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    def __init__(self, mode, input_rate=0, context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float))
        
        # TODO: Retry telling the NFMDemodulator to have its output rate be pipe_rate instead of using a resampler. Something went wrong when trying that before. Same thing is done in multimon.py
        self.__fm_demod = NFMDemodulator(
            mode='NFM',
            input_rate=input_rate,
            no_audio_filter=True,  # don't remove CTCSS tone
            tau=None)  # no deemphasis
        assert self.__fm_demod.get_output_type().get_kind() == 'MONO'
        fm_audio_rate = self.__fm_demod.get_output_type().get_sample_rate()

        self.__output_type = SignalType(kind='MONO', sample_rate=8000)
        
        self.connect(
            self,
            self.__fm_demod,
            make_resampler(fm_audio_rate, _demod_rate),
            dsd_block_ff(),
            self)
    
    @exported_value(type=Reference(), changes='never')
    def get_fm_demod(self):
        return self.__fm_demod
    
    def can_set_mode(self, mode):
        return False
    
    def get_output_type(self):
        return self.__output_type
    
    @exported_value(changes='never')
    def get_band_filter_shape(self):
        return self.__fm_demod.get_band_filter_shape()


_modeDef = ModeDef(mode=u'DSD',  # TODO: Ought to declare all the individual modes that DSD can decode -- once we have a way to not spam the mode selector with that.
    info=EnumRow(label=u'DSD', description=u'All modes DSD can decode (P25, DMR, D-STAR, …)'),
    demod_class=DSDDemodulator,
    available=_available)
