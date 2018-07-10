# Copyright 2015 Kevin Reid <kpreid@switchb.org>
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

from twisted.test.proto_helpers import StringTransport
from twisted.trial import unittest
from twisted.internet.task import Clock

from shinysdr.plugins.elecraft import _ElecraftClientProtocol
from shinysdr.test.testutil import state_smoke_test


class TestElecraftProtocol(unittest.TestCase):
    """Test _ElecraftClientProtocol and _ElecraftRadio.
    
    This test uses those implementation classes rather than the public interface because the public interface is hardcoded to attempt to open a serial device."""
    
    def setUp(self):
        self.clock = Clock()
        self.tr = StringTransport()
        self.protocol = _ElecraftClientProtocol(reactor=self.clock)
        self.proxy = self.protocol._proxy()
        self.protocol.makeConnection(self.tr)
        self.protocol.connectionMade()
    
    def test_state_smoke(self):
        state_smoke_test(self.proxy)
    
    def test_initial_send(self):
        self.assertIn('AI2;', self.tr.value())
        self.assertIn('K31;', self.tr.value())
        self.assertIn('IF;', self.tr.value())
    
    def test_simple_receive(self):
        self.protocol.dataReceived('FA00000000012;')
        self.assertEqual(12.0, self.proxy.get_rx_main().state()['freq'].get())
    
    def test_continues_after_bad_data(self):
        self.protocol.dataReceived('\x00\x00;;FA00000000012;')
        self.assertEqual(12.0, self.proxy.get_rx_main().state()['freq'].get())
    
    def test_not_too_much_polling(self):
        self.tr.clear()
        self.assertEqual('', self.tr.value())
        self.clock.pump([0.01] * 150)
        self.assertEqual('FA;', self.tr.value())
        self.clock.pump([0.01] * 500)
        self.assertEqual('FA;FA;FA;FA;FA;FA;', self.tr.value())
