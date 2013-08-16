from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog

from sdr.values import Cell, ExportedState
from sdr.receiver import MultistageChannelFilter

import subprocess
import os

pipe_rate = 2000000
transition_width = 500000

# Does not inherit sdr.receiver.Receiver because that defines a variable receive frequency.
class ModeSReceiver(gr.hier_block2, ExportedState):
	rec_freq = 1090000000
	
	def __init__(self, mode='MODE-S', input_rate=0, input_center_freq=0, audio_rate=0, control_hook=None):
		assert input_rate > 0
		gr.hier_block2.__init__(
			self, 'Mode S/ADS-B/1090 receiver',
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			# TODO: Add generic support for receivers with no audio output
			gr.io_signature(2, 2, gr.sizeof_float * 1),
		)
		self.mode = mode
		self.input_rate = input_rate
		self.input_center_freq = input_center_freq
		
		# Subprocess
		self.dump1090 = subprocess.Popen(
			args=['dump1090', '--ifile', '-'],
			stdin=subprocess.PIPE,
			stdout=None,
			stderr=None,
			close_fds=True)
		
		# Output
		self.band_filter_block = filter = MultistageChannelFilter(
			input_rate=input_rate,
			output_rate=pipe_rate, # expected by dump1090
			cutoff_freq=pipe_rate / 2,
			transition_width=transition_width) # TODO optimize filter band
		interleaver = blocks.interleave(gr.sizeof_char)
		self.connect(
			self,
			filter,
			blocks.complex_to_real(1),
			blocks.multiply_const_ff(255.0/2),
			blocks.add_const_ff(255.0/2),
			blocks.float_to_uchar(),
			(interleaver, 0),
			# we dup the fd because the stdin object and file_descriptor_sink both expect to own it
			# TODO: verify no fd leak
			blocks.file_descriptor_sink(gr.sizeof_char, os.dup(self.dump1090.stdin.fileno())))
		self.connect(
			filter,
			blocks.complex_to_imag(1),
			blocks.multiply_const_ff(255.0/2),
			blocks.add_const_ff(255.0/2),
			blocks.float_to_uchar(),
			(interleaver, 1))
		# Dummy audio
		zero = analog.sig_source_f(0, analog.GR_CONST_WAVE, 0, 0, 0)
		self.throttle = blocks.throttle(gr.sizeof_float, audio_rate)
		self.connect(zero, self.throttle)
		self.connect(self.throttle, (self, 0))
		self.connect(self.throttle, (self, 1))

	def state_def(self, callback):
		super(ModeSReceiver, self).state_def(callback)
		callback(Cell(self, 'mode', writable=True))
		callback(Cell(self, 'band_filter_shape'))
		callback(Cell(self, 'rec_freq', writable=False, ctor=float))
		callback(Cell(self, 'is_valid'))

	def get_is_valid(self):
		return abs(self.rec_freq - self.input_center_freq) < (self.input_rate - pipe_rate) / 2

	def get_rec_freq(self):
		return self.rec_freq

	def get_mode(self):
		return self.mode

	# TODO: duplicated code with main Receiver, which is further evidence for refactoring to separate management-by-top-block from receiver implementation
	def set_mode(self, mode):
		if mode != self.mode:
			self.control_hook.replace_me(mode)

	def get_band_filter_shape(self):
		return {
			'low': -pipe_rate/2,
			'high': pipe_rate/2,
			'width': transition_width
		}
	
	def _update_band_center(self):
		self.band_filter_block.set_center_freq(self.rec_freq - self.input_center_freq)
	
	def set_input_center_freq(self, value):
		self.input_center_freq = value
		self._update_band_center()
