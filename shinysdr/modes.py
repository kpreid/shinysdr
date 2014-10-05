# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=no-method-argument, no-init
# (pylint is confused by interfaces)

from __future__ import absolute_import, division

from twisted.plugin import IPlugin, getPlugins
from zope.interface import Interface, implements  # available via Twisted

from shinysdr import plugins


__all__ = []  # appended later


class IDemodulator(Interface):
	def can_set_mode(mode):
		'''
		Return whether this demodulator can reconfigure itself to demodulate the specified mode.
		
		If it returns False, it will typically be replaced with a newly created demodulator.
		'''
	
	def set_mode(mode):
		'''
		Per can_set_mode.
		'''
	
	def get_half_bandwidth():
		'''
		TODO explain
		'''
	
	def get_output_type():
		'''
		Return the SignalType of the demodulator's output, which must currently be stereo audio at any sample rate.
		'''


__all__.append('IDemodulator')


class ITunableDemodulator(IDemodulator):
	def set_rec_freq(freq):
		'''
		Set the nominal (carrier) frequency offset of the signal to be demodulated within the input signal.
		'''


__all__.append('ITunableDemodulator')


class _IModeDef(Interface):
	'''
	Demodulator plugin interface object
	'''
	# Only needed to make the plugin system work
	# TODO write interface methods anyway


class ModeDef(object):
	implements(IPlugin, _IModeDef)
	
	# Twisted plugin system caches whether-a-plugin-class-was-found permanently, so we need to avoid _not_ having a ModeDef if the plugin has some sort of dependency it checks -- thus the 'available' flag can be used to hide a mode while still having an _IModeDef
	def __init__(self, mode, label, demodClass, available=True):
		self.mode = mode
		self.label = label
		self.demodClass = demodClass
		self.available = available


__all__.append('ModeDef')


def get_modes():
	# TODO caching? prebuilt mode table?
	return [p for p in getPlugins(_IModeDef, plugins) if p.available]


__all__.append('get_modes')


def lookup_mode(mode):
	# TODO sensible lookup table (doesn't matter for now because small N)
	for mode_def in get_modes():
		if mode_def.mode == mode:
			return mode_def
	return None


__all__.append('lookup_mode')
