# Copyright 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

import StringIO
import os
import os.path

from twisted.trial import unittest
from zope.interface import implementer  # available via Twisted

from shinysdr.db_import import GeoFilter, IImporter, ImporterFilter
from shinysdr.db_import.tool import import_main
from shinysdr.test.testutil import Files


class TestImporterFilter(unittest.TestCase):
    def test_1(self):
        filt = ImporterFilterSpecimen(StubImporter(
            mkrecords(['foo', 'bar', 'omit'])))
        self.assertEqual(
            [r[u'label'] for r in run_importer(filt, '')],
            ['foo filtered', 'bar filtered'])
    
    def test_geo_filter_exclude_no(self):
        filt = GeoFilter(
            StubImporter([
                {'label': 'none', 'location': None},
                {'label': 'center', 'location': [30, 60]},
                {'label': 'offcenter', 'location': [30.2, 60.2]},
                {'label': 'justoutside', 'location': [30.6, 59.4]},
                {'label': 'distant', 'location': [60, 60]},
            ]),
            latitude=30,
            longitude=60,
            radius=50e3,
            include_no_location=False)
        self.assertEqual(
            [r[u'label'] for r in run_importer(filt, '')],
            ['center', 'offcenter'])
    
    def test_geo_filter_include_no(self):
        filt = GeoFilter(
            StubImporter([
                {'label': 'none', 'location': None},
                {'label': 'center', 'location': [30, 60]},
            ]),
            latitude=30,
            longitude=60,
            radius=10,
            include_no_location=True)
        self.assertEqual(
            [r[u'label'] for r in run_importer(filt, '')],
            ['none', 'center'])


class ImporterFilterSpecimen(ImporterFilter):
    def _record_filter(self, record):
        if record[u'label'] == 'omit':
            return None
        else:
            new_record = dict(record)
            new_record[u'label'] += ' filtered'
            return new_record


class TestImportTool(unittest.TestCase):
    def setUp(self):
        self.__files = Files({})
        self.__in_file = os.path.join(self.__files.dir, 'in')
    
    def tearDown(self):
        self.__files.close()
    
    def test_smoke(self):
        self.__files.create({'in': ''})
        out_file_obj = StringIO.StringIO()
        import_main(argv=['shinysdr-import', 'uls', self.__in_file], out=out_file_obj)
        self.assertEquals('Location,Mode,Frequency,Name,Latitude,Longitude,Comment\r\n', out_file_obj.getvalue())


def run_importer(importer, input_text):
    f = StringIO.StringIO(input_text)
    importer.add_file('-', f, warning_callback=lambda w: None)
    records = []
    importer.create_database(records.append, warning_callback=lambda w: None)
    return records


@implementer(IImporter)
class StubImporter(object):
    def __init__(self, records):
        self.__records = records
    
    def add_file(self, pathname, open_file, warning_callback):
        pass
    
    def create_database(self, callback, warning_callback):
        for record in self.__records:
            callback(record)


def mkrecords(iterable):
    for i, item in enumerate(iterable):
        if isinstance(item, dict):
            record = dict(item)
        else:
            record = {u'label': unicode(item)}
        if u'lowerFreq' not in record or u'upperFreq' not in record:
            record[u'lowerFreq'] = record[u'upperFreq'] = i
        yield record
