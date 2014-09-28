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

import os.path
import shutil
import tempfile

from twisted.internet import reactor
from twisted.trial import unittest

# from shinysdr.plugins import basic_demod
from shinysdr.plugins.simulate import SimulatedDevice
from shinysdr.top import Top

class DemodulatorSmokeTest(unittest.TestCase):
	def setUp(self):
		# Using a top block is the simplest way to set up the proper environment for a demodulator.
		self.__top = Top(devices={'s1': SimulatedDevice()})
	
	def __test(self, mode):
		self.__top.add_receiver(mode, key='a')
		self.__top.start()  # TODO overriding internals
		self.__top.stop()
	
	def test_iq(self):
		self.__test('IQ')
	
	def test_am(self):
		self.__test('AM')
	
	def test_nfm(self):
		self.__test('NFM')
	
	def test_wfm(self):
		self.__test('WFM')
	
	def test_lsb(self):
		self.__test('LSB')
	
	def test_usb(self):
		self.__test('USB')
	
	def test_cw(self):
		self.__test('CW')
