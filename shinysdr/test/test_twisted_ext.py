# Copyright 2016 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.twisted_ext import fork_deferred, test_subprocess


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
        self.assertTrue(test_subprocess(['echo', 'x'], 'x', shell=False))

    def test_stdout_failure(self):
        self.assertFalse(test_subprocess(['echo', 'y'], 'x', shell=False))

    # TODO test command-not-found
    # TODO test stderr
    # TODO test shell mode
