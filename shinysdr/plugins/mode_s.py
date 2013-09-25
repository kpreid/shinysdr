from zope.interface import implements

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog

from shinysdr.receiver import ModeDef, IDemodulator
from shinysdr.values import ExportedState, exported_value
from shinysdr.blocks import MultistageChannelFilter, SubprocessSink


pipe_rate = 2000000
transition_width = 500000


class ModeSDemodulator(gr.hier_block2, ExportedState):
	implements(IDemodulator)
	
	def __init__(self, mode='MODE-S', input_rate=0, input_center_freq=0, audio_rate=0, context=None):
		assert input_rate > 0
		gr.hier_block2.__init__(
			self, 'Mode S/ADS-B/1090 demodulator',
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			# TODO: Add generic support for demodulators with no audio output
			gr.io_signature(2, 2, gr.sizeof_float * 1),
		)
		self.mode = mode
		self.input_rate = input_rate
		
		# Subprocess
		self.dump1090 = SubprocessSink(['dump1090', '--ifile', '-'])
		
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
			self.dump1090)
		
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

	def can_set_mode(self, mode):
		return False

	def get_half_bandwidth(self):
		return pipe_rate / 2

	@exported_value()
	def get_band_filter_shape(self):
		return {
			'low': -pipe_rate/2,
			'high': pipe_rate/2,
			'width': transition_width
		}

pluginDef = ModeDef('MODE-S', label='Mode S', demodClass=ModeSDemodulator)
