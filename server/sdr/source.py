#!/usr/bin/env python

import gnuradio
import gnuradio.blocks
from gnuradio import gr
from gnuradio import blocks
from gnuradio import blks2
from gnuradio import analog
from gnuradio import filter
from gnuradio.gr import firdes

import osmosdr

import sdr
from sdr import Cell, Range


class Source(gr.hier_block2, sdr.ExportedState):
	'''Generic wrapper for multiple source types, yielding complex samples.'''
	def __init__(self, name):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(0, 0, 0),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		self.tune_hook = lambda: None

	def set_tune_hook(self, value):
		self.tune_hook = value

	def state_def(self, callback):
		super(Source, self).state_def(callback)
		callback(Cell(self, 'sample_rate', ctor=int))
		# all sources should also have 'freq' but writability is not guaranteed so not specified here

	def get_sample_rate(self):
		raise NotImplementedError()

	def needs_renew(self):
		return False
	
	def renew(self):
		return self


class AudioSource(Source):
	def __init__(self,
			name='Audio Device Source',
			device_name='',
			quadrature_as_stereo=False,
			**kwargs):
		Source.__init__(self, name=name, **kwargs)
		self.__name = name  # for reinit only
		self.__device_name = device_name
		self.__sample_rate = 44100
		self.__quadrature_as_stereo = quadrature_as_stereo
		self.__complex = gnuradio.blocks.float_to_complex(1)
		self.__source = gnuradio.audio.source(
			self.__sample_rate,
			device_name=device_name,  # TODO configurability
			ok_to_block=True)
		self.connect(self.__source, self.__complex, self)
		if quadrature_as_stereo:
			# if we don't do this, the imaginary component is 0 and the spectrum is symmetric
			self.connect((self.__source, 1), (self.__complex, 1))
	
	def __str__(self):
		return 'Audio ' + self.__device_name
	
	def state_def(self, callback):
		super(AudioSource, self).state_def(callback)
		callback(Cell(self, 'freq', ctor=float))
		
	def get_sample_rate(self):
		return self.__sample_rate

	def needs_renew(self):
		return True
	
	def renew(self):
		return AudioSource(
			name=self.__name,
			device_name=self.__device_name,
			quadrature_as_stereo=self.__quadrature_as_stereo)

	def get_freq(self):
		return 0


ch = 0  # osmosdr channel, to avoid magic number


class OsmoSDRSource(Source):
	def __init__(self,
			osmo_device,
			name='OsmoSDR Source',
			sample_rate=2400000,
			**kwargs):
		Source.__init__(self, name=name, **kwargs)

		# TODO present sample rate configuration using source.get_sample_rates().values()
		# TODO present hw freq range
		
		self.__osmo_device = osmo_device
		self.freq = freq = 98e6
		self.correction_ppm = 0
		
		self.osmosdr_source_block = source = osmosdr.source_c("nchan=1 " + osmo_device)
		# Note: Docs for these setters at gr-osmosdr/lib/source_iface.h
		source.set_sample_rate(sample_rate)
		source.set_center_freq(freq, ch)
		# freq_corr: We implement correction internally because setting this at runtime breaks things
		source.set_iq_balance_mode(0, ch)  # TODO
		# gain_mode and gain: handled by accessors
		source.set_antenna("", ch)  # n/a to RTLSDR
		source.set_bandwidth(0, ch)  # TODO is this relevant
		# Note: There is a DC cancel facility but it is not implemented for RTLSDR
	
		self.connect(self.osmosdr_source_block, self)
	
	def __str__(self):
		return 'OsmoSDR ' + self.__osmo_device

	def state_def(self, callback):
		super(OsmoSDRSource, self).state_def(callback)
		callback(Cell(self, 'freq', writable=True, ctor=float))
		callback(Cell(self, 'correction_ppm', writable=True, ctor=float))
		callback(Cell(self, 'agc', writable=True, ctor=bool))
		
		gain_range = self.osmosdr_source_block.get_gain_range(ch)
		# Note: range may have gaps and we don't represent that
		callback(Cell(self, 'gain', writable=True, ctor=
			Range(gain_range.start(), gain_range.stop(), strict=False)))
		
	def get_sample_rate(self):
		# TODO review why cast
		return int(self.osmosdr_source_block.get_sample_rate())
		
	def get_freq(self):
		return self.freq

	def set_freq(self, freq):
		actual_freq = self._compute_frequency(freq)
		# TODO: This limitation is in librtlsdr's interface. If we support other gr-osmosdr devices, change it.
		maxint32 = 2 ** 32 - 1
		if actual_freq < 0 or actual_freq > maxint32:
			raise ValueError('Frequency must be between 0 and ' + str(maxint32) + ' Hz')
		self.freq = freq
		self._update_frequency()

	def get_correction_ppm(self):
		return self.correction_ppm
	
	def set_correction_ppm(self, value):
		self.correction_ppm = value
		# Not using the hardware feature because I only get garbled output from it
		#self.osmosdr_source_block.set_freq_corr(value, 0)
		self._update_frequency()
	
	def _compute_frequency(self, effective_freq):
		if effective_freq == 0.0:
			# Quirk: Tuning to 3686.6-3730 MHz (on some tuner HW) causes operation effectively at 0Hz.
			# Original report: <http://www.reddit.com/r/RTLSDR/comments/12d2wc/a_very_surprising_discovery/>
			return 3700e6
		else:
			return effective_freq * (1 - 1e-6 * self.correction_ppm)
	
	def _update_frequency(self):
		self.osmosdr_source_block.set_center_freq(self._compute_frequency(self.freq), 0)
		# TODO: read back actual frequency and store
		self.tune_hook()

	def get_agc(self):
		return bool(self.osmosdr_source_block.get_gain_mode(ch))

	def set_agc(self, value):
		self.osmosdr_source_block.set_gain_mode(bool(value), ch)
	
	def get_gain(self):
		return self.osmosdr_source_block.get_gain(ch)
	
	def set_gain(self, value):
		self.osmosdr_source_block.set_gain(float(value), ch)


class SimulatedSource(Source):
	def __init__(self, name='Simulated Source', **kwargs):
		Source.__init__(self, name=name, **kwargs)
		
		audio_rate = 1e4
		rf_rate = self.__sample_rate = 200e3
		interp = int(rf_rate / audio_rate)
		
		def make_interpolator():
			return filter.interp_fir_filter_ccf(
				interp,
				firdes.low_pass(
					1, # gain
					rf_rate,
					audio_rate / 2,
					audio_rate * 0.2,
					firdes.WIN_HAMMING))
		
		def make_channel(freq):
			osc = analog.sig_source_c(rf_rate, analog.GR_COS_WAVE, freq, 1, 0)
			mult = blocks.multiply_cc(1)
			self.connect(osc, (mult, 1))
			return mult
		
		self.bus = blocks.add_vcc(1)
		bus_input = 0
		self.connect(
			self.bus,
			blocks.throttle(gr.sizeof_gr_complex, rf_rate),
			self)
		
		# Audio input signal
		pitch = analog.sig_source_f(audio_rate, analog.GR_SAW_WAVE, -1, 2000, 1000)
		audio_signal = vco = blocks.vco_f(audio_rate, 1, 1)
		self.connect(pitch, vco)
		
		# Noise source
		self.connect(
			analog.noise_source_c(analog.GR_GAUSSIAN, 0.01, 0),
			(self.bus, bus_input))
		bus_input = bus_input + 1
		
		# Baseband / DSB channel
		self.connect(
			audio_signal,
			blocks.float_to_complex(1),
			make_interpolator(),
			(self.bus, bus_input))
		bus_input = bus_input + 1
		
		# AM channel
		self.connect(
			audio_signal,
			blocks.float_to_complex(1),
			blocks.add_const_cc(1),
			make_interpolator(),
			make_channel(10e3),
			(self.bus, bus_input))
		bus_input = bus_input + 1
		
		# NFM channel
		self.connect(
			audio_signal,
			blks2.nbfm_tx(
				audio_rate=audio_rate,
				quad_rate=rf_rate,
				tau=75e-6,
				max_dev=5e3),
			make_channel(30e3),
			(self.bus, bus_input))
		bus_input = bus_input + 1
	
	def __str__(self):
		return 'Simulated RF'

	def state_def(self, callback):
		super(SimulatedSource, self).state_def(callback)
		callback(Cell(self, 'freq', writable=False, ctor=float))
		#callback(Cell(self, 'gain', writable=True, ctor=float))
		
	def get_sample_rate(self):
		# TODO review why cast
		return int(self.__sample_rate)
		
	def get_freq(self):
		return 0
