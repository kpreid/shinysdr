#!/usr/bin/env python

import gnuradio
from gnuradio import audio
from gnuradio import blks2
from gnuradio import blocks
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.gr import firdes
from optparse import OptionParser
import sdr
from sdr import Cell, BlockCell
import sdr.source
import sdr.receiver
import sdr.receivers.vor

class SpectrumTypeStub: pass

class Top(gr.top_block, sdr.ExportedState):

	def __init__(self):
		gr.top_block.__init__(self, "SDR top block")
		self._running = False
		
		self._make_source()
		self.input_rate = input_rate = self.source.get_sample_rate()
		
		##################################################
		# Variables
		##################################################
		self.audio_rate = audio_rate =   32000
		self.spectrum_resolution = 4096
		self.spectrum_rate = 30

		##################################################
		# Blocks
		##################################################
		self.receiver = None
		self.last_receiver_is_valid = False
		
		self.audio_sink = None
		
		self._make_spectrum()
		
		self._mode = None
		self.set_mode('AM') # triggers connect

	def _do_connect(self):
		self.lock()
		self.disconnect_all()

		# workaround problem with restarting audio sinks on Mac OS X
		if self.source.needs_restart():
			self._make_source()
		self.audio_sink = audio.sink(self.audio_rate, "", False)

		self.connect(self.source, self.spectrum_fft, self.spectrum_probe)

		self.last_receiver_is_valid = self.receiver.get_is_valid()
		if self.receiver is not None and self.last_receiver_is_valid and self.audio_sink is not None:
			self.connect(self.source, self.receiver, self.audio_sink)
		
		self.unlock()

	def _update_receiver_validity(self):
		if self.receiver.get_is_valid() != self.last_receiver_is_valid:
			self._do_connect()

	def state_def(self, callback):
		super(Top, self).state_def(callback)
		callback(Cell(self, 'running', writable=True, ctor=bool))
		callback(Cell(self, 'mode', writable=True, ctor=str))
		callback(Cell(self, 'input_rate', ctor=int))
		callback(Cell(self, 'audio_rate', ctor=int))
		callback(Cell(self, 'spectrum_resolution', True, ctor=int))
		callback(Cell(self, 'spectrum_rate', True, ctor=float))
		callback(Cell(self, 'spectrum_fft', ctor=SpectrumTypeStub))
		callback(BlockCell(self, 'source'))
		callback(BlockCell(self, 'receiver'))

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
		elif kind == 'USB' or kind == 'LSB':
			clas = sdr.receiver.SSBReceiver
		elif kind == 'VOR':
			clas = sdr.receivers.vor.VOR
		else:
			raise ValueError, 'Unknown mode: ' + kind
		try:
			self.lock()
			if self.receiver is not None:
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
			if kind == 'LSB':
				options['lsb'] = True
			self.receiver = clas(
				input_rate=self.input_rate,
				input_center_freq=self.source.get_freq(),
				audio_rate=self.audio_rate,
				revalidate_hook=lambda: self._update_receiver_validity(),
				**options
			)
			self._do_connect()
			self._mode = kind
		finally:
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

	def _make_source(self):
		def tune_hook():
			self._update_receiver_validity()
			self.receiver.set_input_center_freq(self.source.get_freq())
		self.source = sdr.source.OsmoSDRSource(tune_hook=tune_hook)
		#self.source = sdr.source.AudioSource(tune_hook=tune_hook, quadrature_as_stereo=True)

	def _make_spectrum(self):
		self.spectrum_probe = blocks.probe_signal_vf(self.spectrum_resolution)
		self.spectrum_fft = blks2.logpwrfft_c(
			sample_rate=self.input_rate,
			fft_size=self.spectrum_resolution,
			ref_scale=2,
			frame_rate=self.spectrum_rate,
			avg_alpha=1.0,
			average=False,
		)
	
	def get_spectrum_resolution(self):
		return self.spectrum_resolution

	def set_spectrum_resolution(self, spectrum_resolution):
		self.spectrum_resolution = spectrum_resolution
		self._make_spectrum()
		self._do_connect()

	def get_spectrum_rate(self):
		return self.spectrum_rate

	def set_spectrum_rate(self, value):
		self.spectrum_fft.set_vec_rate(value)

	def get_spectrum_fft(self):
		return (self.source.get_freq(), self.spectrum_probe.level())


if __name__ == '__main__':
	parser = OptionParser(option_class=eng_option, usage="%prog: [options]")
	(options, args) = parser.parse_args()
	tb = top()
	tb.start()
	raw_input('Press Enter to quit: ')
	tb.stop()

