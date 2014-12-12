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

# pylint: disable=no-init, attribute-defined-outside-init, maybe-no-member
# (no-init: pylint is confused by interfaces)
# (attribute-defined-outside-init: doing it carefully)
# (maybe-no-member: pylint is confused by set_max_output_buffer)

from __future__ import absolute_import, division

from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import analog
from gnuradio import gr
from gnuradio import blocks

import math

from shinysdr.blocks import rotator_inc
from shinysdr.modes import ITunableDemodulator, get_modes, lookup_mode
from shinysdr.signals import SignalType
from shinysdr.types import Enum, Range
from shinysdr.values import ExportedState, BlockCell, exported_value, setter, unserialize_exported_state


# arbitrary non-infinite limit
_audio_power_minimum_dB = -60
_audio_power_minimum_amplitude = 10 ** (_audio_power_minimum_dB / 10)


_dummy_audio_rate = 2000


class IReceiver(Interface):
    '''
    Marker interface for receivers.
    
    (This exists even though Receiver has no class hierarchy because the client would like to know what's a receiver block, and interface information is automatically delivered to the client.)
    '''


class Receiver(gr.hier_block2, ExportedState):
    implements(IReceiver)
    
    def __init__(self, mode,
            input_rate=0,
            input_center_freq=0,
            rec_freq=100.0,
            audio_gain=-6,
            audio_pan=0,
            audio_channels=0,
            context=None):
        assert input_rate > 0
        assert audio_channels == 1 or audio_channels == 2
        gr.hier_block2.__init__(
            # str() because insists on non-unicode
            self, str('%s receiver' % (mode,)),
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(audio_channels, audio_channels, gr.sizeof_float * 1),
        )
        
        if lookup_mode(mode) is None:
            # TODO: communicate back to client if applicable
            log.msg('Unknown mode %r in Receiver(); using AM' % (mode,))
            mode = 'AM'
        
        # Provided by caller
        self.context = context
        self.input_rate = input_rate
        self.input_center_freq = input_center_freq
        self.__audio_channels = audio_channels
        
        # Simple state
        self.mode = mode
        self.rec_freq = rec_freq
        self.audio_gain = audio_gain
        self.audio_pan = min(1, max(-1, audio_pan))
        
        # Blocks
        self.__rotator = blocks.rotator_cc()
        self.demodulator = self.__make_demodulator(mode, {})
        self.__update_demodulator_info()
        self.__audio_gain_blocks = [blocks.multiply_const_ff(0.0) for _ in xrange(self.__audio_channels)]
        self.probe_audio = analog.probe_avg_mag_sqrd_f(0, alpha=10.0 / 44100)  # TODO adapt to output audio rate
        
        # Other internals
        self.__last_output_type = None
        
        self.__update_rotator()  # initialize rotator, also in case of __demod_tunable
        self.__update_audio_gain()
        self.__do_connect()
    
    def state_def(self, callback):
        super(Receiver, self).state_def(callback)
        # TODO decoratorify
        callback(BlockCell(self, 'demodulator'))
    
    def __update_demodulator_info(self):
        self.__demod_tunable = ITunableDemodulator.providedBy(self.demodulator)
        output_type = self.demodulator.get_output_type()
        assert isinstance(output_type, SignalType)
        # TODO: better expression of this condition
        assert output_type.get_kind() == 'STEREO' or output_type.get_kind() == 'MONO' or output_type.get_kind() == 'NONE'
        self.__demod_output = output_type.get_kind() != 'NONE'
        self.__demod_stereo = output_type.get_kind() == 'STEREO'
        self.__output_type = SignalType(
            kind='STEREO',
            sample_rate=output_type.get_sample_rate() if self.__demod_output else _dummy_audio_rate)
    
    def __do_connect(self):
        self.context.lock()
        try:
            self.disconnect_all()
            
            # Connect input of demodulator
            if self.__demod_tunable:
                self.connect(self, self.demodulator)
            else:
                self.connect(self, self.__rotator, self.demodulator)
            
            if self.__demod_output:
                # Connect output of demodulator
                self.connect((self.demodulator, 0), self.__audio_gain_blocks[0])  # left or mono
                if self.__audio_channels == 2:
                    self.connect(
                        (self.demodulator, 1 if self.__demod_stereo else 0),
                        self.__audio_gain_blocks[1])
                else:
                    if self.__demod_stereo:
                        self.connect((self.demodulator, 1), blocks.null_sink(gr.sizeof_float))
                
                # Connect output of receiver
                for ch in xrange(self.__audio_channels):
                    self.connect(self.__audio_gain_blocks[ch], (self, ch))
                
                # Level meter
                # TODO: should mix left and right or something
                self.connect((self.demodulator, 0), self.probe_audio)
            else:
                # Dummy output.
                # TODO: Teach top block about no-audio so we don't have to have a dummy output.
                throttle = blocks.throttle(gr.sizeof_float, _dummy_audio_rate)
                throttle.set_max_output_buffer(_dummy_audio_rate // 10)  # ensure smooth output
                self.connect(
                    analog.sig_source_f(0, analog.GR_CONST_WAVE, 0, 0, 0),
                    throttle)
                for ch in xrange(self.__audio_channels):
                    self.connect(throttle, (self, ch))
            
            if self.__output_type != self.__last_output_type:
                self.__last_output_type = self.__output_type
                self.context.changed_output_type()
        finally:
            self.context.unlock()

    def get_output_type(self):
        return self.__output_type

    def set_input_rate(self, value):
        value = int(value)
        if self.input_rate == value:
            return
        self.input_rate = value
        self._rebuild_demodulator()

    def set_input_center_freq(self, value):
        self.input_center_freq = value
        self.__update_rotator()
        # note does not revalidate() because the caller will handle that

    # type construction is deferred because we don't want loading this file to trigger loading plugins
    @exported_value(ctor_fn=lambda self: Enum({d.mode: d.label for d in get_modes()}))
    def get_mode(self):
        return self.mode
    
    @setter
    def set_mode(self, mode):
        mode = unicode(mode)
        if self.demodulator and self.demodulator.can_set_mode(mode):
            self.demodulator.set_mode(mode)
            self.mode = mode
        else:
            self._rebuild_demodulator(mode=mode)

    # TODO: rename rec_freq to just freq
    @exported_value(ctor=float)
    def get_rec_freq(self):
        return self.rec_freq
    
    @setter
    def set_rec_freq(self, rec_freq):
        self.rec_freq = float(rec_freq)
        self.__update_rotator()
        self.context.revalidate()
    
    # TODO: support non-audio demodulators at which point these controls should be optional
    @exported_value(ctor=Range([(-30, 20)], strict=False))
    def get_audio_gain(self):
        return self.audio_gain

    @setter
    def set_audio_gain(self, value):
        self.audio_gain = value
        self.__update_audio_gain()
    
    @exported_value(ctor_fn=lambda self: Range([(-1, 1)] if self.__audio_channels > 1 else [(0, 0)], strict=True))
    def get_audio_pan(self):
        return self.audio_pan
    
    @setter
    def set_audio_pan(self, value):
        self.audio_pan = value
        self.__update_audio_gain()
    
    @exported_value(ctor=bool)
    def get_is_valid(self):
        valid_bandwidth = self.input_rate / 2 - abs(self.rec_freq - self.input_center_freq)
        return self.demodulator is not None and valid_bandwidth >= self.demodulator.get_half_bandwidth()
    
    # Note that the receiver cannot measure RF power because we don't know what the channel bandwidth is; we have to leave that to the demodulator.
    @exported_value(ctor=Range([(_audio_power_minimum_dB, 0)], strict=False))
    def get_audio_power(self):
        if self.get_is_valid():
            return 10 * math.log10(max(_audio_power_minimum_amplitude, self.probe_audio.level()))
        else:
            # will not be receiving samples, so probe's value will be meaningless
            return _audio_power_minimum_dB
    
    def __update_rotator(self):
        offset = self.rec_freq - self.input_center_freq
        if self.__demod_tunable:
            self.demodulator.set_rec_freq(offset)
        else:
            self.__rotator.set_phase_inc(rotator_inc(rate=self.input_rate, shift=-offset))
    
    # called from facet
    def _rebuild_demodulator(self, mode=None):
        self.__rebuild_demodulator_nodirty(mode)
        self.__do_connect()

    def __rebuild_demodulator_nodirty(self, mode=None):
        if self.demodulator is None:
            defaults = {}
        else:
            defaults = self.demodulator.state_to_json()
        if mode is None:
            mode = self.mode
        self.demodulator = self.__make_demodulator(mode, defaults)
        self.__update_demodulator_info()
        self.__update_rotator()
        self.mode = mode
        
        # Replace blocks downstream of the demodulator so as to flush samples that are potentially at a different sample rate and would therefore be audibly wrong. Caller will handle reconnection.
        self.__audio_gain_blocks = [blocks.multiply_const_ff(0.0) for _ in xrange(self.__audio_channels)]
        self.__update_audio_gain()

    def __make_demodulator(self, mode, state):
        '''Returns the demodulator.'''

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
            input_rate=self.input_rate,
            context=facet)
        for sh_key, sh_ctor in mode_def.shared_objects.iteritems():
            init_kwargs[sh_key] = self.context.get_shared_object(sh_ctor)
        demodulator = unserialize_exported_state(
            ctor=clas,
            state=state,
            kwargs=init_kwargs)
        
        # until _enabled, ignore any callbacks resulting from unserialization calling setters
        facet._enabled = True
        return demodulator

    def __update_audio_gain(self):
        gain_lin = 10 ** (self.audio_gain / 10)
        if self.__audio_channels == 2:
            pan = self.audio_pan
            # TODO: Determine correct computation for panning. http://en.wikipedia.org/wiki/Pan_law seems relevant but was short on actual formulas. May depend on headphones vs speakers? This may be correct already for headphones -- it sounds nearly-flat to me.
            self.__audio_gain_blocks[0].set_k(gain_lin * (1 - pan))
            self.__audio_gain_blocks[1].set_k(gain_lin * (1 + pan))
        else:
            self.__audio_gain_blocks[0].set_k(gain_lin)


class ContextForDemodulator(object):
    def __init__(self, receiver):
        self._receiver = receiver
        self._enabled = False  # assigned outside
    
    def rebuild_me(self):
        assert self._enabled
        self._receiver._rebuild_demodulator()

    def lock(self):
        self._receiver.context.lock()

    def unlock(self):
        self._receiver.context.unlock()
