# Copyright 2014, 2015 Kevin Reid <kpreid@switchb.org>
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


'''
APRS support plugin. This does not provide a complete APRS receiver, but only an APRS message parser (parse_tnc2), and an information store (APRSInformation).

If APRSInformation is exported to the web client its data will appear on the map.
'''


# References:
# The parser was primarily tested on examples of live data. The reference
# documentation used was the APRS specification, which is unfortunately
# provided as an original version and multiple documents specifying changes:
# <http://www.aprs.org/doc/APRS101.PDF>
# <http://www.aprs.org/aprs11.html>
# <http://www.aprs.org/aprs12.html>


# pylint: disable=bad-whitespace, too-many-locals, too-many-return-statements, too-many-branches, unused-variable
# (bad-whitespace: we have a column-aligned data table)
# (too-many-*: parsers are hairy)
# (unused-variable: parser tuples)


from __future__ import absolute_import, division

from collections import namedtuple
from datetime import datetime
import os.path
import re

from twisted.web import static
from zope.interface import Interface, implements  # available via Twisted

from shinysdr.telemetry import TelemetryItem, Track, empty_track
from shinysdr.types import Notice
from shinysdr.values import CollectionState, ExportedState, exported_value
from shinysdr.web import ClientResourceDef


_SECONDS_PER_HOUR = 60 * 60
_METERS_PER_NAUTICAL_MILE = 1852
_KNOTS_TO_METERS_PER_SECOND = _METERS_PER_NAUTICAL_MILE / _SECONDS_PER_HOUR
_FEET_TO_METERS = 0.3048

drop_unheard_timeout_seconds = 600  # 10 minutes, standard APRS cycle time


class IAPRSInformation(Interface):
    '''marker interface for client'''
    pass


class APRSInformation(CollectionState):
    '''
    Accepts APRS messages and exports the accumulated information obtained from them.
    '''
    implements(IAPRSInformation)
    
    def __init__(self):
        self.__stations = {}
        CollectionState.__init__(self, self.__stations, dynamic=True)
    
    # not exported
    def receive(self, message):
        '''Store the supplied APRSMessage object.'''
        self.__ensure_station(message.source).receive(message)
        for fact in message.facts:
            if isinstance(fact, ObjectItemReport):
                if fact.live:
                    # TODO kludgy. review for correctness.
                    # consider defining an 'object' instead of 'station' type, which can then be given a 'reported by' field.
                    self.__ensure_station(fact.name).receive(APRSMessage(
                        receive_time=message.receive_time,
                        source=fact.name,
                        destination=None,
                        via=None,
                        payload=None,
                        facts=fact.facts,
                        errors=message.errors,
                        comment=message.comment))
                else:
                    if fact.name in self.__stations:
                        del self.__stations[fact.name]
        
        # logically independent but this is a convenient time, and this approach allows us to borrow the receive time rather than reading the system clock ourselves.
        self.__flush_not_seen(message.receive_time)

    def __ensure_station(self, address):
        if address not in self.__stations:
            self.__stations[address] = APRSStation(address)
        return self.__stations[address]
    
    def __flush_not_seen(self, current_time):
        deletes = []
        limit = current_time - drop_unheard_timeout_seconds
        for key, old_station in self.__stations.iteritems():
            if old_station.get_last_heard_time() <= limit:
                deletes.append(key)
        for key in deletes:
            del self.__stations[key]


class IAPRSStation(Interface):
    '''marker interface for client'''
    pass


class APRSStation(ExportedState):
    implements(IAPRSStation)
    
    def __init__(self, address):
        self.__last_heard_time = None
        self.__address = address
        self.__track = empty_track
        self.__status = u''
        self.__symbol = None
        self.__last_comment = u''
        self.__last_parse_error = u''

    def receive(self, message):
        self.__last_heard_time = message.receive_time
        for fact in message.facts:
            if isinstance(fact, Position):
                self.__track = self.__track._replace(
                    latitude=TelemetryItem(fact.latitude, message.receive_time),
                    longitude=TelemetryItem(fact.longitude, message.receive_time),
                )
            if isinstance(fact, Altitude):
                conversion = _FEET_TO_METERS if fact.feet_not_meters else 1
                self.__track = self.__track._replace(
                    altitude=TelemetryItem(fact.value * conversion, message.receive_time),
                )
            if isinstance(fact, Velocity):
                self.__track = self.__track._replace(
                    h_speed=TelemetryItem(fact.speed_knots * _KNOTS_TO_METERS_PER_SECOND, message.receive_time),
                    track_angle=TelemetryItem(fact.course_degrees, message.receive_time),
                )
            elif isinstance(fact, Status):
                # TODO: Empirically, not always ASCII. Move this implicit decoding off into parse stages.
                self.__status = unicode(fact.text)
            elif isinstance(fact, Symbol):
                self.__symbol = unicode(fact.id)
            else:
                # TODO: Warn somewhere in this case (recognized by parser but not here)
                pass
        self.__last_comment = unicode(message.comment)
        if len(message.errors) > 0:
            self.__last_parse_error = '; '.join(message.errors)
    
    @exported_value(ctor=float)
    def get_last_heard_time(self):
        return self.__last_heard_time
    
    @exported_value(ctor=unicode)
    def get_address(self):
        return self.__address

    @exported_value(ctor=Track)
    def get_track(self):
        return self.__track

    @exported_value(ctor=unicode)
    def get_symbol(self):
        '''APRS symbol table identifier and symbol.'''
        return self.__symbol

    @exported_value(ctor=unicode)
    def get_status(self):
        '''String status text.'''
        return self.__status

    @exported_value(ctor=unicode)
    def get_last_comment(self):
        return self.__last_comment

    @exported_value(ctor=Notice(always_visible=False))
    def get_last_parse_error(self):
        return self.__last_parse_error


APRSMessage = namedtuple('APRSMessage', [
    'receive_time',  # unix time: when the message was received
    'source',  # string: AX.25 address
    'destination',  # string: AX.25 address
    'via',  # string: comma-separated addresses
    'payload',  # string: AX.25 information
    'facts',  # list: of fact objects parsed from the message
    'errors',  # list: of strings describing parse failures
    'comment',  # APRS comment text
])


# fact
Capabilities = namedtuple('Capabilities', [
    'capabilities',  # dict with string keys (tokens) and string-or-None values
])


# fact
Altitude = namedtuple('Altitude', [
    'value',  # number: value
    'feet_not_meters',  # boolean: true=units are feet, false=units are meters
    # This horrible representation was chosen to ensure not losing data.
])


# fact
Messaging = namedtuple('Messaging', [
    'supported',  # boolean
])


# fact
ObjectItemReport = namedtuple('ObjectItemReport', [
    'object',  # boolean: true=Object, false=Item
    'name',  # string
    'live',  # boolean
    'facts',  # list of facts: about this object (rather than the source address)
])


# fact
Position = namedtuple('Position', [
    'latitude',  # float: degrees north, WGS84
    'longitude',  # float: degrees east, WGS84
])


# fact
# TODO: Represent non-precalculated format
RadioRange = namedtuple('RadioRange', [
    'miles',  # float
])


# fact
Telemetry = namedtuple('Telemetry', [
    'channel',  # integer: channel 1-5
    'value',  # float: value
])


# fact
Status = namedtuple('Status', [
    'text',  # string
])


# fact
Symbol = namedtuple('Symbol', [
    'id',  # string
])


# fact
Timestamp = namedtuple('Timestamp', [
    'time',  # datetime object
])


# fact
Velocity = namedtuple('Velocity', [
    'speed_knots',  # number
    'course_degrees',  # number
])


def parse_tnc2(line, receive_time):
    '''Parse "TNC2 text format" APRS messages.'''
    if not isinstance(line, unicode):
        # TODO: Is there a more-often-than-not used encoding beyond ASCII, that we should use here?
        line = unicode(line, 'ascii', 'replace')
    facts = []
    errors = []
    match = re.match(r'^([^:>,]+?)>([^:>,]+)((?:,[^:>]+)*):(.*?)$', line)
    if not match:
        errors.append('Could not parse TNC2')
        return APRSMessage(receive_time, '', '', '', line, facts, errors, line)
    else:
        source, destination, via, payload = match.groups()
        comment = _parse_payload(facts, errors, source, destination, payload, receive_time)
        return APRSMessage(receive_time, source, destination, via, payload, facts, errors, comment)


def _parse_payload(facts, errors, source, destination, payload, receive_time):
    if len(payload) < 1:
        errors.append('zero length information')
        return payload
    data_type = payload[0]
    
    if data_type == '!' or data_type == '=':  # Position Without Timestamp
        facts.append(Messaging(data_type == '='))
        return _parse_position_and_symbol(facts, errors, payload[1:])
    
    if data_type == '/' or data_type == '@':  # Position With Timestamp
        facts.append(Messaging(data_type == '@'))
        match = re.match(r'^.(.{7})(.*)$', payload)
        if not match:
            errors.append('Position With Timestamp is too short')
            return payload
        else:
            time_str, position_str = match.groups()
            _parse_dhm_hms_timestamp(facts, errors, time_str, receive_time)
            return _parse_position_and_symbol(facts, errors, position_str)
    
    elif data_type == '<':  # Capabilities
        facts.append(Capabilities(dict(map(_parse_capability, payload[1:].split(',')))))
        return ''
    
    elif data_type == '>':  # Status
        # TODO: parse timestamp
        facts.append(Status(payload[1:]))
        return ''
    
    elif data_type == '`' or data_type == "'":  # Mic-E position
        match = re.match(r'^.(.)(.)(.)(.)(.)(.)(..)(.*)$', payload)
        if not match:
            errors.append('Mic-E Information is too short')
            return payload
        elif len(destination) < 6:
            errors.append('Mic-E Destination Address is too short')
            return payload
        else:
            # TODO: deal with ssid/7th byte
            # This is a generic application of the decoding table: note that not all of the resulting values are meaningful (e.g. only ns_bits[3] is a north/south value).
            lat_digits, message_bits, ns_bits, lon_offset_bits, ew_bits = zip(*[_mic_e_addr_decode_table[x] for x in destination[0:6]])
            latitude_string = ''.join(lat_digits[0:4]) + '.' + ''.join(lat_digits[4:6]) + ns_bits[3]
            latitude = _parse_angle(latitude_string)
            longitude_offset = lon_offset_bits[4]
            
            # TODO: parse Mic-E "message"/"position comment" bits
            
            # TODO: interpret data type ID values (note spec revisions about it)
            
            d28, m28, h28, sp28, dc28, se28, symbol_rev, type_and_more = match.groups()
            
            # decode longitude, as specified in http://www.aprs.org/doc/APRS101.PDF page 48
            lon_d = ord(d28) - 28 + longitude_offset
            if 180 <= lon_d <= 189:
                lon_d -= 80
            elif 190 <= lon_d <= 199:
                lon_d -= 190
            lon_m = ord(m28) - 28
            if lon_m >= 60:
                lon_m -= 60
            lon_s = ord(h28) - 28
            longitude = ew_bits[5] * (lon_d + (lon_m + lon_s / 100) / 60)
            # TODO: interpret position ambiguity from latitude
            
            if latitude is not None:
                facts.append(Position(latitude, longitude))
            else:
                errors.append('Mic-E latitude does not parse: %r' % latitude_string)
            
            # decode course and speed, as specified in http://www.aprs.org/doc/APRS101.PDF page 52
            dc = ord(dc28) - 28
            speed = (ord(sp28) - 28) * 10 + dc // 10
            course = dc % 10 + (ord(se28) - 28)
            if speed >= 800:
                speed -= 800
            if course >= 400:
                course -= 400
            facts.append(Velocity(speed_knots=speed, course_degrees=course))
            
            _parse_symbol(facts, errors, symbol_rev[1] + symbol_rev[0])
            
            # Type code per http://www.aprs.org/aprs12/mic-e-types.txt
            # TODO: parse and process manufacturer codes
            type_match = re.match(r"^([] >`'])(?:(...)\})?(.*)$", type_and_more)
            if type_match is None:
                errors.append('Mic-E contained non-type-code text: %r' % type_and_more)
                return type_and_more
            else:
                type_code, opt_altitude, more_text = type_match.groups()
                # TODO: process type code
                if opt_altitude is not None:
                    facts.append(Altitude(value=_parse_base91(opt_altitude) - 10000, feet_not_meters=False))
                return more_text  # or should this be a status fact?

    elif data_type == ';':  # Object
        match = re.match(r'^.(.{9})([*_])(.{7})(.*)$', payload)
        if not match:
            errors.append('Object Information did not parse')
            return payload
        else:
            name, live_str, time_str, position_ext_and_comment = match.groups()
            obj_facts = []
            
            _parse_dhm_hms_timestamp(obj_facts, errors, time_str, receive_time)
            comment = _parse_position_and_symbol(obj_facts, errors, position_ext_and_comment)
            
            facts.append(ObjectItemReport(
                object=True,
                name=name,
                live=live_str == '*',
                facts=obj_facts))
            return comment

    elif data_type == 'T':  # Telemetry (1.0.1 format)
        # more lenient than spec because a real packet I saw had decimal points and variable field lengths
        match = re.match(r'^T#([^,]*|MIC),?([^,]*),([^,]*),([^,]*),([^,]*),([^,]*),([01]{8})(.*)$', payload)
        if not match:
            errors.append('Telemetry did not parse: %r' % payload)
            return ''
        else:
            seq, a1, a2, a3, a4, a5, digital, comment = match.groups()
            _parse_telemetry_value(facts, errors, a1, 1)
            _parse_telemetry_value(facts, errors, a2, 2)
            _parse_telemetry_value(facts, errors, a3, 3)
            _parse_telemetry_value(facts, errors, a4, 4)
            _parse_telemetry_value(facts, errors, a5, 5)
            # TODO: handle seq # (how is it used in practice?) and digital
            return comment
        
    else:
        errors.append('unrecognized data type: %r' % data_type)
        return payload


_mic_e_addr_decode_table = {
    # per APRS 1.1 http://www.aprs.org/doc/APRS101.PDF page 44
    # (lat digit, message bit, lat dir, lon offset, lon dir)
    '0': ('0', 0, 'S',   0, +1),
    '1': ('1', 0, 'S',   0, +1),
    '2': ('2', 0, 'S',   0, +1),
    '3': ('3', 0, 'S',   0, +1),
    '4': ('4', 0, 'S',   0, +1),
    '5': ('5', 0, 'S',   0, +1),
    '6': ('6', 0, 'S',   0, +1),
    '7': ('7', 0, 'S',   0, +1),
    '8': ('8', 0, 'S',   0, +1),
    '9': ('9', 0, 'S',   0, +1),
    'A': ('0', 1, ' ',   0,  0),
    'B': ('1', 1, ' ',   0,  0),
    'C': ('2', 1, ' ',   0,  0),
    'D': ('3', 1, ' ',   0,  0),
    'E': ('4', 1, ' ',   0,  0),
    'F': ('5', 1, ' ',   0,  0),
    'G': ('6', 1, ' ',   0,  0),
    'H': ('7', 1, ' ',   0,  0),
    'I': ('8', 1, ' ',   0,  0),
    'J': ('9', 1, ' ',   0,  0),
    'K': (' ', 1, ' ',   0,  0),
    'L': (' ', 0, 'S',   0, +1),
    'P': ('0', 1, 'N', 100, -1),
    'Q': ('1', 1, 'N', 100, -1),
    'R': ('2', 1, 'N', 100, -1),
    'S': ('3', 1, 'N', 100, -1),
    'T': ('4', 1, 'N', 100, -1),
    'U': ('5', 1, 'N', 100, -1),
    'V': ('6', 1, 'N', 100, -1),
    'W': ('7', 1, 'N', 100, -1),
    'X': ('8', 1, 'N', 100, -1),
    'Y': ('9', 1, 'N', 100, -1),
    'Z': (' ', 1, 'N', 100, -1),
}


def _parse_symbol(facts, errors, symbol):
    # TODO: Interpret symbol string more
    facts.append(Symbol(symbol))


def _parse_capability(capability):
    match = re.match(r'^(.*?)=(.*)$', capability)
    if match:
        return match.groups()
    else:
        return capability, None


def _parse_position_and_symbol(facts, errors, data):
    # Uncompressed position
    match = re.match(r'^(\d.{7})(.)(.{9})(.)(.*)$', data)
    if match:
        lat, symbol1, lon, symbol2, ext_and_comment = match.groups()
        plat = _parse_angle(lat)
        plon = _parse_angle(lon)
        if plat is not None and plon is not None:
            facts.append(Position(plat, plon))
        else:
            errors.append('lat/lon does not parse: %r' % ((lat, lon),))
        symbol = symbol1 + symbol2
        _parse_symbol(facts, errors, symbol)
        return _parse_comment_altitude(facts, errors,
             _parse_data_extension(facts, errors, ext_and_comment, symbol))
    
    # Compressed position
    match = re.match(r'^(.)(.{4})(.{4})(.)(.)(.)(.)(.*)$', data)
    if match:
        symbol1, lat, lon, symbol2, c, s, comptype, comment = match.groups()
        plat = 90 - _parse_base91(lat) / 380926
        plon = -180 + _parse_base91(lon) / 190463
        facts.append(Position(plat, plon))
        _parse_symbol(facts, errors, symbol1 + symbol2)
        comptype_bits = _parse_base91(comptype)
        if comptype_bits & 0b11000 == 0b10000:
            # compressed altitude
            facts.append(Altitude(
                value=1.002 ** _parse_base91(c + s),
                feet_not_meters=True))
        elif c == ' ':
            # no data
            pass
        elif c == '{':
            # radio range
            facts.append(RadioRange(1.08 ** _parse_base91(s)))
        elif 0 <= _parse_base91(c) <= 89:
            # course/speed
            # TODO: report errors on out of range values
            facts.append(Velocity(
                speed_knots=1.08 ** _parse_base91(s) - 1, 
                course_degrees=_parse_base91(c) * 4))
        # TODO: Parse "compression type" field (incl altitude)
        # TODO: Should we be parsing comment-altitude here?
        return comment
    
    errors.append('Position does not parse')
    return data


def _parse_data_extension(facts, errors, data, symbol):
    if not len(data) >= 7:
        return data
    
    match = re.match(r'^(\d\d\d)/(\d\d\d)(.*)$', data)
    if match and symbol is not '\\l':  # not an area object, which is ambiguous
        # TODO: Deal with wind direction case
        course, speed, comment = match.groups()
        facts.append(Velocity(speed_knots=int(speed), course_degrees=int(course)))
        return comment
    
    match = re.match(r'^PHG(\d)(\d)(\d)(\d)(.*)$', data)
    if match:
        # TODO: Store this data
        p, h, g, d, comment = match.groups()
        errors.append('PHG parsing not implemented')
        return comment
    
    match = re.match(r'^RNG(\d\d\d\d)(.*)$', data)
    if match:
        range_str, comment = match.groups()
        facts.append(RadioRange(int(range_str)))
        return comment
    
    match = re.match(r'^DFS(\d)(\d)(\d)(\d)(.*)$', data)
    if match:
        # TODO: Store this data
        s, h, g, d, comment = match.groups()
        errors.append('DFS parsing not implemented')
        return comment
    
    match = re.match(r'^(\d)(\d\d)([/1]\d)(\d\d)(.*)$', data)
    if match:
        # TODO: Store this data
        type_code, yy, color_code, xx, comment = match.groups()
        errors.append('Area object not implemented')
        # TODO: Parse line "corridor"
        return comment
    
    return data


def _parse_dhm_hms_timestamp(facts, errors, data, receive_time):
    match = re.match(r'^(\d\d)(\d\d)(\d\d)([zh/])$', data)
    if not match:
        errors.append('DHM/HMS timestamp does not parse')
        return

    f1, f2, f3, kind = match.groups()
    n1 = int(f1)
    n2 = int(f2)
    n3 = int(f3)
    
    # TODO: This logic has not been completely tested.
    # TODO: We should probably take larger-than-current day numbers as the previous month, and similar for hours just before midnight in 'h' format
    try:
        if kind == 'h':
            absolute_time = datetime.utcfromtimestamp(receive_time).replace(hour=n1, minute=n2, second=n3)
        elif kind == 'z':
            absolute_time = datetime.utcfromtimestamp(receive_time).replace(day=n1, hour=n2, minute=n3, second=0, microsecond=0)
        else:  # kind == '/'
            absolute_time = datetime.fromtimestamp(receive_time).replace(day=n1, hour=n2, minute=n3, second=0, microsecond=0)
    except ValueError, e:
        errors.append('DHM/HMS timestamp invalid: %s' % (e.message,))
        return
    
    facts.append(Timestamp(absolute_time))


def _parse_angle(angle_str):
    # TODO return imprecision information
    # TODO old notes say "." is allowed as imprecision, check
    match = re.match(r'^(\d{1,3})([\d ]{2}\.[\d ]{2})([NESW])$', angle_str)
    if not match:
        return None
    else:
        degrees, minutes, direction = match.groups()
        minutes = minutes.replace(' ', '0')
        if direction == 'S' or direction == 'W':
            sign = -1
        else:
            sign = 1
        return sign * (float(degrees) + float(minutes) / 60)


def _parse_comment_altitude(facts, errors, comment):
    match = re.search(r'/A=(\d{6})', comment)
    if match:
        facts.append(Altitude(value=int(match.group(1)), feet_not_meters=True))
        comment = comment[:match.start()] + comment[match.end():]
    return comment


def _parse_base91(text):
    # per http://www.aprs.org/doc/APRS101.PDF page 55
    # TODO: Error checking (out of range digits)
    value = 0
    for ch in text:
        value = value * 91 + ord(ch) - 33
    return value


def _parse_telemetry_value(facts, errors, value_str, channel):
    try:
        value = float(value_str)
    except ValueError:
        errors.append('Telemetry channel %i did not parse: %r' % (channel, value_str))
        return
    facts.append(Telemetry(channel=channel, value=value))


plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='aprs.js')
