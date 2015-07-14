# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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
# (no-member: pylint is confused by numpy)

from __future__ import absolute_import, division

import math

from zope.interface import implements

from gnuradio import analog
from gnuradio import blocks
from gnuradio import digital
from gnuradio import filter as grfilter
from gnuradio.filter import firdes
from gnuradio import gr
import numpy

from shinysdr.filters import MultistageChannelFilter
from shinysdr.modes import ModeDef, IDemodulator, IModulator
from shinysdr.signals import SignalType, no_signal
from shinysdr.types import Range
from shinysdr.values import BlockCell, ExportedState, exported_value


try:
    import rtty  # gr-rtty
    _available = True
except ImportError:
    _available = False


# note: this string is ordered so that the first bit (on the air) is the least significant bit of the index in the string
ITA2_LETTERS = u"nTrO HNM\nLRGIPCVEZ"  + "DBSYFXAWJfUQKl"
ITA2_FIGURES = u"n5r9 #,.\n)4&80:;3\"" + "e?b6!/-2'f71(l"
_ITA2_LETTERS_SHIFT = ITA2_LETTERS.index("l")
_ITA2_FIGURES_SHIFT = ITA2_LETTERS.index("f")


_DEFAULT_BAUD = 45.45
_DATA_BITS = 5
_HALF_BITS_PER_CODE = (1 + _DATA_BITS) * 2 + 3


class RTTYDemodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    __filter_low = 1500
    __filter_high = 2500
    __transition = 100

    def __init__(self, mode,
            input_rate=0,
            context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, 'RTTY demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
        )
        self.__text = u''
        
        baud = _DEFAULT_BAUD  # TODO param
        self.baud = baud

        demod_rate = 6000  # TODO optimize this value
        self.samp_rate = demod_rate  # TODO rename
        
        self.__channel_filter = MultistageChannelFilter(
            input_rate=input_rate,
            output_rate=demod_rate,
            cutoff_freq=self.__filter_high,
            transition_width=self.__transition)  # TODO optimize filter band
        self.__sharp_filter = grfilter.fir_filter_ccc(
            1,
            firdes.complex_band_pass(1.0, demod_rate,
                self.__filter_low,
                self.__filter_high,
                self.__transition,
                firdes.WIN_HAMMING))
        self.fsk_demod = RTTYFSKDemodulator(input_rate=demod_rate, baud=baud)
        self.__real = blocks.complex_to_real(vlen=1)
        self.__char_queue = gr.msg_queue(limit=100)
        self.char_sink = blocks.message_sink(gr.sizeof_char, self.__char_queue, True)

        self.connect(
            self,
            self.__channel_filter,
            self.__sharp_filter,
            self.fsk_demod,
            rtty.rtty_decode_ff(rate=demod_rate, baud=baud, polarity=False),
            self.char_sink)
        
        self.connect(
            self.__sharp_filter,
            self.__real,
            self)
    
    def state_def(self, callback):
        super(RTTYDemodulator, self).state_def(callback)
        # TODO decoratorify
        callback(BlockCell(self, 'fsk_demod'))
    
    def get_output_type(self):
        return SignalType(kind='MONO', sample_rate=self.samp_rate)

    def can_set_mode(self, mode):
        '''implement IDemodulator'''
        return False
    
    def get_half_bandwidth(self):
        '''implement IDemodulator'''
        return self.__filter_high

    @exported_value()
    def get_band_filter_shape(self):
        return {
            'low': self.__filter_low,
            'high': self.__filter_high,
            'width': self.__transition
        }

    @exported_value(type=unicode)
    def get_text(self):
        queue = self.__char_queue
        # we would use .delete_head_nowait() but it returns a crashy wrapper instead of a sensible value like None. So implement a test (which is safe as long as we're the only reader)
        if not queue.empty_p():
            message = queue.delete_head()
            if message.length() > 0:
                bitstring = message.to_string()
            else:
                bitstring = ''  # avoid crash bug
            textstring = self.__text
            textstring += bitstring
            self.__text = textstring[-20:]
        return self.__text


# Because we don't currently have an encoder which can operate as a block, the rtty modulator is limited to looping a fixed message. This is good enough for simulation testing.
class RTTYModulator(gr.hier_block2, ExportedState):
    implements(IModulator)
    
    def __init__(self, context, mode, rtty_baud=_DEFAULT_BAUD, rtty_shift=170.0, message='\0'):
        gr.hier_block2.__init__(
            self, self.__class__.__name__,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1))
        
        encoded_message = map(float, _encode_rtty_alloc(map(ord, message)))  # TODO char encoding issues
        
        half_bit_rate = rtty_baud * 2
        wanted_bandwidth = rtty_shift * 1.5
        sample_rate_as_half_bits = int(math.ceil(wanted_bandwidth / half_bit_rate))
        self.__sample_rate_out = sample_rate_as_half_bits * half_bit_rate
        
        self.__char_rate = half_bit_rate / _HALF_BITS_PER_CODE
        self.__baud = rtty_baud
        
        self.connect(
            blocks.vector_source_f(encoded_message, repeat=True),
            # RTTYEncoder(),
            blocks.repeat(gr.sizeof_float, sample_rate_as_half_bits),
            blocks.add_const_ff(-0.5),
            analog.frequency_modulator_fc((2 * math.pi) * rtty_shift / self.__sample_rate_out),
            self)
    
    def get_input_type(self):
        return no_signal
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__sample_rate_out)


class RTTYFSKDemodulator(gr.hier_block2, ExportedState):
    '''
    Demodulate FSK with parameters suitable for gr-rtty.
    
    TODO: Make this into something more reusable once we have other examples of FSK.
    Note this differs from the GFSK demod in gnuradio.digital by having a DC blocker.
    '''
    def __init__(self, input_rate, baud):
        gr.hier_block2.__init__(
            self, 'RTTY FSK demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1),
        )
        
        self.bit_time = bit_time = input_rate / baud
        
        fsk_deviation_hz = 85  # TODO param or just don't care
        
        self.__dc_blocker = grfilter.dc_blocker_ff(int(bit_time * _HALF_BITS_PER_CODE * 10), False)
        self.__quadrature_demod = analog.quadrature_demod_cf(-input_rate / (2 * math.pi * fsk_deviation_hz))
        self.__freq_probe = blocks.probe_signal_f()
        
        self.connect(
            self,
            self.__quadrature_demod,
            self.__dc_blocker,
            digital.binary_slicer_fb(),
            blocks.char_to_float(scale=1),
            self)
        self.connect(self.__dc_blocker, self.__freq_probe)

    @exported_value(type=Range([(-2, 2)]))
    def get_probe(self):
        return abs(self.__freq_probe.level())


def _to_bits(code):
    '''
    ITA2 code number to _HALF_BITS_PER_CODE-element array
    '''
    l = [0, 0]
    for i in xrange(_DATA_BITS):
        j = _DATA_BITS - 1 - i
        l.append((code >> j) & 1)
        l.append((code >> j) & 1)
    l.append(1)
    l.append(1)
    l.append(1)
    return numpy.array(l, dtype=numpy.float32)


def _reverse_table():
    rev = [(_to_bits(0), _to_bits(_ITA2_LETTERS_SHIFT))] * 256
    for table, shift in [(ITA2_LETTERS, _to_bits(_ITA2_LETTERS_SHIFT)), (ITA2_FIGURES, _to_bits(_ITA2_LETTERS_SHIFT))]:
        for code, char in enumerate(table):
            if char == 'f' or char == 'l': continue
            rev[ord(char)] = rev[ord(char.lower())] = (_to_bits(code), shift)
    return rev


_ASCII_TO_ITA2 = _reverse_table()


def _encode_rtty(char_in, bits_out):
    index_in = 0
    index_out = 0
    limit_in = len(char_in)
    limit_out = len(bits_out) - _HALF_BITS_PER_CODE * 2
    while index_out < limit_out and index_in < limit_in:
        # TODO: not encoding shift
        code_bits, _shift = _ASCII_TO_ITA2[char_in[index_in]]
        bits_out[index_out:index_out + _HALF_BITS_PER_CODE] = code_bits
        index_out += _HALF_BITS_PER_CODE
        index_in += 1
    return (index_in, index_out)


def _encode_rtty_alloc(char_in):
    # TODO: should not need the + 1
    out = numpy.full([(len(char_in) + 1) * _HALF_BITS_PER_CODE * 2], 0, dtype=numpy.float32)
    count_in, count_out = _encode_rtty(char_in, out)
    assert count_in == len(char_in), 'Did not encode all %s characters but only %s' % (len(char_in), count_in)
    return out[:count_out]


# Not usable because python blocks have bad interactions with reconfiguration or something.
# class RTTYEncoder(gr.basic_block):
#   '''
#   Convert ASCII to a bit-stream with 2 bits per symbol (except for stop bits which are 3).
#   '''
#   def __init__(self):
#       gr.basic_block.__init__(self,
#           name=self.__class__.__name__,
#           in_sig=[numpy.uint8],
#           out_sig=[numpy.float32])
#   
#   def forecast(self, noutput_items, ninput_items_required):
#       ninput_items_required[0] = int(math.ceil(noutput_items / _HALF_BITS_PER_CODE))
#   
#   def general_work(self, input_items, output_items):
#       char_in = input_items[0]
#       bits_out = output_items[0]
#       count_in, count_out = _encode_rtty(char_in, bits_out)
#       self.consume_each(count_in)
#       return count_out


# Plugin exports
pluginMode = ModeDef(
    mode='RTTY',
    label='RTTY',
    demod_class=RTTYDemodulator,
    mod_class=RTTYModulator,
    available=_available and False)  # disabled until it works better
