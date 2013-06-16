#!/usr/bin/env python

from gnuradio import gr
from gnuradio import blocks
from gnuradio import blks2
from gnuradio import filter
from gnuradio.gr import firdes
import sdr
from sdr import Cell

class Receiver(gr.hier_block2, sdr.ExportedState):
	def __init__(self, name, input_rate=0, input_center_freq=0, audio_rate=0, rec_freq=0, audio_gain=1, squelch_threshold=-100, revalidate_hook=lambda: None):
		assert input_rate > 0
		assert audio_rate > 0
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(1, 1, gr.sizeof_gr_complex*1),
			gr.io_signature(1, 1, gr.sizeof_float*1),
		)
		self.input_rate = input_rate
		self.input_center_freq = input_center_freq
		self.audio_rate = audio_rate
		self.rec_freq = rec_freq
		self.audio_gain = audio_gain
		self.revalidate_hook = revalidate_hook
		
		self.audio_gain_block = gr.multiply_const_vff((self.audio_gain,))
		
		# TODO: squelch alpha needs to depend on intermediate sample rate
		self.squelch_block = gr.simple_squelch_cc(squelch_threshold, 0.0002)

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
		self.audio_gain_block.set_k((gain,))

	def state_def(self, callback):
		super(Receiver, self).state_def(callback)
		callback(Cell(self, 'band_filter_shape'))
		callback(Cell(self, 'rec_freq', writable=True, ctor=float))
		callback(Cell(self, 'audio_gain', writable=True, ctor=float))
		callback(Cell(self, 'squelch_threshold', writable=True, ctor=float))
		callback(Cell(self, 'is_valid'))
	
	def get_rec_freq(self):
		return self.rec_freq
	
	def set_rec_freq(self, rec_freq):
		self.rec_freq = rec_freq
		self._update_band_center()
		self.revalidate_hook()

class SimpleAudioReceiver(Receiver):
	def __init__(self, name='Audio Receiver', demod_rate=0, band_filter=None, band_filter_transition=None, **kwargs):
		Receiver.__init__(self, name=name, **kwargs)
		
		self.band_filter = band_filter
		self.band_filter_transition = band_filter_transition
		
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
		raise ValueError
	primes = []
	while n > 1:
		for i in xrange(2, n//2 + 1):
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
			gr.io_signature(1, 1, gr.sizeof_gr_complex*1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex*1),
		)
		
		total_decimation = input_rate // output_rate
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
				taps = gr.firdes.low_pass(
					1.0,
					stage_input_rate,
					cutoff_freq,
					transition_width,
					gr.firdes.WIN_HAMMING)
			else:
				# TODO check for collision with user filter
				user_inner = cutoff_freq-transition_width/2
				limit = next_rate/2
				taps = gr.firdes.low_pass(
					1.0,
					stage_input_rate,
					(user_inner + limit)/2,
					limit - user_inner,
					gr.firdes.WIN_HAMMING)
			
			#print 'Stage %i decimation %i rate %i taps %i' % (i, stage_decimation, stage_input_rate, len(taps))
			
			# filter block
			if first:
				stage_filter = filter.freq_xlating_fir_filter_ccc(
					stage_decimation,
					taps,
					0, # not-yet-set frequency
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
			#print 'resampling %s/%s = %s' % (output_rate, stage_input_rate, float(output_rate) / stage_input_rate)
			# TODO: combine resampler with final filter stage
			self.connect(
				prev_block,
				blks2.pfb_arb_resampler_ccf(float(output_rate) / stage_input_rate),
				self)
	
	def set_center_freq(self, freq):
		self.freq_filter_block.set_center_freq(freq)

def make_resampler(in_rate, out_rate):
	# magic numbers from gqrx
	resample_ratio = float(out_rate)/in_rate
	pfbsize = 32
	return gr.pfb_arb_resampler_fff(
		resample_ratio,
		firdes.low_pass(pfbsize, pfbsize, 0.4*resample_ratio, 0.2*resample_ratio),
		pfbsize)

class AMReceiver(SimpleAudioReceiver):
	def __init__(self, name='AM', **kwargs):
		demod_rate = 48000
		
		SimpleAudioReceiver.__init__(self, name=name, demod_rate=demod_rate, band_filter=5000, band_filter_transition=5000, **kwargs)
	
		input_rate = self.input_rate
		audio_rate = self.audio_rate
		
		# TODO: 0.1 is needed to avoid clipping; is there a better place to tweak our level vs. other receivers?
		self.agc_block = gr.feedforward_agc_cc(1024, 0.1)
		self.demod_block = gr.complex_to_mag(1)
		self.resampler_block = make_resampler(demod_rate, audio_rate)
		
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.agc_block,
			self.demod_block,
			self.resampler_block,
			self.audio_gain_block,
			self)


class FMReceiver(SimpleAudioReceiver):
	def __init__(self, name='FM', deviation=75000, demod_rate=48000, band_filter=None, band_filter_transition=None, **kwargs):
		SimpleAudioReceiver.__init__(self, name=name, demod_rate=demod_rate, band_filter=band_filter, band_filter_transition=band_filter_transition, **kwargs)
		
		input_rate = self.input_rate
		audio_rate = self.audio_rate

		decim = int(demod_rate/audio_rate)

		self.demod_block = blks2.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=decim,
			deviation=deviation,
			audio_pass=15000,
			audio_stop=16000,
			tau=75e-6,
		)
		self.resampler_block = make_resampler(demod_rate/decim, audio_rate)
		
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.demod_block,
			self.resampler_block,
			self.audio_gain_block,
			self)

class NFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Narrowband FM', demod_rate=48000, deviation=5000, band_filter=5000, band_filter_transition=1000, **kwargs)

class WFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Wideband FM', demod_rate=240000, deviation=75000, band_filter=80000, band_filter_transition=20000, **kwargs)


class SSBReceiver(SimpleAudioReceiver):
	def __init__(self, name='SSB', lsb=False, audio_rate=0, **kwargs):
		demod_rate = audio_rate
		SimpleAudioReceiver.__init__(self,
			name=name,
			audio_rate=audio_rate,
			demod_rate=demod_rate,
			band_filter=audio_rate / 2, # unused
			band_filter_transition = audio_rate / 2, # unused
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
			gr.firdes.complex_band_pass(1.0, demod_rate,
				self.band_filter_low,
				self.band_filter_high,
				self.band_filter_width,
				gr.firdes.WIN_HAMMING))
		
		self.ssb_demod_block = blocks.complex_to_real(1)
		
		self.connect(
			self,
			self.band_filter_block,
			self.sharp_filter_block,
			self.squelch_block,
			self.ssb_demod_block,
			self.audio_gain_block,
			self)

	# override
	def get_band_filter_shape(self):
		return {
			'low': self.band_filter_low,
			'high': self.band_filter_high,
			'width': self.band_filter_width
		}
