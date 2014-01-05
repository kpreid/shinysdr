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

from twisted.trial import unittest

from shinysdr.top import Top
from shinysdr.plugins import simulate


class TestTop(unittest.TestCase):
	def test_source_switch_update(self):
		'''
		Regression test: Switching sources was not updating receiver input frequency.
		'''
		top = Top(sources={
			's1': simulate.SimulatedSource(freq=0),
			's2': simulate.SimulatedSource(freq=1e6),
		})
		top.set_source_name('s1')
		(_, receiver) = top.add_receiver('AM', key='a')
		receiver.set_rec_freq(1e6)
		self.assertFalse(receiver.get_is_valid())
		top.set_source_name('s2')
		self.assertTrue(receiver.get_is_valid())
