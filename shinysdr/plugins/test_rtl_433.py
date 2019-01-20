# Copyright 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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

import six

from twisted.trial import unittest

from shinysdr.plugins.rtl_433 import RTL433Demodulator, RTL433ProcessProtocol
from shinysdr.testutil import DemodulatorTestCase, LogTester


class TestRTL433Demodulator(DemodulatorTestCase):
    def setUp(self):
        self.setUpFor(mode='rtl_433', skip_if_unavailable=True, demod_class=RTL433Demodulator)
    
    def tearDown(self):
        self.demodulator._close()  # TODO temporary kludge!!! Clean up in a way that actually works in non-tests!


class TestRTL433Protocol(unittest.TestCase):
    """Check behavior of protocol object against fixed test data."""
    timeout = 5
    
    def setUp(self):
        self.log_tester = LogTester()
        self.received = []
        self.protocol = RTL433ProcessProtocol(target=self.received.append, log=self.log_tester.log)
    
    def test_success(self):
        self.protocol.outReceived(b'{"foo":"bar"}\n')
        if six.PY2:
            self.log_tester.check(dict(text="rtl_433 message: {u'foo': u'bar'}"))
        else:
            self.log_tester.check(dict(text="rtl_433 message: {'foo': 'bar'}"))
        self.assertEqual(len(self.received), 1)
    
    def test_not_json(self):
        self.protocol.outReceived(b'foo\n')
        self.log_tester.check(dict(text="bad JSON from rtl_433: 'foo'"))
        self.assertEqual(self.received, [])
