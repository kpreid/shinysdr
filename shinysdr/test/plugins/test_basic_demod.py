# Copyright 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

from shinysdr.test.testutil import DemodulatorTestCase


class TestIQ(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='IQ')


class TestAM(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='AM')


class TestUnselectiveAM(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='AM-unsel')


class TestNFM(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='NFM')


class TestWFM(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='WFM')


class TestLSB(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='LSB')


class TestUSB(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='USB')


class TestCW(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='CW')
