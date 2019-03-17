# Copyright 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import time

import six

from twisted.internet import reactor as the_reactor  # TODO eliminate
from twisted.internet.protocol import ProcessProtocol
from twisted.protocols.basic import LineReceiver
from twisted.logger import Logger
from zope.interface import implementer

from gnuradio import analog
from gnuradio import gr

from shinysdr.i.blocks import make_sink_to_process_stdin
from shinysdr.i.pycompat import repr_no_string_tag
from shinysdr.filters import MultistageChannelFilter
from shinysdr.math import dB
from shinysdr.interfaces import BandShape, ModeDef, IDemodulator
from shinysdr.signals import no_signal
from shinysdr.telemetry import ITelemetryMessage, ITelemetryObject
from shinysdr.twisted_ext import test_subprocess
from shinysdr.types import EnumRow, TimestampT
from shinysdr.values import ExportedState, LooseCell, exported_value


drop_unheard_timeout_seconds = 120
upper_preferred_demod_rate = 250000  # Taken from rtl_433's default


@implementer(IDemodulator)
class RTL433Demodulator(gr.hier_block2, ExportedState):
    __log = Logger()  # TODO: log to context/client
    
    def __init__(self, mode='433', input_rate=0, context=None):
        assert input_rate > 0
        assert context is not None
        gr.hier_block2.__init__(
            self, type(self).__name__,
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(0, 0, 0))
        
        # The input bandwidth chosen is not primarily determined by the bandwidth of the input signals, but by the frequency error of the transmitters. Therefore it is not too critical, and we can choose the exact rate to make the filtering easy.
        if input_rate <= upper_preferred_demod_rate:
            # Skip having a filter at all.
            self.__band_filter = None
            demod_rate = input_rate
        else:
            # TODO: This gunk is very similar to the stuff that MultistageChannelFilter does. See if we can share some code.
            lower_rate = input_rate
            lower_rate_prev = None
            while lower_rate > upper_preferred_demod_rate and lower_rate != lower_rate_prev:
                lower_rate_prev = lower_rate
                if lower_rate % 5 == 0 and lower_rate > upper_preferred_demod_rate * 3:
                    lower_rate /= 5
                elif lower_rate % 2 == 0:
                    lower_rate /= 2
                else:
                    # non-integer ratio
                    lower_rate = upper_preferred_demod_rate
                    break
            demod_rate = lower_rate
            
            self.__band_filter = MultistageChannelFilter(
                input_rate=input_rate,
                output_rate=demod_rate,
                cutoff_freq=demod_rate * 0.4,
                transition_width=demod_rate * 0.2)
        
        # Subprocess
        # using /usr/bin/env because twisted spawnProcess doesn't support path search
        # pylint: disable=no-member
        self.__process = the_reactor.spawnProcess(
            RTL433ProcessProtocol(context.output_message, self.__log),
            '/usr/bin/env',
            env=None,  # inherit environment
            # These arguments were last reviewed for rtl_433 18.12-142-g6c3ca9b
            args=[
                b'env', b'rtl_433',
                b'-F', b'json',  # output format
                b'-r', str(demod_rate) + b'sps:iq:cf32:-',  # specify input format and to use stdin
                b'-M', 'newmodel',
            ],
            childFDs={
                0: 'w',
                1: 'r',
                2: 2
            })
        sink = make_sink_to_process_stdin(self.__process, itemsize=gr.sizeof_gr_complex)
        
        agc = analog.agc2_cc(reference=dB(-4))
        agc.set_attack_rate(200 / demod_rate)
        agc.set_decay_rate(200 / demod_rate)
        
        if self.__band_filter:
            self.connect(
                self,
                self.__band_filter,
                agc)
        else:
            self.connect(
                self,
                agc)
        self.connect(agc, sink)
    
    def _close(self):
        # TODO: This never gets called except in tests. Do this better, like by having an explicit life cycle for demodulators.
        self.__process.loseConnection()
    
    @exported_value(type=BandShape, changes='never')
    def get_band_shape(self):
        """implements IDemodulator"""
        if self.__band_filter:
            return self.__band_filter.get_shape()
        else:
            # TODO Reuse UnselectiveAMDemodulator's approach to this
            return BandShape(stop_low=0, pass_low=0, pass_high=0, stop_high=0, markers={})
    
    def get_output_type(self):
        """implements IDemodulator"""
        return no_signal


class RTL433ProcessProtocol(ProcessProtocol):
    def __init__(self, target, log):
        self.__target = target
        self.__log = log
        self.__line_receiver = LineReceiver()
        self.__line_receiver.delimiter = b'\n'
        self.__line_receiver.lineReceived = self.__lineReceived
    
    def outReceived(self, data):
        """Implements ProcessProtocol."""
        # split lines
        self.__line_receiver.dataReceived(data)
        
    def errReceived(self, data):
        """Implements ProcessProtocol."""
        # we should inherit stderr, not pipe it
        raise Exception('shouldn\'t happen')
    
    def __lineReceived(self, line):
        # rtl_433's JSON encoder is not perfect (e.g. it will emit unescaped newlines), so protect against parse failures
        try:
            message = json.loads(line)
        except ValueError:
            self.__log.warn('bad JSON from rtl_433: {rtl_433_line}', rtl_433_line=repr_no_string_tag(line))
            return
        self.__log.info('rtl_433 message: {rtl_433_json!r}', rtl_433_json=message)
        # rtl_433 provides a time field, but when in file-input mode it assumes the input is not real-time and generates start-of-file-relative timestamps, so we can't use them directly.
        wrapper = RTL433MessageWrapper(message, time.time())
        self.__target(wrapper)


# This includes both rtl_433's notion of device ID and also device type identification that makes a more informative to the user, and distinct, key. Distinctness from unrelated things is important because the telemetry object namespace is shared with other systems.
_id_component_fields = {
    'model',
    'type',
    'subtype',
    'id',
    'channel',
    
    # legacy non-consistent fields -- these are likely to go away in a future rtl_433 version
    'device',
    'dev_id',
    'rc',
    'rid',
    'sid',
}
# Fields that aren't interesting enough.
_ignored_fields = {
    'mic',
    'time',
}


@implementer(ITelemetryMessage)
class RTL433MessageWrapper(object):
    def __init__(self, message, receive_time):
        self.message = message  # a parsed rtl_433 JSON-format message
        self.receive_time = float(receive_time)
        
        id_keys = sorted(k for k in message if k in _id_component_fields)
        self.object_id = u'-'.join(six.text_type(message[k]) for k in id_keys)
    
    def get_object_id(self):
        return self.object_id
    
    def get_object_constructor(self):
        return RTL433MsgGroup


# TODO: It would make sense to make this a CollectionState object to have simple dynamic fields.
@implementer(ITelemetryObject)
class RTL433MsgGroup(ExportedState):
    def __init__(self, object_id):
        """Implements ITelemetryObject."""
        self.__cells = {}
        self.__last_heard_time = None
    
    def state_is_dynamic(self):
        """Overrides ExportedState."""
        return True
    
    def state_def(self):
        """Overrides ExportedState."""
        for d in super(RTL433MsgGroup, self).state_def():
            yield d
        for d in six.iteritems(self.__cells):
            yield d
    
    # not exported
    def receive(self, message_wrapper):
        """Implements ITelemetryObject."""
        self.__last_heard_time = message_wrapper.receive_time
        shape_changed = False
        for k, v in six.iteritems(message_wrapper.message):
            if k in _id_component_fields or k in _ignored_fields:
                continue
            if k not in self.__cells:
                shape_changed = True
                self.__cells[k] = LooseCell(
                    value=None,
                    type=object,
                    writable=False,
                    persists=False,
                    label=k,
                    sort_key='1' + k)
            self.__cells[k].set_internal(v)
        self.state_changed()
        if shape_changed:
            self.state_shape_changed()
    
    def is_interesting(self):
        """Implements ITelemetryObject."""
        return True
    
    def get_object_expiry(self):
        """implement ITelemetryObject"""
        return self.__last_heard_time + drop_unheard_timeout_seconds
    
    @exported_value(type=TimestampT(), changes='explicit', label='Last heard', sort_key='9heard')
    def get_last_heard_time(self):
        return self.__last_heard_time


_rtl_433_unavailability = test_subprocess(
    ['rtl_433', '-r', '/dev/null'],
    b'Reading samples from file',
    shell=False)


plugin_mode = ModeDef(mode='433',
    info=EnumRow(label='rtl_433', description='OOK telemetry decoded by rtl_433 mostly found at 433 MHz'),
    demod_class=RTL433Demodulator,
    unavailability=_rtl_433_unavailability)
