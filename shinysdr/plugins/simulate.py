# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from zope.interface import implements  # available via Twisted

from gnuradio import analog
from gnuradio import blocks
from gnuradio import channels
from gnuradio import gr
from gnuradio.filter import rational_resampler

from shinysdr.blocks import rotator_inc
from shinysdr.filters import make_resampler
from shinysdr.math import dB, todB
from shinysdr.modes import IModulator, lookup_mode
from shinysdr.signals import SignalType, no_signal
from shinysdr.devices import Device, IRXDriver
from shinysdr.types import Range
from shinysdr.values import CollectionState, ExportedState, LooseCell, exported_block, exported_value, setter


__all__ = []  # appended later


def SimulatedDevice(name='Simulated RF', freq=0.0, allow_tuning=False):
    rx_driver = _SimulatedRXDriver(name)
    return Device(
        name=name,
        vfo_cell=LooseCell(
            key='freq',
            value=freq,
            type=Range([(-1e9, 1e9)]) if allow_tuning else Range([(freq, freq)]),  # TODO kludge magic numbers
            writable=True,
            persists=False,
            post_hook=rx_driver._set_sim_freq),
        rx_driver=rx_driver)


__all__.append('SimulatedDevice')


# deprecated alias
SimulatedSource = SimulatedDevice


class _SimulatedRXDriver(ExportedState, gr.hier_block2):
    implements(IRXDriver)
    
    # TODO: be not hardcoded; for now this is convenient
    audio_rate = 1e4
    rf_rate = 200e3

    def __init__(self, name):
        gr.hier_block2.__init__(
            self, name,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        rf_rate = self.rf_rate
        audio_rate = self.audio_rate
        
        self.__noise_level = -22
        self.__transmitters = {}
        
        self.__transmitters_cs = CollectionState(self.__transmitters, dynamic=True)
        
        self.__bus = blocks.add_vcc(1)
        self.__channel_model = channels.channel_model(
            noise_voltage=dB(self.__noise_level),
            frequency_offset=0,
            epsilon=1.01,  # TODO: expose this parameter
            # taps=...,  # TODO: apply something here?
        )
        self.__rotator = blocks.rotator_cc()
        self.__throttle = blocks.throttle(gr.sizeof_gr_complex, rf_rate)
        self.connect(
            self.__bus,
            self.__throttle,
            self.__channel_model,
            self.__rotator,
            self)
        signals = []
        
        def add_modulator(freq, key, mode_or_modulator_ctor, **kwargs):
            if isinstance(mode_or_modulator_ctor, type):
                mode = None
                ctor = mode_or_modulator_ctor
            else:
                mode = mode_or_modulator_ctor
                mode_def = lookup_mode(mode)
                if mode_def is None:  # missing plugin, say
                    return
                ctor = mode_def.mod_class
            context = None  # TODO implement context
            modulator = ctor(context=context, mode=mode, **kwargs)
            tx = _SimulatedTransmitter(modulator, audio_rate, rf_rate, freq)
            
            self.connect(audio_signal, tx)
            signals.append(tx)
            self.__transmitters[key] = tx
        
        # Audio input signal
        pitch = analog.sig_source_f(audio_rate, analog.GR_SAW_WAVE, -1, 2000, 1000)
        audio_signal = vco = blocks.vco_f(audio_rate, 1, 1)
        self.connect(pitch, vco)
        
        # Channels
        add_modulator(0.0, 'usb', 'USB')
        add_modulator(10e3, 'am', 'AM')
        add_modulator(30e3, 'fm', 'NFM')
        add_modulator(-30e3, 'vor1', 'VOR', angle=0)
        add_modulator(-60e3, 'vor2', 'VOR', angle=math.pi / 2)
        add_modulator(50e3, 'rtty', 'RTTY', message='The quick brown fox jumped over the lazy dog.\n')
        add_modulator(80e3, 'chirp', ChirpModulator)
        
        bus_input = 0
        for signal in signals:
            self.connect(signal, (self.__bus, bus_input))
            bus_input = bus_input + 1
        
        self.__signal_type = SignalType(
            kind='IQ',
            sample_rate=rf_rate)
        self.__usable_bandwidth = Range([(-rf_rate / 2, rf_rate / 2)])
        
    
    @exported_block()
    def get_transmitters(self):
        return self.__transmitters_cs

    # implement IRXDriver
    @exported_value(type=SignalType)
    def get_output_type(self):
        return self.__signal_type
        
    def _set_sim_freq(self, freq):
        self.__rotator.set_phase_inc(rotator_inc(rate=self.rf_rate, shift=-freq))
    
    # implement IRXDriver
    def get_tune_delay(self):
        return 0.0
    
    # implement IRXDriver
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth
    
    # implement IRXDriver
    def close(self):
        pass
    
    @exported_value(type=Range([(-50, 0)]))
    def get_noise_level(self):
        return self.__noise_level
    
    @setter
    def set_noise_level(self, value):
        self.__channel_model.set_noise_voltage(dB(value))
        self.__noise_level = value

    def notify_reconnecting_or_restarting(self):
        # The throttle block runs on a clock which does not stop when the flowgraph stops; resetting the sample rate restarts the clock.
        # The necessity of this kludge has been filed as a gnuradio bug at <http://gnuradio.org/redmine/issues/649>
        self.__throttle.set_sample_rate(self.__throttle.sample_rate())


class _SimulatedTransmitter(gr.hier_block2, ExportedState):
    """provides frequency parameters"""
    def __init__(self, modulator, audio_rate, rf_rate, freq):
        modulator = IModulator(modulator)
        
        gr.hier_block2.__init__(
            self, 'SimulatedChannel',
            gr.io_signature(1, 1, gr.sizeof_float * 1),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__freq = freq
        self.__rf_rate = rf_rate
        self.__modulator = modulator
        
        modulator_input_type = modulator.get_input_type()
        if modulator_input_type.get_kind() == 'MONO':
            audio_resampler = make_resampler(audio_rate, modulator_input_type.get_sample_rate())
            self.connect(self, audio_resampler, modulator)
        elif modulator_input_type.get_kind() == 'NONE':
            self.connect(self, blocks.null_sink(gr.sizeof_float))
        else:
            raise Exception('don\'t know how to supply input of type %s' % modulator_input_type)
        
        rf_resampler = rational_resampler.rational_resampler_ccf(
            interpolation=int(rf_rate),
            decimation=int(modulator.get_output_type().get_sample_rate()))
        self.__rotator = blocks.rotator_cc(rotator_inc(rate=rf_rate, shift=freq))
        self.__mult = blocks.multiply_const_cc(dB(-10))
        self.connect(modulator, rf_resampler, self.__rotator, self.__mult, self)
    
    @exported_block()
    def get_modulator(self):
        return self.__modulator

    @exported_value(type_fn=lambda self: Range([(-self.__rf_rate / 2, self.__rf_rate / 2)], strict=False))
    def get_freq(self):
        return self.__freq
    
    @setter
    def set_freq(self, value):
        self.__freq = float(value)
        self.__rotator.set_phase_inc(rotator_inc(rate=self.__rf_rate, shift=self.__freq))
    
    @exported_value(type=Range([(-50.0, 0.0)], strict=False))
    def get_gain(self):
        return todB(self.__mult.k().real)
    
    @setter
    def set_gain(self, value):
        self.__mult.set_k(dB(value))


class ChirpModulator(gr.hier_block2, ExportedState):
    implements(IModulator)
    
    def __init__(self, context, mode, chirp_rate=0.1, output_rate=10000):
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex))
        
        self.__output_rate = output_rate
        self.__chirp_rate = chirp_rate
        
        self.__control = analog.sig_source_f(output_rate, analog.GR_SAW_WAVE, chirp_rate, output_rate * 2 * math.pi, 0)
        chirp_vco = blocks.vco_c(output_rate, 1, 1)
        
        self.connect(
            self.__control,
            chirp_vco,
            self)
    
    def get_input_type(self):
        return no_signal
    
    def get_output_type(self):
        return SignalType(kind='IQ', sample_rate=self.__output_rate)
    
    @exported_value(parameter='chirp_rate', type=Range([(-10.0, 10.0)], strict=False))
    def get_chirp_rate(self):
        return self.__chirp_rate
    
    @setter
    def set_chirp_rate(self, value):
        self.__chirp_rate = value
        self.__control.set_frequency(value)
