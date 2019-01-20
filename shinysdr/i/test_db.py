# Copyright 2013, 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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
import textwrap

import six

from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet import reactor
from twisted.web import http

from shinysdr.i import db
from shinysdr.i.network.base import SiteWithDefaultHeaders
from shinysdr.testutil import Files, assert_http_resource_properties, http_get, http_post_json


class TestRecords(unittest.TestCase):
    def test_normalize_complete_result(self):
        self.assertEqual(
            {
                u'type': u'channel',
                u'lowerFreq': 1e6,
                u'upperFreq': 2e6,
                u'mode': u'',
                u'label': u'',
                u'notes': u'',
                u'location': None
            },
            db.normalize_record({
                'lowerFreq': 1e6,
                'upperFreq': 2e6,
            }))
    
    def test_freq_shorthand(self):
        r = db.normalize_record({
            'freq': 1,
        })
        self.assertEqual(r['lowerFreq'], 1)
        self.assertEqual(r['upperFreq'], 1)
        self.assertNotIn('freq', r)
    
    def test_normalize_float(self):
        r = db.normalize_record({
            'lowerFreq': 1,
            'upperFreq': 2
        })
        self.assertIsInstance(r['lowerFreq'], float)
        self.assertIsInstance(r['upperFreq'], float)
    
    def test_bad_field(self):
        def f():
            db.normalize_record({
                'lowerFreq': 1,
                'upperFreq': 1,
                'foo': 'bar',
            })
        
        self.assertRaises(ValueError, f)

    def test_missing_field(self):
        def f():
            db.normalize_record({
                'label': 'foo',
            })
        
        self.assertRaises(ValueError, f)


class TestCSV(unittest.TestCase):
    def __assertDiag(self, diagnostics, expect_diagnostics):
        for i, (line, class_, text) in enumerate(expect_diagnostics):
            if i >= len(diagnostics):
                self.fail('No diagnostic #%i' % i)
            actual = diagnostics[i]
            self.assertEqual((line, text), actual.args)
            self.assertIsInstance(actual, class_)
        self.assertEqual(len(diagnostics), len(expect_diagnostics), 'extra diagnostics')
    
    def __parse(self, s, expect_records, expect_diagnostics):
        read_records, diagnostics = db._parse_csv_file(six.StringIO(s))
        self.__assertDiag(diagnostics, expect_diagnostics)
        self.assertEqual(expect_records, read_records)
    
    def __roundtrip(self, records, expect_diagnostics):
        file_obj = six.StringIO()
        db._write_csv_file(file_obj, records)
        file_obj.seek(0)
        read_records, diagnostics = db._parse_csv_file(file_obj)
        self.assertEqual(records, read_records)
        self.__assertDiag(diagnostics, expect_diagnostics)
    
    def test_no_frequency(self):
        self.__parse(
            'Name,Frequency\na,1\nb',
            {1: db.normalize_record({'freq': 1e6, 'label': 'a'})},
            [(3, Warning, 'Record contains no value for Frequency column; line discarded.')])
    
    def test_frequency_syntax(self):
        self.__parse(
            'Name,Frequency\na,100.000.000',
            {},
            [(2, Warning, 'Frequency value is not a decimal number or range; line discarded.')])
    
    def test_short_line(self):
        self.__parse(
            'Frequency,Name,Comment\n1,a',
            {1: db.normalize_record({'freq': 1e6, 'label': 'a'})},
            [])
    
    def test_long_line(self):
        self.__parse(
            'Frequency,Name\n1,a,boom',
            {1: db.normalize_record({'freq': 1e6, 'label': 'a'})},
            [(2, Warning, 'Record contains extra columns; data discarded.')])

    def test_parse_rkey(self):
        self.__parse(
            'Location,Frequency\n3,100\n1,101',
            {
                3: db.normalize_record({'freq': 100e6}),
                1: db.normalize_record({'freq': 101e6}),
            },
            [])

    def test_roundtrip_channel(self):
        self.__roundtrip(
            {1: {
                u'type': u'channel',
                u'lowerFreq': 1.1e6,
                u'upperFreq': 1.1e6,
                u'mode': u'FOO',
                u'label': u'a',
                u'notes': u'b',
                u'location': None}},
            [])

    def test_roundtrip_band(self):
        self.__roundtrip(
            {1: {
                u'type': u'band',
                u'lowerFreq': 1.1e6,
                u'upperFreq': 1.2e6,
                u'mode': u'FOO',
                u'label': u'a',
                u'notes': u'b',
                u'location': None}},
            [])

    def test_roundtrip_location(self):
        self.__roundtrip(
            {1: {
                u'type': u'band',
                u'lowerFreq': 1.1e6,
                u'upperFreq': 1.2e6,
                u'mode': u'FOO',
                u'label': u'a',
                u'notes': u'b',
                u'location': [10.0, 20.0]}},
            [])

    def test_roundtrip_unicode(self):
        self.__roundtrip(
            {1: {
                u'type': u'channel',
                u'lowerFreq': 1.1e6,
                u'upperFreq': 1.1e6,
                u'mode': u'FOO\u2022',
                u'label': u'a\u2022',
                u'notes': u'b\u2022',
                u'location': [10.0, 20.0]}},
            [])


class TestDirectory(unittest.TestCase):
    def setUp(self):
        self.__files = Files({})
    
    def tearDown(self):
        self.__files.close()
    
    # TODO: more testing
    def test_1(self):
        self.__files.create({
            'a.csv': textwrap.dedent('''\
                 Name,Frequency
                 a,1
            '''),
            'not-a-csv': '',
        })
        dbs, diagnostics = db.databases_from_directory(reactor, self.__files.dir)
        self.assertEqual([], diagnostics)
        self.assertEqual(['a.csv'], list(dbs.keys()))

    def test_no_directory(self):
        path = self.__files.dir + '_does_not_exist'
        dbs, diagnostics = db.databases_from_directory(reactor, path)
        self.assertEqual([], list(dbs.keys()))
        self.assertEqual(1, len(diagnostics))
        self.assertEqual(path, diagnostics[0][0])
        self.assertIn('Error opening database directory', str(diagnostics[0][1]))


class TestDatabasesResource(unittest.TestCase):
    def setUp(self):
        db_model = db.DatabaseModel(reactor, {}, writable=True)
        dbs_resource = db.DatabasesResource({'foo&bar': db_model})
        self.port = reactor.listenTCP(0, SiteWithDefaultHeaders(dbs_resource), interface="127.0.0.1")  # pylint: disable=no-member
    
    def tearDown(self):
        return self.port.stopListening()
    
    def __url(self, path):
        return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
    
    def test_index_common(self):
        return assert_http_resource_properties(self, self.__url('/'))
    
    @defer.inlineCallbacks
    def test_index_response(self):
        response, data = yield http_get(reactor, self.__url('/'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html;charset=utf-8'])
        # TODO: Actually parse/check-that-parses the document
        self.assertSubstring(textwrap.dedent('''\
            <li><a href="foo%26bar/">foo&amp;bar</a></li>
        '''), data)


class TestDatabaseResource(unittest.TestCase):
    test_records = {
        1: db.normalize_record({
            u'type': u'channel',
            u'lowerFreq': 10e6,
            u'upperFreq': 10e6,
            u'mode': u'AM',
            u'label': u'chname',
            u'notes': u'comment',
            u'location': [0, 90],
        }),
        2: db.normalize_record({
            u'type': u'band',
            u'lowerFreq': 10e6,
            u'upperFreq': 20e6,
            u'mode': u'AM',
            u'label': u'bandname',
            u'notes': u'comment',
            u'location': None,
        }),
    }
    response_json = {
        u'records': {six.text_type(k): v for k, v in test_records.items()},
        u'writable': True,
    }
    
    def setUp(self):
        db_model = db.DatabaseModel(reactor, dict(self.test_records), writable=True)
        dbResource = db.DatabaseResource(db_model)
        self.port = reactor.listenTCP(0, SiteWithDefaultHeaders(dbResource), interface="127.0.0.1")  # pylint: disable=no-member
    
    def tearDown(self):
        return self.port.stopListening()
    
    def __url(self, path):
        url = 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
        if six.PY2:
            return url.encode('ascii')
        else:
            return url
    
    def test_index_common(self):
        return assert_http_resource_properties(self, self.__url('/'))
    
    @defer.inlineCallbacks
    def test_index_response(self):
        response, data = yield http_get(reactor, self.__url('/'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        j = json.loads(data)
        self.assertEqual(j, self.response_json)

    def test_record_common(self):
        return assert_http_resource_properties(self, self.__url('/1'))
    
    @defer.inlineCallbacks
    def test_record_response(self):
        response, data = yield http_get(reactor, self.__url('/1'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        j = json.loads(data)
        self.assertEqual(j, self.test_records[1])

    @defer.inlineCallbacks
    def test_update_good(self):
        new_data = {
            u'type': u'channel',
            u'lowerFreq': 20e6,
            u'upperFreq': 20e6,
            u'label': u'modified',
        }
        index = u'1'
        modified = dict(self.response_json[u'records'])
        modified[index] = db.normalize_record(new_data)

        response, data = yield http_post_json(reactor, self.__url('/' + str(index)), {
            'old': self.response_json[u'records'][index],
            'new': new_data
        })
        if response.code >= 300:
            print(data)
        self.assertEqual(response.code, http.NO_CONTENT)
        
        _read_response, read_data = yield http_get(reactor, self.__url('/'))
        j = json.loads(read_data)
        self.assertEqual(j[u'records'], modified)

    @defer.inlineCallbacks
    def test_create(self):
        new_record = {
            u'type': u'channel',
            u'lowerFreq': 20e6,
            u'upperFreq': 20e6,
        }

        response, data = yield http_post_json(reactor, self.__url('/'), {
            'new': new_record
        })
        if response.code >= 300:
            print(data)
        self.assertEqual(response.code, http.CREATED)
        url = 'ONLYONE'.join(response.headers.getRawHeaders('Location'))
        self.assertEqual(url, self.__url('/3'))  # URL of new entry
        
        _read_response, read_data = yield http_get(reactor, self.__url('/'))
        j = json.loads(read_data)
        self.assertEqual(j[u'records'][u'3'], db.normalize_record(new_record))
