#!/usr/bin/env python

import gnuradio
import gnuradio.blocks
from gnuradio import gr

import osmosdr

import sdr
from sdr import Cell

class Source(gr.hier_block2, sdr.ExportedState):
	'''Generic wrapper for multiple source types, yielding complex samples.'''
	def __init__(self, name):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(0, 0, 0),
			gr.io_signature(1, 1, gr.sizeof_gr_complex*1),
		)
		self.tune_hook = lambda: None

	def set_tune_hook(self, value):
		self.tune_hook = value

	def state_def(self, callback):
		super(Source, self).state_def(callback)
		callback(Cell(self, 'sample_rate', ctor=int))
		# all sources should also have 'freq' but writability is not guaranteed so not specified here

	def get_sample_rate(self):
		raise NotImplementedError

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
		self.__name = name # for reinit only
		self.__device_name = device_name
		self.__sample_rate = 44100
		self.__quadrature_as_stereo = quadrature_as_stereo
		self.__complex = gnuradio.blocks.float_to_complex(1)
		self.__source = gnuradio.audio.source(
			self.__sample_rate,
			device_name=device_name, # TODO configurability
			ok_to_block=True)
		self.connect(self.__source, self.__complex, self)
		if quadrature_as_stereo:
			# if we don't do this, the imaginary component is 0 and the spectrum is symmetric
			self.connect((self.__source, 1), (self.__complex, 1))
	
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

ch = 0 # osmosdr channel, to avoid magic number
class OsmoSDRSource(Source):
	def __init__(self, name='OsmoSDR Source', **kwargs):
		Source.__init__(self, name=name, **kwargs)

		# TODO present sample rate configuration using source.get_sample_rates().values()
		# TODO present hw freq range
		
		self.freq = freq = 98e6
		self.correction_ppm = 0
		
		osmo_device = "rtl=0"
		self.osmosdr_source_block = source = osmosdr.source_c("nchan=1 " + osmo_device)
		# Note: Docs for these setters at gr-osmosdr/lib/source_iface.h
		source.set_sample_rate(3200000)
		source.set_center_freq(freq, ch)
		# freq_corr: We implement correction internally because setting this at runtime breaks things
		source.set_iq_balance_mode(0, ch) # TODO
		# gain_mode and gain: handled by accessors
		source.set_antenna("", ch) # n/a to RTLSDR
		source.set_bandwidth(0, ch) # TODO is this relevant
		# Note: There is a DC cancel facility but it is not implemented for RTLSDR
	
		self.connect(self.osmosdr_source_block, self)
	
	def state_def(self, callback):
		super(OsmoSDRSource, self).state_def(callback)
		callback(Cell(self, 'freq', writable=True, ctor=float))
		callback(Cell(self, 'correction_ppm', writable=True, ctor=float))
		callback(Cell(self, 'agc', writable=True, ctor=bool))
		callback(Cell(self, 'gain', writable=True, ctor=float))
		
	def get_sample_rate(self):
		# TODO review why cast
		return int(self.osmosdr_source_block.get_sample_rate())
		
	def get_freq(self):
		return self.freq

	def set_freq(self, freq):
		actual_freq = self._compute_frequency(freq)
		# TODO: This limitation is in librtlsdr. If we support other gr-osmosdr devices, change it.
		maxint32 = 2**32 - 1
		if actual_freq < 0 or actual_freq > maxint32:
			raise ValueError, 'Frequency must be between 0 and ' + str(maxint32) + ' Hz'
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
