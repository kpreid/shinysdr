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
Converts FCC ULS databases into ShinySDR databases.

Reference material:
  DB downloads: http://wireless.fcc.gov/uls/index.htm?job=transaction&page=weekly
  Field definitions: http://wireless.fcc.gov/uls/documentation/pa_ddef42.pdf
'''


from __future__ import absolute_import, division, print_function, unicode_literals

from collections import defaultdict

import six

from zope.interface import implementer  # available via Twisted

from shinysdr.db_import import IImporter, ImporterDef


@implementer(IImporter)
class ULSImporter(object):
    def __init__(self):
        # keys are Unique System Identifiers, values are ...?
        self.__records = defaultdict(lambda: defaultdict(list))
    
    def add_file(self, pathname, open_file, warning_callback):
        """Implements IImporter."""
        i = 0
        for line in open_file:
            i = i + 1
            self.__put(line, i, warning_callback)
    
    def __put(self, line, line_number, warning_callback):
        line = line.strip()
        fields = line.split(b'|')
        # TODO: Instead of working line-by-line, expect a certain number of columns and ignore newlines in the wrong place
        
        if len(fields) < 2:
            warning_callback('bad line: %r' % (fields,))
            return
    
        # field definitions: http://wireless.fcc.gov/uls/documentation/pa_ddef42.pdf
        record_type = fields[0]
        system_id = fields[1]
        self.__records[system_id][record_type].append(fields)
    
    def create_database(self, callback, warning_callback):
        """Implements IImporter."""
        # pylint: disable=unused-variable
        
        # TODO: Process more record types. Old ranking of interestingness, possibly overspecialized:
        # 1. HD F2 LO EM CO
        # 2. AC AN L3 F3 F4
        # 3. 'AD', 'EN', 'A2', 'RE', 'MW', 'CG', 'FA', 'SH', 'SR', 'SE', 'SV', 'LM', 'MI', 'BC', 'FC', 'HS', 'TA', 'BD', 'AS', 'CF', 'IA', 'SC', 'SF', 'BO', 'CP', 'SI', 'UA', 'AC', 'AM', 'VC', 'MK', 'TL', 'MP', 'MC', 'MF', 'LS', 'L2', 'LF', 'OP', 'BL', 'AN', 'RC', 'RZ', 'FT', 'IR', 'CS', 'FS', 'FF', 'BF', 'RA', 'PC', 'PA', 'SG', 'AT', 'AH', 'LH', 'BE', 'MH', 'ME', 'LA', 'CD', 'RI', 'LD', 'LL', 'LC', 'L3', 'L4', 'O2', 'L5', 'L6', 'A3', 'F3', 'F4', 'F5', 'F6', 'P2', 'TP'
        for system_id, rtypes in six.iteritems(self.__records):
            latitude = None
            longitude = None
            address_1 = ''
            address_full = ''
            for loc_record in rtypes['LO']:
                if latitude is not None:
                    warning_callback('Duplicate location record! %s' % (system_id,))
                latitude = parse_dms(*loc_record[19:23])
                longitude = parse_dms(*loc_record[23:27])
                if latitude is None or longitude is None:
                    warning_callback('Unparseable location record! %s' % (system_id,))
                address_1 = loc_record[11]
                address_full = loc_record[11:15]
            
            for freq_record in rtypes['FR']:
                # print(freq_record, file=sys.stderr)
                call_sign, freq_action_performed, location_number, antenna_number, class_station_code, op_altitude_code, freq_assigned, freq_upper_band, freq_carrier = freq_record[4:13]
                freq_assigned = float(freq_assigned)
                callback({
                    'type': 'channel',  # TODO should be 'station' but that type isn't defined yet
                    'lowerFreq': freq_assigned,
                    'upperFreq': freq_assigned,
                    'mode': 'AM',
                    'label': call_sign + ' ' + address_1,
                    'notes': '\n'.join(address_full),
                    'location': [latitude, longitude],
                })


def parse_dms(degrees, minutes, seconds, direction):
    try:
        return (-1 if direction in 'SW' else 1) * (float(degrees) + float(minutes) / 60.0 + float(seconds) / 3600.0)
    except ValueError:
        return None


_plugin = ImporterDef(
    name='uls',
    description='FCC ULS pipe-delimited database files.',
    importer_class=ULSImporter)
