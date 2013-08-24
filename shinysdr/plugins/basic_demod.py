from __future__ import division

from zope.interface import implements
from twisted.plugin import IPlugin

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import firdes

from shinysdr.receiver import ModeDef, IDemodulator
from shinysdr.blocks import MultistageChannelFilter, make_resampler
from shinysdr.values import ExportedState, Range, exported_value, setter

import math

class Demodulator(gr.hier_block2, ExportedState):
	implements(IDemodulator)
	def __init__(self, mode,
			input_rate=0,
			audio_rate=0,
			context=None):
		assert input_rate > 0
		assert audio_rate > 0
		gr.hier_block2.__init__(
			# str() because insists on non-unicode
			self, str('%s receiver' % (mode,)),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(2, 2, gr.sizeof_float * 1),
		)
		self.mode = mode
		self.input_rate = input_rate
		self.audio_rate = audio_rate
		self.context = context
		

	def can_set_mode(self, mode):
		return False

	def get_half_bandwidth(self):
		raise NotImplementedError('Demodulator.get_half_bandwidth')

	# TODO: remove this indirection
	def connect_audio_output(self, l_port, r_port):
		self.connect(l_port, (self, 0))
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
	def __init__(self, demod_rate=0, band_filter=None, band_filter_transition=None, **kwargs):
		Demodulator.__init__(self, **kwargs)
		SquelchMixin.__init__(self, demod_rate)
		
		self.band_filter = band_filter
		self.band_filter_transition = band_filter_transition
		self.demod_rate = demod_rate

		input_rate = self.input_rate
		audio_rate = self.audio_rate
		
		self.band_filter_block = MultistageChannelFilter(
			input_rate=input_rate,
			output_rate=demod_rate,
			cutoff_freq=band_filter,
			transition_width=band_filter_transition)

	def get_half_bandwidth(self):
		return self.band_filter

	@exported_value()
	def get_band_filter_shape(self):
		return {
			'low': -self.band_filter,
			'high': self.band_filter,
			'width': self.band_filter_transition
		}


class IQDemodulator(SimpleAudioDemodulator):
	def __init__(self, mode='IQ', audio_rate=0, **kwargs):
		assert audio_rate > 0
		SimpleAudioDemodulator.__init__(self,
			mode=mode,
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


pluginDef_iq = ModeDef('IQ', label='Raw I/Q', demodClass=IQDemodulator)


class AMDemodulator(SimpleAudioDemodulator):
	def __init__(self, **kwargs):
		demod_rate = 48000
		
		SimpleAudioDemodulator.__init__(self, demod_rate=demod_rate, band_filter=5000, band_filter_transition=5000, **kwargs)
	
		input_rate = self.input_rate
		audio_rate = self.audio_rate
		
		inherent_gain = 0.5  # fudge factor so that our output is similar level to narrow FM
		self.agc_block = analog.feedforward_agc_cc(int(.02 * demod_rate), inherent_gain)
		self.demod_block = blocks.complex_to_mag(1)
		self.resampler_block = make_resampler(demod_rate, audio_rate)
		
		# assuming below 40Hz is not of interest
		dc_blocker = grfilter.dc_blocker_ff(audio_rate // 40, False)
		
		self.connect(
			self,
			self.band_filter_block,
			self.rf_squelch_block,
			self.agc_block,
			self.demod_block,
			dc_blocker,
			self.resampler_block)
		self.connect(self.band_filter_block, self.rf_probe_block)
		self.connect_audio_output(self.resampler_block, self.resampler_block)


pluginDef_am = ModeDef('AM', label='AM', demodClass=AMDemodulator)


class FMDemodulator(SimpleAudioDemodulator):
	def __init__(self, mode, deviation=75000, demod_rate=48000, post_demod_rate=None, band_filter=None, band_filter_transition=None, tau=75e-6, **kwargs):
		SimpleAudioDemodulator.__init__(self,
			mode=mode,
			demod_rate=demod_rate,
			band_filter=band_filter,
			band_filter_transition=band_filter_transition,
			**kwargs)
		
		input_rate = self.input_rate
		audio_rate = self.audio_rate

		audio_decim = int(demod_rate / post_demod_rate)
		self.post_demod_rate = demod_rate / audio_decim

		self.demod_block = analog.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=audio_decim,
			deviation=deviation,
			audio_pass=post_demod_rate * 0.5 - 1000,
			audio_stop=post_demod_rate * 0.5,
			tau=tau,
		)
		self.do_connect()
	
	def do_connect(self):
		self.connect(
			self,
			self.band_filter_block,
			self.rf_squelch_block,
			self.demod_block)
		self.connect(self.band_filter_block, self.rf_probe_block)
		self.connect_audio_stage()
		
	def _make_resampler(self):
		return make_resampler(self.post_demod_rate, self.audio_rate)

	def connect_audio_stage(self):
		'''Override point for stereo'''
		resampler = self._make_resampler()
		self.connect(self.demod_block, resampler)
		self.connect_audio_output(resampler, resampler)


class NFMDemodulator(FMDemodulator):
	def __init__(self, audio_rate, **kwargs):
		# TODO support 2.5kHz deviation
		deviation = 5000
		transition = 1000
		FMDemodulator.__init__(self,
			demod_rate=48000,  # TODO justify this number
			audio_rate=audio_rate,
			post_demod_rate=audio_rate,
			deviation=deviation,
			band_filter=deviation + transition * 0.5,
			band_filter_transition=transition,
			**kwargs)


pluginDef_nfm = ModeDef('NFM', label='Narrow FM', demodClass=NFMDemodulator)


class WFMDemodulator(FMDemodulator):
	def __init__(self, stereo=True, audio_filter=True, **kwargs):
		self.stereo = stereo
		self.audio_filter = audio_filter
		FMDemodulator.__init__(self,
			demod_rate=240000,  # TODO justify these numbers
			post_demod_rate=120000,
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
		# TODO: Reconfiguring this way causes the flowgraph to sometimes stop (until prodded by some other change). Troubleshoot.
		#self.lock()
		#self.disconnect_all()
		#self.do_connect()
		#self.unlock()
		self.context.rebuild_me()
	
	@exported_value(ctor=bool)
	def get_audio_filter(self):
		return self.audio_filter
	
	@setter
	def set_audio_filter(self, value):
		if value == self.audio_filter: return
		self.audio_filter = bool(value)
		self.context.rebuild_me()

	def connect_audio_stage(self):
		demod_rate = self.demod_rate
		stereo_rate = self.post_demod_rate
		audio_rate = self.audio_rate
		normalizer = 2 * math.pi / stereo_rate
		pilot_tone = 19000
		pilot_low = pilot_tone * 0.9
		pilot_high = pilot_tone * 1.1

		def make_audio_filter():
			return grfilter.fir_filter_fff(
				1,  # decimation
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
		difference_real = blocks.complex_to_real(1)
		mono_channel_filter = make_audio_filter()
		resamplerL = self._make_resampler()
		resamplerR = self._make_resampler()
		mixL = blocks.add_ff(1)
		mixR = blocks.sub_ff(1)
		
		# connections
		if self.audio_filter:
			self.connect(self.demod_block, mono_channel_filter)
			mono = mono_channel_filter
		else:
			mono = self.demod_block

		if self.stereo:
			# stereo pilot tone tracker
			self.connect(
				self.demod_block,
				stereo_pilot_filter,
				stereo_pilot_pll)
			self.connect(stereo_pilot_pll, (stereo_pilot_doubler, 0))
			self.connect(stereo_pilot_pll, (stereo_pilot_doubler, 1))
			self.connect(stereo_pilot_doubler, stereo_pilot_out)
		
			# pick out stereo left-right difference channel
			self.connect(self.demod_block, (difference_channel_mixer, 0))
			self.connect(stereo_pilot_out, (difference_channel_mixer, 1))
			self.connect(difference_channel_mixer, difference_channel_filter)
		
			# recover left/right channels
			self.connect(difference_channel_filter, (mixL, 1))
			self.connect(difference_channel_filter, (mixR, 1))
			self.connect(mono, (mixL, 0), resamplerL)
			self.connect(mono, (mixR, 0), resamplerR)
			self.connect_audio_output(resamplerL, resamplerR)
		else:
			self.connect(mono, resamplerL)
			self.connect_audio_output(resamplerL, resamplerL)


pluginDef_wfm = ModeDef('WFM', label='Broadcast FM', demodClass=WFMDemodulator)


class SSBDemodulator(SimpleAudioDemodulator):
	def __init__(self, mode, audio_rate=0, **kwargs):
		if mode == 'LSB':
			lsb = True
		elif mode == 'USB':
			lsb = False
		else:
			raise ValueError('Not an SSB mode: %r' % (mode,))
		demod_rate = audio_rate
		
		SimpleAudioDemodulator.__init__(self,
			mode=mode,
			audio_rate=audio_rate,
			demod_rate=demod_rate,
			band_filter=audio_rate / 2,  # unused
			band_filter_transition=audio_rate / 2,  # unused
			**kwargs)
		input_rate = self.input_rate
		
		half_bandwidth = 2800 / 2
		if lsb:
			band_mid = -200 - half_bandwidth
		else:
			band_mid = 200 + half_bandwidth
		self.band_filter_low = band_mid - half_bandwidth
		self.band_filter_high = band_mid + half_bandwidth
		self.band_filter_width = half_bandwidth / 5
		self.sharp_filter_block = grfilter.fir_filter_ccc(
			1,
			firdes.complex_band_pass(1.0, demod_rate,
				self.band_filter_low,
				self.band_filter_high,
				self.band_filter_width,
				firdes.WIN_HAMMING))
		
		self.agc_block = analog.agc2_cc(reference=0.25)
		
		self.ssb_demod_block = blocks.complex_to_real(1)
		
		self.connect(
			self,
			self.band_filter_block,
			self.sharp_filter_block,
			self.rf_squelch_block,
			self.agc_block,
			self.ssb_demod_block)
		self.connect(self.sharp_filter_block, self.rf_probe_block)
		self.connect_audio_output(self.ssb_demod_block, self.ssb_demod_block)

	# override
	def get_band_filter_shape(self):
		return {
			'low': self.band_filter_low,
			'high': self.band_filter_high,
			'width': self.band_filter_width
		}


pluginDef_lsb = ModeDef('LSB', label='SSB (L)', demodClass=SSBDemodulator)
pluginDef_usb = ModeDef('USB', label='SSB (U)', demodClass=SSBDemodulator)
