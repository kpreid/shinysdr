# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division, unicode_literals

from twisted.trial import unittest

from shinysdr.i.session import Session
from shinysdr.i.top import Top
from shinysdr.plugins.simulate import SimulatedDevice
from shinysdr.test.testutil import state_smoke_test


class TestSession(unittest.TestCase):
    def test_state_smoke(self):
        state_smoke_test(Session(
            receive_flowgraph=Top(devices={'s1': SimulatedDevice()}),
            features={}))
