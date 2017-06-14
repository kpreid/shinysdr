# Copyright 2017 Phil Frost <indigo@bitglue.com>
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

from zope.interface import implementer
from zope.interface.verify import verifyObject

from twisted.internet import defer
from twisted.trial import unittest
from twisted.internet import task

from shinysdr.plugins.wspr.blocks import WSPRFilter, WAVIntervalSink
from shinysdr.plugins.wspr.interfaces import IWAVIntervalListener


class TestWSPRFilter(unittest.TestCase):
    def test_for_smoke(self):
        WSPRFilter(48000)


class TestWAVIntervalSink(unittest.TestCase):
    def setUp(self):
        self.clock = task.Clock()

        self.listener = FakeListener()

        self.sink = WAVIntervalSink(
            interval=120,
            duration=115,
            listener=self.listener,
            sample_rate=48000,

            _callLater=self.clock.callLater,
            _time=self.clock.seconds,
            _deferToThread=self.deferToThread,
        )

    def deferToThread(self, f, *args, **kwargs):
        """What thread?"""
        return defer.succeed(f(*args, **kwargs))

    def test_listener_interface(self):
        verifyObject(IWAVIntervalListener, self.listener)

    def advance_to_next_interval(self):
        self.clock.advance(120 - (self.clock.seconds() % 120))

    def test_time(self):
        self.sink.start_running()

        # initially nothing has happened.
        self.assertFalse(self.listener._filesClosed)
        self.assertFalse(self.listener._filesOpened)

        # start of first interval.
        self.advance_to_next_interval()
        self.assertEqual(self.listener._filesOpened, ['120'])

        # just before end of first interval.
        self.clock.advance(114)
        self.assertEqual(self.listener._filesClosed, [])

        # end of first interval.
        self.clock.advance(1)
        self.assertEqual(self.listener._filesClosed, ['120'])

        # next interval begins.
        self.advance_to_next_interval()
        self.assertEqual(self.listener._filesOpened, ['120', '240'])
        self.assertEqual(self.listener._filesClosed, ['120'])

    def test_start(self):
        # nothing is scheduled
        self.assertFalse(self.clock.getDelayedCalls())

        # until we start it
        self.sink.start_running()
        self.assertEqual(len(self.clock.getDelayedCalls()), 1)

        # and starting it again doesn't start it twice.
        self.sink.start_running()
        self.assertEqual(len(self.clock.getDelayedCalls()), 1)

    # More things to test, but so little time.
    #
    # What if interval == duration? (Currently undefined behavior)
    #
    # What if there's an error in opening or closing the wav file?
    #
    # Are the interactions with the wavfile_sink block being done in a thread?
    # They block on aquiring locks and file IO.
    #
    # Are the internal connections sane?


@implementer(IWAVIntervalListener)
class FakeListener(object):
    def __init__(self):
        self._filesOpened = []
        self._filesClosed = []

    def fileClosed(self, filename):
        self._filesClosed.append(filename)

    def fileOpened(self, filename):
        self._filesOpened.append(filename)

    def filename(self, time):
        return str(int(time))
