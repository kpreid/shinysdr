from __future__ import absolute_import

from shinysdr.source import Source
from shinysdr.values import exported_value, setter, Range, Enum

import osmosdr


ch = 0  # single channel number used


class OsmoSDRProfile(object):
	'''
	Description of the characteristics of specific hardware which cannot
	be obtained automatically via OsmoSDR.
	'''
	def __init__(self, dc_offset=False, e4000=False):
		'''
		dc_offset: If true, the output has a DC offset and tuning should
		    the area around DC.
		e4000: The device is an RTL2832U + E4000 tuner and can be
		    confused into tuning to 0 Hz.
		'''
		# TODO: Propagate DC offset info to client tune() -- currently unused
		self.dc_offset = dc_offset
		self.e4000 = e4000


class OsmoSDRSource(Source):
	def __init__(self,
			osmo_device,
			name=None,
			profile=OsmoSDRProfile(),
			sample_rate=2400000,
			**kwargs):
		if name is None:
			name = 'OsmoSDR %s' % osmo_device
		Source.__init__(self, name=name, **kwargs)
		
		self.__osmo_device = osmo_device
		self.__profile = profile
		
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

	def get_sample_rate(self):
		# TODO review why cast
		return int(self.osmosdr_source_block.get_sample_rate())
	
	# TODO: apply correction_ppm to freq range
	@exported_value(ctor_fn=lambda self: convert_osmosdr_range(
		self.osmosdr_source_block.get_freq_range(ch), strict=False, add_zero=self.__profile.e4000))
	def get_freq(self):
		return self.freq

	@setter
	def set_freq(self, freq):
		actual_freq = self._compute_frequency(freq)
		self.freq = freq
		self._update_frequency()
		# TODO: According to OsmoSDR's interface, the frequency tuned to (get_center_freq) may not be the one we requested. Handle that.

	def get_tune_delay(slf):
		return 0.25  # TODO: make configurable and/or account for as many factors as we can

	@exported_value(ctor=float)
	def get_correction_ppm(self):
		return self.correction_ppm
	
	@setter
	def set_correction_ppm(self, value):
		self.correction_ppm = value
		# Not using the hardware feature because I only get garbled output from it
		#self.osmosdr_source_block.set_freq_corr(value, 0)
		self._update_frequency()
	
	def _compute_frequency(self, effective_freq):
		if effective_freq == 0.0 and self.__profile.e4000:
			# Quirk: Tuning to 3686.6-3730 MHz (on some tuner HW) causes operation effectively at 0Hz.
			# Original report: <http://www.reddit.com/r/RTLSDR/comments/12d2wc/a_very_surprising_discovery/>
			return 3700e6
		else:
			return effective_freq * (1 - 1e-6 * self.correction_ppm)
	
	def _update_frequency(self):
		self.osmosdr_source_block.set_center_freq(self._compute_frequency(self.freq), 0)
		# TODO: read back actual frequency and store
		
		self.tune_hook()

	# TODO: Perhaps expose individual gain stages.
	@exported_value(ctor_fn=lambda self: convert_osmosdr_range(
			self.osmosdr_source_block.get_gain_range(ch), strict=False))
	def get_gain(self):
		return self.osmosdr_source_block.get_gain(ch)
	
	@setter
	def set_gain(self, value):
		self.osmosdr_source_block.set_gain(float(value), ch)
	
	@exported_value(ctor=bool)
	def get_agc(self):
		return bool(self.osmosdr_source_block.get_gain_mode(ch))
	
	@setter
	def set_agc(self, value):
		self.osmosdr_source_block.set_gain_mode(bool(value), ch)
	
	@exported_value(ctor_fn=lambda self: Enum(
		{unicode(name): unicode(name) for name in self.osmosdr_source_block.get_antennas()}))
	def get_antenna(self):
		return unicode(self.osmosdr_source_block.get_antenna(ch))
		# TODO review whether set_antenna is safe to expose
	
	# Note: dc_cancel has a 'manual' mode we are not yet exposing
	@exported_value(ctor=bool)
	def get_dc_cancel(self):
		return bool(self.dc_state)
	
	@setter
	def set_dc_cancel(self, value):
		self.dc_state = bool(value)
		if self.dc_state:
			mode = 2  # automatic mode
		else:
			mode = 0
		self.osmosdr_source_block.set_dc_offset_mode(mode, ch)
	
	# Note: iq_balance has a 'manual' mode we are not yet exposing
	@exported_value(ctor=bool)
	def get_iq_balance(self):
		return bool(self.iq_state)

	@setter
	def set_iq_balance(self, value):
		self.iq_state = bool(value)
		if self.iq_state:
			mode = 2  # automatic mode
		else:
			mode = 0
		self.osmosdr_source_block.set_iq_balance_mode(mode, ch)
	
	@exported_value(ctor_fn=lambda self: convert_osmosdr_range(
		self.osmosdr_source_block.get_bandwidth_range(ch)))
	def get_bandwidth(self):
		return self.osmosdr_source_block.get_bandwidth(ch)
	
	@setter
	def set_bandwidth(self, value):
		self.osmosdr_source_block.set_bandwidth(float(value), ch)


def convert_osmosdr_range(meta_range, add_zero=False, **kwargs):
	subranges = []
	for i in xrange(0, meta_range.size()):
		range = meta_range[i]
		subranges.append((range.start(), range.stop()))
	if add_zero:
		subranges[0:0] = [(0, 0)]
	return Range(subranges, **kwargs)
