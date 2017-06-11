# -*- coding: utf-8 -*-
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

"""
Converts data from the SatNOGS DB into ShinySDR databases.

See:
https://db.satnogs.org/api/
http://docs.satnogs.org/db/api.html
"""

from __future__ import absolute_import, division

import json
import os.path
import textwrap

from zope.interface import implementer  # available via Twisted

from shinysdr.db_import import IImporter, ImporterDef


@implementer(IImporter)
class SatNOGSImporter(object):
    def __init__(self):
        self.__transmitters = []
        self.__satellites = {}
        self.__modes = {}
    
    def add_file(self, pathname, open_file, warning_callback):
        """Implements IImporter."""
        basename = os.path.basename(pathname)
        records = json.load(open_file)
        if not records:
            warning_callback('file %r is empty' % pathname)
            return
        if 'transmitters' in basename:
            loader = self.__load_transmitter
        elif 'satellites' in basename:
            loader = self.__load_satellite
        elif 'modes' in basename:
            loader = self.__load_mode
        else:
            first_record = records[0]
            if u'uplink_low' in first_record:
                loader = self.__load_transmitter
            elif u'names' in first_record and u'image' in first_record:
                loader = self.__load_satellite
            elif set(first_record.keys()) == {u'id', u'name'}:
                loader = self.__load_mode
            else:
                warning_callback('file %r is not a recognized type' % (pathname,))
        for record in records:
            loader(record)
    
    def __load_transmitter(self, record):
        self.__transmitters.append(record)
    
    def __load_satellite(self, record):
        self.__satellites[record[u'norad_cat_id']] = record
    
    def __load_mode(self, record):
        self.__modes[record[u'id']] = record
    
    def __get_mode_string(self, mode_id):
        """Returns the ShinySDR mode string for a SatNOGS mode ID, or the SatNOGS name if no better mapping exits."""
        # TODO: Find out whether SatNOGS mode ID numbers are intended to be stable. If so, we should write our own mapping for our supported modes instead of using the API given names.
        record = self.__modes.get(mode_id)
        if not record:
            return 'satnogs:%s' % (mode_id,)
        mode_name = record[u'name']
        # TODO: After we have mode aliases or support FM/NFM explicitly, fix this mapping
        if mode_name == u'FMN' or mode_name == u'FM':
            mode_name = u'NFM'
        return mode_name
    
    def __get_satellite(self, norad_cat_id):
        record = self.__satellites.get(norad_cat_id)
        if not record:
            record = {u'name': '%s' % (norad_cat_id,), u'names': "", u'image': None}
        return record
    
    def create_database(self, callback, warning_callback):
        """Implements IImporter."""
        for transmitter_record in self.__transmitters:
            satellite_record = self.__get_satellite(transmitter_record[u'norad_cat_id'])
            transmitter_id = transmitter_record[u'uuid']
            mode_id = transmitter_record[u'mode_id']
            label = u'%s — %s' % (satellite_record[u'name'], transmitter_record[u'description'])
            
            # TODO: Once there's a TX frequency/offset field supported, put in the uplink frequencies too.
            lower = transmitter_record[u'downlink_low'] or transmitter_record[u'downlink_high']
            upper = transmitter_record[u'downlink_high'] or transmitter_record[u'downlink_low']
            if not lower:
                warning_callback('no downlink frequencies, skipping: %s %s' % (transmitter_id, label))
                continue
            
            callback({
                'type': 'channel',  # TODO should be 'station' but that type isn't defined yet
                'lowerFreq': lower,
                'upperFreq': upper,
                'mode': u'' if mode_id is None else self.__get_mode_string(mode_id),
                'label': label,
                'notes': self.__describe_transmitter(transmitter_record, satellite_record),
                'location': None,  # TODO: fill in once we have satellite support
            })

    def __describe_transmitter(self, transmitter_record, satellite_record):
        def subst(s):
            return s.format(t=transmitter_record, s=satellite_record)
        result = subst(textwrap.dedent('''\
            Satellite: {s[norad_cat_id]} {s[name]}
            
            Transmitter: {t[description]}
            Alive: {t[alive]}'''))
        if transmitter_record[u'uplink_low'] or transmitter_record[u'uplink_high']:
            result += subst(textwrap.dedent('''\
                
                Uplink: {t[uplink_low]} - {t[uplink_high]}
                Inverting: {t[invert]}'''))
        return result

_plugin = ImporterDef(
    name='satnogs',
    description='SatNOGS DB JSON.',
    importer_class=SatNOGSImporter)
