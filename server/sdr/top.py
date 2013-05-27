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
import sdr
import sdr.receiver

class Top(gr.top_block, sdr.ExportedState):

	def __init__(self):
		gr.top_block.__init__(self, "SDR top block")
		self._running = False

		##################################################
		# Variables
		##################################################
		self.input_rate = input_rate = 3200000
		self.audio_rate = audio_rate =   32000
		self.hw_freq = hw_freq = 98e6
		self.fftsize = fftsize = 2048
		self.hw_correction_ppm = 0

		##################################################
		# Blocks
		##################################################
		self.receiver = None
		self.audio_sink_0 = None
		
		self.osmosdr_source_block = osmosdr.source_c( args="nchan=" + str(1) + " " + "rtl=0" )
		self.osmosdr_source_block.set_sample_rate(input_rate)
		self.osmosdr_source_block.set_center_freq(hw_freq, 0)
		self.osmosdr_source_block.set_freq_corr(0, 0)
		self.osmosdr_source_block.set_iq_balance_mode(0, 0)
		self.osmosdr_source_block.set_gain_mode(1, 0)
		self.osmosdr_source_block.set_gain(10, 0)
		self.osmosdr_source_block.set_if_gain(24, 0)
		self.osmosdr_source_block.set_bb_gain(20, 0)
		self.osmosdr_source_block.set_antenna("", 0)
		self.osmosdr_source_block.set_bandwidth(0, 0)
		
		self.spectrum_probe = blocks.probe_signal_vf(fftsize)
		self.spectrum_fft = blks2.logpwrfft_c(
			sample_rate=input_rate,
			fft_size=fftsize,
			ref_scale=2,
			frame_rate=30,
			avg_alpha=1.0,
			average=False,
		)
		
		self._mode = None
		self.set_mode('WFM') # triggers connect

	def _do_connect(self):
		self.disconnect_all()

		# workaround problem with restarting audio sinks on Mac OS X
		self.audio_sink_0 = audio.sink(self.audio_rate, "", False)

		self.connect(self.osmosdr_source_block, self.receiver, self.audio_sink_0)
		self.connect(self.osmosdr_source_block, self.spectrum_fft, self.spectrum_probe)

	def state_keys(self, callback):
		super(Top, self).state_keys(callback)
		callback('running')
		callback('mode')
		#callback('input_rate')
		#callback('audio_rate')
		callback('hw_freq')
		callback('hw_correction_ppm')
		#callback('fftsize')
		#callback('spectrum_fft')
		callback('receiver_state')
	def get_receiver_state(self):
		return self.receiver.state_to_json()
	def set_receiver_state(self, value):
		self.receiver.state_from_json(value)

	def start(self):
		self._do_connect() # audio sink workaround
		super(Top, self).start()

	def get_running(self):
		return self._running
	def set_running(self, value):
		if value != self._running:
			self._running = value
			if value:
				self.start()
			else:
				self.stop()
				self.wait()

	def get_mode(self):
		return self._mode

	def set_mode(self, kind):
		if kind == self._mode:
			return
		if kind == 'NFM':
			clas = sdr.receiver.NFMReceiver
		elif kind == 'WFM':
			clas = sdr.receiver.WFMReceiver
		elif kind == 'AM':
			clas = sdr.receiver.AMReceiver
		else:
			raise ValueError, 'Unknown mode: ' + kind
		self._mode = kind
		self.lock()
		if self.receiver is not None:
			self.disconnect(self.receiver)
			options = {
				'audio_gain': self.receiver.get_audio_gain(),
				'rec_freq': self.receiver.get_rec_freq(),
				'squelch_threshold': self.receiver.get_squelch_threshold(),
			}
		else:
			options = {
				'audio_gain': 0.25,
				'rec_freq': 97.7e6,
				'squelch_threshold': -100
			}
		self.receiver = clas(
			input_rate=self.input_rate,
			input_center_freq=self.hw_freq,
			audio_rate=self.audio_rate,
			**options
		)
		self._do_connect()
		self.unlock()

	def get_input_rate(self):
		return self.input_rate

	# TODO: this looks unsafe (doesn't adjust decimation), fix or toss
	#def set_input_rate(self, input_rate):
	#	self.input_rate = input_rate
	#	self.osmosdr_source_block.set_sample_rate(self.input_rate)
	#	self.freq_xlating_fir_filter_xxx_0.set_taps((gr.firdes.low_pass(1.0, self.input_rate, self.band_filter, 8*100e3, gr.firdes.WIN_HAMMING)))

	def get_audio_rate(self):
		return self.audio_rate

	def get_hw_freq(self):
		return self.hw_freq

	def set_hw_freq(self, hw_freq):
		self.hw_freq = hw_freq
		self._update_frequency()

	def get_hw_correction_ppm(self):
		return self.hw_correction_ppm
	
	def set_hw_correction_ppm(self, value):
		self.hw_correction_ppm = value
		# Not using the hardware feature because I only get garbled output from it
		#self.osmosdr_source_block.set_freq_corr(value, 0)
		self._update_frequency()
		
	def _update_frequency(self):
		adj_freq = self.hw_freq * (1 + 1e-6 * self.hw_correction_ppm)
		self.osmosdr_source_block.set_center_freq(adj_freq, 0)
		self.receiver.set_input_center_freq(self.hw_freq)

	def get_fftsize(self):
		return self.fftsize

	def set_fftsize(self, fftsize):
		self.fftsize = fftsize
		# TODO er, missing some updaters? GRC didn't generate any

	def get_spectrum_fft(self):
		return (self.hw_freq, self.spectrum_probe.level())


if __name__ == '__main__':
	parser = OptionParser(option_class=eng_option, usage="%prog: [options]")
	(options, args) = parser.parse_args()
	tb = top()
	tb.start()
	raw_input('Press Enter to quit: ')
	tb.stop()

