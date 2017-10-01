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

from __future__ import absolute_import, division, unicode_literals

import json
import os
import os.path
import shutil
import StringIO
import tempfile
import textwrap

from twisted.trial import unittest
from twisted.internet import reactor
from twisted.web import http
from twisted.web import server

from shinysdr.i import db
from shinysdr.test import testutil


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
        read_records, diagnostics = db._parse_csv_file(StringIO.StringIO(s))
        self.__assertDiag(diagnostics, expect_diagnostics)
        self.assertEqual(expect_records, read_records)
    
    def __roundtrip(self, records, expect_diagnostics):
        file_obj = StringIO.StringIO()
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
        self.__temp_dir = tempfile.mkdtemp(prefix='shinysdr_test_db_tmp')
    
    def tearDown(self):
        shutil.rmtree(self.__temp_dir)
    
    # TODO: more testing
    def test_1(self):
        with open(os.path.join(self.__temp_dir, 'a.csv'), 'w') as f:
            f.write(textwrap.dedent('''\
                Name,Frequency
                a,1
            '''))
        with open(os.path.join(self.__temp_dir, 'not-a-csv'), 'w') as f:
            pass
        dbs, diagnostics = db.databases_from_directory(reactor, self.__temp_dir)
        self.assertEqual([], diagnostics)
        self.assertEqual(['a.csv'], dbs.keys())

    def test_no_directory(self):
        path = self.__temp_dir + '_does_not_exist'
        dbs, diagnostics = db.databases_from_directory(reactor, path)
        self.assertEqual([], dbs.keys())
        self.assertEqual(1, len(diagnostics))
        self.assertEqual(path, diagnostics[0][0])
        self.assertIn('Error opening database directory', str(diagnostics[0][1]))


class TestDatabasesResource(unittest.TestCase):
    def setUp(self):
        db_model = db.DatabaseModel(reactor, {}, writable=True)
        dbs_resource = db.DatabasesResource({'foo&bar': db_model})
        self.port = reactor.listenTCP(0, server.Site(dbs_resource), interface="127.0.0.1")
    
    def tearDown(self):
        return self.port.stopListening()
    
    def __url(self, path):
        return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
    
    def test_index_response(self):
        def callback((response, data)):
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html'])
            self.assertEqual(data, textwrap.dedent('''\
                <html><title>Databases</title><ul>
                <li><a href="foo%26bar/">foo&amp;bar</a>
                </ul>
            '''))
        return testutil.http_get(reactor, self.__url('/')).addCallback(callback)



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
        u'records': {unicode(k): v for k, v in test_records.iteritems()},
        u'writable': True,
    }
    
    def setUp(self):
        # pylint: disable=no-member
        db_model = db.DatabaseModel(reactor, dict(self.test_records), writable=True)
        dbResource = db.DatabaseResource(db_model)
        self.port = reactor.listenTCP(0, server.Site(dbResource), interface="127.0.0.1")
    
    def tearDown(self):
        return self.port.stopListening()
    
    def __url(self, path):
        return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
    
    def test_index_response(self):
        def callback((response, data)):
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
            j = json.loads(data)
            self.assertEqual(j, self.response_json)
        return testutil.http_get(reactor, self.__url('/')).addCallback(callback)

    def test_record_response(self):
        def callback((response, data)):
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
            j = json.loads(data)
            self.assertEqual(j, self.test_records[1])
        return testutil.http_get(reactor, self.__url('/1')).addCallback(callback)

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

        d = testutil.http_post(reactor, self.__url('/' + str(index)), {
            'old': self.response_json[u'records'][index],
            'new': new_data
        })

        def proceed((response, data)):
            if response.code >= 300:
                print data
            self.assertEqual(response.code, http.NO_CONTENT)
            
            def check((read_response, read_data)):
                j = json.loads(read_data)
                self.assertEqual(j[u'records'], modified)
            
            return testutil.http_get(reactor, self.__url('/')).addCallback(check)
        d.addCallback(proceed)
        return d

    def test_create(self):
        new_record = {
            u'type': u'channel',
            u'lowerFreq': 20e6,
            u'upperFreq': 20e6,
        }

        d = testutil.http_post(reactor, self.__url('/'), {
            'new': new_record
        })

        def proceed((response, data)):
            if response.code >= 300:
                print data
            self.assertEqual(response.code, http.CREATED)
            url = 'ONLYONE'.join(response.headers.getRawHeaders('Location'))
            self.assertEqual(url, self.__url('/3'))  # URL of new entry
            
            def check((read_response, read_data)):
                j = json.loads(read_data)
                self.assertEqual(j[u'records'][u'3'], db.normalize_record(new_record))
            
            return testutil.http_get(reactor, self.__url('/')).addCallback(check)
        d.addCallback(proceed)
        return d
