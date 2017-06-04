"""GNU Radio blocks for WSPR"""

from __future__ import division, absolute_import

import time
from math import pi

from twisted.internet import reactor, threads
from twisted.python import log

from gnuradio import gr, blocks, analog
from gnuradio.blocks import wavfile_sink

from shinysdr.filters import MultistageChannelFilter
from shinysdr.math import dB


class WAVIntervalSink(gr.hier_block2):
    """Sink samples to a series of WAV files at regular intervals.

    `listener` gets notified of events and decides where the files go. See
    `IWAVIntervalListener` for the interface to implement.

    Whenever the current time is a round multiple of `interval`, a new file is
    opened and samples are written there. `duration` seconds later, it's
    closed, until the next round multiple of `interval'.

    Behavior if the duration and interval are equal is undefined.
    """

    _next_delayed_call = None

    def __init__(
        self,
        interval,
        duration,
        listener,
        sample_rate,

        _callLater=reactor.callLater,
        _time=time.time,
        _deferToThread=threads.deferToThread,
    ):
        gr.hier_block2.__init__(
            self, 'WAV Interval Sink',
            gr.io_signature(1, 1, gr.sizeof_float),
            gr.io_signature(0, 0, 0))

        self._callLater = _callLater
        self._time = _time
        self._deferToThread = _deferToThread

        self.interval = interval
        self.listener = listener
        self.duration = duration

        self._sink = wavfile_sink(
            # There doesn't seem to be a way to create a sink without
            # immediately opening a file :(
            filename='/dev/null',
            n_channels=1,
            sample_rate=sample_rate,
            bits_per_sample=16)

        self.connect(self, self._sink)

    def start_running(self):
        if self._next_delayed_call is None:
            self._schedule_next_start()

    def _schedule_next_start(self):
        now = self._time()
        time_running = now % self.interval
        last_started = now - time_running
        next_run = last_started + self.interval

        self._next_delayed_call = self._callLater(
            next_run - now,
            self._start_recording, next_run,
        )

    def _start_recording(self, start_time):
        filename = self.listener.filename(start_time)

        self._deferToThread(
            self._open_wav, filename
        ).addCallback(
            self.listener.fileOpened
        ).addErrback(log.err)

        self._next_delayed_call = self._callLater(
            self.duration,
            self._stop_recording, filename)

    def _stop_recording(self, filename):
        self._deferToThread(
            self._close_wav, filename
        ).addCallback(
            self.listener.fileClosed
        ).addErrback(log.err)

        self._schedule_next_start()

    def _open_wav(self, filename):
        # called in thread.
        self._sink.open(filename)
        return filename

    def _close_wav(self, filename):
        self._sink.close()
        return filename


class WSPRFilter(gr.hier_block2):
    """Filter the incomming complex stream to floats compatible with wsprd

    The default settings are appropriate for WAV output for wsprd. It expects a
    200 Hz (or 500 Hz with the -w option) wide band centered on 1500 Hz, at a
    12kHz sample rate. By default, the passband is 800 Hz to minimize any
    distortion.

    A slow AGC is included. Emperically, wsprd seems to perform better with it.

    Also suitable for audio monitoring.
    """

    # wsprd requires wav files at 12kHz sample rates. The WSPR band is 200 Hz
    # wide, centered on 1500 Hz in the recording. The passband is a good deal
    # wider to avoid any distortion that would impair decoding, and also catch
    # beacons that might be just outside the band.

    def __init__(
        self,
        input_rate,
        output_rate=12000,
        output_frequency=1500,
        transition_width=100,
        width=800
    ):
        """Make a new WSPRFilter.

        input_rate: the incomming sample rate

        output_rate: output sample rate

        output_frequency: 0Hz in the complex input will be centered on this
        frequency in the real output

        width, transition_width: passband and transition band widths.
        """

        gr.hier_block2.__init__(
            self, 'WSPR Filter',
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float))

        self.connect(
            self,

            MultistageChannelFilter(
                input_rate=input_rate,
                output_rate=output_rate,
                cutoff_freq=width / 2,
                transition_width=transition_width),

            blocks.rotator_cc(2 * pi * output_frequency / output_rate),

            blocks.complex_to_real(vlen=1),

            analog.agc2_ff(
                reference=dB(-10),
                attack_rate=8e-1,
                decay_rate=8e-1),

            self,
        )


__all__ = ['WAVIntervalSink', 'WSPRFilter']
