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

from gnuradio import analog
from gnuradio import blocks
from gnuradio import channels
from gnuradio import filter as grfilter
from gnuradio import gr
from gnuradio.filter import firdes

import math

from shinysdr.blocks import rotator_inc
from shinysdr.signals import SignalType
from shinysdr.source import Source
from shinysdr.types import Range
from shinysdr.values import BlockCell, CollectionState, ExportedState, exported_value, setter


class SimulatedSource(Source):
	# TODO: be not hardcoded; for now this is convenient
	audio_rate = 1e4
	rf_rate = 200e3

	def __init__(self, name='Simulated Source', freq=0.0):
		Source.__init__(self,
			name=name,
			freq_range=Range([(freq, freq)]))
		self.freq_cell.set(freq)
		
		rf_rate = self.rf_rate
		audio_rate = self.audio_rate
		
		self.__freq = freq
		self.noise_level = -2
		self._transmitters = {}
		
		self.transmitters = CollectionState(self._transmitters, dynamic=True)
		
		self.bus = blocks.add_vcc(1)
		self.channel_model = channels.channel_model(
			noise_voltage=10 ** (self.noise_level / 10.0),
			frequency_offset=0,
			epsilon=1.01,  # TODO: expose this parameter
			#taps=...,  # TODO: apply something here?
			)
		self.throttle = blocks.throttle(gr.sizeof_gr_complex, rf_rate)
		self.connect(
			self.bus,
			self.channel_model,
			self.throttle,
			self)
		signals = []
		
		def add_modulator(freq, key, ctor, **kwargs):
			modulator = ctor(audio_rate=audio_rate, rf_rate=rf_rate, **kwargs)
			tx = _SimulatedTransmitter(modulator, rf_rate, freq)
			
			self.connect(audio_signal, tx)
			signals.append(tx)
			self._transmitters[key] = tx
		
		# Audio input signal
		pitch = analog.sig_source_f(audio_rate, analog.GR_SAW_WAVE, -1, 2000, 1000)
		audio_signal = vco = blocks.vco_f(audio_rate, 1, 1)
		self.connect(pitch, vco)
		
		# Channels
		add_modulator(0.0, 'dsb', _DSBModulator)
		add_modulator(10e3, 'am', _AMModulator)
		add_modulator(30e3, 'fm', _FMModulator)
		add_modulator(-30e3, 'vor1', _VORModulator, angle=0)
		add_modulator(-60e3, 'vor2', _VORModulator, angle=math.pi / 2)
		
		bus_input = 0
		for signal in signals:
			self.connect(signal, (self.bus, bus_input))
			bus_input = bus_input + 1
		
		self.__signal_type = SignalType(
			kind='IQ',
			sample_rate=rf_rate)
	
	def __str__(self):
		return 'Simulated RF'

	def state_def(self, callback):
		super(SimulatedSource, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(BlockCell(self, 'transmitters'))

	@exported_value(ctor=SignalType)
	def get_output_type(self):
		return self.__signal_type
		
	def _really_set_frequency(self, freq):
		pass
	
	def get_tune_delay(self):
		return 0.0
	
	@exported_value(ctor=Range([(-50, 0)]))
	def get_noise_level(self):
		return self.noise_level
	
	@setter
	def set_noise_level(self, value):
		self.channel_model.set_noise_voltage(10.0 ** (value / 10))
		self.noise_level = value

	def notify_reconnecting_or_restarting(self):
		# The throttle block runs on a clock which does not stop when the flowgraph stops; resetting the sample rate restarts the clock.
		# The necessity of this kludge has been filed as a gnuradio bug at <http://gnuradio.org/redmine/issues/649>
		self.throttle.set_sample_rate(self.throttle.sample_rate())


_interp_taps = firdes.low_pass(
	1,  # gain
	SimulatedSource.rf_rate,
	SimulatedSource.audio_rate / 2,
	SimulatedSource.audio_rate * 0.2,
	firdes.WIN_HAMMING)


def _make_interpolator(real=False):
	interp = int(SimulatedSource.rf_rate / SimulatedSource.audio_rate)
	if real:
		return grfilter.interp_fir_filter_fff(interp, _interp_taps)
	else:
		return grfilter.interp_fir_filter_ccf(interp, _interp_taps)


# TODO: Eventually we expect to have general transmit support and so put the modulators next to the demodulators. For now, they can be here.


class _SimulatedTransmitter(gr.hier_block2, ExportedState):
	'''provides frequency parameters'''
	def __init__(self, modulator, rf_rate, freq):
		gr.hier_block2.__init__(
			self, 'SimulatedChannel',
			gr.io_signature(1, 1, gr.sizeof_float * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.__freq = freq
		self.__rf_rate = rf_rate
		
		self.modulator = modulator  # exported
		
		self.__rotator = blocks.rotator_cc(rotator_inc(rate=rf_rate, shift=freq))
		self.__mult = blocks.multiply_const_cc(1.0)
		self.connect(self, modulator, self.__rotator, self.__mult, self)
	
	def state_def(self, callback):
		super(_SimulatedTransmitter, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(BlockCell(self, 'modulator'))

	@exported_value(ctor_fn=lambda self: Range([(-self.__rf_rate / 2, self.__rf_rate / 2)], strict=False))
	def get_freq(self):
		return self.__freq
	
	@setter
	def set_freq(self, value):
		self.__freq = float(value)
		self.__rotator.set_phase_inc(rotator_inc(rate=self.__rf_rate, shift=self.__freq))
	
	@exported_value(ctor=Range([(-50.0, 0.0)], strict=False))
	def get_gain(self):
		return 10 * math.log10(self.__mult.k().real)
	
	@setter
	def set_gain(self, value):
		self.__mult.set_k(10.0 ** (float(value) / 10))


class _DSBModulator(gr.hier_block2, ExportedState):
	def __init__(self, audio_rate, rf_rate):
		gr.hier_block2.__init__(
			self, 'SimulatedSource DSB modulator',
			gr.io_signature(1, 1, gr.sizeof_float * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.connect(
			self,
			blocks.float_to_complex(1),
			_make_interpolator(),
			self)


class _AMModulator(gr.hier_block2, ExportedState):
	def __init__(self, audio_rate, rf_rate):
		gr.hier_block2.__init__(
			self, 'SimulatedSource AM modulator',
			gr.io_signature(1, 1, gr.sizeof_float * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.connect(
			self,
			blocks.float_to_complex(1),
			blocks.add_const_cc(1),
			_make_interpolator(),
			self)


class _FMModulator(gr.hier_block2, ExportedState):
	def __init__(self, audio_rate, rf_rate):
		gr.hier_block2.__init__(
			self, 'SimulatedSource FM modulator',
			gr.io_signature(1, 1, gr.sizeof_float * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.connect(
			self,
			analog.nbfm_tx(
				audio_rate=audio_rate,
				quad_rate=rf_rate,
				tau=75e-6,
				max_dev=5e3),
			self)


class _VORModulator(gr.hier_block2, ExportedState):
	__vor_sig_freq = 30

	def __init__(self, audio_rate, rf_rate, angle):
		gr.hier_block2.__init__(
			self, 'SimulatedSource VOR modulator',
			gr.io_signature(1, 1, gr.sizeof_float * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.__rf_rate = rf_rate
		self.__angle = angle
		
		# TODO: My signal level parameters are probably wrong because this signal doesn't look like a real VOR signal
		
		vor_dev = 480
		vor_30 = analog.sig_source_f(audio_rate, analog.GR_COS_WAVE, self.__vor_sig_freq, 1, 0)
		vor_add = blocks.add_cc(1)
		vor_audio = blocks.add_ff(1)
		# Audio/AM signal
		self.connect(
			vor_30,
			blocks.multiply_const_ff(0.3),  # M_n
			(vor_audio, 0))
		self.connect(
			self,
			blocks.multiply_const_ff(0.07),  # M_i
			(vor_audio, 1))
		# Carrier component
		self.connect(
			analog.sig_source_c(0, analog.GR_CONST_WAVE, 0, 0, 1),
			(vor_add, 0))
		# AM component
		self.__delay = blocks.delay(gr.sizeof_gr_complex, 0)  # configured by set_angle
		self.connect(
			vor_audio,
			blocks.float_to_complex(1),
			_make_interpolator(),
			self.__delay,
			(vor_add, 1))
		# FM component
		vor_fm_mult = blocks.multiply_cc(1)
		self.connect(  # carrier generation
			analog.sig_source_f(rf_rate, analog.GR_COS_WAVE, 9960, 1, 0), 
			blocks.float_to_complex(1),
			(vor_fm_mult, 1))
		self.connect(  # modulation
			vor_30,
			_make_interpolator(real=True),
			analog.frequency_modulator_fc(2 * math.pi * vor_dev / rf_rate),
			blocks.multiply_const_cc(0.3),  # M_d
			vor_fm_mult,
			(vor_add, 2))
		self.connect(
			vor_add,
			self)
		
		# calculate and initialize delay
		self.set_angle(angle)
	
	@exported_value(ctor=Range([(0, 2 * math.pi)], strict=False))
	def get_angle(self):
		return self.__angle
	
	@setter
	def set_angle(self, value):
		value = float(value)
		compensation = math.pi / 180 * -6.5  # empirical, calibrated against VOR receiver (and therefore probably wrong)
		value = value + compensation
		value = value % (2 * math.pi)
		phase_shift = int(self.__rf_rate / self.__vor_sig_freq * (value / (2 * math.pi)))
		self.__delay.set_dly(phase_shift)
		self.__angle = value
