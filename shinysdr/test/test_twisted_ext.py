# -*- coding: utf-8 -*-
# Copyright 2016, 2018 Kevin Reid and the ShinySDR contributors
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

import textwrap

from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.internet import reactor as the_reactor

from shinysdr.twisted_ext import SerialPortEndpoint, fork_deferred, test_subprocess


class TestForkDeferred(unittest.TestCase):
    def test_success(self):
        outcomes = []
        d = defer.Deferred()
        d2 = fork_deferred(d)
        d.addCallback(lambda x: outcomes.append('dc ' + x))
        d2.addCallback(lambda x: outcomes.append('d2c ' + x))
        self.assertEquals(outcomes, [])
        d.callback('value')
        self.assertEquals(outcomes, ['d2c value', 'dc value'])
    
    # TODO test of errback, stricter tests(?)


class TestTestSubprocess(unittest.TestCase):
    def test_stdout_success(self):
        self.assertFalse(test_subprocess(['echo', 'x'], b'x', shell=False))
    
    def test_stdout_failure(self):
        self.assertEquals(test_subprocess(['echo', 'y•'], b'x', shell=False),
            textwrap.dedent("""\
                Expected `echo y•` to give output containing 'x', but the actual output was:
                y•
                """))
    
    # TODO test command-not-found
    # TODO test stderr
    # TODO test shell mode


class TestSerialPortEndpoint(unittest.TestCase):
    # We cannot rely on the existence of any serial ports or it being OK to try to open them, so this is just a smoke test: does creating the endpoint succeed?
    
    def test_smoke(self):
        endpoint = SerialPortEndpoint('NOTAREALSERIALPORT', the_reactor, baudrate=115200)
        IStreamClientEndpoint(endpoint)
    
    # TODO consider making an attempt to open that is known to fail
