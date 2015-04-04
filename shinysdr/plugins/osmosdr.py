# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

from zope.interface import implements  # available via Twisted

from gnuradio import gr

from shinysdr.devices import Device, FrequencyShift, IRXDriver, merge_devices
from shinysdr.signals import SignalType
from shinysdr.types import Enum, Range
from shinysdr.values import BlockCell, Cell, ExportedState, LooseCell, exported_value, setter

import osmosdr


__all__ = []


ch = 0  # single channel number used


# TODO: Allow profiles to export information about known spurious signals in receivers, in the form of a freq-DB. Note that they must be flagged as uncalibrated freqs.
# Ex: Per <http://www.reddit.com/r/RTLSDR/comments/1nl3tl/has_anybody_done_a_comparison_of_where_the_spurs/> all RTL2832U have harmonics of 28.8MHz and 48MHz.


class OsmoSDRProfile(object):
    '''
    Description of the characteristics of specific hardware which cannot
    be obtained automatically via OsmoSDR.
    '''
    def __init__(self, dc_offset=False, e4000=False):
        '''
        dc_offset: If true, the output has a DC offset and tuning should
            avoid the area around DC.
        e4000: The device is an RTL2832U + E4000 tuner and can be
            confused into tuning to 0 Hz.
        '''
        # TODO: Propagate DC offset info to client tune() -- currently unused
        self.dc_offset = dc_offset
        self.e4000 = e4000


class _OsmoSDRTuning(object):
    def __init__(self, profile, correction_ppm, source):
        self.__profile = profile
        self.__correction_ppm = correction_ppm
        self.__source = source
        self.__vfo_cell = LooseCell(
            key='freq',
            value=0.0,
            # TODO: Eventually we'd like to be able to make the freq range vary dynamically with the correction setting
            ctor=convert_osmosdr_range(
                source.get_freq_range(ch),
                strict=False,
                transform=self.from_hardware_freq,
                add_zero=profile.e4000),
            writable=True,
            persists=True,
            post_hook=self.__set_freq)
    
    def __set_freq(self, freq):
        self.__source.set_center_freq(self.to_hardware_freq(freq))
        
    def to_hardware_freq(self, effective_freq):
        if abs(effective_freq) < 1e-2 and self.__profile.e4000:
            # Quirk: Tuning to 3686.6-3730 MHz on the E4000 causes operation effectively at 0Hz.
            # Original report: <http://www.reddit.com/r/RTLSDR/comments/12d2wc/a_very_surprising_discovery/>
            return 3700e6
        else:
            return effective_freq * (1 - 1e-6 * self.__correction_ppm)
    
    def from_hardware_freq(self, freq):
        freq = freq / (1 - 1e-6 * self.__correction_ppm)
        if 3686.6e6 <= freq <= 3730e6 and self.__profile.e4000:
            freq = 0.0
        return freq
    
    def get_vfo_cell(self):
        return self.__vfo_cell

    def get_correction_ppm(self):
        return self.__correction_ppm
    
    def set_correction_ppm(self, value):
        self.__correction_ppm = float(value)
        # Not using the osmosdr feature because changing it at runtime produces glitches like the sample rate got changed; therefore we emulate it ourselves. TODO: I am informed that using set_freq_corr can correct sample-clock error, so we ought to at least use it on init.
        # self.osmosdr_source_block.set_freq_corr(value, 0)
        self.__set_freq(self.__vfo_cell.get())
    
    def calc_usable_bandwidth(self, sample_rate):
        passband = sample_rate * (3/8)  # 3/4 of + and - halves
        if self.__profile.dc_offset:
            epsilon = 1.0  # Range has only inclusive bounds, so we need a nonzero value.
            return Range([(-passband, -epsilon), (epsilon, passband)])
        else:
            return Range([(-passband, passband)])


def OsmoSDRDevice(
        osmo_device,
        name=None,
        profile=OsmoSDRProfile(),
        sample_rate=None,
        external_freq_shift=0.0,  # deprecated
        correction_ppm=0.0):
    '''
    osmo_device: gr-osmosdr device string
    name: block name (usually not specified)
    profile: an OsmoSDRProfile (see docs)
    sample_rate: desired sample rate, or None == guess a good rate
    external_freq_shift: external (down|up)converter frequency (Hz) -- DEPRECATED, use shinysdr.devices.FrequencyShift
    correction_ppm: oscillator frequency calibration (parts-per-million)
    '''
    # The existence of the correction_ppm parameter is a workaround for the current inability to dynamically change an exported field's type (the frequency range), allowing them to be initialized early enough, in the configuration, to take effect. (Well, it's also nice to hardcode them in the config if you want to.)
    if name is None:
        name = 'OsmoSDR %s' % osmo_device
    
    source = osmosdr.source('numchan=1 ' + osmo_device)
    if source.get_num_channels() < 1:
        # osmosdr.source doesn't throw an exception, allegedly because gnuradio can't handle it in a hier_block2 initializer. But we want to fail understandably, so recover by detecting it (sample rate = 0, which is otherwise nonsense)
        raise LookupError('OsmoSDR device not found (device string = %r)' % osmo_device)
    elif source.get_num_channels() > 1:
        raise LookupError('Too many devices/channels; need exactly one (device string = %r)' % osmo_device)
    
    tuning = _OsmoSDRTuning(profile, correction_ppm, source)
    vfo_cell = tuning.get_vfo_cell()
    
    if sample_rate is None:
        # If sample_rate is unspecified, we pick the closest available rate to a reasonable value. (Reasonable in that it's within the data handling capabilities of this software and of USB 2.0 connections.) Previously, we chose the maximum sample rate, but that may be too high for the connection the RF hardware, or too high for the CPU to FFT/demodulate.
        source.set_sample_rate(convert_osmosdr_range(source.get_sample_rates())(2.4e6))
    else:
        source.set_sample_rate(sample_rate)
    
    rx_driver = _OsmoSDRRXDriver(
        source=source,
        name=name,
        sample_rate=sample_rate,
        tuning=tuning)
    
    hw_initial_freq = source.get_center_freq()
    if hw_initial_freq == 0.0:
        # If the hardware/driver isn't providing a reasonable default (RTLs don't), do it ourselves; go to the middle of the FM broadcast band (rounded up or down to what the hardware reports it supports).
        vfo_cell.set(100e6)
    else:
        print hw_initial_freq
        vfo_cell.set(tuning.from_hardware_freq(hw_initial_freq))
    
    self = Device(
        name=name,
        vfo_cell=vfo_cell,
        rx_driver=rx_driver)
    
    # implement legacy option in terms of new devices
    if external_freq_shift == 0.0:
        return self
    else:
        return merge_devices([self, FrequencyShift(-external_freq_shift)])


__all__.append('SimulatedDevice')


OsmoSDRSource = OsmoSDRDevice  # legacy alias


class _OsmoSDRRXDriver(ExportedState, gr.hier_block2):
    implements(IRXDriver)
    
    # Note: Docs for gr-osmosdr are in comments at gr-osmosdr/lib/source_iface.h
    def __init__(self,
            source,
            name,
            sample_rate,
            tuning):
        gr.hier_block2.__init__(
            self, name,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )

        self.__name = name
        self.__tuning = tuning
        self.__source = source
        
        self.connect(self.__source, self)
        
        self.gains = Gains(source)
        
        # Misc state
        self.dc_state = 0
        self.iq_state = 0
        source.set_dc_offset_mode(self.dc_state, ch)  # no getter, set to known state
        source.set_iq_balance_mode(self.iq_state, ch)  # no getter, set to known state
        
        sample_rate = float(source.get_sample_rate())
        self.__signal_type = SignalType(
            kind='IQ',
            sample_rate=sample_rate)
        self.__usable_bandwidth = tuning.calc_usable_bandwidth(sample_rate)
        
        
    def state_def(self, callback):
        super(_OsmoSDRRXDriver, self).state_def(callback)
        # TODO make this possible to be decorator style
        callback(BlockCell(self, 'gains'))
    
    @exported_value(ctor=SignalType)
    def get_output_type(self):
        return self.__signal_type
    
    # implement IRXDriver
    def get_tune_delay(self):
        return 0.25  # TODO: make configurable and/or account for as many factors as we can

    # implement IRXDriver
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth
    
    # implement IRXDriver
    def close(self):
        # Not found to be strictly necessary, because Device will drop this driver, but hey.
        self.__source = None
        self.disconnect_all()
    
    @exported_value(ctor=float)
    def get_correction_ppm(self):
        return self.__tuning.get_correction_ppm()
    
    @setter
    def set_correction_ppm(self, value):
        self.__tuning.set_correction_ppm(value)
    
    @exported_value(ctor_fn=lambda self: convert_osmosdr_range(
            self.__source.get_gain_range(ch), strict=False))
    def get_gain(self):
        return self.__source.get_gain(ch)
    
    @setter
    def set_gain(self, value):
        self.__source.set_gain(float(value), ch)
    
    @exported_value(ctor=bool)
    def get_agc(self):
        return bool(self.__source.get_gain_mode(ch))
    
    @setter
    def set_agc(self, value):
        self.__source.set_gain_mode(bool(value), ch)
    
    @exported_value(ctor_fn=lambda self: Enum(
        {unicode(name): unicode(name) for name in self.__source.get_antennas()}))
    def get_antenna(self):
        return unicode(self.__source.get_antenna(ch))
        # TODO review whether set_antenna is safe to expose
    
    # Note: dc_cancel has a 'manual' mode we are not yet exposing
    @exported_value(ctor=bool)
    def get_dc_cancel(self):
        return bool(self.dc_state)
    
    @setter
    def set_dc_cancel(self, value):
        self.dc_state = bool(value)
        if self.dc_state:
            mode = 2  # automatic mode
        else:
            mode = 0
        self.__source.set_dc_offset_mode(mode, ch)
    
    # Note: iq_balance has a 'manual' mode we are not yet exposing
    @exported_value(ctor=bool)
    def get_iq_balance(self):
        return bool(self.iq_state)

    @setter
    def set_iq_balance(self, value):
        self.iq_state = bool(value)
        if self.iq_state:
            mode = 2  # automatic mode
        else:
            mode = 0
        self.__source.set_iq_balance_mode(mode, ch)
    
    # add_zero because zero means automatic setting based on sample rate.
    # TODO: Display automaticness in the UI rather than having a zero value.
    @exported_value(ctor_fn=lambda self: convert_osmosdr_range(
        self.__source.get_bandwidth_range(ch), add_zero=True))
    def get_bandwidth(self):
        return self.__source.get_bandwidth(ch)
    
    @setter
    def set_bandwidth(self, value):
        self.__source.set_bandwidth(float(value), ch)
    
    def notify_reconnecting_or_restarting(self):
        pass


class Gains(ExportedState):
    def __init__(self, source):
        self.__source = source
    
    def state_def(self, callback):
        source = self.__source
        for name in source.get_gain_names():
            # use a function to close over name
            _install_gain_cell(self, source, name, callback)


def _install_gain_cell(self, source, name, callback):
    def gain_getter():
        return source.get_gain(name, ch)
    
    def gain_setter(value):
        source.set_gain(float(value), name, ch)
    
    gain_range = convert_osmosdr_range(source.get_gain_range(name, ch))
    
    # TODO: There should be a type of Cell such that we don't have to setattr
    setattr(self, 'get_' + name, gain_getter)
    setattr(self, 'set_' + name, gain_setter)
    callback(Cell(self, name, ctor=gain_range, writable=True, persists=True))


def convert_osmosdr_range(meta_range, add_zero=False, transform=lambda f: f, **kwargs):
    # TODO: Recognize step values from osmosdr
    subranges = []
    for i in xrange(0, meta_range.size()):
        single_range = meta_range[i]
        subranges.append((transform(single_range.start()), transform(single_range.stop())))
    if add_zero:
        subranges[0:0] = [(0, 0)]
    return Range(subranges, **kwargs)
