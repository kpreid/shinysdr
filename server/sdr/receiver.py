#!/usr/bin/env python

from gnuradio import audio
from gnuradio import blks2
from gnuradio import blocks
from gnuradio import eng_notation
from gnuradio import filter
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from gnuradio.gr import firdes
from optparse import OptionParser
import osmosdr

class Receiver(gr.hier_block2):
	def __init__(self, name, input_rate=0, input_center_freq=0, audio_rate=0, rec_freq=0, audio_gain=1, squelch_threshold=-100):
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
		
		# TODO: squelch alpha needs to depend on intermediate sample rate
		self.squelch_block = gr.simple_squelch_cc(squelch_threshold, 0.05)

	def get_squelch_threshold(self):
		return self.squelch_block.threshold()

	def set_squelch_threshold(self, level):
		self.squelch_block.set_threshold(level)

	def set_audio_gain(self, k):
		self.audio_gain_block.set_k((k,))

class FMReceiver(Receiver):
	def __init__(self, name='FM', deviation=75000, **kwargs):
		Receiver.__init__(self, name=name, **kwargs)

		input_rate = self.input_rate
		audio_rate = self.audio_rate
		band_filter = self.band_filter = deviation
		demod_rate = 128000
		# TODO: Choose demod rate based on matching input and audio rates and the band_filter
		
		if input_rate % demod_rate != 0:
			raise ValueError, 'Input rate %s is not a multiple of demodulator rate %s' % (self.input_rate, demod_rate)
		if demod_rate % audio_rate != 0:
			raise ValueError, 'Demodulator rate %s is not a multiple of audio rate %s' % (demod_rate, audio_rate)

		##################################################
		# Blocks
		##################################################
		self.band_filter_block = filter.freq_xlating_fir_filter_ccc(int(input_rate/demod_rate), (gr.firdes.low_pass(1.0, input_rate, band_filter, 8*100e3, gr.firdes.WIN_HAMMING)), 0, input_rate)
		self._update_band_center()
		
		self.blks2_fm_demod_cf_0 = blks2.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=int(demod_rate/audio_rate),
			deviation=deviation,
			audio_pass=15000,
			audio_stop=16000,
			tau=75e-6,
		)
		
		# note: fm_demod has a gain parameter, but it is part of the filter, and cannot be adjusted
		self.audio_gain_block = gr.multiply_const_vff((self.audio_gain,))
		
		##################################################
		# Connections
		##################################################
		self.connect(
			self,
			self.band_filter_block,
			self.squelch_block,
			self.blks2_fm_demod_cf_0,
			self.audio_gain_block,
			self)

	def _update_band_center(self):
		self.band_filter_block.set_center_freq(self.rec_freq - self.input_center_freq)

	def set_input_center_freq(self, value):
		self.input_center_freq = value
		self._update_band_center()

	def get_band_filter(self):
		return self.band_filter

	def get_rec_freq(self):
		return self.rec_freq

	def set_rec_freq(self, rec_freq):
		self.rec_freq = rec_freq
		self._update_band_center()

	def get_audio_gain(self):
		return self.audio_gain_block.k()[0]

	def set_audio_gain(self, k):
		self.audio_gain_block.set_k((k,))

class NFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Narrowband FM', deviation=5000, **kwargs)

class WFMReceiver(FMReceiver):
	def __init__(self, **kwargs):
		FMReceiver.__init__(self, name='Wideband FM', deviation=75000, **kwargs)
