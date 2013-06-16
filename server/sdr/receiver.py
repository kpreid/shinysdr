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
		
		if input_rate % demod_rate != 0:
			raise ValueError, 'Input rate %s is not a multiple of demodulator rate %s' % (self.input_rate, demod_rate)
		if demod_rate % audio_rate != 0:
			raise ValueError, 'Demodulator rate %s is not a multiple of audio rate %s' % (demod_rate, audio_rate)

		self.band_filter_block = filter.freq_xlating_fir_filter_ccc(
			int(input_rate/demod_rate),
			gr.firdes.low_pass(1.0, input_rate, band_filter, band_filter_transition, gr.firdes.WIN_HAMMING),
			0,
			input_rate)
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
		demod_rate = 64000
		
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
	def __init__(self, name='FM', deviation=75000, band_filter=None, band_filter_transition=None, **kwargs):
		# TODO: Choose demod rate principledly based on matching input and audio rates and the band_filter
		if band_filter < 10000:
			demod_rate = 64000
		else:
			demod_rate = 128000
		
		SimpleAudioReceiver.__init__(self, name=name, demod_rate=demod_rate, band_filter=band_filter, band_filter_transition=band_filter_transition, **kwargs)
		
		input_rate = self.input_rate
		audio_rate = self.audio_rate

		self.demod_block = blks2.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=int(demod_rate/audio_rate),
			deviation=deviation,
			audio_pass=15000,
			audio_stop=16000,
			tau=75e-6,
		)
		
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.demod_block,
			self.audio_gain_block,
			self)

class NFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Narrowband FM', deviation=5000, band_filter=5000, band_filter_transition=1000, **kwargs)

class WFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Wideband FM', deviation=75000, band_filter=80000, band_filter_transition=20000, **kwargs)


class SSBReceiver(SimpleAudioReceiver):
	def __init__(self, name='SSB', lsb=False, audio_rate=0, **kwargs):
		demod_rate = audio_rate
		SimpleAudioReceiver.__init__(self,
			name=name,
			audio_rate=audio_rate,
			demod_rate=demod_rate,
			band_filter=audio_rate / 2,
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
