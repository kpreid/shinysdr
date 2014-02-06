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

from twisted.trial import unittest
from twisted.internet import defer, reactor

from shinysdr.plugins.hamlib import connect_to_rig


class TestHamlibRig(unittest.TestCase):
	timeout = 5
	
	def setUp(self):
		d = connect_to_rig(reactor, options=['-m', '1'], port=4530)
		
		def on_connect(rig):
			self.__rig = rig
		
		d.addCallback(on_connect)
		return d
	
	def tearDown(self):
		return self.__rig.close()
	
	def test_noop(self):
		'''basic connect and disconnect, check is clean'''
		pass

	@defer.inlineCallbacks
	def test_getter(self):
		yield self.__rig.sync()
		self.assertEqual(self.__rig.state()['Frequency'].get(), 145e6)

	@defer.inlineCallbacks
	def test_setter(self):
		yield self.__rig.sync()
		self.__rig.state()['Frequency'].set(123e6)
		yield self.__rig.sync()
		self.assertEqual(self.__rig.state()['Frequency'].get(), 123e6)

	@defer.inlineCallbacks
	def test_sync(self):
		yield self.__rig.sync()
		yield self.__rig.sync()
