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


# TODO: It is unclear whether this module is a sensible division of the program. Think about it some more.


class SignalType(object):
	def __init__(self, sample_rate, kind):
		self.__sample_rate = float(sample_rate)
		self.__kind = unicode(kind)
	
	def get_sample_rate(self):
		'''Sample rate in samples per second.'''
		return self.__sample_rate
	
	def get_kind(self):
		# TODO will probably want to change this
		'''
		One of the 'IQ', 'USB', 'LSB', 'MONO', or 'STEREO'.
		
		Note that due to the current implementation, USB and LSB are complex with a zero Q component.
		'''
		return self.__kind


