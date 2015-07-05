# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=too-many-public-methods, unused-variable
# (too-many-public-methods: bogus reports for TestCase)
# (unused-variable: unused parse tuple results)

from __future__ import absolute_import, division

from datetime import datetime

from twisted.trial import unittest

from shinysdr.plugins.aprs import APRSInformation, APRSStation, APRSMessage, Capabilities, ObjectItemReport, Messaging, Position, Status, Symbol, Telemetry, Timestamp, Velocity, parse_tnc2
from shinysdr.telemetry import TelemetryItem, empty_track


# January 2, 2000, 12:30:30 + 1 microsecond
_dummy_receive_datetime = datetime(2000, 1, 2, 12, 30, 30, 1, None)
_dummy_receive_time = (_dummy_receive_datetime - datetime(1970, 1, 1)).total_seconds()


class TestAPRSParser(unittest.TestCase):
    def __check(self, line, parsed):
        self.assertEqual(parse_tnc2(line, _dummy_receive_time), parsed)
    
    def __check_parsed(self, line, facts, errors, comment=''):
        parsed = parse_tnc2(line, _dummy_receive_time)
        # Check errors first so if we fail to parse we report the errors and not only missing facts
        self.assertEqual(parsed.errors, errors)
        self.assertEqual(parsed.facts, facts)
        self.assertEqual(parsed.comment, comment)
    
    def test_not_tnc2(self):
        self.__check(
            'BOOM',
            APRSMessage(
                receive_time=_dummy_receive_time,
                source='',
                destination='',
                via='',
                payload='BOOM',
                facts=[],
                errors=['Could not parse TNC2'],
                comment='BOOM'))
    
    def test_not_ascii(self):
        # TODO: Obtain an actual sample non-ASCII APRS message for testing. This one is just made up because previous code crashed without logging the problematic message.
        self.__check_parsed(
            'FOO>BAR:>a\xB0b',
            facts=[Status(u'a\uFFFDb')],
            errors=[],
            comment='')
    
    def test_capabilities(self):
        self.__check_parsed(
            'KW0RCA-2>APJI40,N6ACK-10*,WIDE2-1:<IGATE,MSG_CNT=1,LOC_CNT=47',
            facts=[Capabilities({
                'IGATE': None,
                'MSG_CNT': '1',
                'LOC_CNT': '47',
            })],
            errors=[],
            comment='')
    
    def test_parse_and_position_without_timestamp(self):
        '''this test case looks at the entire message structure'''
        self.__check(
            'N6WKZ-3>APU25N,WB6TMS-3*,N6ZX-3*,WIDE2*:=3746.42N112226.00W# {UIV32N}',
            APRSMessage(
                receive_time=_dummy_receive_time,
                source='N6WKZ-3',
                destination='APU25N',
                via=',WB6TMS-3*,N6ZX-3*,WIDE2*',
                payload='=3746.42N112226.00W# {UIV32N}',
                facts=[
                    Messaging(True),
                    Position((37 + 46.42 / 60), -(122 + 26.00 / 60)),
                    Symbol('1#'),
                ],
                errors=[],
                comment=' {UIV32N}'))

    def test_position_without_timestamp_bad(self):
        self.__check_parsed(
            'FOO>BAR:=^^^^^',
            facts=[Messaging(True)],
            errors=['Position does not parse'],
            comment='^^^^^')
    
    def test_position_without_timestamp_without_messaging(self):
        self.__check_parsed(
            'N6ZX-3>APN391:!3726.16NS12219.21W#PHG2436/A=002080',
            facts=[
                Messaging(False),
                Position((37 + 26.16 / 60), -(122 + 19.21 / 60)),
                Symbol('S#')],
            errors=[],
            comment='PHG2436/A=002080')
    
    def test_position_with_timestamp_with_messaging(self):
        # TODO this message looks to have other stuff we should parse
        self.__check_parsed(
            'KA6UPU-1>APRS,N6ZX-3*,WIDE1*:@160256z3755.50N/12205.43W_204/003g012t059r000p000P000h74b10084.DsVP',
            facts=[
                Messaging(True),
                Timestamp(_dummy_receive_datetime.replace(day=16, hour=2, minute=56, second=0, microsecond=0)),
                Position((37 + 55.50 / 60), -(122 + 05.43 / 60)),
                Symbol('/_'),
            ],
            errors=[],
            comment='204/003g012t059r000p000P000h74b10084.DsVP')

    def test_position_with_timestamp_without_messaging(self):
        # TODO this message looks to have other stuff we should parse
        self.__check_parsed(
            'KMEP1>APT311,N6ZX-3*,WIDE1*,WIDE2-1:/160257z3726.79N\\12220.18Wv077/000/A=001955/N6ZX, Kings Mt. Eme',
            facts=[
                Messaging(False),
                Timestamp(_dummy_receive_datetime.replace(day=16, hour=2, minute=57, second=0, microsecond=0)),
                Position((37 + 26.79 / 60), -(122 + 20.18 / 60)),
                Symbol(u'\\v'),
            ],
            errors=[],
            comment='077/000/A=001955/N6ZX, Kings Mt. Eme')

    def test_position_with_timestamp_zero_error(self):
        # TODO this message looks to have other stuff we should parse
        self.__check_parsed(
            'N6TVE-11>APTW01,TCPIP*,qAC,T2BWI:@000000z3429.95N/11949.07W_087/004g006t068r000p000XTvEJeeWx',
            facts=[
                Messaging(True),
                Position((34 + 29.95 / 60), -(119 + 49.07 / 60)),
                Symbol(u'/_'),
            ],
            errors=['DHM/HMS timestamp invalid: day is out of range for month'],
            comment='087/004g006t068r000p000XTvEJeeWx')
        

    def test_mic_e(self):
        self.__check_parsed(
            'KQ1N-7>SV2RYV,W6BXN-3*,N6ZX-3*,WIDE2*:`00krA4[/`"5U}_',
            facts=[
                # TODO: Check pos and vel against results from some other parser, in more cases
                Position(latitude=36.382666666666665, longitude=-120.3465),
                Velocity(speed_knots=63, course_degrees=31),
                Symbol('/['),
            ],
            errors=[],
            # TODO: The _ is actually a manufacturer/version code or something but we don't support that yet
            comment='_')
    
    def test_status(self):
        self.__check_parsed(
            'WE6Z>APT314,K6FGA-1*,N6ZX-3*,WIDE2*:>147.195',
            facts=[Status('147.195')],
            errors=[],
            comment='')
    
    def test_object_report(self):
        # TODO: test case w/ compressed position
        # TODO: test case w/ data-in-comment-field
        self.__check_parsed(
            'KE6KYI>APU25N,K6TUO-3*,N6ZX-3*,WIDE2*:;FD TCARES*061508z3803.13N/12017.88WrTCARES Field Day Site June 28-29',
            facts=[ObjectItemReport(
                object=True,
                name='FD TCARES',
                live=True,
                facts=[
                    Timestamp(_dummy_receive_datetime.replace(day=6, hour=15, minute=8, second=0, microsecond=0)),
                    Position(latitude=38.052166666666665, longitude=-120.298),
                    Symbol('/r'),
                ])],
            errors=[],
            comment='TCARES Field Day Site June 28-29')
    
    def test_telemetry(self):
        # TODO: binary is missing
        self.__check_parsed(
            'N8QH-8>APOT30,N8QH-9*,N6ZX-3*,WIDE2*:T#242,132,037,066,041,048,00000000',
            facts=[
                Telemetry(channel=1, value=132),
                Telemetry(channel=2, value=37),
                Telemetry(channel=3, value=66),
                Telemetry(channel=4, value=41),
                Telemetry(channel=5, value=48)],
            errors=[],
            comment='')
    
    def test_telemetry_format_error(self):
        self.__check_parsed(
            'FOO>BAR:T#001,002',
            facts=[],
            errors=["Telemetry did not parse: u'T#001,002'"],
            comment='')
    
    def test_telemetry_value_format_error(self):
        self.__check_parsed(
            'FOO>BAR:T#000,1,2,bang,4,5,00000000',
            facts=[Telemetry(channel=1, value=1),
            Telemetry(channel=2, value=2),
            Telemetry(channel=4, value=4),
            Telemetry(channel=5, value=5)],
            errors=["Telemetry channel 3 did not parse: u'bang'"],
            comment='')


class TestAPRSInformation(unittest.TestCase):
    def setUp(self):
        self.i = APRSInformation()
    
    def test_new_station(self):
        self.assertEqual([], self.i.state().keys())
        self.i.receive(parse_tnc2(
            'N6WKZ-3>APU25N,WB6TMS-3*,N6ZX-3*,WIDE2*:=3746.42N112226.00W# {UIV32N}',
            _dummy_receive_time))
        self.assertEqual(['N6WKZ-3'], self.i.state().keys())

    def test_object_item_report(self):
        self.i.receive(parse_tnc2(
            'KE6AFE-2>APU25N,WR6ABD*,NCA1:;TFCSCRUZ *160323z3655.94N\12200.92W?70 In 10 Minutes',
            _dummy_receive_time))
        self.assertEqual(['KE6AFE-2', 'TFCSCRUZ '], self.i.state().keys())
        # TODO test value

    def test_drop_old(self):
        self.i.receive(parse_tnc2('FOO>RX:>', _dummy_receive_time))
        self.assertEqual(['FOO'], self.i.state().keys())
        self.i.receive(parse_tnc2('BAR>RX:>', _dummy_receive_time + 599.9))
        self.assertEqual({'BAR', 'FOO'}, set(self.i.state().keys()))
        self.i.receive(parse_tnc2('BAR>RX:>', _dummy_receive_time + 600))
        self.assertEqual(['BAR'], self.i.state().keys())


class TestAPRSStation(unittest.TestCase):
    def setUp(self):
        self.s = APRSStation('TEST')
        
    def __message(self, facts):
        return APRSMessage(
            receive_time=_dummy_receive_time,
            source='',
            destination='',
            via='',
            payload='',
            facts=facts,
            errors=[],
            comment='')
    
    def test_address(self):
        self.assertEqual(self.s.get_address(), 'TEST')
    
    def test_track(self):
        self.assertEqual(empty_track, self.s.get_track())
        self.s.receive(self.__message([
            Position(31, -42)
        ]))
        self.assertEqual(empty_track._replace(
            latitude=TelemetryItem(31, _dummy_receive_time),
            longitude=TelemetryItem(-42, _dummy_receive_time),
        ), self.s.get_track())
        
    def test_symbol(self):
        self.assertEqual(None, self.s.get_symbol())
        self.s.receive(self.__message([
            Symbol('/=')
        ]))
        self.assertEqual('/=', self.s.get_symbol())
        
    def test_status(self):
        self.assertEqual('', self.s.get_status())
        self.s.receive(self.__message([
            Status('foo')
        ]))
        self.assertEqual('foo', self.s.get_status())
