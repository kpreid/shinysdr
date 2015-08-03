# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=no-member
# (no-member: Twisted reactor)

from __future__ import absolute_import, division

import time
import warnings

from twisted.internet import reactor
from twisted.internet.protocol import ProcessProtocol
from twisted.protocols.basic import LineReceiver
from twisted.python import log
from zope.interface import implements

from gnuradio import analog
from gnuradio import gr
from gnuradio import blocks

from shinysdr.blocks import make_sink_to_process_stdin, test_subprocess
from shinysdr.filters import make_resampler
from shinysdr.modes import ModeDef, IDemodulator
from shinysdr.plugins.basic_demod import NFMDemodulator
from shinysdr.plugins.aprs import APRSInformation, parse_tnc2
from shinysdr.signals import SignalType
from shinysdr.types import Enum
from shinysdr.values import BlockCell, ExportedState, exported_value, setter

pipe_rate = 22050  # what multimon-ng expects
_maxint32 = 2 ** 15 - 1
audio_gain = 0.5
int_scale = _maxint32 * audio_gain


class MultimonNGDemodulator(gr.hier_block2, ExportedState):
    # This is not an IDemodulator; it takes float input, requires a fixed input rate and lacks other characteristics.
    
    def __init__(self, protocol, context, multimon_demod_args):
        gr.hier_block2.__init__(
            self, '%s(%r, %r)' % (self.__class__.__name__, multimon_demod_args, protocol),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
        )
        
        # Subprocess
        # using /usr/bin/env because twisted spawnProcess doesn't support path search
        process = reactor.spawnProcess(
            protocol,
            '/usr/bin/env',
            env=None,  # inherit environment
            args=['env', 'multimon-ng', '-t', 'raw'] + multimon_demod_args + ['-v', '10', '-'],
            childFDs={
                0: 'w',
                1: 'r',
                2: 2
            })
        sink = make_sink_to_process_stdin(process, itemsize=gr.sizeof_short)
        
        # Output
        to_short = blocks.float_to_short(vlen=1, scale=int_scale)
        self.connect(
            self,
            # blocks.complex_to_float(),
            to_short,
            sink)
        # Audio copy output
        unconverter = blocks.short_to_float(vlen=1, scale=int_scale)
        self.connect(to_short, unconverter)
        self.connect(unconverter, self)
        
    def get_input_type(self):
        return SignalType(kind='MONO', sample_rate=pipe_rate)
    
    def get_output_type(self):
        return SignalType(kind='MONO', sample_rate=pipe_rate)


_aprs_squelch_type = Enum({
    u'mute': u'Muted',
    u'ctcss': 'Voice Alert',
    u'monitor': u'Monitor'}, strict=True)


class APRSDemodulator(gr.hier_block2, ExportedState):
    '''
    Demod APRS and feed into an APRSInformation object.
    '''
    def __init__(self, aprs_information=None, context=None):
        gr.hier_block2.__init__(
            self, self.__class__.__name__,
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
        )
        
        if aprs_information is not None:
            self.__information = aprs_information
        else:
            self.__information = APRSInformation()
        
        def receive(line):
            # %r here provides robustness against arbitrary bytes.
            log.msg(u'APRS: %r' % (line,))
            message = parse_tnc2(line, time.time())
            log.msg(u'   -> %s' % (message,))
            self.__information.receive(message)
        
        self.__mm_demod = MultimonNGDemodulator(
            multimon_demod_args=['-A'],
            protocol=APRSProcessProtocol(receive),
            context=context)
        
        # APRS Voice Alert squelch -- see http://www.aprs.org/VoiceAlert3.html
        self.__squelch_mode = None
        self.__squelch_block = analog.ctcss_squelch_ff(
            rate=int(self.__mm_demod.get_output_type().get_sample_rate()),
            freq=100.0,  # TODO: should allow the other Voice Alert tones
            level=0.05,  # amplitude of tone -- TODO: sometimes opens for noise, needs adjustment
            len=0,  # use default
            ramp=0,  # no ramping
            gate=False)
        self.__router = blocks.multiply_matrix_ff([[0, 0]])
        self.set_squelch(u'ctcss')
        
        self.connect(
            self,
            self.__mm_demod,
            self.__squelch_block,
            self.__router,
            self)
        self.connect(self.__mm_demod, (self.__router, 1))
    
    def get_input_type(self):
        return self.__mm_demod.get_input_type()
    
    def get_output_type(self):
        return self.__mm_demod.get_output_type()
    
    @exported_value(type=_aprs_squelch_type)
    def get_squelch(self):
        return self.__squelch_mode
    
    @setter
    def set_squelch(self, value):
        value = _aprs_squelch_type(value)
        if value == self.__squelch_mode: return
        self.__squelch_mode = value
        if value == u'mute':
            self.__router.set_A([[0, 0]])
        elif value == u'monitor':
            self.__router.set_A([[0, 1]])
        elif value == u'ctcss':
            self.__router.set_A([[1, 0]])
        else:
            warnings.warn('can\'t happen: bad squelch value: %r' % (value,))
            # and leave level at what it was


# TODO: Eliminate this class and replace it with adapters available to any demodulator
class FMAPRSDemodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    def __init__(self, mode, input_rate=0, aprs_information=None, context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, str(mode) + ' (FM + Multimon-NG) demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
        )
        self.mode = mode
        self.input_rate = input_rate
        
        # FM demod
        # TODO: Retry telling the NFMDemodulator to have its output rate be pipe_rate instead of using a resampler. Something went wrong when trying that before. Same thing is done in dsd.py
        self.fm_demod = NFMDemodulator(
            mode='NFM',
            input_rate=input_rate,
            no_audio_filter=True,  # don't remove CTCSS tone
            tau=None)  # no deemphasis
        assert self.fm_demod.get_output_type().get_kind() == 'MONO'
        fm_audio_rate = self.fm_demod.get_output_type().get_sample_rate()
        
        # Subprocess
        self.mm_demod = APRSDemodulator(
            aprs_information=aprs_information)
        mm_audio_rate = self.mm_demod.get_input_type().get_sample_rate()
        
        # Output
        self.connect(
            self,
            self.fm_demod,
            make_resampler(fm_audio_rate, mm_audio_rate),
            self.mm_demod,
            self)
    
    def state_def(self, callback):
        super(FMAPRSDemodulator, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'mm_demod'))
    
    def can_set_mode(self, mode):
        return False
    
    def get_half_bandwidth(self):
        return self.fm_demod.get_half_bandwidth()
    
    def get_output_type(self):
        return self.mm_demod.get_output_type()
    
    @exported_value()
    def get_band_filter_shape(self):
        return self.fm_demod.get_band_filter_shape()


class APRSProcessProtocol(ProcessProtocol):
    def __init__(self, target):
        self.__target = target
        self.__line_receiver = LineReceiver()
        self.__line_receiver.delimiter = '\n'
        self.__line_receiver.lineReceived = self.__lineReceived
        self.__last_line = None
    
    def outReceived(self, data):
        # split lines
        self.__line_receiver.dataReceived(data)
        
    def errReceived(self, data):
        # we should inherit stderr, not pipe it
        raise Exception('shouldn\'t happen')
    
    def __lineReceived(self, line):
        if line == '':  # observed glitch in output
            pass
        elif line.startswith('Enabled demodulators:'):
            pass
        elif line.startswith('$ULTW') and self.__last_line is not None:  # observed glitch in output; need to glue to previous line, I think?
            ll = self.__last_line
            self.__last_line = None
            self.__target(ll + line)
        elif line.startswith('APRS: '):
            line = line[len('APRS: '):]
            self.__last_line = line
            self.__target(line)
        else:
            # TODO: Log these properly
            print 'Not APRS line: %r' % line


# TODO: Arrange for a way for the user to see why it is unavailable.
_multimon_available = test_subprocess('multimon-ng -h; exit 0', 'available demodulators:', shell=True)


pluginDef_APRS = ModeDef(
    mode='APRS',  # TODO: Rename mode to be more accurate
    label='APRS',
    demod_class=FMAPRSDemodulator,
    shared_objects={'aprs_information': APRSInformation},
    available=_multimon_available)
