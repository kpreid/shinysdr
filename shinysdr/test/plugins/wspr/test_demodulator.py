# -*- coding: utf-8 -*-
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

import os
from textwrap import dedent

from zope.interface import implementer
from zope.interface.verify import verifyObject

from twisted.trial import unittest
from twisted.internet.interfaces import IProcessProtocol
from twisted.internet import defer
from twisted.internet.task import Clock

from gnuradio import gr

from shinysdr.interfaces import IDemodulator, IDemodulatorContext
from shinysdr.values import LooseCell

from shinysdr.plugins.wspr.demodulator import (
    _STATUS_IDLE,
    _STATUS_RECEIVING,
    _STATUS_DECODING,
    _STATUS_DECODING_AND_RECEIVING,
    WAVIntervalListener, WSPRDemodulator, WsprdProtocol)
from shinysdr.plugins.wspr.interfaces import IWAVIntervalListener


class FakeWavfileSink(object):
    def __init__(self, filename, n_channels, sample_rate, bits_per_sample):
        self._filename = filename
        self._n_channels = n_channels
        self._sample_rate = sample_rate
        self._bits_per_sample = bits_per_sample

        self._events = []

    def open(self, filename):
        self._events.append(('open', filename))
        self._filename = filename

    def close(self):
        self._events.append('close')
        self._filename = None


@implementer(IDemodulatorContext)
class FakeContext(object):
    def __init__(self):
        self.messages = []
        # 12,345,678 Hz, all the time, every day.
        self.__absolute_frequency_cell = LooseCell(
            value=12345678,
            type=float,
            writable=False,
            persists=False)
        
        verifyObject(IDemodulatorContext, self)  # Ensure we are a good fake.

    def rebuild_me(self):
        raise Exception('not implemented')

    def lock(self):
        raise Exception('not implemented')

    def unlock(self):
        raise Exception('not implemented')

    def get_absolute_frequency_cell(self):
        return self.__absolute_frequency_cell

    def output_message(self, message):
        self.messages.append(message)


class TestIntervalListener(unittest.TestCase):
    audio_frequency = 1234
    wsprd_path = '/here/is/wsprd'

    def setUp(self):
        self.directory = self.mktemp()
        os.mkdir(self.directory)
        self.context = FakeContext()
        self.clockAndSpawn = Clock()
        self.clockAndSpawn.spawnProcess = self.spawnProcess
        self.spawned = []

        self.listener = WAVIntervalListener(
            self.directory,
            self.context,
            self.audio_frequency,

            _find_wsprd=self.find_wsprd,
            _time=self.time,
            _reactor=self.clockAndSpawn)

    def time(self):
        """Return some unix timestamp."""
        return 123987901.7

    def find_wsprd(self):
        return self.wsprd_path

    def spawnProcess(self,
            processProtocol,
            executable,
            args,
            env,
            path):
        self.spawned.append((processProtocol, executable, args, env, path))

    def test_interface(self):
        verifyObject(IWAVIntervalListener, self.listener)

    def test_filename(self):
        # Mon Jun  5 00:54:00 UTC 2017
        test_time = 1496624040.0
        filename = self.listener.filename(test_time)

        # frequency_YYMMDD_HHMM.wav
        self.assertEqual(filename, os.path.join(self.directory, '12345678_170605_0054.wav'))

    def test_fileOpened(self):
        self.assertEqual(self.listener.get_status(), _STATUS_IDLE)
        self.listener.fileOpened('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_RECEIVING)

    def test_fileClosed(self):
        self.listener.fileOpened('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_RECEIVING)
        self.listener.fileClosed('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_DECODING)
        self.assertEqual(len(self.spawned), 1)

        protocol, executable, args, _, path = self.spawned[0]

        self.assertEqual(protocol.wav_filename, 'some file')
        self.assertEqual(protocol.decode_time, self.time())

        self.assertEqual(executable, self.wsprd_path)

        rx_frequency = self.context.get_absolute_frequency_cell().get()
        dial_frequency = (rx_frequency - self.audio_frequency) / 1e6
        self.assertIn(str(dial_frequency), args)

        self.assertEqual(path, self.directory)
        
        protocol.processEnded(None)
        self.assertEqual(self.listener.get_status(), _STATUS_IDLE)

    def test_frequency_change(self):
        """If the frequency changes during the recording, don't decode it.

        We especially wouldn't want to upload spots for one band when they
        happened on another.
        """
        self.listener.fileOpened('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_RECEIVING)
        self.context.get_absolute_frequency_cell().set_internal(654321)
        self.clockAndSpawn.advance(1)  # Allow cell subscription to fire.
        self.assertEqual(self.listener.get_status(), _STATUS_IDLE)
        self.listener.fileClosed('some file')
        self.assertFalse(self.spawned)
        self.assertEqual(self.listener.get_status(), _STATUS_IDLE)

    def test_decode_runs_long_status(self):
        """Confirm expected behavior if decode and receive overlap."""
        self.listener.fileOpened('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_RECEIVING)

        self.listener.fileClosed('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_DECODING)

        self.listener.fileOpened('some file')
        self.assertEqual(self.listener.get_status(), _STATUS_DECODING_AND_RECEIVING)

        protocol, _, _, _, _ = self.spawned[0]
        protocol.processEnded(None)
        self.assertEqual(self.listener.get_status(), _STATUS_RECEIVING)


class FakeWAVIntervalSink(gr.hier_block2):
    def __init__(self, interval, duration, listener, sample_rate):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float),
            gr.io_signature(0, 0, 0))

    def start_running(self):
        pass


# TODO: Enable this once we can clean up afterward
# class TestDemodulatorBasic(DemodulatorTestCase):
#     def setUp(self):
#         self.setUpFor('WSPR', demod_class=WSPRDemodulator)


class TestDemodulatorSpecific(unittest.TestCase):
    tempdir = None

    def setUp(self):
        self.demodulator = WSPRDemodulator(
            'WSPR',
            48000,
            None,
            _WAVIntervalSink=FakeWAVIntervalSink,
            _mkdtemp=self._mkdtemp,
            _find_wsprd=lambda: '/here/is/wsprd')

    def _mkdtemp(self):
        self.tempdir = self.mktemp()
        os.mkdir(self.tempdir)
        return self.tempdir

    def test_interface(self):
        demodulator = WSPRDemodulator(
            'WSPR',
            48000,
            None,
            _WAVIntervalSink=FakeWAVIntervalSink,
            _find_wsprd=lambda: '/here/is/wsprd')
        verifyObject(IDemodulator, demodulator)

    def test_temporary_directory(self):
        self.assertTrue(os.path.isdir(self.tempdir))
        self.demodulator.close()
        self.assertFalse(os.path.exists(self.tempdir))

    def test_temporary_directory_already_deleted(self):
        """It's OK if the temp directory has been deleted before cleanup."""
        os.rmdir(self.tempdir)
        self.demodulator.close()


class TestWsprdProtocol(unittest.TestCase):
    def setUp(self):
        self.context = FakeContext()
        self.wavfile = self.mktemp()
        self.threads = ThreadDeferrer()
        open(self.wavfile, 'w').write('fake wav file\n')
        self.proto = WsprdProtocol(self.context, self.wavfile, self.time(), defer.Deferred())
        self.proto._deferToThread = self.threads

    def test_interface(self):
        verifyObject(IProcessProtocol, self.proto)

    def time(self):
        """Return some unix timestamp."""
        return 179823128.3

    def test_one_spot(self):
        self.proto.outReceived('2322 -21  1.5   14.097110  -1  WA7MOX EL16 33\n')
        self.assertEqual(len(self.context.messages), 1)

        message = self.context.messages[0]
        self.assertEqual(message.time, self.time())
        self.assertEqual(message.snr, -21)
        self.assertEqual(message.dt, 1.5)
        self.assertEqual(message.frequency, 14.09711)
        self.assertEqual(message.drift, -1)
        self.assertEqual(message.call, 'WA7MOX')
        self.assertEqual(message.grid, 'EL16')
        self.assertEqual(message.txpower, 33)

    def test_indirect_call(self):
        """<call> becomes call

        For calls or grids that don't fit in one interval, WSPR can transmit in
        two intervals. When this happens, wsprd will report the call with
        <brackets> around it. This isn't really what we want to see on the map.
        """
        self.proto.outReceived('2322 -21  1.5   14.097110  -1  <WA7MOX> EL16 33\n')
        self.assertEqual(len(self.context.messages), 1)
        message = self.context.messages[0]
        self.assertEqual(message.call, 'WA7MOX')

    def test_unknown_call(self):
        """<...> as a call translates to None

        If there's a two-part transmission but wsprd is missing the first part
        and thus does not have the call, it will output <...>.
        """
        self.proto.outReceived('2322 -21  1.5   14.097110  -1  <...> EL16 33\n')
        self.assertEqual(len(self.context.messages), 1)
        message = self.context.messages[0]
        self.assertEqual(message.call, None)

    def test_malformed_line(self):
        """A malformed line is ignored."""
        self.proto.outReceived(dedent("""
            2322 -21  1.5   14.097110  -1  <WA7MOX> EL16 33
            garbage
            2322 -22  1.5   14.097130  -1  <W8II> EN82 20
        """))
        self.assertEqual(len(self.context.messages), 2)
        self.assertEqual(self.context.messages[0].call, 'WA7MOX')
        self.assertEqual(self.context.messages[1].call, 'W8II')

    def test_line_in_parts(self):
        """A single line may arrive in pieces."""
        self.proto.outReceived('2322 -21  1.5   14.097110  ')
        self.assertEqual(len(self.context.messages), 0)
        self.proto.outReceived('-1  WA7MOX EL16 33\n')
        self.assertEqual(len(self.context.messages), 1)
        message = self.context.messages[0]
        self.assertEqual(message.call, 'WA7MOX')

    def test_deletes_file(self):
        """The WAV file is deleted after processing."""
        self.proto.processEnded(None)
        self.assertTrue(os.path.exists(self.wavfile))
        self.threads.run_threads()
        self.assertFalse(os.path.exists(self.wavfile))


class ThreadDeferrer(object):
    """Imitation of reactor.deferToThread that doesn't use threads."""
    def __init__(self):
        self.deferred_to_thread = []

    def __call__(self, f, *args, **kwargs):
        d = defer.Deferred()
        self.deferred_to_thread.append((f, args, kwargs, d))
        return d

    def run_threads(self):
        for f, args, kwargs, d in self.deferred_to_thread:
            d.callback(f(*args, **kwargs))
        self.deferred_to_thread = []
