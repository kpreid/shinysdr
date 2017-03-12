# -*- coding: utf-8 -*-
# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from collections import Counter

from zope.interface import Interface, implements  # available via Twisted

from gnuradio import audio
from gnuradio import blocks
from gnuradio import gr

from shinysdr.signals import SignalType
from shinysdr.telemetry import TelemetryItem, Track, empty_track
from shinysdr.types import RangeT, ReferenceT
from shinysdr.values import CellDict, CollectionState, ExportedState, LooseCell, ViewCell, exported_value, nullExportedState


__all__ = []


class IDevice(Interface):
    """
    The only implementation of IDevice is Device; it is used only as an explicit type.
    """


class IRXDriver(Interface):
    """
    Additional requirements:
    The object must be a GNU Radio source block with the specified output type.
    get_output_type should be exported.
    """
    
    def get_output_type():
        """Should return an instance of SignalType describing the output signal.
        
        The value MUST NOT change in an incompatible way during the lifetime of the source.
        """

    def get_tune_delay():
        """Return the amount of time, in seconds, between a call to set_freq() and the new center frequency taking effect as observed at top.monitor.fft.
        
        TODO: We need a better strategy for this. Stream tags might help if we can get them in the right places.
        
        TODO: With the device refactoring, tune delays should come from VFOs not rx drivers.
        """
    
    def get_usable_bandwidth():
        """Return a RangeT object which specifies what portion of the bandwidth of the output signal should be conidered usable, in baseband Hz.
        
        Usable here means that it is within the filter passband and does not contain spurs (in particular, a DC offset).
        """
    
    def close():
        """
        Perform a clean shutdown.
        
        This may or may not leave the driver in an unusable state.
        """
    
    def notify_reconnecting_or_restarting():
        pass


__all__.append('IRXDriver')


class ITXDriver(Interface):
    """
    Additional requirements:
    The object must be a GNU Radio sink block with the specified input type.
    get_input_type should be exported.
    """

    def get_input_type():
        """Should return an instance of SignalType describing the input signal.
        
        The value MUST NOT change in an incompatible way during the lifetime of the source.
        """
    
    def close():
        """Perform a clean shutdown.
        
        This may or may not leave the driver in an unusable state.
        """
    
    def notify_reconnecting_or_restarting():
        pass
    
    def set_transmitting(value, midpoint_hook):
        """Enable or disable actual transmission.
        
        The flowgraph will be locked or stopped before this method is called.
        
        This method will not be called redundantly.
        """


__all__.append('ITXDriver')


class IComponent(Interface):
    """A Component is an object incorporated in a Device and has no specific other role."""
    def close():
        """Perform a clean shutdown.
        
        This may or may not leave the component in an unusable state.
        """


__all__.append('IComponent')


class Device(ExportedState):
    """
    A Device aggregates the functions of one or more pieces of radio hardware or drivers for same; particularly:
    
    * receiver
    * transmitter (not yet implemented)
    * VFO
    
    For example, if one is using a sound card-based transceiver, then there would be an audio-source, an audio-sink, and a separate interface to the VFO and other hardware controls. These are completely unrelated as far as the operating system and GNU Radio are concerned, but the Device object aggregates all of those so that the user interface can display them as properly related and control them in sync.
    """
    implements(IDevice)
    # pylint: disable=no-member
    # (confused by nullExportedState)

    def __init__(self,
            name=None,
            rx_driver=nullExportedState,
            tx_driver=nullExportedState,
            vfo_cell=None,
            components={}):
        # pylint: disable=dangerous-default-value
        """
        rx_driver -- may be nullExportedState
        tx_driver -- may be nullExportedState
        vfo_cell -- may be None
        """
        if vfo_cell is None:
            vfo_cell = _stub_vfo
        assert vfo_cell.key() == 'freq'
        assert isinstance(vfo_cell.type(), RangeT)
        # TODO: Consider using an unconditional wrapper around the VFO cell which sets the cell metadata consistently.
        
        self.__name = name
        self.__vfo_cell = vfo_cell
        self.rx_driver = IRXDriver(rx_driver) if rx_driver is not nullExportedState else nullExportedState
        self.tx_driver = ITXDriver(tx_driver) if tx_driver is not nullExportedState else nullExportedState
        coerced_components = {}
        for key, component in components.iteritems():
            coerced_components[key] = IComponent(component)
        self.__components = CellDict(initial_state=coerced_components)
        self.__components_state = CollectionState(self.__components)
        
        self.__transmitting = False
    
    def get_name(self):
        return self.__name
    
    def state_def(self, callback):
        super(Device, self).state_def(callback)
        callback(self.__vfo_cell)
    
    def can_receive(self):
        return self.rx_driver is not nullExportedState
    
    def can_transmit(self):
        return self.tx_driver is not nullExportedState
    
    def can_tune(self):
        return self.__vfo_cell is not _stub_vfo
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_rx_driver(self):
        return self.rx_driver
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_tx_driver(self):
        return self.tx_driver
    
    @exported_value(type=ReferenceT(), changes='never')
    def get_components(self):
        return self.__components_state
    
    def get_vfo_cell(self):
        return self.__vfo_cell
    
    def get_components_dict(self):
        """Do not mutate the dictionary returned."""
        return self.__components
    
    def get_freq(self):
        """
        Get the frequency from the VFO cell.
        
        (Convenience/consistency equivalent to self.state()['freq'].get.)
        """
        return self.__vfo_cell.get()
    
    def set_freq(self, value):
        """
        Set the frequency in the VFO cell.
        
        (Convenience/consistency equivalent to self.state()['freq'].set.)
        """
        return self.__vfo_cell.set(value)
    
    def set_transmitting(self, value, midpoint_hook=lambda: None):
        """
        Start or stop transmitting. This may involve flowgraph reconfiguration, and as such the caller is responsible for locking or stopping the flowgraph(s) around this call.
        
        If there is no TX driver, then this has no effect.
        
        The output of the RX driver while transmitting is undefined; it may produce no samples, produce meaningless samples at the normal rate, or be unaffected (full duplex).
        """
        value = bool(value)
        if not self.can_transmit() or value == self.__transmitting:
            midpoint_hook()
            return
        self.__transmitting = value
        self.tx_driver.set_transmitting(value, midpoint_hook)
    
    def close(self):
        """
        Instruct the drivers to perform a clean shutdown, and discard them.
        """
        if self.rx_driver is not nullExportedState:
            self.rx_driver.close()
            self.rx_driver = nullExportedState
        if self.tx_driver is not nullExportedState:
            self.tx_driver.close()
            self.tx_driver = nullExportedState
        for key, component in self.__components.iteritems():
            component.close()
            self.__components[key] = nullExportedState
    
    def notify_reconnecting_or_restarting(self):
        if self.rx_driver is not nullExportedState:
            self.rx_driver.notify_reconnecting_or_restarting()
        if self.tx_driver is not nullExportedState:
            self.tx_driver.notify_reconnecting_or_restarting()


__all__.append('Device')


def _ConstantVFOCell(value):
    value = float(value)
    return LooseCell(
        key='freq',
        value=value,
        type=RangeT([(value, value)]),
        writable=False,
        persists=False)


_stub_vfo = _ConstantVFOCell(0.0)


def merge_devices(devices):
    devices = [IDevice(d) for d in devices]
    if len(devices) == 1:
        return devices[0]
    else:
        names = [d.get_name() for d in devices if d.get_name() is not None]
        rx_drivers = [d.get_rx_driver() for d in devices if d.can_receive()]
        tx_drivers = [d.get_tx_driver() for d in devices if d.can_transmit()]
        vfo_cells = [d.get_vfo_cell() for d in devices if d.can_tune()]
        component_names = Counter(k for d in devices for k in d.get_components_dict())
        merged_components = {}
        for i, d in enumerate(devices):
            if any(component_names[k] > 1 for k in d.get_components_dict()):
                prefix = u'%i-' % i
            else:
                prefix = ''
            for k, component in d.get_components_dict().iteritems():
                merged_components[prefix + k] = component
        return Device(
            name=None if len(names) == 0 else '+'.join(names),
            rx_driver=_at_most_one('RX driver', nullExportedState, rx_drivers),
            tx_driver=_at_most_one('TX driver', nullExportedState, tx_drivers),
            vfo_cell=_merge_vfos(vfo_cells),
            components=merged_components)


__all__.append('merge_devices')


def _at_most_one(name, zero, items):
    if len(items) == 1:
        return items[0]
    elif len(items) == 0:
        return zero
    else:
        raise ValueError(u'Exactly one %s must be provided, not %i' % (name, len(items)))


def _merge_vfos(vfos):
    fixed = 0.0
    variable = []
    for vfo in vfos:
        p = vfo.type().get_single_point()
        if p is not None:
            fixed += p
        else:
            variable.append(vfo)
    if len(variable) == 0:
        if fixed == 0.0:
            return None
        else:
            return _ConstantVFOCell(fixed)
    elif len(variable) == 1:
        variable_one = variable[0]
        if fixed == 0.0:
            return variable_one
        else:
            return ViewCell(
                base=variable_one,
                get_transform=lambda x: x + fixed,
                set_transform=lambda x: x - fixed,
                key='freq',
                type=variable_one.type().shifted_by(fixed),
                writable=True,
                persists=variable_one.metadata().persists)
    else:
        raise ValueError('Multiple non-stub VFOs not yet supported.')


# ---------------------------------------------------------------------
# Below this point: basic devices.


def FrequencyShift(shift, name=None):
    """
    Define a fixed VFO frequency shift, such as if a upconverter/downconverter/transverter is in use.
    
    The shift value should be set to the needed change in the _displayed_ frequency. For example, if using a 125 MHz upconverter for receiving HF (such as the popular Ham-It-Up), one should specify a shift of -125e6.
    """
    shift = float(shift)
    return Device(name=name, vfo_cell=_ConstantVFOCell(shift))


__all__.append('FrequencyShift')


def AudioDevice(
        rx_device='',  # may be used positionally, not recommented
        tx_device=None,
        name=None,
        sample_rate=44100,
        channel_mapping=None):
    rx_device = str(rx_device)
    if tx_device is not None:
        tx_device = str(tx_device)
    channel_mapping = _coerce_channel_mapping(channel_mapping)
    
    if name is None:
        full_name = u'Audio ' + rx_device
        if tx_device is not None:
            full_name += '/' + tx_device
    else:
        full_name = unicode(name)

    rx_driver = _AudioRXDriver(
        device_name=rx_device,
        sample_rate=sample_rate,
        channel_mapping=channel_mapping)
    if tx_device is not None:
        tx_driver = _AudioTXDriver(
            device_name=tx_device,
            sample_rate=sample_rate,
            channel_mapping=channel_mapping)
    else:
        tx_driver = nullExportedState
    
    return Device(
        name=full_name,
        vfo_cell=LooseCell(
            key='freq',
            value=0.0,
            type=RangeT([(0.0, 0.0)]),
            writable=True,
            persists=False),
        rx_driver=rx_driver,
        tx_driver=tx_driver)


__all__.append('AudioDevice')


def _coerce_channel_mapping(channel_mapping):
    if channel_mapping is None:  # Not documented value, just default.
        return _coerce_channel_mapping('IQ')
    elif isinstance(channel_mapping, int):
        if channel_mapping <= 0:
            raise TypeError('AudioDevice: channel_mapping channel number must be greater than 0, but was %r' % (channel_mapping,))
        return [[int(i == channel_mapping - 1) for i in xrange(0, channel_mapping)]]
    elif channel_mapping == 'IQ':
        return [[1, 0], [0, 1]]
    elif channel_mapping == 'QI':
        return [[0, 1], [1, 0]]
    elif isinstance(channel_mapping, tuple) or isinstance(channel_mapping, list):
        if not 1 <= len(channel_mapping) <= 2:
            raise TypeError('AudioDevice: len(channel_mapping) must be 1 or 2 but was %r' % (len(channel_mapping),))
        for i, row in enumerate(channel_mapping):
            if not (isinstance(row, tuple) or isinstance(row, list)):
                raise TypeError('AudioDevice: channel_mapping[%r] must be a list of input channel gains' % (i,))
            for j, elem in enumerate(row):
                if not (isinstance(elem, float) or isinstance(elem, int)):
                    raise TypeError('AudioDevice: channel_mapping[%r][%r] must be a numeric gain value' % (i, j))
        if len(channel_mapping) == 2 and len(channel_mapping[0]) != len(channel_mapping[1]):
            raise TypeError('AudioDevice: channel_mapping must have the same number of input channels in each row but had %d and %d' % (len(channel_mapping[0]), len(channel_mapping[1])))
        if len(channel_mapping[0]) == 0:
            raise TypeError('AudioDevice: channel_mapping must specify at least one input channel')
        return channel_mapping
    else:
        raise TypeError('AudioDevice: channel_mapping parameter must be a channel number, "IQ", "QI", or a 2×N list-of-lists matrix, but was %r' % (channel_mapping,))


def find_audio_rx_names():
    # TODO: request that gnuradio support device enumeration
    try:
        AudioDevice(rx_device='')
        return ['']
    except RuntimeError:  # thrown by gnuradio
        return []


__all__.append('find_audio_rx_names')


class _AudioRXDriver(ExportedState, gr.hier_block2):
    implements(IRXDriver)
    
    def __init__(self,
            device_name,
            sample_rate,
            channel_mapping):
        self.__device_name = device_name
        self.__sample_rate = sample_rate
        
        if len(channel_mapping) == 2:
            self.__signal_type = SignalType(
                kind='IQ',
                sample_rate=self.__sample_rate)
            # TODO should be configurable
            self.__usable_bandwidth = RangeT([(-self.__sample_rate / 2, self.__sample_rate / 2)])
        else:
            self.__signal_type = SignalType(
                kind='USB',  # TODO obtain correct type from config (or say hamlib)
                sample_rate=self.__sample_rate)
            self.__usable_bandwidth = RangeT([(500, 2500)])
        
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(0, 0, 0),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
        )
        
        self.__source = audio.source(
            self.__sample_rate,
            device_name=self.__device_name,
            ok_to_block=True)
        
        channel_matrix = blocks.multiply_matrix_ff(channel_mapping)
        combine = blocks.float_to_complex(1)
        # TODO: min() is to support mono sources with default channel mapping. Handle this better, and give a warning if an explicit mapping is too big.
        for i in xrange(0, min(len(channel_mapping[0]),
                               self.__source.output_signature().max_streams())):
            self.connect((self.__source, i), (channel_matrix, i))
        for i in xrange(0, len(channel_mapping)):
            self.connect((channel_matrix, i), (combine, i))
        self.connect(combine, self)
    
    # implement IRXDriver
    @exported_value(type=SignalType, changes='never')
    def get_output_type(self):
        return self.__signal_type

    # implement IRXDriver
    def get_tune_delay(self):
        # TODO: Tune delay should be associated with VFOs (or devices) too
        return 0.0
    
    # implement IRXDriver
    def get_usable_bandwidth(self):
        return self.__usable_bandwidth
    
    # implement IRXDriver
    def close(self):
        self.disconnect_all()
        self.__source = None
    
    # implement IRXDriver
    def notify_reconnecting_or_restarting(self):
        pass


class _AudioTXDriver(ExportedState, gr.hier_block2):
    implements(ITXDriver)
    
    def __init__(self,
            device_name,
            sample_rate,
            channel_mapping):
        self.__device_name = device_name
        self.__sample_rate = sample_rate
        
        self.__signal_type = SignalType(
            # TODO: type should be able to be LSB
            kind='IQ' if len(channel_mapping) == 2 else 'USB',
            sample_rate=self.__sample_rate)
        
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(0, 0, 0),
        )
        
        sink = audio.sink(
            self.__sample_rate,
            device_name=self.__device_name,
            ok_to_block=True)
        
        # TODO: ignoring channel_mapping parameter, shouldn't be
        split = blocks.complex_to_float(1)
        self.connect(self, split, (sink, 0))
        self.connect((split, 1), (sink, 1))

    @exported_value(type=SignalType, changes='never')
    def get_input_type(self):
        return self.__signal_type

    def get_tune_delay(self):
        # TODO: Tune delay should be associated with VFOs (or devices) too
        return 0.0
    
    def close(self):
        self.disconnect_all()
    
    def notify_reconnecting_or_restarting(self):
        pass
    
    def set_transmitting(self, value, midpoint_hook):
        # Noop -- audio hardware is full duplex.
        # TODO: But audio interfaces to radios generally have separate PTT control. Probably non-driver components should get TX notifications also.
        pass


def PositionedDevice(latitude, longitude):
    """
    Combine with other devices to specify a device's location on the Earth.
    """
    return Device(components={'position': _PositionedDeviceComponent(latitude, longitude)})


class IPositionedDevice(Interface):
    """
    Client marker interface only.
    """


class _PositionedDeviceComponent(ExportedState):
    implements(IComponent, IPositionedDevice)
    
    def __init__(self, latitude, longitude):
        self.__track = empty_track._replace(
            latitude=TelemetryItem(float(latitude), None),
            longitude=TelemetryItem(float(longitude), None))

    def close(self):
        """implements IComponent"""

    @exported_value(type=Track, changes='never', label='Antenna location')
    def get_track(self):
        return self.__track
