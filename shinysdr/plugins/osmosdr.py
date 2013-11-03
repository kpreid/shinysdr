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

from __future__ import absolute_import

from shinysdr.source import Source
from shinysdr.values import exported_value, setter, Range, Enum

import osmosdr


ch = 0  # single channel number used


# TODO: Allow profiles to export information about known spurious signals in receivers, in the form of a freq-DB. Note that they must be flagged as uncalibrated freqs.
# Ex: Per <http://www.reddit.com/r/RTLSDR/comments/1nl3tl/has_anybody_done_a_comparison_of_where_the_spurs/> all RTL2832U have harmonics of 28.8MHz and 48MHz.


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
	# TODO remove Source superclass overall
	def __init__(self,
			osmo_device,
			name=None,
			profile=OsmoSDRProfile(),
			sample_rate=None,
			**kwargs):
		'''
		osmo_device: gr-osmosdr device string
		name: block name (usually not specified)
		profile: an OsmoSDRProfile (see docs)
		sample_rate: desired sample rate, or None == maximum available rate.
		'''
		if name is None:
			name = 'OsmoSDR %s' % osmo_device
		Source.__init__(self, name=name, **kwargs)
		
		self.__osmo_device = osmo_device
		self.__profile = profile
		
		self.freq = freq = 98e6
		self.external_freq_shift = 0
		self.correction_ppm = 0
		self.dc_state = 0
		self.iq_state = 0
		
		self.osmosdr_source_block = source = osmosdr.source("nchan=1 " + osmo_device)
		# Note: Docs for these setters at gr-osmosdr/lib/source_iface.h
		if sample_rate is None:
			source.set_sample_rate(source.get_sample_rates().stop())
		else:
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
		self.osmosdr_source_block.get_freq_range(ch),
		strict=False,
		transform=lambda f: self._invert_frequency(f),
		add_zero=self.__profile.e4000))
	def get_freq(self):
		return self.freq

	@setter
	def set_freq(self, freq):
		self.freq = freq
		self._update_frequency()

	def get_tune_delay(slf):
		return 0.25  # TODO: make configurable and/or account for as many factors as we can
	
	@exported_value(ctor=float)
	def get_external_freq_shift(self):
		return self.external_freq_shift
	
	@setter
	def set_external_freq_shift(self, value):
		self.external_freq_shift = float(value)
		self._update_frequency()
	
	@exported_value(ctor=float)
	def get_correction_ppm(self):
		return self.correction_ppm
	
	@setter
	def set_correction_ppm(self, value):
		self.correction_ppm = float(value)
		# Not using the osmosdr feature because changing it at runtime produces glitches like the sample rate got changed
		#self.osmosdr_source_block.set_freq_corr(value, 0)
		self._update_frequency()
	
	def _compute_frequency(self, effective_freq):
		effective_freq += self.external_freq_shift
		if abs(effective_freq) < 1e-2 and self.__profile.e4000:
			# Quirk: Tuning to 3686.6-3730 MHz on the E4000 causes operation effectively at 0Hz.
			# Original report: <http://www.reddit.com/r/RTLSDR/comments/12d2wc/a_very_surprising_discovery/>
			return 3700e6
		else:
			return effective_freq * (1 - 1e-6 * self.correction_ppm)
	
	def _invert_frequency(self, freq):
		'''hardware frequency to displayed frequency, inverse of _compute_frequency'''
		freq = freq / (1 - 1e-6 * self.correction_ppm)
		if 3686.6e6 <= freq <= 3730e6 and self.__profile.e4000:
			freq = 0.0
		freq -= self.external_freq_shift
		return freq
	
	def _update_frequency(self):
		self.osmosdr_source_block.set_center_freq(self._compute_frequency(self.freq), 0)
		
		# update freq to what osmosdr reported, but only if the difference is large enough that it probably isn't just FP error in the corrections
		# TODO: This doesn't seem to be working quite right so has been disabled for now. Need to more precisely examine whether it's actually broken (osmosdr being too asynchronous?) or whether our UI is rounding wrong (or similar).
		#tuned_freq = self._invert_frequency(self.osmosdr_source_block.get_center_freq())
		#if abs(tuned_freq - self.freq) > 1e-10:
		#	self.freq = tuned_freq
		
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


def convert_osmosdr_range(meta_range, add_zero=False, transform=lambda f: f, **kwargs):
	subranges = []
	for i in xrange(0, meta_range.size()):
		range = meta_range[i]
		subranges.append((transform(range.start()), transform(range.stop())))
	if add_zero:
		subranges[0:0] = [(0, 0)]
	return Range(subranges, **kwargs)
