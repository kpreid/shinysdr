# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

from gnuradio import gr


# TODO: It is unclear whether this module is a sensible division of the program. Think about it some more.


__all__ = []  # appended later


class SignalType(object):
	def __init__(self, sample_rate, kind):
		self.__sample_rate = float(sample_rate)
		self.__kind = unicode(kind)
		# TODO: validate args
	
	# TODO __eq__ and so on
	
	def get_sample_rate(self):
		'''Sample rate in samples per second.'''
		return self.__sample_rate
	
	def get_kind(self):
		# TODO will probably want to change this
		'''
		One of 'NONE', 'IQ', 'USB', 'LSB', 'MONO', or 'STEREO'.
		
		Note that due to the current implementation, USB and LSB are complex with a zero Q component.
		'''
		return self.__kind
	
	def get_itemsize(self):
		if self.__kind == 'NONE':
			return 0
		elif self.__kind == 'MONO' or self.__kind == 'STEREO':
			return gr.sizeof_float
		else:
			return gr.sizeof_gr_complex
	
	def is_analytic(self):
		'''Regardless of the signal being represented as gr_complex, does it have a two-sided spectrum?'''
		return self.__kind == 'IQ'
	
	def compatible_items(self, other):
		assert isinstance(other, SignalType)
		return self.get_itemsize() == other.get_itemsize()


__all__.append('SignalType')


__all__.append('no_signal')


no_signal = SignalType(kind='NONE', sample_rate=0.0)