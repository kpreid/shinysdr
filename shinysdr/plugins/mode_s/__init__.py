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

# pylint: disable=maybe-no-member, no-member
# (maybe-no-member: GR swig)
# (no-member: Twisted reactor)

from __future__ import absolute_import, division

import os.path
import time
import traceback

from twisted.internet import reactor  # TODO eliminate
from twisted.web import static
from zope.interface import Interface, implements

from gnuradio import gr
from gnuradio import gru

try:
    import air_modes
    _available = True
except ImportError:
    _available = False

from shinysdr.filters import MultistageChannelFilter
from shinysdr.interfaces import ClientResourceDef, IDemodulator, ModeDef
from shinysdr.math import LazyRateCalculator
from shinysdr.signals import no_signal
from shinysdr.telemetry import ITelemetryMessage, ITelemetryObject, TelemetryItem, TelemetryStore, Track, empty_track
from shinysdr.types import EnumRow, Notice, Range, Timestamp
from shinysdr.values import CollectionState, ExportedState, exported_value, setter




drop_unheard_timeout_seconds = 60


_SECONDS_PER_HOUR = 60 * 60
_METERS_PER_NAUTICAL_MILE = 1852
_KNOTS_TO_METERS_PER_SECOND = _METERS_PER_NAUTICAL_MILE / _SECONDS_PER_HOUR
_CM_PER_INCH = 2.54
_INCH_PER_FOOT = 12
_METERS_PER_FEET = (_CM_PER_INCH * _INCH_PER_FOOT) / 100


class ModeSDemodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    def __init__(self, mode='MODE-S', input_rate=0, context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, 'Mode S/ADS-B/1090 demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(0, 0, 0))
        
        demod_rate = 2000000
        transition_width = 500000
        
        hex_msg_queue = gr.msg_queue(100)
        
        self.__band_filter = MultistageChannelFilter(
            input_rate=input_rate,
            output_rate=demod_rate,
            cutoff_freq=demod_rate / 2,
            transition_width=transition_width)  # TODO optimize filter band
        self.__demod = air_modes.rx_path(
            rate=demod_rate,
            threshold=7.0,  # default used in air-modes code but not exposed
            queue=hex_msg_queue,
            use_pmf=False,
            use_dcblock=True)
        self.connect(
            self,
            self.__band_filter,
            self.__demod)
        
        self.__messages_seen = 0
        self.__message_rate_calc = LazyRateCalculator(lambda: self.__messages_seen, min_interval=2)
        
        # Parsing
        # TODO: These bits are mimicking gr-air-modes toplevel code. Figure out if we can have less glue.
        # Note: gr pubsub is synchronous -- subscribers are called on the publisher's thread
        parser_output = gr.pubsub.pubsub()
        parser = air_modes.make_parser(parser_output)
        cpr_decoder = air_modes.cpr_decoder(my_location=None)  # TODO: get position info from device
        air_modes.output_print(cpr_decoder, parser_output)
        def callback(msg):  # called on msgq_runner's thrad
            # pylint: disable=broad-except
            try:
                reactor.callFromThread(parser, msg.to_string())
            except Exception:
                print traceback.format_exc()
        
        self.__msgq_runner = gru.msgq_runner(hex_msg_queue, callback)
        
        def parsed_callback(msg):
            timestamp = time.time()
            self.__messages_seen += 1
            context.output_message(ModeSMessageWrapper(msg, cpr_decoder, timestamp))
        
        for i in xrange(0, 2 ** 5):
            parser_output.subscribe('type%i_dl' % i, parsed_callback)

    def __del__(self):
        self.__msgq_runner.stop()
    
    @exported_value(type=Range([(0, 30)]))
    def get_decode_threshold(self):
        return self.__demod.get_threshold(None)
    
    @setter
    def set_decode_threshold(self, value):
        self.__demod.set_threshold(float(value))
    
    @exported_value(float)
    def get_message_rate(self):
        return round(self.__message_rate_calc.get(), 1)
    
    def can_set_mode(self, mode):
        return False

    def get_output_type(self):
        return no_signal
    
    @exported_value()
    def get_band_filter_shape(self):
        return self.__band_filter.get_shape()


class ModeSMessageWrapper(object):
    implements(ITelemetryMessage)
    
    def __init__(self, message, cpr_decoder, receive_time):
        self.message = message  # a gr-air-modes message
        self.cpr_decoder = cpr_decoder
        self.receive_time = float(receive_time)
    
    def get_object_id(self):
        # Unfortunately, gr-air-modes doesn't provide a function to implement this gunk -- imitating output_print.catch_nohandler
        data = self.message.data
        if "aa" in data.fields:
            address_int = data["aa"]
        else:
            address_int = self.message.ecc
        
        return '%.6x' % (address_int,)
    
    def get_object_constructor(self):
        return Aircraft


class IAircraft(Interface):
    """marker interface for client"""
    pass


class Aircraft(ExportedState):
    implements(IAircraft, ITelemetryObject)
    
    def __init__(self, object_id):
        """Implements ITelemetryObject. object_id is the hex formatted address."""
        self.__last_heard_time = None
        self.__track = empty_track
        self.__call = None
        self.__ident = None
        self.__aircraft_type = None
    
    # not exported
    def receive(self, message_wrapper):
        message = message_wrapper.message
        cpr_decoder = message_wrapper.cpr_decoder
        receive_time = message_wrapper.receive_time
        self.__last_heard_time = receive_time
        # Unfortunately, gr-air-modes doesn't provide a function to implement this gunk -- imitating its output_flightgear code which
        data = message.data
        t = data.get_type()
        if t == 0:
            self.__track = self.__track._replace(
                altitude=TelemetryItem(air_modes.decode_alt(data['ac'], True) * _METERS_PER_FEET, receive_time))
            # TODO more info available here
        elif t == 4:
            self.__track = self.__track._replace(
                altitude=TelemetryItem(air_modes.decode_alt(data['ac'], True) * _METERS_PER_FEET, receive_time))
            # TODO more info available here
        elif t == 5:
            self.__ident = air_modes.decode_id(data['id'])
            # TODO more info available here
        elif t == 17:  # ADS-B
            bdsreg = data['me'].get_type()
            if bdsreg == 0x05:
                # TODO use unused info
                (altitude_feet, latitude, longitude, _range, _bearing) = air_modes.parseBDS05(data, cpr_decoder)
                self.__track = self.__track._replace(
                    altitude=TelemetryItem(altitude_feet * _METERS_PER_FEET, receive_time),
                    latitude=TelemetryItem(latitude, receive_time),
                    longitude=TelemetryItem(longitude, receive_time),
                )
            elif bdsreg == 0x06:
                # TODO use unused info
                (_ground_track, latitude, longitude, _range, _bearing) = air_modes.parseBDS06(data, cpr_decoder)
                self.__track = self.__track._replace(
                    latitude=TelemetryItem(latitude, receive_time),
                    longitude=TelemetryItem(longitude, receive_time),
                )
            elif bdsreg == 0x08:
                (self.__call, self.__aircraft_type) = air_modes.parseBDS08(data)
            elif bdsreg == 0x09:
                subtype = data['bds09'].get_type()
                if subtype == 0:
                    (velocity, heading, vertical_speed, _turn_rate) = air_modes.parseBDS09_0(data)
                    # TODO: note we're stuffing the heading in as track angle. Is there something better to do?
                    self.__track = self.__track._replace(
                        h_speed=TelemetryItem(velocity * _KNOTS_TO_METERS_PER_SECOND, receive_time),
                        heading=TelemetryItem(heading, receive_time),
                        track_angle=TelemetryItem(heading, receive_time),
                        v_speed=TelemetryItem(vertical_speed, receive_time),
                        # TODO add turn rate
                    )
                elif subtype == 1:
                    (velocity, heading, vertical_speed) = air_modes.parseBDS09_1(data)
                    self.__track = self.__track._replace(
                        h_speed=TelemetryItem(velocity * _KNOTS_TO_METERS_PER_SECOND, receive_time),
                        heading=TelemetryItem(heading, receive_time),
                        track_angle=TelemetryItem(heading, receive_time),
                        v_speed=TelemetryItem(vertical_speed, receive_time),
                        # TODO reset turn rate?
                    )
                else:
                    # TODO report
                    pass
            else:
                # TODO report
                pass
        else:
            # TODO report
            pass
    
    def is_interesting(self):
        """
        Implements ITelemetryObject. Does this aircraft have enough information to be worth mentioning?
        """
        # TODO: Loosen this rule once we have more efficient state transfer (no polling) and better UI for viewing them on the client.
        return \
            self.__track.latitude.value is not None or \
            self.__track.longitude.value is not None or \
            self.__call is not None or \
            self.__aircraft_type is not None
    
    def get_object_expiry(self):
        """implement ITelemetryObject"""
        return self.__last_heard_time + drop_unheard_timeout_seconds
    
    @exported_value(type=Timestamp())
    def get_last_heard_time(self):
        return self.__last_heard_time
    
    @exported_value(type=unicode)
    def get_call(self):
        return self.__call
    
    @exported_value(type=int)
    def get_ident(self):
        return self.__ident
    
    @exported_value(type=unicode)
    def get_aircraft_type(self):
        return self.__aircraft_type
    
    @exported_value(type=Track)
    def get_track(self):
        return self.__track


plugin_mode = ModeDef(mode='MODE-S',
    info=EnumRow(label='Mode S', description='Aviation telemetry found at 1090 MHz'),
    demod_class=ModeSDemodulator,
    available=_available)
plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='mode_s.js')
