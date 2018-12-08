# Copyright 2014, 2018 Kevin Reid and the ShinySDR contributors
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

from shinysdr.plugins.multimon import FMAPRSDemodulator
from shinysdr.test.testutil import DemodulatorTestCase


class TestFMAPRSDemodulator(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='APRS', skip_if_unavailable=True, demod_class=FMAPRSDemodulator)
    
    def tearDown(self):
        self.demodulator._close()  # TODO temporary kludge!!! Clean up in a way that actually works in non-tests!
