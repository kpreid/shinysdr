# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

from zope.interface import implementer  # available via Twisted

from gnuradio import gr
from gnuradio import blocks

import osmosdr

from shinysdr.devices import Device, IRXDriver, ITXDriver
from shinysdr.signals import SignalType
from shinysdr.types import ConstantT, EnumT, QuantityT, RangeT, ReferenceT
from shinysdr import units
from shinysdr.values import ExportedState, LooseCell, PollingCell, exported_value, nullExportedState, setter


__all__ = []


ch = 0  # single channel number used


# Constants from gr-osmosdr that aren't swig-exported
DCOffsetOff = 0
DCOffsetManual = 1
DCOffsetAutomatic = 2
IQBalanceOff = 0
IQBalanceManual = 1
IQBalanceAutomatic = 2


# default tune_delay value
DEFAULT_DELAY = 0.07


# TODO: Allow profiles to export information about known spurious signals in receivers, in the form of a freq-DB. Note that they must be flagged as uncalibrated freqs.
# Ex: Per <http://www.reddit.com/r/RTLSDR/comments/1nl3tl/has_anybody_done_a_comparison_of_where_the_spurs/> all RTL2832U have harmonics of 28.8MHz and 48MHz.


class OsmoSDRProfile(object):
    """
    Description of the characteristics of specific hardware which cannot
    be obtained automatically via OsmoSDR.
    """
    
    def __init__(self,
            tx=False,  # safe assumption
            agc=True,  # show useless controls > hide functionality
            dc_cancel=True,  # ditto
            dc_offset=True,  # safe assumption
            tune_delay=DEFAULT_DELAY,
            e4000=False):
        """
        All values are booleans.
        
        tx: The device supports transmitting (osmosdr.sink).
        agc: The device has a hardware AGC (set_gain_mode works).
        dc_cancel: The device supports DC offset auto cancellation
            (set_dc_offset_mode auto works).
        dc_offset: The output has a DC offset and tuning should
            avoid the area around DC.
        e4000: The device is an RTL2832U + E4000 tuner and can be
            confused into tuning to 0 Hz.
        """
        
        # TODO: If the user specifies an OsmoSDRProfile without a full set of explicit args, derive the rest from the device string instead of using defaults.
        self.tx = bool(tx)
        self.agc = bool(agc)
        self.dc_cancel = bool(dc_cancel)
        self.dc_offset = bool(dc_offset)
        self.tune_delay = float(tune_delay)
        self.e4000 = bool(e4000)
    
    # TODO: Is there a good way to not have to write all this "implementation of a simple structure" boilerplate, that isn't "inherit namedtuple" which imposes further constraints?
    
    def __eq__(self, other):
        # pylint: disable=unidiomatic-typecheck
        return type(self) == type(other) and self.__dict__ == other.__dict__
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    __hash__ = None
    
    def __repr__(self):
        return 'OsmoSDRProfile(%s)' % (', '.join('%s=%s' % kv for kv in self.__dict__.iteritems()))


__all__.append('OsmoSDRProfile')


def profile_from_device_string(device_string):
    # TODO: The input is actually an "args" string, which contains multiple devices space-separated. We should support this, but it is hard because osmosdr does not export the internal args_to_vector function and parsing it ourselves would need to be escaping-aware.
    params = {k: v for k, v in osmosdr.device_t(device_string).items()}
    for param_key in params.iterkeys():
        if param_key in _default_profiles:
            # is a device of this type
            return _default_profiles[param_key]
    # no match / unknown
    return OsmoSDRProfile()


if 1 == 1:  # dummy block for pylint
    # pylint: disable=bad-whitespace
    _default_profiles = {
        'file':    OsmoSDRProfile(tx=False, agc=False, dc_cancel=False, dc_offset=False, tune_delay=0.0),
        'osmosdr': OsmoSDRProfile(tx=False, agc=True,  dc_cancel=False, dc_offset=True,  tune_delay=DEFAULT_DELAY),  # TODO confirm dc
        'fcd':     OsmoSDRProfile(tx=False, agc=False, dc_cancel=False, dc_offset=False, tune_delay=DEFAULT_DELAY),
        'rtl':     OsmoSDRProfile(tx=False, agc=True,  dc_cancel=False, dc_offset=False, tune_delay=0.13),
        'rtl_tcp': OsmoSDRProfile(tx=False, agc=True,  dc_cancel=False, dc_offset=False, tune_delay=DEFAULT_DELAY),
        'uhd':     OsmoSDRProfile(tx=True,  agc=False, dc_cancel=True,  dc_offset=True,  tune_delay=0.0),
        'miri':    OsmoSDRProfile(tx=False, agc=True,  dc_cancel=False, dc_offset=True,  tune_delay=DEFAULT_DELAY),  # TODO confirm dc
        'hackrf':  OsmoSDRProfile(tx=True,  agc=False, dc_cancel=False, dc_offset=True,  tune_delay=0.045),
        'bladerf': OsmoSDRProfile(tx=True,  agc=False, dc_cancel=False, dc_offset=True,  tune_delay=DEFAULT_DELAY),
        'rfspace': OsmoSDRProfile(tx=False, agc=False, dc_cancel=False, dc_offset=True,  tune_delay=DEFAULT_DELAY),
        'airspy':  OsmoSDRProfile(tx=False, agc=False, dc_cancel=False, dc_offset=True,  tune_delay=DEFAULT_DELAY),
        'soapy':   OsmoSDRProfile(tx=True,  agc=True,  dc_cancel=True,  dc_offset=False, tune_delay=DEFAULT_DELAY),
    }
    _default_profiles['sdr-iq'] = _default_profiles['rfspace']
    _default_profiles['sdr-ip'] = _default_profiles['rfspace']
    _default_profiles['netsdr'] = _default_profiles['rfspace']


class _OsmoSDRTuning(object):
    def __init__(self, profile, correction_ppm, osmo_block):
        self.__profile = profile
        self.__correction_ppm = correction_ppm
        self.__osmo_block = osmo_block
        self.__vfo_cell = LooseCell(
            value=0.0,
            # TODO: Eventually we'd like to be able to make the freq range vary dynamically with the correction setting
            type=convert_osmosdr_range(
                osmo_block.get_freq_range(ch),
                strict=False,
                transform=self.from_hardware_freq,
                unit=units.Hz,
                add_zero=profile.e4000),
            writable=True,
            persists=True,
            post_hook=self.__set_freq)
    
    def __set_freq(self, freq):
        self.__osmo_block.set_center_freq(self.to_hardware_freq(freq))
        
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
        passband = sample_rate * (3 / 8)  # 3/4 of + and - halves
        if self.__profile.dc_offset:
            epsilon = 1.0  # TODO: Put width in the profile.
            return RangeT([(-passband, -epsilon), (epsilon, passband)])
        else:
            return RangeT([(-passband, passband)])
    
    def set_block(self, value):
        self.__osmo_block = value
        if self.__osmo_block is not None:
            self.__set_freq(self.__vfo_cell.get())


def OsmoSDRDevice(
        osmo_device,
        name=None,
        profile=None,
        sample_rate=None,
        correction_ppm=0.0):
    """
    osmo_device: gr-osmosdr device string
    name: block name (usually not specified)
    profile: an OsmoSDRProfile (see docs)
    sample_rate: desired sample rate, or None == guess a good rate
    correction_ppm: oscillator frequency calibration (parts-per-million)
    
    See documentation in shinysdr/i/webstatic/manual/configuration.html.
    """
    # The existence of the correction_ppm parameter is a workaround for the current inability to dynamically change an exported field's type (the frequency range), allowing them to be initialized early enough, in the configuration, to take effect. (Well, it's also nice to hardcode them in the config if you want to.)
    osmo_device = str(osmo_device)  # ensure not unicode type as we talk to byte-oriented C++
    if name is None:
        name = 'OsmoSDR %s' % osmo_device
    if profile is None:
        profile = profile_from_device_string(osmo_device)
    
    source = osmosdr.source(b'numchan=1 ' + osmo_device)
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
        osmo_device=osmo_device,
        source=source,
        profile=profile,
        name=name,
        tuning=tuning)
    
    if profile.tx:
        tx_sample_rate = 2000000  # TODO KLUDGE NOT GENERAL need to use profile
        tx_driver = _OsmoSDRTXDriver(
            osmo_device=osmo_device,
            rx=rx_driver,
            name=name,
            tuning=tuning,
            sample_rate=tx_sample_rate)
    else:
        tx_driver = nullExportedState
    
    hw_initial_freq = source.get_center_freq()
    if hw_initial_freq == 0.0:
        # If the hardware/driver isn't providing a reasonable default (RTLs don't), do it ourselves; go to the middle of the FM broadcast band (rounded up or down to what the hardware reports it supports).
        vfo_cell.set(100e6)
    else:
        print hw_initial_freq
        vfo_cell.set(tuning.from_hardware_freq(hw_initial_freq))
    
    return Device(
        name=name,
        vfo_cell=vfo_cell,
        rx_driver=rx_driver,
        tx_driver=tx_driver)


__all__.append('OsmoSDRDevice')


@implementer(IRXDriver)
class _OsmoSDRRXDriver(ExportedState, gr.hier_block2):
    
    # Note: Docs for gr-osmosdr are in comments at gr-osmosdr/lib/source_iface.h
    def __init__(self,
            osmo_device,
            source,
            profile,
            name,
            tuning):
        gr.hier_block2.__init__(
            self, b'RX ' + str(name),
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__osmo_device = osmo_device
        self.__source = source
        self.__profile = profile
        self.__name = name
        self.__tuning = tuning
        self.__antenna_type = EnumT({unicode(name): unicode(name) for name in self.__source.get_antennas()}, strict=True)
        
        self.connect(self.__source, self)
        
        self.__gains = Gains(source, self)
        
        # State of the source that there are no getters for, so we must keep our own copy of
        self.__track_dc_offset_mode = DCOffsetOff
        self.__track_iq_balance_mode = IQBalanceOff
        source.set_dc_offset_mode(self.__track_dc_offset_mode, ch)
        source.set_iq_balance_mode(self.__track_iq_balance_mode, ch)
        
        # Blocks
        self.__state_while_inactive = {}
        self.__placeholder = blocks.vector_source_c([])
        
        sample_rate = float(source.get_sample_rate())
        self.__signal_type = SignalType(
            kind='IQ',
            sample_rate=sample_rate)
        self.__usable_bandwidth = tuning.calc_usable_bandwidth(sample_rate)
    
    @exported_value(type=SignalType, changes='never')
    def get_output_type(self):
        return self.__signal_type
    
    # implement IRXDriver
    def get_tune_delay(self):
        return self.__profile.tune_delay

    # implement IRXDriver
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth
    
    # implement IRXDriver
    def close(self):
        self._stop_rx()
        self.__tuning = None
    
    @exported_value(
        type=QuantityT(unit=units.ppm),
        changes='this_setter',
        label='Freq.corr.')
    def get_correction_ppm(self):
        return self.__tuning.get_correction_ppm()
    
    @setter
    def set_correction_ppm(self, value):
        self.__tuning.set_correction_ppm(value)
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_gains(self):
        return self.__gains
    
    @exported_value(
        type_fn=lambda self: convert_osmosdr_range(
            self.__source.get_gain_range(ch), unit=units.dB, strict=False),
        changes='this_setter',
        label='Gain')
    def get_gain(self):
        if self.__source is None: return 0.0
        return self.__source.get_gain(ch)
    
    @setter
    def set_gain(self, value):
        self.__source.set_gain(float(value), ch)
        # The single gain and individual-stage gain controls have an unspecified relationship to each other. Thus, changing one must poll the other.
        self.__gains.state_changed()
    
    @exported_value(
        type_fn=lambda self: bool if self.__profile.agc else ConstantT(False),
        changes='this_setter',
        label='AGC on')
    def get_agc(self):
        if self.__source is None: return False
        return bool(self.__source.get_gain_mode(ch))
    
    @setter
    def set_agc(self, value):
        self.__source.set_gain_mode(bool(value), ch)
    
    @exported_value(
        type_fn=lambda self: self.__antenna_type,
        changes='this_setter',
        label='Antenna')
    def get_antenna(self):
        if self.__source is None: return ''
        return unicode(self.__source.get_antenna(ch))
    
    @setter
    def set_antenna(self, value):
        # TODO we should have a provision for restricting antenna selection when transmit is possible to avoid hardware damage
        self.__source.set_antenna(str(self.__antenna_type(value)), ch)
    
    # Note: dc_offset_mode has a 'manual' mode we are not yet exposing, which is why the internal tracking is an enum integer but the exported value is a boolean
    @exported_value(
        type_fn=lambda self: bool if self.__profile.dc_cancel else ConstantT(False),
        changes='this_setter',
        label='Use DC cancellation')
    def get_dc_cancel(self):
        return bool(self.__track_dc_offset_mode)
    
    @setter
    def set_dc_cancel(self, value):
        if value:
            mode = DCOffsetAutomatic
        else:
            mode = DCOffsetOff
        self.__source.set_dc_offset_mode(mode, ch)
        self.__track_dc_offset_mode = mode
    
    # Note: iq_balance_mode has a 'manual' mode we are not yet exposing, which is why the internal tracking is an enum integer but the exported value is a boolean
    @exported_value(type=bool,    # TODO: detect gr-iqbal
        changes='this_setter',
        label='Use IQ balancer')
    def get_iq_balance(self):
        return bool(self.__track_iq_balance_mode)

    @setter
    def set_iq_balance(self, value):
        if value:
            mode = IQBalanceAutomatic
        else:
            mode = IQBalanceOff
        self.__source.set_iq_balance_mode(mode, ch)
        self.__track_iq_balance_mode = mode
    
    # add_zero because zero means automatic setting based on sample rate.
    # TODO: Display automaticness in the UI rather than having a zero value.
    @exported_value(
        type_fn=lambda self: convert_osmosdr_range(
            self.__source.get_bandwidth_range(ch), unit=units.Hz, add_zero=True),
        changes='this_setter',
        label='Analog bandwidth',
        description='Bandwidth of the analog antialiasing filter.')
    def get_bandwidth(self):
        if self.__source is None: return 0.0
        return self.__source.get_bandwidth(ch)
    
    @setter
    def set_bandwidth(self, value):
        self.__source.set_bandwidth(float(value), ch)
    
    def notify_reconnecting_or_restarting(self):
        pass

    # link to tx driver
    def _stop_rx(self):
        self.disconnect_all()
        self.__state_while_inactive = self.state_to_json()
        self.__tuning.set_block(None)
        self.__gains.close()
        self.__source = None
        self.connect(self.__placeholder, self)
    
    # link to tx driver
    def _start_rx(self):
        self.disconnect_all()
        self.__source = osmosdr.source('numchan=1 ' + self.__osmo_device)
        self.__source.set_sample_rate(self.__signal_type.get_sample_rate())
        self.__tuning.set_block(self.__source)
        self.__gains = Gains(self.__source, self)
        self.connect(self.__source, self)
        self.state_from_json(self.__state_while_inactive)


@implementer(ITXDriver)
class _OsmoSDRTXDriver(ExportedState, gr.hier_block2):
    def __init__(self,
            osmo_device,
            rx,
            name,
            tuning,
            sample_rate):
        gr.hier_block2.__init__(
            self, b'TX ' + str(name),
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(0, 0, 0))
        
        self.__osmo_device = osmo_device
        self.__rx_driver = rx
        self.__tuning = tuning
        
        self.__signal_type = SignalType(
            kind='IQ',
            sample_rate=sample_rate)
        
        self.__sink = None
        self.__placeholder = blocks.null_sink(gr.sizeof_gr_complex)
        self.__state_while_inactive = {}
        
        self.connect(self, self.__placeholder)
    
    # implement ITXDriver
    def get_input_type(self):
        return self.__signal_type
    
    # implement ITXDriver
    def close(self):
        self.disconnect_all()
        self.__rx_driver = None
        self.__sink = None
        self.__tuning = None
    
    # implement ITXDriver
    def notify_reconnecting_or_restarting(self):
        pass
    
    # implement ITXDriver
    def set_transmitting(self, value, midpoint_hook):
        self.disconnect_all()
        if value:
            self.__rx_driver._stop_rx()
            midpoint_hook()
            self.__sink = osmosdr.sink(self.__osmo_device)
            self.__sink.set_sample_rate(self.__signal_type.get_sample_rate())
            self.__tuning.set_block(self.__sink)
            self.connect(self, self.__sink)
            self.state_from_json(self.__state_while_inactive)
        else:
            self.__state_while_inactive = self.state_to_json()
            self.__tuning.set_block(None)
            self.__sink = None
            self.connect(self, self.__placeholder)
            midpoint_hook()
            self.__rx_driver._start_rx()


class Gains(ExportedState):
    def __init__(self, source, rxd):
        self.__source_ref = [source]
        self.__rxd_ref = [rxd]
    
    # be able to drop source ref even from the cells
    def close(self):
        self.__source_ref[0] = None
        self.__rxd_ref[0] = None
    
    def state_def(self):
        for d in super(Gains, self).state_def():
            yield d
        source_ref = self.__source_ref
        for name in source_ref[0].get_gain_names():
            # use a function to close over name
            yield _install_gain_cell(self, source_ref, self.__rxd_ref, name)


def _install_gain_cell(self, source_ref, rxd_ref, name):
    def gain_getter():
        source = source_ref[0]
        return 0 if source is None else source.get_gain(name, ch)
    
    def gain_setter(value):
        source = source_ref[0]
        if source is not None:
            source.set_gain(float(value), name, ch)
        rxd = rxd_ref[0]
        if rxd is not None:
            # The single gain and individual-stage gain controls have an unspecified relationship to each other. Thus, changing one must poll the other.
            rxd.state_changed('gain')
    
    gain_range = convert_osmosdr_range(source_ref[0].get_gain_range(name, ch), unit=units.dB)
    
    # TODO: There should be a type of Cell such that we don't have to setattr but still implement the storage unlike LooseCell
    setattr(self, 'get_' + name, gain_getter)
    setattr(self, 'set_' + name, gain_setter)
    return name, PollingCell(self, name,
        type=gain_range,
        writable=True,
        persists=True,
        changes='this_setter',
        label=name)


def convert_osmosdr_range(meta_range, add_zero=False, transform=lambda f: f, **kwargs):
    # TODO: Recognize step values from osmosdr
    subranges = []
    for i in xrange(0, meta_range.size()):
        single_range = meta_range[i]
        subranges.append((transform(single_range.start()), transform(single_range.stop())))
    if add_zero or not subranges:  # don't generate an invalid empty RangeT
        subranges[0:0] = [(0, 0)]
    return RangeT(subranges, **kwargs)
