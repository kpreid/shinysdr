# Copyright 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

from zope.interface import implementer

from gnuradio import analog
from gnuradio import blocks
from gnuradio import gr

try:
    # gr-radioteletype
    # https://github.com/bitglue/gr-radioteletype
    from radioteletype.demodulators import (
        psk31_coherent_demodulator_cc,
        psk31_constellation_decoder_cb)
    _unavailability = None
except ImportError as e:
    _unavailability = unicode(e)

from shinysdr.math import dB, rotator_inc
from shinysdr.filters import MultistageChannelFilter
from shinysdr.interfaces import ModeDef, IDemodulator, BandShape
from shinysdr.signals import SignalType
from shinysdr.values import ExportedState, StringSinkCell, exported_value


@implementer(IDemodulator)
class PSK31Demodulator(gr.hier_block2, ExportedState):
    '''Demodulate PSK31.'''
    
    __symbol_rate = 31.25
    __demod_rate = 4000

    __cutoff = __symbol_rate
    __transition_width = __symbol_rate

    __audio_frequency = 1500

    def __init__(self, mode, input_rate=0, context=None):
        assert input_rate > 0
        self.__input_rate = input_rate
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float))
        
        channel_filter = self.__make_channel_filter()

        self.__text_cell = StringSinkCell(encoding='us-ascii')
        self.__text_sink = self.__text_cell.create_sink_internal()

        # The output of the channel filter is oversampled so we don't need to
        # interpolate for the audio monitor. So we'll downsample before going into
        # the demodulator.
        samp_per_sym = 8
        downsample = self.__demod_rate / samp_per_sym / self.__symbol_rate
        assert downsample % 1 == 0
        downsample = int(downsample)

        self.connect(
            self,
            channel_filter,
            blocks.keep_one_in_n(gr.sizeof_gr_complex, downsample),
            psk31_coherent_demodulator_cc(samp_per_sym=samp_per_sym),
            psk31_constellation_decoder_cb(
                varicode_decode=True,
                differential_decode=True),
            self.__text_sink)
        
        self.connect(
            channel_filter,
            blocks.rotator_cc(rotator_inc(self.__demod_rate, self.__audio_frequency)),
            blocks.complex_to_real(vlen=1),
            analog.agc2_ff(
                reference=dB(-10),
                attack_rate=8e-1,
                decay_rate=8e-1),
            self)

    def __make_channel_filter(self):
        '''Return the channel filter.

        psk31_demodulator_cbc includes filters, so this filter will be wide to
        assure the passband has no group delay and make it easier to listen to.

        Output has frequencies from -250 to +250.
        '''
        return MultistageChannelFilter(
            input_rate=self.__input_rate,
            output_rate=self.__demod_rate,
            cutoff_freq=250 - 25,
            transition_width=25)

    def state_def(self):
        for d in super(PSK31Demodulator, self).state_def():
            yield d
        # TODO make this possible to be decorator style
        yield 'text', self.__text_cell

    @exported_value(type=BandShape, changes='never')
    def get_band_shape(self):
        """implement IDemodulator"""
        return BandShape.bandpass_transition(
            low=-self.__cutoff,
            high=self.__cutoff,
            transition=self.__transition_width)
    
    def get_output_type(self):
        """implement IDemodulator"""
        return SignalType(kind='MONO', sample_rate=self.__demod_rate)


pluginMode = ModeDef(mode='PSK31',
    info='PSK31',
    demod_class=PSK31Demodulator,
    unavailability=_unavailability)
