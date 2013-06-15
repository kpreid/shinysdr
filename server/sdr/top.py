#!/usr/bin/env python

from gnuradio import audio
from gnuradio import blks2
from gnuradio import blocks
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.gr import firdes
from optparse import OptionParser
import osmosdr
import sdr
from sdr import Cell
import sdr.receiver
import sdr.receivers.vor

def SpectrumTypeStub(x): return x
def SubBlockStub(x): raise 'Not yet supported'

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
		self.fftsize = fftsize = 4096
		self.hw_correction_ppm = 0

		##################################################
		# Blocks
		##################################################
		self.receiver = None
		self.last_receiver_is_valid = False
		
		self.audio_sink = None
		
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
		self.lock()
		self.disconnect_all()

		self.connect(self.osmosdr_source_block, self.spectrum_fft, self.spectrum_probe)

		# workaround problem with restarting audio sinks on Mac OS X
		self.audio_sink = audio.sink(self.audio_rate, "", False)

		self.last_receiver_is_valid = self.receiver.get_is_valid()
		if self.receiver is not None and self.last_receiver_is_valid and self.audio_sink is not None:
			self.connect(self.osmosdr_source_block, self.receiver, self.audio_sink)
		
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
		callback(Cell(self, 'hw_freq', writable=True, ctor=float))
		callback(Cell(self, 'hw_correction_ppm', writable=True, ctor=float))
		#callback(Cell(self, 'fftsize', True, ctor=int))
		callback(Cell(self, 'spectrum_fft', ctor=SpectrumTypeStub))
		# TODO: receiver_state should be serialized, yes, but not exported -- but also lose this distinction
		callback(Cell(self, 'receiver_state', writable=True, ctor=SubBlockStub))
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
		elif kind == 'USB' or kind == 'LSB':
			clas = sdr.receiver.SSBReceiver
		elif kind == 'VOR':
			clas = sdr.receivers.vor.VOR
		else:
			raise ValueError, 'Unknown mode: ' + kind
		self._mode = kind
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
			input_center_freq=self.hw_freq,
			audio_rate=self.audio_rate,
			revalidate_hook=lambda: self._update_receiver_validity(),
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
		actual_freq = self._compute_frequency(hw_freq)
		# TODO: This limitation is in librtlsdr. If we support other gr-osmosdr devices, change it.
		maxint32 = 2**32 - 1
		if actual_freq < 0 or actual_freq > maxint32:
			raise ValueError, 'Frequency must be between 0 and ' + str(maxint32) + ' Hz'
		self.hw_freq = hw_freq
		self._update_frequency()
		self._update_receiver_validity()

	def get_hw_correction_ppm(self):
		return self.hw_correction_ppm
	
	def set_hw_correction_ppm(self, value):
		self.hw_correction_ppm = value
		# Not using the hardware feature because I only get garbled output from it
		#self.osmosdr_source_block.set_freq_corr(value, 0)
		self._update_frequency()
	
	def _compute_frequency(self, effective_freq):
		if effective_freq == 0.0:
			# Quirk: Tuning to 3686.6-3730 MHz (on some tuner HW) causes operation effectively at 0Hz.
			# Original report: <http://www.reddit.com/r/RTLSDR/comments/12d2wc/a_very_surprising_discovery/>
			return 3700e6
		else:
			return effective_freq * (1 - 1e-6 * self.hw_correction_ppm)
	
	def _update_frequency(self):
		self.osmosdr_source_block.set_center_freq(self._compute_frequency(self.hw_freq), 0)
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

