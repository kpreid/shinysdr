# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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

# TODO: fully clean up this GRC-generated file

from __future__ import absolute_import, division, print_function, unicode_literals

import math
import os.path

from twisted.web import static
from zope.interface import implementer

from gnuradio import analog
from gnuradio import blocks
from gnuradio import fft
from gnuradio import gr
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import firdes

from shinysdr.filters import make_resampler
from shinysdr.interfaces import ClientResourceDef, ModeDef, IDemodulator, IModulator
from shinysdr.plugins.basic_demod import SimpleAudioDemodulator, design_lofi_audio_filter
from shinysdr.signals import SignalType
from shinysdr.types import QuantityT, RangeT
from shinysdr import units
from shinysdr.values import ExportedState, exported_value, setter

audio_modulation_index = 0.07
fm_subcarrier = 9960
fm_deviation = 480


@implementer(IDemodulator)
class VOR(SimpleAudioDemodulator):
    def __init__(self, mode='VOR', zero_point=59, **kwargs):
        self.channel_rate = channel_rate = 40000
        internal_audio_rate = 20000  # TODO over spec'd
        self.zero_point = zero_point

        transition = 5000
        SimpleAudioDemodulator.__init__(self,
            mode=mode,
            audio_rate=internal_audio_rate,
            demod_rate=channel_rate,
            band_filter=fm_subcarrier * 1.25 + fm_deviation + transition / 2,
            band_filter_transition=transition,
            **kwargs)

        self.dir_rate = dir_rate = 10

        if internal_audio_rate % dir_rate != 0:
            raise ValueError('Audio rate %s is not a multiple of direction-finding rate %s' % (internal_audio_rate, dir_rate))
        self.dir_scale = dir_scale = internal_audio_rate // dir_rate
        self.audio_scale = audio_scale = channel_rate // internal_audio_rate

        self.zeroer = blocks.add_const_vff((zero_point * (math.pi / 180), ))
        
        self.dir_vector_filter = grfilter.fir_filter_ccf(1, firdes.low_pass(
            1, dir_rate, 1, 2, firdes.WIN_HAMMING, 6.76))
        self.am_channel_filter_block = grfilter.fir_filter_ccf(1, firdes.low_pass(
            1, channel_rate, 5000, 5000, firdes.WIN_HAMMING, 6.76))
        self.goertzel_fm = fft.goertzel_fc(channel_rate, dir_scale * audio_scale, 30)
        self.goertzel_am = fft.goertzel_fc(internal_audio_rate, dir_scale, 30)
        self.fm_channel_filter_block = grfilter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1.0, channel_rate, fm_subcarrier / 2, fm_subcarrier / 2, firdes.WIN_HAMMING)), fm_subcarrier, channel_rate)
        self.multiply_conjugate_block = blocks.multiply_conjugate_cc(1)
        self.complex_to_arg_block = blocks.complex_to_arg(1)
        self.am_agc_block = analog.feedforward_agc_cc(1024, 1.0)
        self.am_demod_block = analog.am_demod_cf(
            channel_rate=channel_rate,
            audio_decim=audio_scale,
            audio_pass=5000,
            audio_stop=5500,
        )
        self.fm_demod_block = analog.quadrature_demod_cf(1)
        self.phase_agc_fm = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0)
        self.phase_agc_am = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0)
        
        self.probe = blocks.probe_signal_f()
        
        self.audio_filter_block = grfilter.fir_filter_fff(1, design_lofi_audio_filter(internal_audio_rate, False))

        ##################################################
        # Connections
        ##################################################
        # Input
        self.connect(
            self,
            self.band_filter_block)
        # AM chain
        self.connect(
            self.band_filter_block,
            self.am_channel_filter_block,
            self.am_agc_block,
            self.am_demod_block)
        # AM audio
        self.connect(
            self.am_demod_block,
            blocks.multiply_const_ff(1.0 / audio_modulation_index * 0.5),
            self.audio_filter_block)
        self.connect_audio_output(self.audio_filter_block)
        
        # AM phase
        self.connect(
            self.am_demod_block,
            self.goertzel_am,
            self.phase_agc_am,
            (self.multiply_conjugate_block, 0))
        # FM phase
        self.connect(
            self.band_filter_block,
            self.fm_channel_filter_block,
            self.fm_demod_block,
            self.goertzel_fm,
            self.phase_agc_fm,
            (self.multiply_conjugate_block, 1))
        # Phase comparison and output
        self.connect(
            self.multiply_conjugate_block,
            self.dir_vector_filter,
            self.complex_to_arg_block,
            blocks.multiply_const_ff(-1),  # opposite angle conventions
            self.zeroer,
            self.probe)

    @exported_value(type=QuantityT(units.degree), changes='this_setter', label='Zero')
    def get_zero_point(self):
        return self.zero_point

    @setter
    def set_zero_point(self, zero_point):
        self.zero_point = zero_point
        self.zeroer.set_k((self.zero_point * (math.pi / 180), ))

    # TODO: Have a dedicated angle type which can be specified as referenced to true/magnetic north
    @exported_value(type=QuantityT(units.degree), changes='continuous', label='Bearing')
    def get_angle(self):
        return self.probe.level()


@implementer(IModulator)
class VORModulator(gr.hier_block2, ExportedState):
    __vor_sig_freq = 30
    __audio_rate = 10000
    __rf_rate = 30000  # needs to be above fm_subcarrier * 2

    def __init__(self, context, mode, angle=0.0):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__angle = 0.0  # dummy statically visible value will be overwritten
        
        # TODO: My signal level parameters are probably wrong because this signal doesn't look like a real VOR signal
        
        vor_30 = analog.sig_source_f(self.__audio_rate, analog.GR_COS_WAVE, self.__vor_sig_freq, 1, 0)
        vor_add = blocks.add_cc(1)
        vor_audio = blocks.add_ff(1)
        # Audio/AM signal
        self.connect(
            vor_30,
            blocks.multiply_const_ff(0.3),  # M_n
            (vor_audio, 0))
        self.connect(
            self,
            blocks.multiply_const_ff(audio_modulation_index),  # M_i
            (vor_audio, 1))
        # Carrier component
        self.connect(
            analog.sig_source_c(0, analog.GR_CONST_WAVE, 0, 0, 1),
            (vor_add, 0))
        # AM component
        self.__delay = blocks.delay(gr.sizeof_gr_complex, 0)  # configured by set_angle
        self.connect(
            vor_audio,
            make_resampler(self.__audio_rate, self.__rf_rate),  # TODO make a complex version and do this last
            blocks.float_to_complex(1),
            self.__delay,
            (vor_add, 1))
        # FM component
        vor_fm_mult = blocks.multiply_cc(1)
        self.connect(  # carrier generation
            analog.sig_source_f(self.__rf_rate, analog.GR_COS_WAVE, fm_subcarrier, 1, 0), 
            blocks.float_to_complex(1),
            (vor_fm_mult, 1))
        self.connect(  # modulation
            vor_30,
            make_resampler(self.__audio_rate, self.__rf_rate),
            analog.frequency_modulator_fc(2 * math.pi * fm_deviation / self.__rf_rate),
            blocks.multiply_const_cc(0.3),  # M_d
            vor_fm_mult,
            (vor_add, 2))
        self.connect(
            vor_add,
            self)
        
        # calculate and initialize delay
        self.set_angle(angle)
    
    @exported_value(type=RangeT([(0, 2 * math.pi)], unit=units.degree, strict=False), changes='this_setter', label='Bearing')
    def get_angle(self):
        return self.__angle
    
    @setter
    def set_angle(self, value):
        value = float(value)
        compensation = math.pi / 180 * -6.5  # empirical, calibrated against VOR receiver (and therefore probably wrong)
        value = value + compensation
        value = value % (2 * math.pi)
        phase_shift = int(self.__rf_rate / self.__vor_sig_freq * (value / (2 * math.pi)))
        self.__delay.set_dly(phase_shift)
        self.__angle = value
    
    def get_input_type(self):
        return SignalType(kind='MONO', sample_rate=self.__audio_rate)
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__rf_rate)


# Twisted plugin exports
pluginMode = ModeDef(mode='VOR',
    info='VOR',
    demod_class=VOR,
    mod_class=VORModulator)
pluginClient = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='vor.js')
