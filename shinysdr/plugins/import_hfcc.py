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

'''
Converts shortwave broadcasting schedules into ShinySDR databases.

To obtain the input data, and for documentation on the format, see:
http://www.hfcc.org/data/guidepost.phtml
'''

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple
import os.path
import re

from zope.interface import implementer  # available via Twisted

from shinysdr.db_import import IImporter, ImporterDef


_Col = namedtuple('Col', [
    'name',
    'start',  # 1-indexed inclusive column number
    'stop',  # 1-indexed inclusive (or 0-indexed exclusive) column number
    'converter',
])


_TableValuePlaceholder = namedtuple('TableValuePlaceholder', ['text', 'table'])


def _Freq(text):
    if text.strip() == '':
        return None
    number = int(text)
    if number < 10:
        return number * 1e6  # "Band in MHz"
    else:
        return number * 1e3  # "Frequency in kHz"


def _Days(text):
    days = []
    for c in text:
        if c != ' ':
            days.append(['XXX', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][int(c)])
    return ' '.join(days)


def _detabulate(table_id):
    def converter(text):
        return _TableValuePlaceholder(text.strip(), table_id)
    
    return converter


def _UTC(text):
    return text[:2] + ':' + text[2:]


def _Date(text):
    # I could say "before 2100, make this relative to the current century", but I will be surprised if the file format remains unchanged that long.
    return '20' + text[4:] + '-' + text[2:4] + '-' + text[:2]


def _Coordinate(text):
    # This is not simply a fixed column match because as of schedule A16, site.txt has an irregular entry "46W380" which would regularly be "046W38". The interpretation here (decimal minutes) is a reasonable guess which makes no difference for the data.
    match = re.match(r'^\s*(\d+)([NSEW])(\d{2})(\d*)\s*$', text)
    if not match:
        raise ValueError('could not parse coordinate: %r' % (text,))
    return (
        (-1 if match.group(2) in 'WS' else 1) *
        (float(match.group(1)) + float(match.group(3) + '.' + match.group(4)) / 60))


if 1 == 1:  # dummy block for pylint
    # pylint: disable=bad-whitespace
    _main_columns = [
        # http://www.itu.int/en/ITU-R/terrestrial/broadcast/HFBC/Documents/File%20format%20for%20submission%20of%20HFBC%20requirements-E.pdf
        _Col(u'freq',         1,    5,  _Freq),
        _Col(u'time_start',   7,   10, _UTC),
        _Col(u'time_stop',    12,  15, _UTC),
        _Col(u'area',         17,  46, unicode),
        _Col(u'location',     48,  50, _detabulate('site')),
        _Col(u'power',        52,  55, float),
        _Col(u'azimuth',      57,  63, float),
        _Col(u'slew',         65,  67, float),
        _Col(u'antenna',      69,  71, _detabulate('antenna')),
        _Col(u'days',         73,  79, _Days),
        _Col(u'date_start',   81,  86, _Date),
        _Col(u'date_stop',    88,  93, _Date),
        _Col(u'mode',         95,  95, {'D': 'AM', 'T': 'LSB', 'N': 'DRM'}.__getitem__),
        _Col(u'antenna_freq', 97, 101, _Freq),
        _Col(u'language',    103, 112, _detabulate('language')),
        _Col(u'admin',       114, 116, _detabulate('admin')),
        _Col(u'broadcaster', 118, 120, _detabulate('broadcas')),
        _Col(u'fmorg',       122, 124, _detabulate('fmorg')),
        _Col(u'ident',       126, 130, int),
        _Col(u'old',         132, 132, unicode),
        _Col(u'alt1',        134, 138, _Freq),
        _Col(u'alt2',        140, 144, _Freq),
        _Col(u'alt3',        146, 150, _Freq),
        _Col(u'notes',       152, 158, unicode),
    ]


_table_defs = {
    # Each table definition here MUST have a 'key' column and 'name' column
    'admin': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 54, unicode),
        _Col(u'name_fr', 56, 105, unicode),
        _Col(u'name_es', 107, 156, unicode),
    ],
    'antenna': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 53, unicode),
        _Col(u'remarks', 55, 75, unicode),
    ],
    'broadcas': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 9999, unicode),
    ],
    'fmorg': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 54, unicode),
        _Col(u'contact', 56, 76, unicode),
        _Col(u'telephone', 77, 90, unicode),
        _Col(u'fax', 91, 105, unicode),
        _Col(u'email', 105, 146, unicode),
        _Col(u'notes', 146, 158, unicode),
    ],
    'language': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 104, unicode),
    ],
    'site': [
        _Col(u'key', 1, 3, unicode),
        _Col(u'name', 4, 34, unicode),
        _Col(u'admin', 36, 38, _detabulate('admin')),
        _Col(u'lat', 40, 44, _Coordinate),
        _Col(u'lon', 46, 51, _Coordinate),
    ],
}


def parse_columnar(line, line_number, column_defs, warning_callback):
    out = {}
    for col in column_defs:
        cell_text = line[col.start - 1:col.stop].strip()
        try:
            converted_value = col.converter(cell_text)
        except (ValueError, TypeError) as e:
            warning_callback(u'%s: field %s: %s' % (line_number, col.name, e))
        out[col.name] = converted_value
    return out


@implementer(IImporter)
class HFCCImporter(object):
    def __init__(self):
        self.__records = []
        self.__tables = {}
    
    def add_file(self, pathname, open_file, warning_callback):
        """Implements IImporter."""
        nameparts = os.path.split(pathname.lower())[-1].split('.')
        if len(nameparts) == 2 and nameparts[0].endswith('all00') and nameparts[1] == 'txt':
            for znum, line in enumerate(open_file):
                line = line.decode('iso-8859-1')
                line_number = znum + 1
                if line.startswith(';'):
                    # comment
                    continue
                self.__records.append(parse_columnar(line, line_number, _main_columns, warning_callback))
        elif len(nameparts) == 2 and nameparts[0] in _table_defs and nameparts[1] == 'txt':
            table_name = nameparts[0]
            table = {}
            self.__tables[table_name] = table
            for znum, line in enumerate(open_file):
                line = line.decode('iso-8859-1')
                line_number = znum + 1
                if line.startswith(';'):
                    # comment
                    continue
                table_record = parse_columnar(line, line_number, _table_defs[table_name], warning_callback)
                table[table_record[u'key']] = table_record
        else:
            warning_callback('file name %r is not a known type' % ('.'.join(nameparts),))
    
    def create_database(self, callback, warning_callback):
        """Implements IImporter."""
        for partial_record in self.__records:
            record = {k: self.__finish_cell(v) for k, v in partial_record.iteritems()}
            if record['freq'] is None:
                continue
            notes = '\n'.join('%s: %s' % (k, record[k]) for k in sorted(record))
            site_record = self.__tables.get(u'site', {}).get(partial_record[u'location'].text)
            if site_record is not None:
                location = [site_record[u'lat'], site_record[u'lon']]
            else:
                location = None
            callback({
                'type': 'channel',  # TODO should be 'station' but that type isn't defined yet
                'lowerFreq': record['freq'],
                'upperFreq': record['freq'],
                'mode': record['mode'],
                'label': '%s (%s)' % (record['broadcaster'], record['admin']),
                'notes': notes,
                'location': location,
            })
    
    def __finish_cell(self, value):
        if isinstance(value, _TableValuePlaceholder):
            fallback = {u'name': '[' + value.text + ']'}
            table_entry = self.__tables.get(value.table, {}).get(value.text, fallback)
            return table_entry[u'name']
        else:
            return value


_plugin = ImporterDef(
    name='hfcc',
    description='HFCC/ITU shortwave broadcast schedule files. The reference tables as well as the main schedule file must be provided.',
    importer_class=HFCCImporter)
