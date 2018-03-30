# -*- coding: utf-8 -*-
# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

import time

from twisted.logger import Logger
from zope.interface import Interface, implementer  # available via Twisted

from gnuradio import analog
from gnuradio import gr
from gnuradio import blocks

from shinysdr.i.modes import get_modes, lookup_mode
from shinysdr.interfaces import IDemodulator, IDemodulatorContext, IDemodulatorModeChange, ITunableDemodulator
from shinysdr.math import dB, rotator_inc, to_dB
from shinysdr.signals import SignalType, no_signal
from shinysdr.types import EnumT, QuantityT, RangeT, ReferenceT
from shinysdr import units
from shinysdr.values import ExportedState, exported_value, setter, unserialize_exported_state


# arbitrary non-infinite limit
_audio_power_minimum_dB = -60
_audio_power_minimum_amplitude = dB(_audio_power_minimum_dB)


_dummy_audio_rate = 2000


class IReceiver(Interface):
    """
    Marker interface for receivers.
    
    (This exists even though Receiver has no class hierarchy because the client would like to know what's a receiver block, and interface information is automatically delivered to the client.)
    """


@implementer(IReceiver)
class Receiver(gr.hier_block2, ExportedState):
    __log = Logger()  # TODO: plumb this in from top so we can start giving error messages to the client e.g. in the "unknown mode" case.
    
    def __init__(self, mode,
            freq_absolute=100.0,
            freq_relative=None,
            freq_linked_to_device=False,
            audio_destination=None,
            device_name=None,
            audio_gain=-6,
            audio_pan=0,
            audio_channels=0,
            context=None):
        assert audio_channels == 1 or audio_channels == 2
        assert audio_destination is not None
        assert device_name is not None
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_float * audio_channels))
        
        if lookup_mode(mode) is None:
            # TODO: communicate back to client if applicable
            self.__log.error('Unknown mode {mode!r} in Receiver(); using AM', mode=mode)
            mode = 'AM'
        
        # Provided by caller
        self.context = context
        self.__audio_channels = audio_channels

        # cached info from device
        self.__device_name = device_name
        
        # Simple state
        self.mode = mode
        self.audio_gain = audio_gain
        self.audio_pan = min(1, max(-1, audio_pan))
        self.__audio_destination = audio_destination
        
        # Receive frequency.
        self.__freq_linked_to_device = bool(freq_linked_to_device)
        if self.__freq_linked_to_device and freq_relative is not None:
            self.__freq_relative = float(freq_relative)
            self.__freq_absolute = self.__freq_relative + self.__get_device().get_freq()
        else:
            self.__freq_absolute = float(freq_absolute)
            self.__freq_relative = self.__freq_absolute - self.__get_device().get_freq()
        
        # Blocks
        self.__rotator = blocks.rotator_cc()
        self.__demodulator = self.__make_demodulator(mode, {})
        self.__update_demodulator_info()
        self.__audio_gain_block = blocks.multiply_const_vff([0.0] * audio_channels)
        self.probe_audio = analog.probe_avg_mag_sqrd_f(0, alpha=10.0 / 44100)  # TODO adapt to output audio rate
        
        # Other internals
        self.__last_output_type = None
        
        self.__update_rotator()  # initialize rotator, also in case of __demod_tunable
        self.__update_audio_gain()
        self.__do_connect(reason=u'initialization')
    
    def __update_demodulator_info(self):
        self.__demod_tunable = ITunableDemodulator.providedBy(self.__demodulator)
        output_type = self.__demodulator.get_output_type()
        assert isinstance(output_type, SignalType)
        # TODO: better expression of this condition
        assert output_type.get_kind() == 'STEREO' or output_type.get_kind() == 'MONO' or output_type.get_kind() == 'NONE'
        self.__demod_output = output_type.get_kind() != 'NONE'
        self.__demod_stereo = output_type.get_kind() == 'STEREO'
        if self.__demod_output:
            self.__output_type = SignalType(
                kind='STEREO',
                sample_rate=output_type.get_sample_rate())
        else:
            self.__output_type = no_signal
    
    def __do_connect(self, reason):
        self.__log.debug('receiver do_connect: {reason}', reason=reason)
        self.context.lock()
        try:
            self.disconnect_all()
            
            # Connect input of demodulator
            if self.__demod_tunable:
                self.connect(self, self.__demodulator)
            else:
                self.connect(self, self.__rotator, self.__demodulator)
            
            if self.__demod_output:
                # Construct stereo-to-mono conversion (used at least for level probe)
                if self.__demod_stereo:
                    splitter = blocks.vector_to_streams(gr.sizeof_float, 2)
                    mono_audio = blocks.multiply_matrix_ff(((0.5, 0.5),))
                    self.connect(self.__demodulator, splitter)
                    self.connect((splitter, 0), (mono_audio, 0))
                    self.connect((splitter, 1), (mono_audio, 1))
                else:
                    mono_audio = self.__demodulator
                
                # Connect mono audio to level probe
                self.connect(mono_audio, self.probe_audio)
                
                # Connect demodulator to output gain control, converting as needed
                if (self.__audio_channels == 2) == self.__demod_stereo:
                    # stereo to stereo or mono to mono
                    self.connect(self.__demodulator, self.__audio_gain_block)
                elif self.__audio_channels == 2 and not self.__demod_stereo:
                    # mono to stereo
                    duplicator = blocks.streams_to_vector(gr.sizeof_float, 2)
                    self.connect(self.__demodulator, (duplicator, 0))
                    self.connect(self.__demodulator, (duplicator, 1))
                    self.connect(duplicator, self.__audio_gain_block)
                elif self.__audio_channels == 1 and self.__demod_stereo:
                    # stereo to mono
                    self.connect(mono_audio, self.__audio_gain_block)
                else:
                    raise Exception('shouldn\'t happen')
                    
                # Connect gain control to output of receiver
                self.connect(self.__audio_gain_block, self)
            else:
                # Dummy output, ignored by containing block
                self.connect(
                    blocks.vector_source_f([], vlen=self.__audio_channels),
                    self)
            
            if self.__output_type != self.__last_output_type:
                self.__last_output_type = self.__output_type
                self.context.changed_needed_connections(u'changed output type')
        finally:
            self.context.unlock()
    
    def get_output_type(self):
        return self.__output_type

    def changed_device_freq(self):
        if self.__freq_linked_to_device:
            self.__freq_absolute = self.__freq_relative + self.__get_device().get_freq()
        else:
            self.__freq_relative = self.__freq_absolute - self.__get_device().get_freq()
        self.__update_rotator()
        # note does not revalidate() because the caller will handle that
        self.state_changed('rec_freq')
        self.state_changed('is_valid')

    @exported_value(type=ReferenceT(), changes='explicit')
    def get_demodulator(self):
        return self.__demodulator

    @exported_value(
        type_fn=lambda self: self.context.get_rx_device_type(),
        changes='this_setter',
        label='RF source')
    def get_device_name(self):
        return self.__device_name
    
    @setter
    def set_device_name(self, value):
        value = self.context.get_rx_device_type()(value)
        if self.__device_name != value:
            self.__device_name = value
            self.changed_device_freq()  # freq
            self._rebuild_demodulator(reason=u'changed device, thus maybe sample rate')  # rate
            self.context.changed_needed_connections(u'changed device')
    
    # type construction is deferred because we don't want loading this file to trigger loading plugins
    @exported_value(
        type_fn=lambda self: EnumT({d.mode: d.info for d in get_modes()}),
        changes='this_setter',
        label='Mode')
    def get_mode(self):
        return self.mode
    
    @setter
    def set_mode(self, mode):
        mode = unicode(mode)
        if mode == self.mode: return
        if self.__demodulator and \
                IDemodulatorModeChange.providedBy(self.__demodulator) and \
                self.__demodulator.can_set_mode(mode):
            self.__demodulator.set_mode(mode)
            self.mode = mode
        else:
            self._rebuild_demodulator(mode=mode, reason=u'changed mode')

    # TODO: rename rec_freq to just freq
    @exported_value(
        type=QuantityT(units.Hz),
        parameter='freq_absolute',
        changes='explicit',
        label='Frequency')
    def get_rec_freq(self):
        return self.__freq_absolute
    
    @setter
    def set_rec_freq(self, absolute):
        absolute = float(absolute)
        
        if self.__freq_linked_to_device:
            # Temporarily violating the (device freq + relative freq = absolute freq) invariant, which will be restored below by changing the device freq.
            self.__freq_absolute = absolute
        else:
            self.__freq_absolute = absolute
            self.__freq_relative = absolute - self.__get_device().get_freq()
        
        self.__update_rotator()

        if self.__freq_linked_to_device:
            # TODO: reconsider whether we should be giving commands directly to the device, vs. going through the context.
            self.__get_device().set_freq(self.__freq_absolute - self.__freq_relative)
        else:
            self.context.revalidate(tuning=True)
        self.state_changed('rec_freq')
        self.state_changed('is_valid')
    
    @exported_value(
        type=bool,
        changes='this_setter',
        label='Follow device',
        description='When this receiver\'s frequency or the device\'s frequency is changed, maintain the relative offset between them.')
    def get_freq_linked_to_device(self):
        return self.__freq_linked_to_device
    
    @setter
    def set_freq_linked_to_device(self, value):
        self.__freq_linked_to_device = bool(value)
    
    # TODO: support non-audio demodulators at which point these controls should be optional
    @exported_value(
        parameter='audio_gain',
        type=RangeT([(-30, 20)], unit=units.dB, strict=False),
        changes='this_setter',
        label='Volume')
    def get_audio_gain(self):
        return self.audio_gain

    @setter
    def set_audio_gain(self, value):
        self.audio_gain = value
        self.__update_audio_gain()
    
    @exported_value(
        type_fn=lambda self: RangeT([(-1, 1)] if self.__audio_channels > 1 else [(0, 0)], strict=True),
        changes='this_setter',
        label='Pan')
    def get_audio_pan(self):
        return self.audio_pan
    
    @setter
    def set_audio_pan(self, value):
        self.audio_pan = value
        self.__update_audio_gain()
    
    @exported_value(
        type_fn=lambda self: self.context.get_audio_destination_type(),
        changes='this_setter',
        label='Audio destination')
    def get_audio_destination(self):
        return self.__audio_destination
    
    @setter
    def set_audio_destination(self, value):
        if self.__audio_destination != value:
            self.__audio_destination = value
            self.context.changed_needed_connections(u'changed destination')
    
    @exported_value(type=bool, changes='explicit')
    def get_is_valid(self):
        if self.__demodulator is None:
            return False
        half_sample_rate = self.__get_device().get_rx_driver().get_output_type().get_sample_rate() / 2
        demod_shape = self.__demodulator.get_band_shape()
        valid_bandwidth_lower = -half_sample_rate - self.__freq_relative
        valid_bandwidth_upper = half_sample_rate - self.__freq_relative
        return (valid_bandwidth_lower <= min(0, demod_shape.pass_low) and
                valid_bandwidth_upper >= max(0, demod_shape.pass_high))
    
    # Note that the receiver cannot measure RF power because we don't know what the channel bandwidth is; we have to leave that to the demodulator.
    # TODO: document what we are using as the reference level. It's not dBFS because we're floating-point and before the gain stage.
    @exported_value(
        type=RangeT([(_audio_power_minimum_dB, 0)], unit=units.dB, strict=False),
        changes='continuous',
        label='Audio power')
    def get_audio_power(self):
        if self.get_is_valid():
            return to_dB(max(_audio_power_minimum_amplitude, self.probe_audio.level()))
        else:
            # will not be receiving samples, so probe's value will be meaningless
            return _audio_power_minimum_dB
    
    def __update_rotator(self):
        device = self.__get_device()
        sample_rate = device.get_rx_driver().get_output_type().get_sample_rate()
        if self.__demod_tunable:
            # TODO: Method should perhaps be renamed to convey that it is relative
            self.__demodulator.set_rec_freq(self.__freq_relative)
        else:
            self.__rotator.set_phase_inc(rotator_inc(rate=sample_rate, shift=-self.__freq_relative))
    
    def __get_device(self):
        return self.context.get_device(self.__device_name)
    
    # called from facet
    def _rebuild_demodulator(self, mode=None, reason='<unspecified>'):
        self.__rebuild_demodulator_nodirty(mode)
        self.__do_connect(reason=u'demodulator rebuilt: %s' % (reason,))
        # TODO write a test showing that revalidate is needed and works
        self.context.revalidate(tuning=False)  # in case our bandwidth changed
        self.state_changed('is_valid')

    def __rebuild_demodulator_nodirty(self, mode=None):
        if self.__demodulator is None:
            defaults = {}
        else:
            defaults = self.__demodulator.state_to_json()
        if mode is None:
            mode = self.mode
        self.__demodulator = self.__make_demodulator(mode, defaults)
        self.__update_demodulator_info()
        self.__update_rotator()
        self.mode = mode
        self.state_changed('demodulator')
        
        # Replace blocks downstream of the demodulator so as to flush samples that are potentially at a different sample rate and would therefore be audibly wrong. Caller will handle reconnection.
        self.__audio_gain_block = blocks.multiply_const_vff([0.0] * self.__audio_channels)
        self.__update_audio_gain()

    def __make_demodulator(self, mode, state):
        """Returns the demodulator."""

        t0 = time.time()
        
        mode_def = lookup_mode(mode)
        if mode_def is None:
            # TODO: Better handling, like maybe a dummy demod
            raise ValueError('Unknown mode: ' + mode)
        clas = mode_def.demod_class

        state = state.copy()  # don't modify arg
        if 'mode' in state: del state['mode']  # don't switch back to the mode we just switched from
        
        facet = ContextForDemodulator(self)
        
        init_kwargs = dict(
            mode=mode,
            input_rate=self.__get_device().get_rx_driver().get_output_type().get_sample_rate(),
            context=facet)
        demodulator = IDemodulator(unserialize_exported_state(
            ctor=clas,
            state=state,
            kwargs=init_kwargs))
        
        # until _enabled, ignore any callbacks resulting from unserialization calling setters
        facet._enabled = True
        self.__log.debug('Constructed {mode} demodulator: {time_ms} ms.', mode=mode, time_ms=(time.time() - t0) * 1000)
        return demodulator

    def __update_audio_gain(self):
        gain_lin = dB(self.audio_gain)
        if self.__audio_channels == 2:
            pan = self.audio_pan
            # TODO: Instead of left-to-left and right-to-right, panning other than center should mix left and right content. (A "pan law" defines the proper mix.) This implies a matrix multiplication type operation.
            self.__audio_gain_block.set_k([
                gain_lin * (1 - pan),
                gain_lin * (1 + pan),
            ])
        else:
            self.__audio_gain_block.set_k([gain_lin])


@implementer(IDemodulatorContext)
class ContextForDemodulator(object):
    def __init__(self, receiver):
        self._receiver = receiver
        self._enabled = False  # assigned outside
    
    def rebuild_me(self):
        print 'rebuild_me'
        assert self._enabled, 'ContextForReceiver({}) is not currently valid'.format(self._receiver)
        self._receiver._rebuild_demodulator(reason=u'rebuild_me')

    def lock(self):
        self._receiver.context.lock()

    def unlock(self):
        self._receiver.context.unlock()
    
    def output_message(self, message):
        assert self._enabled, 'ContextForReceiver({}) is not currently valid'.format(self._receiver)
        self._receiver.context.output_message(message)
    
    def get_absolute_frequency_cell(self):
        # TODO: This should return a read-only cell (until we have a use case demonstrating otherwise) (but we don't have read-only wrapper cells yet)
        return self._receiver.state()['rec_freq']
