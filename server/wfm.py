#!/usr/bin/env python

from gnuradio import audio
from gnuradio import blks2
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
		self.samp_rate = samp_rate = 3200000
		self.band_rate = band_rate = 128e3
		self.audio_rate = audio_rate = 32000
		self.variable_0 = variable_0 = (samp_rate/band_rate, band_rate/audio_rate)
		self.rec_freq = rec_freq = 97.7e6
		self.hw_freq = hw_freq = 98e6
		self.band_filter = band_filter = band_rate*7.0/16.0

		##################################################
		# Blocks
		##################################################
		self.osmosdr_source_c_0_0 = osmosdr.source_c( args="nchan=" + str(1) + " " + "rtl=0" )
		self.osmosdr_source_c_0_0.set_sample_rate(samp_rate)
		self.osmosdr_source_c_0_0.set_center_freq(hw_freq, 0)
		self.osmosdr_source_c_0_0.set_freq_corr(0, 0)
		self.osmosdr_source_c_0_0.set_iq_balance_mode(0, 0)
		self.osmosdr_source_c_0_0.set_gain_mode(1, 0)
		self.osmosdr_source_c_0_0.set_gain(10, 0)
		self.osmosdr_source_c_0_0.set_if_gain(24, 0)
		self.osmosdr_source_c_0_0.set_bb_gain(20, 0)
		self.osmosdr_source_c_0_0.set_antenna("", 0)
		self.osmosdr_source_c_0_0.set_bandwidth(0, 0)
		  
		self.freq_xlating_fir_filter_xxx_0 = filter.freq_xlating_fir_filter_ccc(int(samp_rate/band_rate), (gr.firdes.low_pass(1.0, samp_rate, band_filter, 8*100e3, gr.firdes.WIN_HAMMING)), (rec_freq-hw_freq), samp_rate)
		self.blks2_fm_demod_cf_0 = blks2.fm_demod_cf(
			channel_rate=band_rate,
			audio_decim=int(band_rate/audio_rate),
			deviation=50000,
			audio_pass=15000,
			audio_stop=16000,
			gain=0.5,
			tau=75e-6,
		)
		self.audio_sink_0 = audio.sink(audio_rate, "", False)

		##################################################
		# Connections
		##################################################
		self.connect((self.osmosdr_source_c_0_0, 0), (self.freq_xlating_fir_filter_xxx_0, 0))
		self.connect((self.freq_xlating_fir_filter_xxx_0, 0), (self.blks2_fm_demod_cf_0, 0))
		self.connect((self.blks2_fm_demod_cf_0, 0), (self.audio_sink_0, 0))


	def get_samp_rate(self):
		return self.samp_rate

	def set_samp_rate(self, samp_rate):
		self.samp_rate = samp_rate
		self.osmosdr_source_c_0_0.set_sample_rate(self.samp_rate)
		self.set_variable_0((self.samp_rate/self.band_rate, self.band_rate/self.audio_rate))
		self.freq_xlating_fir_filter_xxx_0.set_taps((gr.firdes.low_pass(1.0, self.samp_rate, self.band_filter, 8*100e3, gr.firdes.WIN_HAMMING)))

	def get_band_rate(self):
		return self.band_rate

	def set_band_rate(self, band_rate):
		self.band_rate = band_rate
		self.set_variable_0((self.samp_rate/self.band_rate, self.band_rate/self.audio_rate))
		self.set_band_filter(self.band_rate*7.0/16.0)

	def get_audio_rate(self):
		return self.audio_rate

	def set_audio_rate(self, audio_rate):
		self.audio_rate = audio_rate
		self.set_variable_0((self.samp_rate/self.band_rate, self.band_rate/self.audio_rate))

	def get_variable_0(self):
		return self.variable_0

	def set_variable_0(self, variable_0):
		self.variable_0 = variable_0

	def get_rec_freq(self):
		return self.rec_freq

	def set_rec_freq(self, rec_freq):
		self.rec_freq = rec_freq
		self.freq_xlating_fir_filter_xxx_0.set_center_freq((self.rec_freq-self.hw_freq))

	def get_hw_freq(self):
		return self.hw_freq

	def set_hw_freq(self, hw_freq):
		self.hw_freq = hw_freq
		self.osmosdr_source_c_0_0.set_center_freq(self.hw_freq, 0)
		self.freq_xlating_fir_filter_xxx_0.set_center_freq((self.rec_freq-self.hw_freq))

	def get_band_filter(self):
		return self.band_filter

	def set_band_filter(self, band_filter):
		self.band_filter = band_filter
		self.freq_xlating_fir_filter_xxx_0.set_taps((gr.firdes.low_pass(1.0, self.samp_rate, self.band_filter, 8*100e3, gr.firdes.WIN_HAMMING)))

if __name__ == '__main__':
	parser = OptionParser(option_class=eng_option, usage="%prog: [options]")
	(options, args) = parser.parse_args()
	tb = wfm()
	tb.start()
	raw_input('Press Enter to quit: ')
	tb.stop()

