# -*- coding: utf-8 -*-
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

# pylint: disable=no-member
# (no-member: Twisted reactor)

from __future__ import absolute_import, division, unicode_literals

from zope.interface import implementer

from gnuradio import gr

try:
    from dsd import dsd_block_ff
    import dsd
    _available_version = 2
except ImportError:
    try:
        from dsd import block_ff as dsd_block_ff
        import dsd
        _available_version = 1
    except ImportError:
        _available_version = None

from shinysdr.filters import make_resampler
from shinysdr.interfaces import BandShape, ModeDef, IDemodulator
from shinysdr.plugins.basic_demod import NFMDemodulator
from shinysdr.signals import SignalType
from shinysdr.types import EnumRow, RangeT, ReferenceT
from shinysdr.values import ExportedState, exported_value, setter


_debug_print = True  # TODO turn this off
_demod_rate = 48000  # hardcoded in gr-dsd
_uvquality_range = RangeT([(1, 4)], integer=True)


@implementer(IDemodulator)
class DSDDemodulator(gr.hier_block2, ExportedState):
    def __init__(self, mode, input_rate=0, uvquality=3, context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float))
        
        self.__context = context
        self.__output_type = SignalType(kind='MONO', sample_rate=8000)
        self.__uvquality = uvquality
        
        # TODO: Retry telling the NFMDemodulator to have its output rate be _demod_rate instead of using a resampler. Something went wrong when trying that before. Same thing is done in multimon.py
        self.__fm_demod = NFMDemodulator(
            mode='NFM',
            input_rate=input_rate,
            no_audio_filter=True,  # don't remove CTCSS tone
            tau=None)  # no deemphasis
        assert self.__fm_demod.get_output_type().get_kind() == 'MONO'
        fm_audio_rate = self.__fm_demod.get_output_type().get_sample_rate()
        self.__resampler = make_resampler(fm_audio_rate, _demod_rate)
        
        self.__do_connect(False)
    
    def __do_connect(self, not_init):
        # TODO: figure out why tests, but not the real server, have a hanging problem if we lock always
        if not_init: self.__context.lock()
        try:
            self.disconnect_all()
            if _available_version == 1:
                # backwards compatibility
                decoder = dsd_block_ff()
            else:
                decoder = dsd_block_ff(
                    # TODO: Add controls to choose frame and mod options at runtime — need to be able to get the enum info from gr-dsd, which may not even be currently available.
                    frame=dsd.dsd_FRAME_AUTO_DETECT,
                    mod=dsd.dsd_MOD_AUTO_SELECT,
                    uvquality=self.__uvquality,
                    errorbars=_debug_print,
                    verbosity=2 if _debug_print else 0)
            self.connect(
                self,
                self.__fm_demod,
                self.__resampler,
                decoder,
                self)
        finally:
            if not_init: self.__context.unlock()
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_fm_demod(self):
        return self.__fm_demod
    
    if _available_version >= 2:
        @exported_value(type=_uvquality_range,
            changes='this_setter',
            label='Unvoiced speech quality',
            parameter='uvquality')
        def get_uvquality(self):
            return self.__uvquality
    
        @setter
        def set_uvquality(self, value):
            value = _uvquality_range(value)
            if self.__uvquality != value:
                self.__uvquality = value
                self.__do_connect(True)
    
    def get_output_type(self):
        return self.__output_type
    
    @exported_value(type=BandShape, changes='never')
    def get_band_shape(self):
        return self.__fm_demod.get_band_shape()


_modeDef = ModeDef(mode=u'DSD',  # TODO: Ought to declare all the individual modes that DSD can decode -- once we have a way to not spam the mode selector with that.
    info=EnumRow(label=u'DSD', description=u'All modes DSD can decode (P25, DMR, D-STAR, …)'),
    demod_class=DSDDemodulator,
    available=bool(_available_version))
