# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

"""Adapters to use ShinySDR components in GNU Radio Companion."""

from __future__ import absolute_import, division

from gnuradio import blocks
from gnuradio import gr

from shinysdr.filters import make_resampler
from shinysdr.interfaces import IDemodulator, IModulator
from shinysdr.i.modes import lookup_mode, get_modes
from shinysdr.values import LooseCell


__all__ = []  # appended later


class DemodulatorAdapter(gr.hier_block2):
    """Adapts IDemodulator to be a GRC block."""
    def __init__(self, mode, input_rate, output_rate, demod_class=None, freq=0.0, quiet=False):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(2, 2, gr.sizeof_float))
        
        if demod_class is None:
            mode_def = lookup_mode(mode)
            if mode_def is None:
                raise Exception('{}: No demodulator registered for mode {!r}, only {!r}'.format(
                    type(self).__name__, mode, [md.mode for md in get_modes()]))
            demod_class = mode_def.demod_class
        
        context = _DemodulatorAdapterContext(adapter=self, freq=freq)
        
        demod = self.__demodulator = IDemodulator(demod_class(
            mode=mode,
            input_rate=input_rate,
            context=context))
        self.connect(self, demod)
        
        output_type = demod.get_output_type()
        demod_output_rate = output_type.get_sample_rate()
        same_rate = demod_output_rate == output_rate
        stereo = output_type.get_kind() == 'STEREO'
        
        # connect outputs, resampling and adapting mono/stereo as needed
        # TODO: Make the logic for this in receiver.py reusable?
        if output_type.get_kind() == 'NONE':
            # TODO: produce correct sample rate of zeroes and maybe a warning
            dummy = blocks.vector_source_f([])
            self.connect(dummy, (self, 0))
            self.connect(dummy, (self, 1))
        else:
            if stereo:
                splitter = blocks.vector_to_streams(gr.sizeof_float, 2)
                self.connect(demod, splitter)
            if same_rate:
                if stereo:
                    self.connect((splitter, 0), (self, 0))
                    self.connect((splitter, 1), (self, 1))
                else:
                    self.connect(demod, (self, 0))
                    self.connect(demod, (self, 1))
            else:
                if not quiet:
                    gr.log.info('{}: Native {} demodulated rate is {}; resampling to {}'.format(
                        type(self).__name__, mode, demod_output_rate, output_rate))
                if stereo:
                    self.connect((splitter, 0), make_resampler(demod_output_rate, output_rate), (self, 0))
                    self.connect((splitter, 1), make_resampler(demod_output_rate, output_rate), (self, 1))
                else:
                    resampler = make_resampler(demod_output_rate, output_rate)
                    self.connect(demod, resampler, (self, 0))
                    self.connect(resampler, (self, 1))
    
    def get_demodulator(self):
        """Return the actual plugin-provided demodulator block."""
        return self.__demodulator


__all__.append('DemodulatorAdapter')


class _DemodulatorAdapterContext(object):
    def __init__(self, adapter, freq):
        self.__adapter = adapter
        self.__freq_cell = LooseCell(
            key='rec_freq',
            value=freq,
            type=float,
            persists=False,
            writable=False)
        
    def rebuild_me(self):
        raise Exception('TODO: DemodulatorAdapter does not yet support rebuild_me')

    def lock(self):
        self.__adapter.lock()

    def unlock(self):
        self.__adapter.unlock()
    
    def output_message(self, message):
        print message
    
    def get_absolute_frequency_cell(self):
        return self.__freq_cell


class ModulatorAdapter(gr.hier_block2):
    """Adapts IModulator to be a GRC block."""
    def __init__(self, mode, input_rate, output_rate, mod_class=None):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_float),
            gr.io_signature(1, 1, gr.sizeof_gr_complex))
        
        if mod_class is None:
            mode_def = lookup_mode(mode)
            if mode_def is None:
                raise Exception('{}: No modulator registered for mode {!r}, only {!r}'.format(
                    type(self).__name__, mode, [md.mode for md in get_modes() if md.mod_class]))
            mod_class = mode_def.mod_class
        
        context = _ModulatorAdapterContext(adapter=self)
        
        modulator = self.__modulator = IModulator(mod_class(
            mode=mode,
            context=context))

        self.__connect_with_resampling(
            self, input_rate,
            modulator, modulator.get_input_type().get_sample_rate(),
            False)
        self.__connect_with_resampling(
            modulator, modulator.get_output_type().get_sample_rate(),
            self, output_rate,
            True)
    
    def get_modulator(self):
        """Return the actual plugin-provided modulator block."""
        return self.__modulator
    
    def __connect_with_resampling(self, from_endpoint, from_rate, to_endpoint, to_rate, complex):
        # pylint: disable=redefined-builtin
        
        if from_rate == to_rate:
            self.connect(from_endpoint, to_endpoint)
        else:
            gr.log.info('{}: Resampling {} to {}'.format(
                type(self).__name__, from_rate, to_rate))
            resampler = make_resampler(from_rate, to_rate, complex=complex)
            self.connect(from_endpoint, resampler, to_endpoint)


__all__.append('ModulatorAdapter')


class _ModulatorAdapterContext(object):
    def __init__(self, adapter):
        self.__adapter = adapter
        
    def lock(self):
        self.__adapter.lock()

    def unlock(self):
        self.__adapter.unlock()
