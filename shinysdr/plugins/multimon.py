# Copyright 2013 Kevin Reid <kpreid@switchb.org>
#
# This file is part of ShinySDR.
# 
# ShinySDR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# ShinySDR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import, division

from zope.interface import implements

from gnuradio import gr
from gnuradio import blocks

from shinysdr.modes import ModeDef, IDemodulator
from shinysdr.types import Notice
from shinysdr.values import ExportedState, exported_value
from shinysdr.blocks import SubprocessSink, test_subprocess, make_resampler
from shinysdr.plugins.basic_demod import NFMDemodulator


pipe_rate = 22050  # what multimon-ng expects
_maxint32 = 2 ** 15 - 1
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
	
	@exported_value(ctor=Notice())
	def get_notice(self):
		return u'Properly displaying output is not yet implemented; see stdout of the server process.'

# TODO: Arrange for a way for the user to see why it is unavailable.
pluginDef_APRS = ModeDef('APRS', label='APRS', demodClass=MultimonNGDemodulator,
	available=test_subprocess('multimon-ng -h; exit 0', 'available demodulators:', shell=True))
