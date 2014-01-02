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
from gnuradio import filter
from gnuradio import gr
from gnuradio.filter import firdes

import math

from shinysdr.values import Range, exported_value, setter
from shinysdr.source import Source


class SimulatedSource(Source):
	def __init__(self, name='Simulated Source', freq=0):
		Source.__init__(self, name=name)
		
		audio_rate = 1e4
		rf_rate = self.__sample_rate = 200e3
		interp = int(rf_rate / audio_rate)
		
		self.__freq = freq
		self.noise_level = -2
		
		interp_taps = firdes.low_pass(
			1, # gain
			rf_rate,
			audio_rate / 2,
			audio_rate * 0.2,
			firdes.WIN_HAMMING)
		def make_interpolator():
			return filter.interp_fir_filter_ccf(interp, interp_taps)
		
		def make_channel(freq):
			osc = analog.sig_source_c(rf_rate, analog.GR_COS_WAVE, freq, 1, 0)
			mult = blocks.multiply_cc(1)
			self.connect(osc, (mult, 1))
			return mult
		
		self.bus = blocks.add_vcc(1)
		self.channel_model = channels.channel_model(
			noise_voltage=10 ** self.noise_level,
			frequency_offset=0,
			epsilon=1.01, # TODO: expose this parameter
			#taps=...,  # TODO: apply something here?
			)
		self.throttle = blocks.throttle(gr.sizeof_gr_complex, rf_rate)
		self.connect(
			self.bus,
			self.channel_model,
			self.throttle,
			self)
		signals = []
		
		# Audio input signal
		pitch = analog.sig_source_f(audio_rate, analog.GR_SAW_WAVE, -1, 2000, 1000)
		audio_signal = vco = blocks.vco_f(audio_rate, 1, 1)
		self.connect(pitch, vco)
		
		# Baseband / DSB channel
		baseband_interp = make_interpolator()
		self.connect(
			audio_signal,
			blocks.float_to_complex(1),
			baseband_interp)
		signals.append(baseband_interp)
		
		# AM channel
		am_channel = make_channel(10e3)
		self.connect(
			audio_signal,
			blocks.float_to_complex(1),
			blocks.add_const_cc(1),
			make_interpolator(),
			am_channel)
		signals.append(am_channel)
		
		# NFM channel
		nfm_channel = make_channel(30e3)
		self.connect(
			audio_signal,
			analog.nbfm_tx(
				audio_rate=audio_rate,
				quad_rate=rf_rate,
				tau=75e-6,
				max_dev=5e3),
			nfm_channel)
		signals.append(nfm_channel)
		
		# VOR channels
		# TODO: My signal level parameters are probably wrong because this signal doesn't look like a real VOR signal
		def add_vor(freq, angle):
			compensation = math.pi / 180 * -6.5  # empirical, calibrated against VOR receiver (and therefore probably wrong)
			angle = angle + compensation
			angle = angle % (2 * math.pi)
			vor_sig_freq = 30
			phase_shift = int(rf_rate / vor_sig_freq * (angle / (2 * math.pi)))
			vor_dev = 480
			vor_channel = make_channel(freq)
			vor_30 = analog.sig_source_f(audio_rate, analog.GR_COS_WAVE, vor_sig_freq, 1, 0)
			vor_add = blocks.add_cc(1)
			vor_audio = blocks.add_ff(1)
			# Audio/AM signal
			self.connect(
				vor_30,
				blocks.multiply_const_ff(0.3), # M_n
				(vor_audio, 0))
			self.connect(audio_signal,
				blocks.multiply_const_ff(0.07), # M_i
				(vor_audio, 1))
			# Carrier component
			self.connect(
				analog.sig_source_c(0, analog.GR_CONST_WAVE, 0, 0, 1),
				(vor_add, 0))
			# AM component
			self.connect(
				vor_audio,
				blocks.float_to_complex(1),
				make_interpolator(),
				blocks.delay(gr.sizeof_gr_complex, phase_shift),
				(vor_add, 1))
			# FM component
			vor_fm_mult = blocks.multiply_cc(1)
			self.connect(  # carrier generation
				analog.sig_source_f(rf_rate, analog.GR_COS_WAVE, 9960, 1, 0), 
				blocks.float_to_complex(1),
				(vor_fm_mult, 1))
			self.connect(  # modulation
				vor_30,
				filter.interp_fir_filter_fff(interp, interp_taps), # float not complex
				analog.frequency_modulator_fc(2 * math.pi * vor_dev / rf_rate),
				blocks.multiply_const_cc(0.3), # M_d
				vor_fm_mult,
				(vor_add, 2))
			self.connect(
				vor_add,
				vor_channel)
			signals.append(vor_channel)
		add_vor(-30e3, 0)
		add_vor(-60e3, math.pi / 2)
		
		bus_input = 0
		for signal in signals:
			self.connect(signal, (self.bus, bus_input))
			bus_input = bus_input + 1
	
	def __str__(self):
		return 'Simulated RF'

	def get_sample_rate(self):
		# TODO review why cast
		return int(self.__sample_rate)
		
	@exported_value(ctor=float)
	def get_freq(self):
		return self.__freq
	
	def get_tune_delay(self):
		return 0.0
	
	@exported_value(ctor=Range([(-5, 1)]))
	def get_noise_level(self):
		return self.noise_level
	
	@setter
	def set_noise_level(self, value):
		self.channel_model.set_noise_voltage(10 ** value)
		self.noise_level = value

	def notify_reconnecting_or_restarting(self):
		# throttle block runs on a clock which does not stop when the flowgraph stops; resetting the sample rate restarts the clock
		self.throttle.set_sample_rate(self.throttle.sample_rate())
