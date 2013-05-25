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
	def __init__(self, name, input_rate=0, input_center_freq=0, audio_rate=0, rec_freq=0, audio_gain=1):
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


class WFMReceiver(Receiver):
	def __init__(self, **kwargs):
		Receiver.__init__(self, 'Wideband FM', **kwargs)

		input_rate = self.input_rate
		audio_rate = self.audio_rate
		self.band_filter = band_filter = 75000
		demod_rate = 128000
		
		# TODO: Resample/twiddle rate as necessary.
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
			deviation=75000,
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

