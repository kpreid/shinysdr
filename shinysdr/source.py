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

from gnuradio import audio
from gnuradio import blocks
from gnuradio import filter as grfilter
from gnuradio import gr
from gnuradio.filter import firdes

from shinysdr.types import Range
from shinysdr.signals import SignalType
from shinysdr.values import ExportedState, LooseCell, exported_value

class Source(gr.hier_block2, ExportedState):
	'''Generic wrapper for multiple source types, yielding complex samples.'''
	def __init__(self, name, freq_range=float):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(0, 0, 0),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		# TODO: 
		self.freq_cell = LooseCell(
			key='freq',
			value=0.0,
			ctor=freq_range,
			writable=True,
			persists=True,
			post_hook=self._really_set_frequency)
	
	def state_def(self, callback):
		super(Source, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(self.freq_cell)
	
	@exported_value(ctor=SignalType)
	def get_output_type(self):
		'''
		Should return an instance of SignalType describing the output signal.
		
		The value MUST NOT change in an incompatible way during the lifetime of the source. 
		'''
		# TODO: Programmatically define what 'incompatible' means
		raise NotImplementedError()

	def get_freq(self):
		return self.freq_cell.get()

	def set_freq(self, freq):
		self.freq_cell.set(freq)
	
	def _really_set_frequency(self, freq):
		'''Override point for changing the hardware frequency etc.'''
		raise NotImplementedError()

	def get_tune_delay(self):
		'''
		Return the amount of time, in seconds, between a call to set_freq() and the new center frequency taking effect as observed at top.monitor.fft.
		
		TODO: We need a better strategy for this. Stream tags might help if we can get them in the right places.
		'''
		raise NotImplementedError()

	def notify_reconnecting_or_restarting(self):
		pass


class AudioSource(Source):
	def __init__(self,
			device_name='',  # may be used positionally, not recommented
			sample_rate=44100,
			quadrature_as_stereo=False,
			tuning_cell=None,
			name='Audio Device Source',
			**kwargs):
		self.__name = name  # for reinit only
		self.__device_name = device_name
		self.__sample_rate_in = sample_rate
		self.__quadrature_as_stereo = quadrature_as_stereo
		self.__tuning_cell = tuning_cell
		
		if self.__quadrature_as_stereo:
			self.__complex = blocks.float_to_complex(1)
			self.__sample_rate_out = sample_rate
			self.__offset = 0.0
		else:
			self.__complex = _Complexifier(hilbert_length=128)
			self.__sample_rate_out = sample_rate / 2
			self.__offset = sample_rate / 4
		
		# TODO: Eliminate the Complexifier, and the quadrature_as_stereo parameter, and just declare our output to be a user specified type (FM or USB probably).
		self.__signal_type = SignalType(
			kind='IQ',
			sample_rate=self.__sample_rate_out)
		
		if self.__tuning_cell is not None:
			freq_range = self.__tuning_cell.type()
			if self.__offset != 0 and isinstance(freq_range, Range): # TODO kludge
				freq_range = freq_range.shifted_by(self.__offset)
			freq = self.__tuning_cell.get() + self.__offset
			self.__tuning_cell.subscribe(self.__update_from_tuning_source)
		else:
			freq_range = Range([(self.__offset, self.__offset)], strict=True)
			freq = self.__offset
		
		Source.__init__(self,
			name=name,
			freq_range=freq_range,
			**kwargs)
		self.freq_cell.set(freq)
		
		self.__source = audio.source(
			self.__sample_rate_in,
			device_name=self.__device_name,
			ok_to_block=True)
		
		self.connect(self.__source, self.__complex, self)
		if self.__quadrature_as_stereo:
			# if we don't do this, the imaginary component is 0 and the spectrum is symmetric
			self.connect((self.__source, 1), (self.__complex, 1))
	
	def __str__(self):
		return 'Audio ' + self.__device_name

	@exported_value(ctor=SignalType)
	def get_output_type(self):
		return self.__signal_type

	def __update_from_tuning_source(self):
		freq = self.__tuning_cell.get() + self.__offset
		self.freq_cell.set_internal(freq)

	def _really_set_frequency(self, freq):
		if self.__tuning_cell is not None:
			self.__tuning_cell.set(freq - self.__offset)
	
	def get_tune_delay(self):
		return 0.0


class _Complexifier(gr.hier_block2):
	'''
	Turn a real signal into a complex signal of half the sample rate with the same band.
	'''
	
	def __init__(self, hilbert_length):
		gr.hier_block2.__init__(
			self, self.__class__.__name__,
			gr.io_signature(1, 1, gr.sizeof_float),
			gr.io_signature(1, 1, gr.sizeof_gr_complex),
		)
		
		# On window selection:
		# http://www.trondeau.com/blog/2013/9/26/hilbert-transform-and-windowing.html
		self.__hilbert = grfilter.hilbert_fc(
			hilbert_length,
			window=firdes.WIN_BLACKMAN_HARRIS)
		self.__rotate = grfilter.freq_xlating_fir_filter_ccc(
			2,  # decimation
			[1],  # taps
			0.25,  # freq shift
			1)  # sample rate
		
		# TODO: We could skip the rotation step by instead passing info downstream (i.e. declaring that our band is 0..f rather than -f/2..f/2). Unclear whether the complexity is worth it. Would need to teach MonitorSink (rotate FFT output) and Receiver (validity criterion) about it.
		
		self.connect(
			self,
			self.__hilbert,
			self.__rotate,
			self)
