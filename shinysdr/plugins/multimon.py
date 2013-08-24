from zope.interface import implements

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog

from shinysdr.receiver import ModeDef, IDemodulator
from shinysdr.values import ExportedState, exported_value
from shinysdr.blocks import MultistageChannelFilter, SubprocessSink, make_resampler
from shinysdr.plugins.basic_demod import NFMDemodulator

import subprocess
import os
import math

pipe_rate = 22050  # what multimon-ng expects
_maxint32 = (2**15-1)
audio_gain = 0.5
int_scale = _maxint32 * audio_gain

class MultimonNGDemodulator(gr.hier_block2, ExportedState):
	implements(IDemodulator)
	
	def __init__(self, mode, input_rate=0, audio_rate=0, context=None):
		assert input_rate > 0
		gr.hier_block2.__init__(
			self, str(mode) + ' (Multimon-NG) demodulator',
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			# TODO: Add generic support for demodulators with no audio output
			gr.io_signature(2, 2, gr.sizeof_float * 1),
		)
		self.mode = mode
		self.input_rate = input_rate
		
		# FM demod
		self.fm_demod = NFMDemodulator(
			mode='NFM',
			input_rate=input_rate,
			audio_rate=pipe_rate,
			tau=None)  # no deemphasis
		
		# Subprocess
		self.process = SubprocessSink(
			args=['multimon-ng', '-t', 'raw', '-a', 'AFSK1200', '-A', '-v', '10', '-'],
			#args=['python', '../play16bit.py'],
			itemsize=gr.sizeof_short)
		
		# Output
		converter = blocks.float_to_short(vlen=1, scale=int_scale)
		self.connect(
			self,
			self.fm_demod,
			converter,
			self.process)
		# Dummy sink for useless stereo output of demod
		self.connect((self.fm_demod, 1), blocks.null_sink(gr.sizeof_float))
		# Audio copy output
		resampler = make_resampler(pipe_rate, audio_rate)
		self.connect(converter, blocks.short_to_float(vlen=1, scale=int_scale), resampler)
		#self.connect(self.fm_demod, resampler)
		self.connect(resampler, (self, 0))
		self.connect(resampler, (self, 1))
	
	def can_set_mode(self, mode):
		return False
	
	def get_half_bandwidth(self):
		return self.fm_demod.get_half_bandwidth()
	
	@exported_value()
	def get_band_filter_shape(self):
		return self.fm_demod.get_band_filter_shape()


pluginDef_APRS = ModeDef('APRS', label='APRS', demodClass=MultimonNGDemodulator)
# TODO defs for other multimon-supported modes
