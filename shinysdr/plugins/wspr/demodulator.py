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

"""WSPR demodulator; glue between GNU Radio and ShinySDR."""

from __future__ import absolute_import, division, unicode_literals

import os.path
import time
import tempfile
import shutil
import errno

from gnuradio import gr

from twisted.internet import defer, reactor, threads
from twisted.internet.protocol import ProcessProtocol
from twisted.python import log
from zope.interface import implementer

from shinysdr.values import ExportedState, SubscriptionContext, exported_value
from shinysdr.interfaces import IDemodulator, BandShape
from shinysdr.signals import SignalType

from .blocks import WAVIntervalSink, WSPRFilter
from .interfaces import IWAVIntervalListener
from .telemetry import WSPRSpot


def find_wsprd():
    path = os.environ.get('PATH', os.pathsep.join(['/usr/local/bin', '/usr/bin', '/bin']))
    for directory in path.split(':'):
        maybe_wsprd = os.path.join(directory, 'wsprd')
        if os.path.isfile(maybe_wsprd) and os.access(maybe_wsprd, os.X_OK):
            return maybe_wsprd

    return None


@implementer(IDemodulator)
class WSPRDemodulator(gr.hier_block2, ExportedState):
    """Decode WSPR (Weak Signal Propagation Reporter).

    Requires `wsprd` to be installed, which is available as part of WSJT-X:

    https://physics.princeton.edu/pulsar/k1jt/wsjtx.html
    """

    # wsprd requires wav files at 12kHz sample rates. The WSPR band is 200 Hz
    # wide, centered on 1500 Hz in the recording. Need to confirm this, but I
    # suspect it doesn't try to decode much outside that range.
    #
    # Our job is to make those recordings, starting on even minutes. Then they
    # are passed to `wsprd` to do the decoding.
    __demod_rate = 12000

    # wsprd requires the WSPR band to be centered on 1500 Hz in its WAV file
    # input.
    __audio_frequency = 1500

    # transmission interval, in seconds. 2 minutes for WSPR. Might be adapted
    # to other JT modes which use other intervals.
    __interval = 120
    __duration = __interval - 5

    def __init__(self,
            mode='WSPR',
            input_rate=0,
            context=None,

            _mkdtemp=tempfile.mkdtemp,
            _WAVIntervalSink=WAVIntervalSink,
            _find_wsprd=find_wsprd):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float))
        self.__context = context
        self.__find_wsprd = _find_wsprd

        # it's not great doing this in the reactor since it could block.
        # However, so can creating GNU Radio blocks.
        self.__recording_dir = _mkdtemp()

        wspr_filter = WSPRFilter(input_rate, output_frequency=self.__audio_frequency)

        self.__listener = WAVIntervalListener(
            self.__recording_dir,
            context,
            self.__audio_frequency,
            _find_wsprd=self.__find_wsprd)

        self.connect(
            self,
            wspr_filter,
            self)

        self.connect(
            wspr_filter,
            self.__make_wav_sink(context, _WAVIntervalSink))

    # TODO: Make a better way to forward to a cell than overriding state_def
    def state_def(self):
        for d in super(WSPRDemodulator, self).state_def():
            yield d
        yield 'status', self.__listener.state()['status']

    def __make_wav_sink(self, context, _WAVIntervalSink):
        wav_sink = _WAVIntervalSink(
            interval=self.__interval,
            duration=self.__duration,
            listener=self.__listener,
            sample_rate=self.__demod_rate)

        # would be cool to not have side effects in __init__, though there
        # doesn't seem to be a way around it with the current demodulator
        # interface.
        wav_sink.start_running()
        return wav_sink

    @exported_value(type=BandShape, changes='never')
    def get_band_shape(self):
        """Implement IDemodulator."""
        return BandShape(
            stop_low=-250,
            pass_low=-100,
            stop_high=250,
            pass_high=100,
            markers=[])

    def get_output_type(self):
        """Implement IDemodulator."""
        return SignalType(kind='MONO', sample_rate=self.__demod_rate)

    def close(self):
        """Clean up temporary files.

        ShinySDR doesn't actually call this, so we rely on __del__ to
        (probably) call it eventually.
        """
        if self.__recording_dir:
            recording_dir = self.__recording_dir
            self.__recording_dir = None
            try:
                shutil.rmtree(recording_dir)
            except OSError as e:
                if e.errno == errno.ENOENT:
                    pass
                else:
                    raise

    def __del__(self):
        self.close()


_STATUS_IDLE = 'Waiting for next even minute'
_STATUS_RECEIVING = 'Receiving'
_STATUS_DECODING = 'Decoding…'
_STATUS_DECODING_AND_RECEIVING = 'Decoding previous & receiving'


@implementer(IWAVIntervalListener)
class WAVIntervalListener(ExportedState):
    # pylint: disable=no-member
    __start_frequency = None
    __frequency_subscription = None
    __invalidated_by_frequency_change = False
    __decoder_active = None

    def __init__(self,
            directory,
            context,
            audio_frequency,

            _reactor=reactor,
            _find_wsprd=find_wsprd,
            _time=time.time):
        self.directory = directory
        self.context = context
        self.audio_frequency = audio_frequency
        self.__wsprd = _find_wsprd()
        if self.__wsprd is None:
            raise Exception('Could not find wsprd. Is WSJT-X installed and wsprd in $PATH?')
        self._time = _time
        self._reactor = _reactor

    def fileOpened(self, filename):
        rf_frequency_cell = self.context.get_absolute_frequency_cell()
        self.__start_frequency, self.__frequency_subscription = rf_frequency_cell.subscribe2(
            self.__check_modified_frequency,
            SubscriptionContext(reactor=self._reactor, poller=None))
        self.__invalidated_by_frequency_change = False
        self.state_changed()

    def fileClosed(self, filename):
        self.__frequency_subscription.unsubscribe()
        self.__frequency_subscription = None
        rf_frequency = self.__start_frequency
        self.__start_frequency = None
        self.state_changed()
        if self.__invalidated_by_frequency_change:
            # If the recording started on one frequency, but finished on
            # another, don't decode the file. We especially wouldn't want to
            # upload spots that were recorded on one band as if they happened
            # on another because the user tuned the radio just before the
            # interval completed.
            return

        # wsprd expects its -f argument to be as if the recording was made with
        # a USB receiver
        dial_freq = (rf_frequency - self.audio_frequency) / 1e6
        self.__decoder_active = defer.Deferred()
        self.__decoder_active.addBoth(self.__decode_finished)
        self._reactor.spawnProcess(
            WsprdProtocol(self.context, filename, self._time(), self.__decoder_active),
            self.__wsprd,
            args=['wsprd', '-d', '-f', str(dial_freq), filename],
            env={},
            path=self.directory)

    def __check_modified_frequency(self, value):
        if value != self.__start_frequency:
            self.__invalidated_by_frequency_change = True
            self.state_changed()

    def __decode_finished(self, _unused_value):
        self.__decoder_active = None

    def filename(self, start_time):
        # TODO: We should be using the same frequency as __start_frequency but
        # there is no guarantee in the interface about the timing of calls to
        # this method vs. fileOpened.
        time_str = time.strftime(b'%y%m%d_%H%M.wav', time.gmtime(start_time))
        filename = b'%s_%s' % (self.context.get_absolute_frequency_cell().get(), time_str)
        return os.path.join(self.directory, filename)
    
    @exported_value(type=unicode, label='Status', changes='explicit')
    def get_status(self):
        recording = (self.__frequency_subscription and
            not self.__invalidated_by_frequency_change)
        if self.__decoder_active and recording:
            return 'Decoding previous & receiving'
        elif self.__decoder_active:
            return 'Decoding…'
        elif recording:
            return 'Receiving'
        else:
            return 'Waiting for next even minute'


class WsprdProtocol(ProcessProtocol):
    __tail = ''
    _WSPRSpot = WSPRSpot
    _deferToThread = staticmethod(threads.deferToThread)

    def __init__(self,
            context,
            wav_filename,
            decode_time,
            status_deferred):
        self.context = context
        self.wav_filename = wav_filename
        self.decode_time = decode_time
        self.__status_deferred = status_deferred

    def outReceived(self, data):
        self.__tail += data
        self._processLines()

    def _processLines(self):
        while '\n' in self.__tail:
            first_line, self.__tail = self.__tail.split('\n', 1)
            self.lineReceived(first_line)

    def processEnded(self, reason):
        self._processLines()
        if self.__tail:
            self.lineReceived(self.__tail)
            del self.__tail

        self._deferToThread(os.unlink, self.wav_filename).addErrback(log.err)
        self.wav_filename = None
        self.__status_deferred.callback(None)

    def lineReceived(self, line):
        line = line.strip()
        if not line:
            return

        if line == '<DecodeFinished>':
            return

        fields = line.split()
        if len(fields) != 8:
            log.msg('malformed wsprd line: %r' % (line,))
            return

        # Don't know what dt is.
        _, snr, dt, freq, drift, call, grid, txpower = fields

        snr = int(snr)
        dt = float(dt)
        freq = float(freq)
        drift = int(drift)
        txpower = int(txpower)

        if call == '<...>':
            # This was a two-part transmission, but we are missing the first
            # part and so can't decode the call.
            call = None
        elif call.startswith('<') and call.endswith('>'):
            # braces indicate the call was inferred from a previous
            # transmission. WSPR will make two transmissions to convey calls or
            # grid locators that don't fit in one 2-minute interval.
            call = call[1:-1]

        spot = self._WSPRSpot(self.decode_time, snr, dt, freq, drift, call, grid, txpower)
        log.msg('WSPR spotted: %r' % (spot,))
        self.context.output_message(spot)


__all__ = ['WSPRDemodulator', 'WAVIntervalListener', 'WsprdProtocol']
