# Copyright 2018 Google LLC.
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

try:
    import limesdr
    _available = True
except ImportError:
    _available = False

from shinysdr.devices import Device, IRXDriver
from shinysdr.i.pycompat import defaultstr
from shinysdr.signals import SignalType
from shinysdr.types import EnumT, RangeT
from shinysdr import units
from shinysdr.values import ExportedState, LooseCell, exported_value, nullExportedState, setter


__all__ = []


# TODO: Support both channels on LimeSDRUSB
ch = 0  # single channel number used


# Constants, not exported by gr-limesdr
LimeSDRMini = 1
LimeSDRUSB = 2
SISO = 1
MIMO = 2
A = 0
B = 1
LNANONE = 0
LNAH = 1
LNAL = 2
LNAW = 3
UPCONVERT = 0
DOWNCONVERT = 1


class _LimeSDRTuning(object):
    def __init__(self, lime_block):
        self.__lime_block = lime_block
        self.__vfo_cell = LooseCell(
            value=0.0,
            type=RangeT([(10e6, 3500e6)],
                        strict=False,
                        unit=units.Hz),
            writable=True,
            persists=True,
            post_hook=self.__set_freq)
    
    def __set_freq(self, freq):
        self.__lime_block.set_rf_freq(freq)
        
    def get_vfo_cell(self):
        return self.__vfo_cell

    def calc_usable_bandwidth(self, total_bandwidth):
        # Assume right up against the edges of the filter are unusable.
        passband = total_bandwidth * (3 / 8)  # 3/4 of + and - halves
        return RangeT([(-passband, passband)])
    
    def set_block(self, value):
        self.__lime_block = value
        if self.__lime_block is not None:
            self.__set_freq(self.__vfo_cell.get())


def create_source(serial, device_type, lna_path, sample_rate, freq, if_bandwidth, gain, calibration=True):
    # TODO: Consider using NCO to avoid DC spur.
    # TODO: Support choosing the channel
    # TODO: Use sample_rate or if_bandwidth as calibr_bandw?
    return limesdr.source(
        serial=serial,
        device_type=device_type,  # LimeSDR-USB
        chip_mode=SISO,  # SISO(1),MIMO(2)
        channel=ch,  # A(0),B(1)
        file_switch=0,  # Don't load settings from a file
        filename=defaultstr(''),
        rf_freq=freq,  # Center frequency in Hz
        samp_rate=sample_rate,
        oversample=0,  # 0(default),1,2,4,8,16,32
        calibration_ch0=1 if calibration and ch == 0 else 0,
        calibr_bandw_ch0=60e6,
        calibration_ch1=1 if calibration and ch == 1 else 0,
        calibr_bandw_ch1=60e6,
        lna_path_mini=lna_path,  # LNAH(1),LNAW(3)
        lna_path_ch0=lna_path,  # no path(0),LNAH(1),LNAL(2),LNAW(3)
        lna_path_ch1=lna_path,  # no path(0),LNAH(1),LNAL(2),LNAW(3)
        analog_filter_ch0=1,
        analog_bandw_ch0=if_bandwidth,
        analog_filter_ch1=1,
        analog_bandw_ch1=if_bandwidth,
        digital_filter_ch0=1,
        digital_bandw_ch0=if_bandwidth,
        digital_filter_ch1=1,
        digital_bandw_ch1=if_bandwidth,
        gain_dB_ch0=gain,
        gain_dB_ch1=gain,
        nco_freq_ch0=0,
        nco_freq_ch1=0,
        cmix_mode_ch0=0,  # UPCONVERT(0), DOWNCONVERT(1)
        cmix_mode_ch1=0,  # UPCONVERT(0), DOWNCONVERT(1)
    )


def LimeSDRDevice(
        serial,
        device_type,
        lna_path=LNAW,
        sample_rate=2.4e6,
        name=None,
        calibration=True):
    """
    serial: device serial number
    device_type: LimeSDRMini or LimeSDRUSB
    lna_path: LNANONE, LNAL, LNAH, or LNAW
    name: block name (usually not specified)
    sample_rate: desired sample rate, or None == guess a good rate
    
    See documentation in shinysdr/i/webstatic/manual/configuration.html.
    """
    
    if not _available:
        raise Exception('LimeSDRDevice: gr-limesdr Python bindings not found; cannot create device')
    
    serial = defaultstr(serial)
    if name is None:
        name = 'LimeSDR %s' % serial

    # TODO: High gain might be unsafe, but low gain might result in failed calibration.
    # Ideally we'd load these initial values from the saved state?
    freq = 1e9
    gain = 50
    if_bandwidth = 3e6

    source = create_source(serial, device_type, lna_path, sample_rate, freq, if_bandwidth, gain, calibration=calibration)
    
    tuning = _LimeSDRTuning(source)
    vfo_cell = tuning.get_vfo_cell()
    
    rx_driver = _LimeSDRRXDriver(
        device_type=device_type,
        source=source,
        lna_path=lna_path,
        name=name,
        tuning=tuning,
        sample_rate=sample_rate)
    
    vfo_cell.set(freq)
    
    return Device(
        name=name,
        vfo_cell=vfo_cell,
        rx_driver=rx_driver,
        tx_driver=nullExportedState)


__all__.append('LimeSDRDevice')


@implementer(IRXDriver)
class _LimeSDRRXDriver(ExportedState, gr.hier_block2):
    
    # Note: Docs for gr-limesdr are in comments at gr-limesdr/include/limesdr/source.h
    def __init__(self,
                 source,
                 device_type,
                 lna_path,
                 name,
                 tuning,
                 sample_rate):
        gr.hier_block2.__init__(
            self, defaultstr('RX ' + name),
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__source = source
        self.__name = name
        self.__tuning = tuning
        
        self.connect(self.__source, self)
        
        # State of the source that there are no getters for, so we must keep our own copy of
        self.__track_gain = 50.
        source.set_gain(int(self.__track_gain), ch)

        self.__track_bandwidth = max(sample_rate / 2, 1.5e6)
        source.set_analog_filter(True, self.__track_bandwidth, ch)

        self.__lna_path_type = EnumT({
            LNANONE: 'None',
            LNAH: 'LNAH',
            LNAL: 'LNAL',
            LNAW: 'LNAW',
        })
        if device_type == LimeSDRMini:
            self.__lna_path_type = EnumT({
                LNAH: 'LNAH',
                LNAW: 'LNAW',
            })
        self.__track_lna_path = lna_path
        
        self.__signal_type = SignalType(
            kind='IQ',
            sample_rate=sample_rate)
        self.__usable_bandwidth = tuning.calc_usable_bandwidth(sample_rate)
    
    @exported_value(type=SignalType, changes='never')
    def get_output_type(self):
        return self.__signal_type
    
    # implement IRXDriver
    def get_tune_delay(self):
        # TODO: Measure this.
        return 0.07

    # implement IRXDriver
    def get_usable_bandwidth(self):
        if self.__track_bandwidth:
            return self.__tuning.calc_usable_bandwidth(self.__track_bandwidth)
        return self.__usable_bandwidth
    
    # implement IRXDriver
    def close(self):
        self.disconnect_all()
        self.__source = None
        self.__tuning = None

    @exported_value(
        type_fn=lambda self: self.__lna_path_type,
        changes='this_setter',
        label='LNA Path')
    def get_lna_path(self):
        return self.__track_lna_path

    @setter
    def set_lna_path(self, lna_path):
        self.__track_lna_path = int(lna_path)
        self.__source.set_lna_path(int(lna_path), ch)
    
    @exported_value(
        type_fn=lambda self: RangeT([(0, 70)], unit=units.dB, strict=False),
        changes='this_setter',
        label='Gain')
    def get_gain(self):
        if self.__source is None: return 0.0
        return self.__track_gain
    
    @setter
    def set_gain(self, value):
        self.__track_gain = int(value)
        self.__source.set_gain(int(value), ch)

    # zero means no filter
    @exported_value(
        type_fn=lambda self: RangeT([(1e3, min(130e6, self.__signal_type.get_sample_rate()))], unit=units.Hz),
        changes='this_setter',
        label='Hardware filter',
        description='Bandwidth of the analog and digital filters.')
    def get_bandwidth(self):
        if self.__source is None: return 0.0
        return self.__track_bandwidth
    
    @setter
    def set_bandwidth(self, value):
        self.__track_bandwidth = float(value)
        if value == self.__signal_type.get_sample_rate():
            self.__source.set_analog_filter(False, 0, ch)
            self.__source.set_digital_filter(False, 0, ch)
            return
        # Analog filter goes down to 1.5e6, digital filter goes arbitrarily low.
        analog = max(value, 1.5e6)
        self.__source.set_analog_filter(True, float(analog), ch)
        self.__source.set_digital_filter(True, float(value), ch)
    
    def notify_reconnecting_or_restarting(self):
        pass


# TODO: Implement TX driver.
