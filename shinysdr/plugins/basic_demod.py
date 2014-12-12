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

from zope.interface import implements

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.analog import fm_emph
from gnuradio.filter import firdes

from shinysdr.modes import ModeDef, IDemodulator, IModulator, ITunableDemodulator
from shinysdr.blocks import MultistageChannelFilter, make_resampler
from shinysdr.signals import SignalType
from shinysdr.types import Range
from shinysdr.values import ExportedState, exported_value, setter

import math


TWO_PI = math.pi * 2


class Demodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    def __init__(self, mode,
            input_rate=0,
            context=None):
        assert input_rate > 0
        
        # early init because we're going to invoke get_output_type()
        self.mode = mode
        self.input_rate = input_rate
        self.context = context
        
        self.__channels = channels = 2 if self.get_output_type().get_kind() == 'STEREO' else 1
        gr.hier_block2.__init__(
            # str() because insists on non-unicode
            self, str('%s receiver' % (mode,)),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(channels, channels, gr.sizeof_float * 1),
        )

    def can_set_mode(self, mode):
        return False

    def get_half_bandwidth(self):
        raise NotImplementedError('Demodulator.get_half_bandwidth')

    def get_output_type(self):
        raise NotImplementedError('Demodulator.get_output_type')

    # TODO: remove this indirection
    def connect_audio_output(self, l_port, r_port=None):
        assert (r_port is not None) == (self.__channels == 2)
        self.connect(l_port, (self, 0))
        if r_port is not None:
            self.connect(r_port, (self, 1))


class SquelchMixin(ExportedState):
    def __init__(self, squelch_rate, squelch_threshold=-100):
        alpha = 9.6 / squelch_rate
        self.rf_squelch_block = analog.simple_squelch_cc(squelch_threshold, alpha)
        self.rf_probe_block = analog.probe_avg_mag_sqrd_c(0, alpha=alpha)

    @exported_value(ctor=Range([(-100, 0)], strict=False))
    def get_rf_power(self):
        return 10 * math.log10(max(1e-10, self.rf_probe_block.level()))

    @exported_value(ctor=Range([(-100, 0)], strict=False, logarithmic=False))
    def get_squelch_threshold(self):
        return self.rf_squelch_block.threshold()

    @setter
    def set_squelch_threshold(self, level):
        self.rf_squelch_block.set_threshold(level)


class SimpleAudioDemodulator(Demodulator, SquelchMixin):
    implements(ITunableDemodulator)
    
    def __init__(self, demod_rate=0, audio_rate=0, band_filter=None, band_filter_transition=None, stereo=False, **kwargs):
        assert audio_rate > 0
        
        self.__signal_type = SignalType(
            kind='STEREO' if stereo else 'MONO',
            sample_rate=audio_rate)
        
        Demodulator.__init__(self, **kwargs)
        SquelchMixin.__init__(self, demod_rate)
        
        self.band_filter = band_filter
        self.band_filter_transition = band_filter_transition
        self.demod_rate = demod_rate
        self.audio_rate = audio_rate

        input_rate = self.input_rate
        
        self.band_filter_block = MultistageChannelFilter(
            input_rate=input_rate,
            output_rate=demod_rate,
            cutoff_freq=band_filter,
            transition_width=band_filter_transition)

    def get_half_bandwidth(self):
        return self.band_filter

    def get_output_type(self):
        return self.__signal_type

    def set_rec_freq(self, freq):
        '''for ITunableDemodulator'''
        self.band_filter_block.set_center_freq(freq)

    @exported_value()
    def get_band_filter_shape(self):
        return {
            'low': -self.band_filter,
            'high': self.band_filter,
            'width': self.band_filter_transition
        }


def design_lofi_audio_filter(rate, lowpass):
    '''
    Audio output filter for speech-type receivers.
    
    Original motivation was to remove CTCSS tones.
    '''
    upper = min(10000, rate / 2)
    transition = 1000
    if lowpass:
        return firdes.low_pass(
            1.0,
            rate,
            upper,
            transition,
            firdes.WIN_HAMMING)
    else:
        return firdes.band_pass(
            1.0,
            rate,
            500,
            upper,
            transition,
            firdes.WIN_HAMMING)


class IQDemodulator(SimpleAudioDemodulator):
    def __init__(self, mode='IQ', **kwargs):
        audio_rate = 96000  # TODO parameter / justify this
        SimpleAudioDemodulator.__init__(self,
            mode=mode,
            stereo=True,
            audio_rate=audio_rate,
            demod_rate=audio_rate,
            band_filter=audio_rate * 0.5,
            band_filter_transition=audio_rate * 0.2,
            **kwargs)
        
        self.split_block = blocks.complex_to_float(1)
        
        self.connect(
            self,
            self.band_filter_block,
            self.rf_squelch_block,
            self.split_block)
        self.connect(self.band_filter_block, self.rf_probe_block)
        self.connect_audio_output((self.split_block, 0), (self.split_block, 1))


pluginDef_iq = ModeDef('IQ', label='Raw I/Q', demod_class=IQDemodulator)


class AMDemodulator(SimpleAudioDemodulator):
    def __init__(self, **kwargs):
        demod_rate = 10000
        
        SimpleAudioDemodulator.__init__(self,
            audio_rate=demod_rate,
            demod_rate=demod_rate,
            band_filter=5000,
            band_filter_transition=5000,
            **kwargs)
    
        inherent_gain = 0.5  # fudge factor so that our output is similar level to narrow FM
        self.agc_block = analog.feedforward_agc_cc(int(.02 * demod_rate), inherent_gain)
        self.demod_block = blocks.complex_to_mag(1)
        
        # assuming below 40Hz is not of interest
        dc_blocker = grfilter.dc_blocker_ff(demod_rate // 40, False)
        
        self.connect(
            self,
            self.band_filter_block,
            self.rf_squelch_block,
            self.agc_block,
            self.demod_block,
            dc_blocker)
        self.connect(self.band_filter_block, self.rf_probe_block)
        self.connect_audio_output(dc_blocker)


class AMModulator(gr.hier_block2, ExportedState):
    implements(IModulator)
    
    def __init__(self, rate=10000):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__rate = rate
        
        self.connect(
            self,
            blocks.float_to_complex(1),
            blocks.add_const_cc(1),
            self)
    
    def get_input_type(self):
        return SignalType(kind='MONO', sample_rate=self.__rate)
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__rate)


pluginDef_am = ModeDef('AM', label='AM', demod_class=AMDemodulator, mod_class=AMModulator)


class FMDemodulator(SimpleAudioDemodulator):
    def __init__(self,
            mode,
            deviation=75000,
            demod_rate=48000,
            band_filter=None,
            band_filter_transition=None,
            tau=75e-6,
            no_audio_filter=False,  # TODO kludge to support APRS demod looking for tones
            **kwargs):
        SimpleAudioDemodulator.__init__(self,
            mode=mode,
            demod_rate=demod_rate,
            band_filter=band_filter,
            band_filter_transition=band_filter_transition,
            **kwargs)
        
        self.__no_audio_filter = no_audio_filter
        
        self.__qdemod = analog.quadrature_demod_cf(demod_rate / (TWO_PI * deviation))
        if tau > 0.0:
            self.__deemph = fm_emph.fm_deemph(demod_rate, tau)
        else:
            self.__deemph = None
        
        self.do_connect()
    
    def do_connect(self):
        self.disconnect_all()
        self.connect(self.band_filter_block, self.rf_probe_block)
        self.connect(
            self,
            self.band_filter_block,
            self.rf_squelch_block,
            self.__qdemod)
        if self.__deemph is not None:
            self.connect(self.__qdemod, self.__deemph)
            output = self.__deemph
        else:
            output = self.__qdemod
        self.connect_audio_stage(output)
    
    def _make_resampler(self, input_port, input_rate):
        taps = design_lofi_audio_filter(input_rate, self.__no_audio_filter)
        if self.audio_rate == input_rate:
            filt = grfilter.fir_filter_fff(1, taps)
            self.connect(input_port, filt)
            return filt
        elif input_rate % self.audio_rate == 0:
            filt = grfilter.fir_filter_fff(input_rate // self.audio_rate, taps)
            self.connect(input_port, filt)
            return filt
        else:
            # TODO: use combined filter and resampler (need to move filter design)
            filt = grfilter.fir_filter_fff(1, taps)
            resampler = make_resampler(input_rate, self.audio_rate)
            self.connect(input_port, filt, resampler)
            return resampler

    def connect_audio_stage(self, input_port):
        '''Override point for stereo'''
        resampler = self._make_resampler(input_port, self.demod_rate)
        self.connect_audio_output(resampler)


class NFMDemodulator(FMDemodulator):
    def __init__(self, **kwargs):
        # TODO support 2.5kHz deviation
        audio_rate = 10000  # TODO justify
        deviation = 5000
        transition = 1000
        FMDemodulator.__init__(self,
            demod_rate=max(deviation * 3, audio_rate),  # TODO justify the 3
            audio_rate=audio_rate,
            deviation=deviation,
            band_filter=deviation + transition * 0.5,
            band_filter_transition=transition,
            **kwargs)


class NFMModulator(gr.hier_block2, ExportedState):
    implements(IModulator)
    
    def __init__(self, audio_rate=10000, rf_rate=20000):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__audio_rate = audio_rate
        self.__rf_rate = rf_rate
        
        self.connect(
            self,
            analog.nbfm_tx(
                audio_rate=audio_rate,
                quad_rate=rf_rate,
                tau=75e-6,
                max_dev=5e3),
            self)
    
    def get_input_type(self):
        return SignalType(kind='MONO', sample_rate=self.__audio_rate)
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__rf_rate)


pluginDef_nfm = ModeDef('NFM', label='Narrow FM', demod_class=NFMDemodulator, mod_class=NFMModulator)


class WFMDemodulator(FMDemodulator):
    def __init__(self, stereo=True, **kwargs):
        self.stereo = stereo
        self.__audio_int_rate = 40000  # lower than demod rate, higher than audio filter
        FMDemodulator.__init__(self,
            stereo=True,  # config for stereo because we can't change at runtime
            audio_rate=self.__audio_int_rate,
            demod_rate=200000,  # higher than deviation*2, higher than stereo pilot freq, multiple of __audio_int_rate
            deviation=75000,
            band_filter=80000,
            band_filter_transition=20000,
            **kwargs)

    @exported_value(ctor=bool)
    def get_stereo(self):
        return self.stereo
    
    @setter
    def set_stereo(self, value):
        if value == self.stereo: return
        self.stereo = bool(value)
        self.context.lock()
        self.do_connect()
        self.context.unlock()
    
    def connect_audio_stage(self, input_port):
        stereo_rate = self.demod_rate
        normalizer = TWO_PI / stereo_rate
        pilot_tone = 19000
        pilot_low = pilot_tone * 0.9
        pilot_high = pilot_tone * 1.1

        def make_audio_filter():
            return grfilter.fir_filter_fff(
                stereo_rate // self.__audio_int_rate,  # decimation
                firdes.low_pass(
                    1.0,
                    stereo_rate,
                    15000,
                    5000,
                    firdes.WIN_HAMMING))

        stereo_pilot_filter = grfilter.fir_filter_fcc(
            1,  # decimation
            firdes.complex_band_pass(
                1.0,
                stereo_rate,
                pilot_low,
                pilot_high,
                300))  # TODO magic number from gqrx
        stereo_pilot_pll = analog.pll_refout_cc(
            0.001,  # TODO magic number from gqrx
            normalizer * pilot_high,
            normalizer * pilot_low)
        stereo_pilot_doubler = blocks.multiply_cc()
        stereo_pilot_out = blocks.complex_to_imag()
        difference_channel_mixer = blocks.multiply_ff()
        difference_channel_filter = make_audio_filter()
        mono_channel_filter = make_audio_filter()
        mixL = blocks.add_ff(1)
        mixR = blocks.sub_ff(1)
        
        # connections
        self.connect(input_port, mono_channel_filter)
        if self.stereo:
            # stereo pilot tone tracker
            self.connect(
                input_port,
                stereo_pilot_filter,
                stereo_pilot_pll)
            self.connect(stereo_pilot_pll, (stereo_pilot_doubler, 0))
            self.connect(stereo_pilot_pll, (stereo_pilot_doubler, 1))
            self.connect(stereo_pilot_doubler, stereo_pilot_out)
        
            # pick out stereo left-right difference channel (at stereo_rate)
            self.connect(input_port, (difference_channel_mixer, 0))
            self.connect(stereo_pilot_out, (difference_channel_mixer, 1))
            self.connect(difference_channel_mixer, difference_channel_filter)
        
            # recover left/right channels (at self.__audio_int_rate)
            self.connect(difference_channel_filter, (mixL, 1))
            self.connect(difference_channel_filter, (mixR, 1))
            resamplerL = self._make_resampler((mixL, 0), self.__audio_int_rate)
            resamplerR = self._make_resampler((mixR, 0), self.__audio_int_rate)
            self.connect(mono_channel_filter, (mixL, 0))
            self.connect(mono_channel_filter, (mixR, 0))
            self.connect_audio_output(resamplerL, resamplerR)
        else:
            resampler = self._make_resampler(mono_channel_filter, self.__audio_int_rate)
            self.connect_audio_output(resampler, resampler)


pluginDef_wfm = ModeDef('WFM', label='Broadcast FM', demod_class=WFMDemodulator)


_ssb_max_agc = 1.5


class SSBDemodulator(SimpleAudioDemodulator):
    def __init__(self, mode, **kwargs):
        if mode == 'LSB':
            lsb = True
            cw = False
        elif mode == 'USB':
            lsb = False
            cw = False
        elif mode == 'CW':
            lsb = False
            cw = True
        else:
            raise ValueError('Not an SSB mode: %r' % (mode,))
        
        demod_rate = 8000  # round number close to SSB bandwidth * 2
        
        SimpleAudioDemodulator.__init__(self,
            mode=mode,
            audio_rate=demod_rate,
            demod_rate=demod_rate,
            band_filter=demod_rate / 2,  # note narrower filter applied later
            band_filter_transition=demod_rate / 2,
            **kwargs)
        
        if cw:
            self.__offset = 1500  # CW beat frequency
            half_bandwidth = self.half_bandwidth = 500
            self.band_filter_width = 120
            band_mid = 0
            agc_reference = 0.1
        else:
            self.__offset = 0
            half_bandwidth = self.half_bandwidth = 2800 / 2  # standard SSB bandwidth
            self.band_filter_width = half_bandwidth / 5
            if lsb:
                band_mid = -200 - half_bandwidth
            else:
                band_mid = 200 + half_bandwidth
            agc_reference = 0.25
        
        self.band_filter_low = band_mid - half_bandwidth
        self.band_filter_high = band_mid + half_bandwidth
        sharp_filter_block = grfilter.fir_filter_ccc(
            1,
            firdes.complex_band_pass(1.0, demod_rate,
                self.band_filter_low + self.__offset,
                self.band_filter_high + self.__offset,
                self.band_filter_width,
                firdes.WIN_HAMMING))
        
        self.agc_block = analog.agc2_cc(reference=agc_reference)
        self.agc_block.set_max_gain(_ssb_max_agc)
        
        ssb_demod_block = blocks.complex_to_real(1)
        
        self.connect(
            self,
            self.band_filter_block,
            sharp_filter_block,
            self.rf_squelch_block,
            self.agc_block,
            ssb_demod_block)
        self.connect(sharp_filter_block, self.rf_probe_block)
        self.connect_audio_output(ssb_demod_block)

    # override
    # TODO: this is the interface used to determine receiver.get_is_valid, but SSB demonstrates that the interface is insufficiently expressive. Should we use get_band_filter_shape instead? Should we use a different interface designed for expressing the channel? Or are signals like SSB which are asymmetric about the "carrier" frequency uncommon enough that we should not worry about handling this case well?
    def get_half_bandwidth(self):
        return self.half_bandwidth
    
    # override
    def set_rec_freq(self, freq):
        super(SSBDemodulator, self).set_rec_freq(freq - self.__offset)
    
    # override
    @exported_value()
    def get_band_filter_shape(self):
        return {
            'low': self.band_filter_low,
            'high': self.band_filter_high,
            'width': self.band_filter_width
        }
    
    @exported_value(ctor=Range([(-100, 10 * math.log10(_ssb_max_agc))]))
    def get_agc_gain(self):
        return 10 * math.log10(self.agc_block.gain())


class DSBModulator(gr.hier_block2, ExportedState):
    implements(IModulator)
    
    def __init__(self, rate=8000):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__rate = rate
        
        self.connect(
            self,
            blocks.float_to_complex(1),
            self)
    
    def get_input_type(self):
        return SignalType(kind='MONO', sample_rate=self.__rate)
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__rate)


# TODO: implement SSB, not DSB, modulator
pluginDef_lsb = ModeDef('LSB', label='SSB (L)', demod_class=SSBDemodulator, mod_class=DSBModulator)
pluginDef_usb = ModeDef('USB', label='SSB (U)', demod_class=SSBDemodulator, mod_class=DSBModulator)
pluginDef_cw = ModeDef('CW', label='CW', demod_class=SSBDemodulator, mod_class=DSBModulator)
