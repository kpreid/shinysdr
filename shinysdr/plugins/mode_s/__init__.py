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

from shinysdr.filters import MultistageChannelFilter
from shinysdr.modes import ModeDef, IDemodulator
from shinysdr.signals import no_signal
from shinysdr.telemetry import TelemetryItem, Track, empty_track
from shinysdr.types import Notice
from shinysdr.values import CollectionState, ExportedState, exported_value
from shinysdr.web import ClientResourceDef

try:
    import air_modes
    _available = True
except ImportError:
    _available = False


demod_rate = 2000000
transition_width = 500000


drop_unheard_timeout_seconds = 60


_SECONDS_PER_HOUR = 60 * 60
_METERS_PER_NAUTICAL_MILE = 1852
_KNOTS_TO_METERS_PER_SECOND = _METERS_PER_NAUTICAL_MILE / _SECONDS_PER_HOUR
_CM_PER_INCH = 2.54
_INCH_PER_FOOT = 12
_METERS_PER_FEET = (_CM_PER_INCH * _INCH_PER_FOOT) / 100

class ModeSDemodulator(gr.hier_block2, ExportedState):
    implements(IDemodulator)
    
    def __init__(self, mode='MODE-S', input_rate=0, mode_s_information=None, context=None):
        assert input_rate > 0
        gr.hier_block2.__init__(
            self, 'Mode S/ADS-B/1090 demodulator',
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(0, 0, 0))
        self.mode = mode
        self.input_rate = input_rate
        if mode_s_information is not None:
            self.__information = mode_s_information
        else:
            self.__information = ModeSInformation()
        
        hex_msg_queue = gr.msg_queue(100)
        
        band_filter = MultistageChannelFilter(
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
            band_filter,
            self.__demod)
        
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
            self.__information.receive(msg, cpr_decoder)
        
        for i in xrange(0, 2 ** 5):
            parser_output.subscribe('type%i_dl' % i, parsed_callback)

    def __del__(self):
        self.__msgq_runner.stop()

    def can_set_mode(self, mode):
        return False

    def get_half_bandwidth(self):
        return demod_rate / 2
    
    def get_output_type(self):
        return no_signal
    
    @exported_value()
    def get_band_filter_shape(self):
        return {
            'low': -demod_rate / 2,
            'high': demod_rate / 2,
            'width': transition_width
        }


class IModeSInformation(Interface):
    '''marker interface for client'''
    pass


class ModeSInformation(CollectionState):
    '''
    Accepts Mode-S messages and exports the accumulated information obtained from them.
    '''
    implements(IModeSInformation)
    
    def __init__(self):
        self.__aircraft = {}
        self.__interesting_aircraft = {}
        CollectionState.__init__(self, self.__interesting_aircraft, dynamic=True)
    
    # not exported
    def receive(self, message, cpr_decoder):
        '''
        Interpret and store the message provided, which should be in the format produced by air_modes.make_parser.
        '''
        # Unfortunately, gr-air-modes doesn't provide a function to implement this gunk -- imitating output_print.catch_nohandler
        data = message.data
        if "aa" in data.fields:
            address_int = data["aa"]
        else:
            address_int = message.ecc
        
        # Process the message
        aircraft = self.__ensure_aircraft(address_int)
        aircraft.receive(message, cpr_decoder)
        
        # Maybe promote the aircraft
        if aircraft.is_interesting():
            self.__interesting_aircraft[self.__string_address(address_int)] = aircraft
        
        # logically independent but this is a convenient time
        self.__flush_not_seen()
    
    def __ensure_aircraft(self, address_int):
        if address_int not in self.__aircraft:
            self.__aircraft[address_int] = Aircraft(address_int)
        return self.__aircraft[address_int]
    
    def __string_address(self, address_int):
        return '%.6x' % (address_int,)
    
    def __flush_not_seen(self):
        deletes = []
        limit = time.time() - drop_unheard_timeout_seconds
        for key, old_aircraft in self.__aircraft.iteritems():
            if old_aircraft.get_last_heard_time() < limit:
                deletes.append(key)
        for key in deletes:
            del self.__aircraft[key]
            address_hex = self.__string_address(key)
            if address_hex in self.__interesting_aircraft:
                del self.__interesting_aircraft[address_hex]


class IAircraft(Interface):
    '''marker interface for client'''
    pass


class Aircraft(ExportedState):
    implements(IAircraft)
    
    def __init__(self, address_hex):
        self.__last_heard_time = None
        self.__track = empty_track
        self.__call = None
        self.__ident = None
        self.__aircraft_type = None
    
    # not exported
    def receive(self, message, cpr_decoder):
        receive_time = time.time()  # TODO: arguably should be an argument
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
                    self.__track = self.__track._replace(
                        h_speed=TelemetryItem(velocity * _KNOTS_TO_METERS_PER_SECOND, receive_time),
                        heading=TelemetryItem(heading, receive_time),
                        v_speed=TelemetryItem(vertical_speed, receive_time),
                        # TODO add turn rate
                    )
                elif subtype == 1:
                    (velocity, heading, vertical_speed) = air_modes.parseBDS09_1(data)
                    self.__track = self.__track._replace(
                        h_speed=TelemetryItem(velocity * _KNOTS_TO_METERS_PER_SECOND, receive_time),
                        heading=TelemetryItem(heading, receive_time),
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
        '''
        Does this aircraft have enough information to be worth mentioning?
        '''
        return \
            self.__track.altitude.value is not None or \
            self.__track.latitude.value is not None or \
            self.__track.longitude.value is not None or \
            self.__call is not None or \
            self.__aircraft_type is not None
        
    @exported_value(ctor=float)
    def get_last_heard_time(self):
        return self.__last_heard_time
    
    @exported_value(ctor=unicode)
    def get_call(self):
        return self.__call
    
    @exported_value(ctor=int)
    def get_ident(self):
        return self.__ident
    
    @exported_value(ctor=unicode)
    def get_aircraft_type(self):
        return self.__aircraft_type
    
    @exported_value(ctor=Track)
    def get_track(self):
        return self.__track


plugin_mode = ModeDef(
    mode='MODE-S',
    label='Mode S',
    demod_class=ModeSDemodulator,
    available=_available,
    shared_objects={'mode_s_information': ModeSInformation})
plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='mode_s.js')
