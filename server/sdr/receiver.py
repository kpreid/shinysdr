#!/usr/bin/env python

import gnuradio
from gnuradio import analog
from gnuradio import gr
from gnuradio import blocks
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio.filter import pfb

import math

from sdr.values import Cell, Range, ExportedState


class Receiver(gr.hier_block2, ExportedState):
	def __init__(self, name, input_rate=0, input_center_freq=0, audio_rate=0, rec_freq=0, audio_gain=1, squelch_threshold=-100, control_hook=None):
		assert input_rate > 0
		assert audio_rate > 0
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(2, 2, gr.sizeof_float * 1),
		)
		self.input_rate = input_rate
		self.input_center_freq = input_center_freq
		self.audio_rate = audio_rate
		self.rec_freq = rec_freq
		self.audio_gain = audio_gain
		self.control_hook = control_hook
		
		self.audio_gain_l_block = blocks.multiply_const_ff(self.audio_gain)
		self.audio_gain_r_block = blocks.multiply_const_ff(self.audio_gain)
		
		# TODO: squelch alpha needs to depend on intermediate sample rate
		self.squelch_block = analog.simple_squelch_cc(squelch_threshold, 0.0002)

	def get_is_valid(self):
		return abs(self.rec_freq - self.input_center_freq) < self.input_rate / 2

	def get_squelch_threshold(self):
		return self.squelch_block.threshold()

	def set_squelch_threshold(self, level):
		self.squelch_block.set_threshold(level)

	def get_audio_gain(self):
		return self.audio_gain
	
	def set_audio_gain(self, gain):
		self.audio_gain = gain
		self.audio_gain_l_block.set_k(gain)
		self.audio_gain_r_block.set_k(gain)
	
	def connect_audio_output(self, l_port, r_port):
		self.connect(l_port, self.audio_gain_l_block, (self, 0))
		self.connect(r_port, self.audio_gain_r_block, (self, 1))

	def state_def(self, callback):
		super(Receiver, self).state_def(callback)
		callback(Cell(self, 'band_filter_shape'))
		callback(Cell(self, 'rec_freq', writable=True, ctor=float))
		callback(Cell(self, 'audio_gain', writable=True, ctor=
			Range(0.01, 100, strict=False, logarithmic=True)))
		callback(Cell(self, 'squelch_threshold', writable=True, ctor=
			Range(-100, 100, strict=False, logarithmic=False)))
		callback(Cell(self, 'is_valid'))
	
	def get_rec_freq(self):
		return self.rec_freq
	
	def set_rec_freq(self, rec_freq):
		self.rec_freq = rec_freq
		self._update_band_center()
		self.control_hook.revalidate()


class SimpleAudioReceiver(Receiver):
	def __init__(self, name='Audio Receiver', demod_rate=0, band_filter=None, band_filter_transition=None, **kwargs):
		Receiver.__init__(self, name=name, **kwargs)
		
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

		self._update_band_center()

	def get_band_filter_shape(self):
		return {
			'low': -self.band_filter,
			'high': self.band_filter,
			'width': self.band_filter_transition
		}

	def _update_band_center(self):
		self.band_filter_block.set_center_freq(self.rec_freq - self.input_center_freq)

	def set_input_center_freq(self, value):
		self.input_center_freq = value
		self._update_band_center()


def _factorize(n):
	# I wish there was a nice standard library function for this...
	# Wrote the simplest thing I could think of
	if n <= 0:
		raise ValueError()
	primes = []
	while n > 1:
		for i in xrange(2, n // 2 + 1):
			if n % i == 0:
				primes.append(i)
				n //= i
				break
		else:
			primes.append(n)
			break
	return primes


class MultistageChannelFilter(gr.hier_block2):
	def __init__(self,
			name='Multistage Channel Filter',
			input_rate=None,
			output_rate=None,
			cutoff_freq=None,
			transition_width=None):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		total_decimation = max(1, input_rate // output_rate)
		stage_decimations = _factorize(total_decimation)
		stage_decimations.reverse()
		if len(stage_decimations) == 0:
			# We need at least one filter to do the frequency shift
			stage_decimations = [1]
		
		prev_block = self
		stage_input_rate = input_rate
		for i, stage_decimation in enumerate(stage_decimations):
			first = i == 0
			last = i == len(stage_decimations) - 1
			next_rate = stage_input_rate / stage_decimation
			
			# filter taps
			if last:
				taps = firdes.low_pass(
					1.0,
					stage_input_rate,
					cutoff_freq,
					transition_width,
					firdes.WIN_HAMMING)
			else:
				# TODO check for collision with user filter
				user_inner = cutoff_freq - transition_width / 2
				limit = next_rate / 2
				taps = firdes.low_pass(
					1.0,
					stage_input_rate,
					(user_inner + limit) / 2,
					limit - user_inner,
					firdes.WIN_HAMMING)
			
			#print 'Stage %i decimation %i rate %i taps %i' % (i, stage_decimation, stage_input_rate, len(taps))
			
			# filter block
			if first:
				stage_filter = filter.freq_xlating_fir_filter_ccc(
					stage_decimation,
					taps,
					0,  # not-yet-set frequency
					stage_input_rate)
				self.freq_filter_block = stage_filter
			else:
				stage_filter = filter.fir_filter_ccc(stage_decimation, taps)
			
			self.connect(prev_block, stage_filter)
			prev_block = stage_filter
			stage_input_rate = next_rate
		
		# final connection and resampling
		if stage_input_rate == output_rate:
			# exact multiple, no fractional resampling needed
			#print 'direct connect %s/%s' % (output_rate, stage_input_rate)
			self.connect(prev_block, self)
		else:
			# TODO: combine resampler with final filter stage
			# TODO: cache filter computation as optfir is used and takes a noticeable time
			self.connect(
				prev_block,
				pfb.arb_resampler_ccf(float(output_rate) / stage_input_rate),
				self)
			#print 'resampling %s/%s = %s' % (output_rate, stage_input_rate, float(output_rate) / stage_input_rate)
	
	def set_center_freq(self, freq):
		self.freq_filter_block.set_center_freq(freq)


def make_resampler(in_rate, out_rate):
	# magic numbers from gqrx
	resample_ratio = float(out_rate) / in_rate
	pfbsize = 32
	return pfb.arb_resampler_fff(
		resample_ratio,
		firdes.low_pass(pfbsize, pfbsize, 0.4 * resample_ratio, 0.2 * resample_ratio),
		pfbsize)


class IQReceiver(SimpleAudioReceiver):
	def __init__(self, name='I/Q', audio_rate=None, **kwargs):
		SimpleAudioReceiver.__init__(self,
			name=name,
			audio_rate=audio_rate,
			demod_rate=audio_rate,
			band_filter=audio_rate * 0.5,
			band_filter_transition=audio_rate * 0.2,
			**kwargs)
		
		self.split_block = blocks.complex_to_float(1)
		
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.split_block)
		self.connect_audio_output((self.split_block, 0), (self.split_block, 1))


class AMReceiver(SimpleAudioReceiver):
	def __init__(self, name='AM', **kwargs):
		demod_rate = 48000
		
		SimpleAudioReceiver.__init__(self, name=name, demod_rate=demod_rate, band_filter=5000, band_filter_transition=5000, **kwargs)
	
		input_rate = self.input_rate
		audio_rate = self.audio_rate
		
		inherent_gain = 0.5  # fudge factor so that our output is similar level to narrow FM
		self.agc_block = analog.feedforward_agc_cc(1024, inherent_gain)
		self.demod_block = blocks.complex_to_mag(1)
		self.resampler_block = make_resampler(demod_rate, audio_rate)
		
		# assuming below 40Hz is not of interest
		dc_blocker = filter.dc_blocker_ff(audio_rate // 40, False)
		
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.agc_block,
			self.demod_block,
			dc_blocker,
			self.resampler_block)
		self.connect_audio_output(self.resampler_block, self.resampler_block)


class FMReceiver(SimpleAudioReceiver):
	def __init__(self, name='FM', deviation=75000, demod_rate=48000, post_demod_rate=None, band_filter=None, band_filter_transition=None, **kwargs):
		SimpleAudioReceiver.__init__(self, name=name, demod_rate=demod_rate, band_filter=band_filter, band_filter_transition=band_filter_transition, **kwargs)
		
		input_rate = self.input_rate
		audio_rate = self.audio_rate

		audio_decim = int(demod_rate / post_demod_rate)
		self.post_demod_rate = demod_rate / audio_decim

		self.demod_block = analog.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=audio_decim,
			deviation=deviation,
			audio_pass=15000,
			audio_stop=16000,
			tau=75e-6,
		)
		self.do_connect()
	
	def do_connect(self):
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.demod_block)
		self.connect_audio_stage()
		
	def _make_resampler(self):
		return make_resampler(self.post_demod_rate, self.audio_rate)

	def connect_audio_stage(self):
		'''Override point for stereo'''
		resampler = self._make_resampler()
		self.connect(self.demod_block, resampler)
		self.connect_audio_output(resampler, resampler)


class NFMReceiver(FMReceiver):
	def __init__(self, audio_rate, **kwargs):
		FMReceiver.__init__(self, name='Narrowband FM', demod_rate=48000, audio_rate=audio_rate, post_demod_rate=audio_rate, deviation=5000, band_filter=6500, band_filter_transition=1000, **kwargs)

class WFMReceiver(FMReceiver):
	def __init__(self, stereo=True, audio_filter=True, **kwargs):
		self.stereo = stereo
		self.audio_filter = audio_filter
		FMReceiver.__init__(self, name='Wideband FM', demod_rate=240000, post_demod_rate=120000, deviation=75000, band_filter=80000, band_filter_transition=20000, **kwargs)

	def state_def(self, callback):
		super(WFMReceiver, self).state_def(callback)
		callback(Cell(self, 'stereo', writable=True, ctor=bool))
		callback(Cell(self, 'audio_filter', writable=True, ctor=bool))
	
	def get_stereo(self):
		return self.stereo
	def set_stereo(self, value):
		if value == self.stereo: return
		self.stereo = bool(value)
		# TODO: Doing it this way causes 'input port 0 out of range for Multistage Channel Filter' which may be a gnuradio bug wrt disconnect_all and hier blocks (previously discussed Feb 2013).
		#self.lock()
		#self.disconnect_all()
		#self.do_connect()
		#self.unlock()
		self.control_hook.rebuild_me()
	
	def get_audio_filter(self):
		return self.audio_filter
	def set_audio_filter(self, value):
		if value == self.audio_filter: return
		self.audio_filter = bool(value)
		self.control_hook.rebuild_me()

	def connect_audio_stage(self):
		demod_rate = self.demod_rate
		stereo_rate = self.post_demod_rate
		audio_rate = self.audio_rate
		normalizer = 2 * math.pi / stereo_rate
		pilot_tone = 19000
		pilot_low = pilot_tone * 0.9
		pilot_high = pilot_tone * 1.1

		def make_audio_filter():
			return filter.fir_filter_fff(
				1,  # decimation
				firdes.low_pass(
					1.0,
					stereo_rate,
					15000,
					5000,
					firdes.WIN_HAMMING))

		stereo_pilot_filter = filter.fir_filter_fcc(
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
		

class SSBReceiver(SimpleAudioReceiver):
	def __init__(self, name='SSB', lsb=False, audio_rate=0, **kwargs):
		demod_rate = audio_rate
		SimpleAudioReceiver.__init__(self,
			name=name,
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
		self.sharp_filter_block = filter.fir_filter_ccc(
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
			self.squelch_block,
			self.agc_block,
			self.ssb_demod_block)
		self.connect_audio_output(self.ssb_demod_block, self.ssb_demod_block)

	# override
	def get_band_filter_shape(self):
		return {
			'low': self.band_filter_low,
			'high': self.band_filter_high,
			'width': self.band_filter_width
		}
