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

class wfm(gr.top_block):

	def __init__(self):
		gr.top_block.__init__(self, "Wfm")

		##################################################
		# Variables
		##################################################
		self.input_rate = input_rate = 3200000
		self.demod_rate = demod_rate =  128000
		self.audio_rate = audio_rate =   32000
		self.rec_freq = rec_freq = 97.7e6
		self.hw_freq = hw_freq = 98e6
		self.fftsize = fftsize = 2048
		self.band_filter = band_filter = 75000

		# TODO: remove this debug output
		print "Band filter: ", band_filter
		print "Input decimation: ", input_rate/demod_rate
		print "Audio decimation: ", demod_rate/audio_rate

		##################################################
		# Blocks
		##################################################
		self.osmosdr_source_c_0_0 = osmosdr.source_c( args="nchan=" + str(1) + " " + "rtl=0" )
		self.osmosdr_source_c_0_0.set_sample_rate(input_rate)
		self.osmosdr_source_c_0_0.set_center_freq(hw_freq, 0)
		self.osmosdr_source_c_0_0.set_freq_corr(0, 0)
		self.osmosdr_source_c_0_0.set_iq_balance_mode(0, 0)
		self.osmosdr_source_c_0_0.set_gain_mode(1, 0)
		self.osmosdr_source_c_0_0.set_gain(10, 0)
		self.osmosdr_source_c_0_0.set_if_gain(24, 0)
		self.osmosdr_source_c_0_0.set_bb_gain(20, 0)
		self.osmosdr_source_c_0_0.set_antenna("", 0)
		self.osmosdr_source_c_0_0.set_bandwidth(0, 0)
		
		self.spectrum_probe = blocks.probe_signal_vf(fftsize)
		self.spectrum_fft = blks2.logpwrfft_c(
			sample_rate=input_rate,
			fft_size=fftsize,
			ref_scale=2,
			frame_rate=30,
			avg_alpha=1.0,
			average=False,
		)
		
		self.freq_xlating_fir_filter_xxx_0 = filter.freq_xlating_fir_filter_ccc(int(input_rate/demod_rate), (gr.firdes.low_pass(1.0, input_rate, band_filter, 8*100e3, gr.firdes.WIN_HAMMING)), 0, input_rate)
		self._update_band_center()
		
		self.blks2_fm_demod_cf_0 = blks2.fm_demod_cf(
			channel_rate=demod_rate,
			audio_decim=int(demod_rate/audio_rate),
			deviation=75000,
			audio_pass=15000,
			audio_stop=16000,
			gain=0.5,
			tau=75e-6,
		)
		
		self.audio_gain_block = gr.multiply_const_vff((0.5,))
		self.audio_sink_0 = audio.sink(audio_rate, "", False)

		##################################################
		# Connections
		##################################################
		self.connect((self.osmosdr_source_c_0_0, 0), (self.freq_xlating_fir_filter_xxx_0, 0))
		self.connect((self.freq_xlating_fir_filter_xxx_0, 0), (self.blks2_fm_demod_cf_0, 0))
		self.connect((self.blks2_fm_demod_cf_0, 0), (self.audio_gain_block, 0))
		self.connect((self.audio_gain_block, 0), (self.audio_sink_0, 0))
		self.connect((self.osmosdr_source_c_0_0, 0), (self.spectrum_fft, 0))
		self.connect((self.spectrum_fft, 0), (self.spectrum_probe, 0))

	def _update_band_center(self):
		self.freq_xlating_fir_filter_xxx_0.set_center_freq(self.rec_freq - self.hw_freq)

	def get_input_rate(self):
		return self.input_rate

	# TODO: this looks unsafe (doesn't adjust decimation), fix or toss
	#def set_input_rate(self, input_rate):
	#	self.input_rate = input_rate
	#	self.osmosdr_source_c_0_0.set_sample_rate(self.input_rate)
	#	self.freq_xlating_fir_filter_xxx_0.set_taps((gr.firdes.low_pass(1.0, self.input_rate, self.band_filter, 8*100e3, gr.firdes.WIN_HAMMING)))

	def get_demod_rate(self):
		return self.demod_rate

	def set_demod_rate(self, demod_rate):
		self.demod_rate = demod_rate
		self.set_band_filter(self.demod_rate*7.0/16.0)

	def get_audio_rate(self):
		return self.audio_rate

	def set_audio_rate(self, audio_rate):
		self.audio_rate = audio_rate

	def get_rec_freq(self):
		return self.rec_freq

	def set_rec_freq(self, rec_freq):
		self.rec_freq = rec_freq
		self._update_band_center()

	def get_hw_freq(self):
		return self.hw_freq

	def set_hw_freq(self, hw_freq):
		self.hw_freq = hw_freq
		self.osmosdr_source_c_0_0.set_center_freq(self.hw_freq, 0)
		self._update_band_center()

	def get_band_filter(self):
		return self.band_filter

	def set_band_filter(self, band_filter):
		self.band_filter = band_filter
		self.freq_xlating_fir_filter_xxx_0.set_taps((gr.firdes.low_pass(1.0, self.input_rate, self.band_filter, 8*100e3, gr.firdes.WIN_HAMMING)))

	def get_fftsize(self):
		return self.fftsize

	def set_fftsize(self, fftsize):
		self.fftsize = fftsize
		# TODO er, missing some updaters? GRC didn't generate any

	def get_audio_gain(self):
		return self.audio_gain_block.k()[0]

	def set_audio_gain(self, k):
		self.audio_gain_block.set_k((k,))

	def get_spectrum_fft(self):
		return self.spectrum_probe.level()


if __name__ == '__main__':
	parser = OptionParser(option_class=eng_option, usage="%prog: [options]")
	(options, args) = parser.parse_args()
	tb = wfm()
	tb.start()
	raw_input('Press Enter to quit: ')
	tb.stop()

