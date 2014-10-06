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

from twisted.internet import reactor
from twisted.internet.protocol import ProcessProtocol
from zope.interface import implements

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog

from shinysdr.modes import ModeDef, IDemodulator
from shinysdr.types import Notice
from shinysdr.values import ExportedState, exported_value
from shinysdr.blocks import MultistageChannelFilter, make_sink_to_process_stdin, test_subprocess


pipe_rate = 2000000
transition_width = 500000
_dummy_audio_rate = 1000


class ModeSDemodulator(gr.hier_block2, ExportedState):
	implements(IDemodulator)
	
	def __init__(self, mode='MODE-S', input_rate=0, context=None):
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
		# TODO need to redefine this
		process = reactor.spawnProcess(
			_Dump1090ProcessProtocol(None),
			'/usr/bin/env',
			env=None,
			args=['env', 'dump1090', '--ifile', '-'],
			childFDs={
				0: 'w',
				1: 1,
				2: 2
			})
		sink = make_sink_to_process_stdin(process, itemsize=gr.sizeof_char)
		
		# Output
		band_filter = MultistageChannelFilter(
			input_rate=input_rate,
			output_rate=pipe_rate,  # expected by dump1090
			cutoff_freq=pipe_rate / 2,
			transition_width=transition_width)  # TODO optimize filter band
		interleaver = blocks.interleave(gr.sizeof_char)
		self.connect(
			self,
			band_filter,
			blocks.complex_to_real(1),
			blocks.multiply_const_ff(255.0 / 2),
			blocks.add_const_ff(255.0 / 2),
			blocks.float_to_uchar(),
			(interleaver, 0),
			sink)
		
		self.connect(
			band_filter,
			blocks.complex_to_imag(1),
			blocks.multiply_const_ff(255.0 / 2),
			blocks.add_const_ff(255.0 / 2),
			blocks.float_to_uchar(),
			(interleaver, 1))
		# Dummy audio
		zero = analog.sig_source_f(0, analog.GR_CONST_WAVE, 0, 0, 0)
		self.throttle = blocks.throttle(gr.sizeof_float, _dummy_audio_rate)
		self.connect(zero, self.throttle)
		self.connect(self.throttle, (self, 0))
		self.connect(self.throttle, (self, 1))

	def can_set_mode(self, mode):
		return False

	def get_half_bandwidth(self):
		return pipe_rate / 2
	
	def get_output_type(self):
		return SignalType(kind='STEREO', sample_rate=_dummy_audio_rate)

	@exported_value()
	def get_band_filter_shape(self):
		return {
			'low': -pipe_rate / 2,
			'high': pipe_rate / 2,
			'width': transition_width
		}
	
	@exported_value(ctor=Notice())
	def get_notice(self):
		return u'Properly displaying output is not yet implemented; see stdout of the server process.'


class _Dump1090ProcessProtocol(ProcessProtocol):
	def __init__(self, target):
		self.__target = target


# TODO: Arrange for a way for the user to see why it is unavailable.
pluginDef = ModeDef('MODE-S', label='Mode S', demod_class=ModeSDemodulator,
	available=test_subprocess(['dump1090', '--help'], '--enable-agc'))
