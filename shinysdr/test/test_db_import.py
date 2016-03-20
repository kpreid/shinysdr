# Copyright 2016 Kevin Reid <kpreid@switchb.org>
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


from __future__ import absolute_import, division

import StringIO

from twisted.trial import unittest
from zope.interface import implements  # available via Twisted

from shinysdr.db_import import GeoFilter, IImporter, ImporterFilter


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


def run_importer(importer, input_text):
    f = StringIO.StringIO(input_text)
    importer.add_file('-', f, warning_callback=lambda w: None)
    records = []
    importer.create_database(records.append, warning_callback=lambda w: None)
    return records


class StubImporter(object):
    implements(IImporter)
    
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
