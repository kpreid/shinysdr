# Copyright 2017 Kevin Reid and the ShinySDR contributors
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

from twisted.trial import unittest

from shinysdr.i.modes import lookup_mode
from shinysdr.i.top import Top
from shinysdr.plugins.simulate import SimulatedDevice
from shinysdr.test.testutil import state_smoke_test


class TestReceiver(unittest.TestCase):
    def setUp(self):
        self.top = Top(devices={'s1': SimulatedDevice()})
        (_key, self.receiver) = self.top.add_receiver('AM', key='a')
    
    def tearDown(self):
        self.top.close_all_devices()

    def test_smoke(self):
        state_smoke_test(self.receiver)

    def test_no_audio_demodulator(self):
        """Smoke test for demodulator with no audio output."""
        # TODO: Allow parameterizing with a different mode table so that we can use a test stub mode rather than a real one. Also fix rtl_433 leaving unclean reactor.
        for mode in ['MODE-S']:
            if lookup_mode(mode):
                self.receiver.set_mode(mode)
                break
        else:
            raise unittest.SkipTest('No no-audio mode available.')
