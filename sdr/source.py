#!/usr/bin/env python

import gnuradio
import gnuradio.blocks
from gnuradio import gr
from gnuradio import blocks
from gnuradio import audio
from gnuradio import analog
from gnuradio import filter
from gnuradio.filter import firdes

import math

from sdr.values import Cell, Range, ExportedState


class Source(gr.hier_block2, ExportedState):
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

	def notify_reconnecting_or_restarting(self):
		pass


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
		self.__complex = blocks.float_to_complex(1)
		self.__source = None
		
		self.connect(self.__complex, self)
		
		self.__do_connect()
	
	def __str__(self):
		return 'Audio ' + self.__device_name
	
	def state_def(self, callback):
		super(AudioSource, self).state_def(callback)
		callback(Cell(self, 'freq', ctor=float))
		
	def get_sample_rate(self):
		return self.__sample_rate

	def notify_reconnecting_or_restarting(self):
		# work around OSX audio source bug; does not work across flowgraph restarts
		self.__do_connect()

	def get_freq(self):
		return 0

	def get_tune_delay(self):
		return 0.0

	def __do_connect(self):
		if self.__source is not None:
			# detailed disconnect because disconnect_all on hier blocks is broken
			self.disconnect(self.__source, self.__complex)
			if self.__quadrature_as_stereo:
				self.disconnect((self.__source, 1), (self.__complex, 1))
		
		# work around OSX audio source bug; does not work across flowgraph restarts
		self.__source = audio.source(
			self.__sample_rate,
			device_name=self.__device_name,
			ok_to_block=True)
		
		self.connect(self.__source, self.__complex)
		if self.__quadrature_as_stereo:
			# if we don't do this, the imaginary component is 0 and the spectrum is symmetric
			self.connect((self.__source, 1), (self.__complex, 1))


class SimulatedSource(Source):
	def __init__(self, name='Simulated Source', **kwargs):
		Source.__init__(self, name=name, **kwargs)
		
		audio_rate = 1e4
		rf_rate = self.__sample_rate = 200e3
		interp = int(rf_rate / audio_rate)
		
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
		self.throttle = blocks.throttle(gr.sizeof_gr_complex, rf_rate)
		self.connect(
			self.bus,
			self.throttle,
			self)
		signals = []
		
		# Audio input signal
		pitch = analog.sig_source_f(audio_rate, analog.GR_SAW_WAVE, -1, 2000, 1000)
		audio_signal = vco = blocks.vco_f(audio_rate, 1, 1)
		self.connect(pitch, vco)
		
		# Noise source
		self.noise_source = analog.noise_source_c(analog.GR_GAUSSIAN, 10 ** self.noise_level, 0)
		signals.append(self.noise_source)
		
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

	def state_def(self, callback):
		super(SimulatedSource, self).state_def(callback)
		callback(Cell(self, 'freq', writable=False, ctor=float))
		callback(Cell(self, 'noise_level', writable=True, ctor=Range(-5, 1)))
		
	def get_sample_rate(self):
		# TODO review why cast
		return int(self.__sample_rate)
		
	def get_freq(self):
		return 0
	
	def get_tune_delay(self):
		return 0.0
	
	def get_noise_level(self):
		return self.noise_level
	
	def set_noise_level(self, value):
		self.noise_source.set_amplitude(10 ** value)
		self.noise_level = value

	def notify_reconnecting_or_restarting(self):
		# throttle block runs on a clock which does not stop when the flowgraph stops; resetting the sample rate restarts the clock
		self.throttle.set_sample_rate(self.throttle.sample_rate())
