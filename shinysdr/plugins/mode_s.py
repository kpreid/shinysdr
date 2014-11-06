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

# pylint: disable=broad-except, maybe-no-member, no-member
# (broad-except: toplevel catch)
# (maybe-no-member: GR swig)
# (no-member: Twisted reactor)

from __future__ import absolute_import, division

import traceback

from twisted.internet import reactor  # TODO eliminate
from zope.interface import implements

from gnuradio import gr
from gnuradio import gru
from gnuradio import blocks
from gnuradio import analog

from shinysdr.modes import ModeDef, IDemodulator
from shinysdr.signals import no_signal
from shinysdr.types import Notice
from shinysdr.values import ExportedState, exported_value
from shinysdr.blocks import MultistageChannelFilter

try:
	import air_modes
	_available = True
except ImportError:
	_available = False


demod_rate = 2000000
transition_width = 500000


class ModeSDemodulator(gr.hier_block2, ExportedState):
	implements(IDemodulator)
	
	def __init__(self, mode='MODE-S', input_rate=0, context=None):
		assert input_rate > 0
		gr.hier_block2.__init__(
			self, 'Mode S/ADS-B/1090 demodulator',
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(0, 0, 0))
		self.mode = mode
		self.input_rate = input_rate
		
		hex_msg_queue = gr.msg_queue(100)
		
		band_filter = MultistageChannelFilter(
			input_rate=input_rate,
			output_rate=demod_rate,
			cutoff_freq=demod_rate / 2,
			transition_width=transition_width)  # TODO optimize filter band
		self.__demod = air_modes.rx_path(
			rate=demod_rate,
			threshold=7.0,  # default used in air-modes code but not exposed
			queue=hex_msg_queue,
			use_pmf=False,
			use_dcblock=True)
		self.connect(
			self,
			band_filter,
			self.__demod)
		
		# Parsing
		# TODO: These bits are mimicking gr-air-modes toplevel code. Figure out if we can have less glue.
		# Note: gr pubsub is synchronous -- subscribers are called on the publisher's thread
		parser_output = gr.pubsub.pubsub()
		parser = air_modes.make_parser(parser_output)
		cpr_decoder = air_modes.cpr_decoder(my_location=None)  # TODO: get position info from device
		air_modes.output_print(cpr_decoder, parser_output)
		def callback(msg):  # called on msgq_runner's thrad
			try:
				reactor.callFromThread(parser, msg.to_string())
			except Exception:
				print traceback.format_exc()
		
		self.__msgq_runner = gru.msgq_runner(hex_msg_queue, callback)

	def __del__(self):
		self.__msgq_runner.stop()

	def can_set_mode(self, mode):
		return False

	def get_half_bandwidth(self):
		return demod_rate / 2
	
	def get_output_type(self):
		return no_signal
	
	@exported_value()
	def get_band_filter_shape(self):
		return {
			'low': -demod_rate / 2,
			'high': demod_rate / 2,
			'width': transition_width
		}
	
	@exported_value(ctor=Notice())
	def get_notice(self):
		return u'Properly displaying output is not yet implemented; see stdout of the server process.'


pluginDef = ModeDef(
	mode='MODE-S',
	label='Mode S',
	demod_class=ModeSDemodulator,
	available=_available)
