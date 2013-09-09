from __future__ import absolute_import

from sdr.source import Source
from sdr.values import Cell, Range, Enum

import osmosdr


ch = 0  # single channel number used


class OsmoSDRSource(Source):
	def __init__(self,
			osmo_device,
			name='OsmoSDR Source',
			sample_rate=2400000,
			**kwargs):
		Source.__init__(self, name=name, **kwargs)
		
		self.__osmo_device = osmo_device
		
		self.freq = freq = 98e6
		self.correction_ppm = 0
		self.dc_state = 0
		self.iq_state = 0
		
		self.osmosdr_source_block = source = osmosdr.source("nchan=1 " + osmo_device)
		# Note: Docs for these setters at gr-osmosdr/lib/source_iface.h
		source.set_sample_rate(sample_rate)
		source.set_center_freq(freq, ch)
		# freq_corr: We implement correction internally because setting this at runtime breaks things
		source.set_dc_offset_mode(self.dc_state, ch)  # no getter, set to known state
		source.set_iq_balance_mode(self.iq_state, ch)  # no getter, set to known state
		# Note: DC cancel facility is not implemented for RTLSDR
	
		self.connect(self.osmosdr_source_block, self)
	
	def __str__(self):
		return 'OsmoSDR ' + self.__osmo_device

	def state_def(self, callback):
		super(OsmoSDRSource, self).state_def(callback)
		# TODO: apply correction_ppm to freq range
		# TODO: understand range gaps and artificially insert 0Hz tuning point when applicable
		callback(Cell(self, 'freq', writable=True, ctor=convert_osmosdr_range(
			self.osmosdr_source_block.get_freq_range(ch), strict=False)))
		callback(Cell(self, 'correction_ppm', writable=True, ctor=float))
		# TODO: Perhaps expose individual gain stages.
		callback(Cell(self, 'gain', writable=True, ctor=convert_osmosdr_range(
			self.osmosdr_source_block.get_gain_range(ch), strict=False)))
		callback(Cell(self, 'agc', writable=True, ctor=bool))
		callback(Cell(self, 'antenna', ctor=Enum(
			{unicode(name): unicode(name) for name in self.osmosdr_source_block.get_antennas()})))
		# Note: dc_cancel and iq_balance have 'manual' modes we are not exposing
		callback(Cell(self, 'dc_cancel', writable=True, ctor=bool))
		callback(Cell(self, 'iq_balance', writable=True, ctor=bool))
		callback(Cell(self, 'bandwidth', writable=True, ctor=convert_osmosdr_range(
			self.osmosdr_source_block.get_bandwidth_range(ch))))
		
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
		# TODO: According to OsmoSDR's interface, the frequency tuned to (get_center_freq) may not be the one we requested. Handle that.

	def get_tune_delay(slf):
		return 0.25  # TODO: make configurable and/or account for as many factors as we can

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

	def get_gain(self):
		return self.osmosdr_source_block.get_gain(ch)
	
	def set_gain(self, value):
		self.osmosdr_source_block.set_gain(float(value), ch)
	
	def get_agc(self):
		return bool(self.osmosdr_source_block.get_gain_mode(ch))
	
	def set_agc(self, value):
		self.osmosdr_source_block.set_gain_mode(bool(value), ch)
	
	def get_antenna(self):
		return unicode(self.osmosdr_source_block.get_antenna(ch))
		# TODO review whether set_antenna is safe to expose
	
	def get_dc_cancel(self):
		return bool(self.dc_state)
	
	def set_dc_cancel(self, value):
		self.dc_state = bool(value)
		if self.dc_state:
			mode = 2  # automatic mode
		else:
			mode = 0
		self.osmosdr_source_block.set_dc_offset_mode(mode, ch)
	
	def get_iq_balance(self):
		return bool(self.iq_state)
	
	def set_iq_balance(self, value):
		self.iq_state = bool(value)
		if self.iq_state:
			mode = 2  # automatic mode
		else:
			mode = 0
		self.osmosdr_source_block.set_iq_balance_mode(mode, ch)
	
	def get_bandwidth(self):
		return self.osmosdr_source_block.get_bandwidth(ch)
	
	def set_bandwidth(self, value):
		self.osmosdr_source_block.set_bandwidth(float(value), ch)


def convert_osmosdr_range(meta_range, **kwargs):
	if len(meta_range.values()) == 0:
		# If we don't check this condition, start() and stop() will raise
		# TODO better stub value
		return Range(-1, -1, **kwargs)
	else:
		# Note: meta_range may have gaps and we don't yet represent that
		return Range(meta_range.start(), meta_range.stop(), **kwargs)
