# Copyright 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

import math

from zope.interface import implementer

from gnuradio import analog
from gnuradio import blocks
from gnuradio import filter as grfilter
from gnuradio.filter import firdes
from gnuradio import gr
import numpy

try:
    # gr-radioteletype
    # https://github.com/bitglue/gr-radioteletype
    from radioteletype.demodulators import rtty_demod_cb
    _available = True
except ImportError:
    _available = False

from shinysdr.math import dB, rotator_inc
from shinysdr.filters import MultistageChannelFilter
from shinysdr.interfaces import BandShape, ModeDef, IDemodulator, IModulator
from shinysdr.signals import SignalType, no_signal
from shinysdr.values import ExportedState, exported_value


# note: this string is ordered so that the first bit (on the air) is the least significant bit of the index in the string
ITA2_LETTERS = u'''nTrO HNM\nLRGIPCVEZDBSYFXAWJfUQKl'''
ITA2_FIGURES = u'''n5r9 #,.\n)4&80:;3"e?b6!/-2'f71(l'''
_ITA2_LETTERS_SHIFT = ITA2_LETTERS.index("l")
_ITA2_FIGURES_SHIFT = ITA2_LETTERS.index("f")


_DEFAULT_BAUD = 45.45
_DATA_BITS = 5
_HALF_BITS_PER_CODE = (1 + _DATA_BITS) * 2 + 3


@implementer(IDemodulator)
class RTTYDemodulator(gr.hier_block2, ExportedState):
    '''Demodulate typical amateur RTTY.

    Input should be centered on the mark frequency. (By convention, RTTY
    contacts are logged at the mark frequency.)

    Assumptions:

        - 45.45 baud
        - 170 Hz spacing
        - Mark tone high

    TODO: make these assumptions parameters.
    '''
    
    __spacing = 170
    __demod_rate = 6000

    __low_cutoff = __spacing * -2
    __high_cutoff = __spacing
    __transition_width = __spacing

    def __init__(self, mode, input_rate=0, context=None):
        assert input_rate > 0
        self.__input_rate = input_rate
        gr.hier_block2.__init__(
            self, 'RTTY demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(1, 1, gr.sizeof_float * 1))
        
        channel_filter = self.__make_channel_filter()

        self.__text = u''
        self.__char_queue = gr.msg_queue(limit=100)
        self.__char_sink = blocks.message_sink(gr.sizeof_char, self.__char_queue, True)

        self.connect(
            self,
            channel_filter,
            self.__make_demodulator(),
            self.__char_sink)
        
        self.connect(
            channel_filter,
            self.__make_audio_filter(),
            blocks.rotator_cc(rotator_inc(self.__demod_rate, 2000 + self.__spacing / 2)),
            blocks.complex_to_real(vlen=1),
            analog.agc2_ff(
                reference=dB(-10),
                attack_rate=8e-1,
                decay_rate=8e-1),
            self)

    def __make_demodulator(self):
        return rtty_demod_cb(
            samp_rate=self.__demod_rate,
            # 6000 / 45.45 / 11 = 12.0012 samples per bit. We want a number
            # that's not too small to avoid quantization errors in the
            # timing.
            decimation=11,
            mark_freq=0,
            space_freq=-self.__spacing)

    def __make_channel_filter(self):
        '''Return the channel filter.

        rtty_demod_cb includes filters, so here we just need a broad, cheap filter to
        decimate.
        '''
        return MultistageChannelFilter(
            input_rate=self.__input_rate,
            output_rate=self.__demod_rate,
            cutoff_freq=self.__spacing * 5,
            transition_width=self.__spacing * 5)

    def __make_audio_filter(self):
        '''Return a filter which selects just the RTTY signal and shifts to AF.

        This isn't anywhere in the digital processing chain, so doesn't need to
        be concerned with signal fidelity as long as it sounds good.
        '''
        taps = firdes.complex_band_pass(
            gain=1.0,
            sampling_freq=self.__demod_rate,
            low_cutoff_freq=self.__low_cutoff,
            high_cutoff_freq=self.__high_cutoff,
            transition_width=self.__transition_width)

        af_filter = grfilter.fir_filter_ccc(
            decimation=1,
            taps=taps)

        return af_filter

    def can_set_mode(self, mode):
        """implement IDemodulator"""
        return False
    
    def set_mode(self, mode):
        """implement IDemodulator"""
        raise Exception('set_mode should not have been called')
    
    @exported_value(type=BandShape, changes='never')
    def get_band_shape(self):
        """implement IDemodulator"""
        return BandShape.bandpass_transition(
            low=self.__low_cutoff,
            high=self.__high_cutoff,
            transition=self.__transition_width,
            markers={
                -self.__spacing: u'S',
                0: u'M',
            })
    
    def get_output_type(self):
        """implement IDemodulator"""
        return SignalType(kind='MONO', sample_rate=self.__demod_rate)

    @exported_value(type=unicode, changes='continuous')
    def get_text(self):
        # pylint: disable=no-member
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
@implementer(IModulator)
class RTTYModulator(gr.hier_block2, ExportedState):
    def __init__(self, context, mode, rtty_baud=_DEFAULT_BAUD, rtty_shift=170.0, message='\0'):
        gr.hier_block2.__init__(
            self, type(self).__name__,
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


def _to_bits(code):
    """
    ITA2 code number to _HALF_BITS_PER_CODE-element array
    """
    l = [0, 0]
    for i in xrange(_DATA_BITS):
        j = _DATA_BITS - 1 - i
        l.append((code >> j) & 1)
        l.append((code >> j) & 1)
    l.append(1)
    l.append(1)
    l.append(1)
    # pylint: disable=no-member
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
    # pylint: disable=no-member
    # TODO: should not need the + 1
    out = numpy.full([(len(char_in) + 1) * _HALF_BITS_PER_CODE * 2], 0, dtype=numpy.float32)
    count_in, count_out = _encode_rtty(char_in, out)
    assert count_in == len(char_in), 'Did not encode all %s characters but only %s' % (len(char_in), count_in)
    return out[:count_out]


# Not usable because python blocks have bad interactions with reconfiguration or something.
# class RTTYEncoder(gr.basic_block):
#   """
#   Convert ASCII to a bit-stream with 2 bits per symbol (except for stop bits which are 3).
#   """
#   def __init__(self):
#       gr.basic_block.__init__(self,
#           name=type(self).__name__,
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
pluginMode = ModeDef(mode='RTTY',
    info='RTTY',
    demod_class=RTTYDemodulator,
    mod_class=RTTYModulator,
    available=_available)
