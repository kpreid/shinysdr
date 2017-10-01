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

import cgi
import contextlib
import csv
import json
import os
import os.path
import urllib

from twisted.python import log
from twisted.web import http
from twisted.web import resource

from shinysdr.types import EnumT, to_value_type


_NO_DEFAULT = object()
_json_columns = {
    u'type': (EnumT({'channel': 'channel', 'band': 'band'}), 'channel'),
    u'lowerFreq': (to_value_type(float), _NO_DEFAULT),
    u'upperFreq': (to_value_type(float), _NO_DEFAULT),
    u'mode': (to_value_type(unicode), u''),
    u'label': (to_value_type(unicode), u''),
    u'notes': (to_value_type(unicode), u''),
    u'location': (lambda x: x, None),  # TODO missing constraint
}

_LOWEST_RKEY = 1


class DatabaseModel(object):
    __dirty = False
    
    def __init__(self, reactor, records, pathname=None, writable=False):
        assert isinstance(records, dict)
        # TODO: don't expose records/writable directly
        self.__reactor = reactor
        self.records = records
        self.__pathname = pathname
        self.writable = writable
    
    def dirty(self):
        """
        Notify that a record has been changed and the database should be written to disk.
        """
        if self.__can_write() and not self.__dirty:
            self.__dirty = True
            self.__reactor.callLater(0.5, self.__write)
    
    def __write(self):
        if self.__can_write() and self.__dirty:
            log.msg('Writing database %s' % (self.__pathname,))
            self.__dirty = False
            with _atomic_open_for_write(self.__pathname, 'wb') as csvfile:
                _write_csv_file(csvfile, self.records)
    
    def __can_write(self):
        return self.__pathname is not None


# TODO: To pair with this, create open-for-read of atomic files which
# * uses the ~ file if the current file is not available
# * fails out early if there is unexpectedly a .new file
@contextlib.contextmanager
def _atomic_open_for_write(name, mode):
    oldname = name + '~'
    newname = name + '.new'
    if os.path.exists(newname):
        raise Exception('Unexpected new file: %s' + oldname)
        # os.remove(newname)
    if os.path.exists(oldname):
        if not os.path.exists(name):
            raise Exception('Unexpected old file only: %s' % oldname)
        os.remove(oldname)  # Windows compatibility
        os.rename(name, oldname)
    ok = False
    try:
        yield open(newname, mode)
        ok = True
    finally:
        if ok:
            os.rename(newname, name)
        else:
            log.msg('Not installing new-version due to error: %s' % newname)


def database_from_csv(reactor, pathname, writable):
    if os.path.exists(pathname):
        with open(pathname, 'rb') as csvfile:
            records, diagnostics = _parse_csv_file(csvfile)
    else:
        if not writable:
            raise Exception('Non-writable specified DB does not exist: %s' % pathname)
        records, diagnostics = [], []
    database = DatabaseModel(reactor, records, pathname=pathname, writable=writable)
    return database, diagnostics


def databases_from_directory(reactor, pathname):
    dbs = {}
    try:
        filenames = os.listdir(pathname)
    except OSError as e:
        return dbs, [(pathname, Warning('Error opening database directory: %r' % (e,)))]
    all_diagnostics = []
    for name in filenames:
        if name.endswith('.csv'):
            database, diagnostics = database_from_csv(reactor, os.path.join(pathname, name), writable=False)
            dbs[name] = database
            for d in diagnostics:
                all_diagnostics.append((name, d))
    return dbs, all_diagnostics


class DatabasesResource(resource.Resource):
    isLeaf = False
    
    def __init__(self, databases):
        resource.Resource.__init__(self)
        self.putChild('', _DbsIndexResource(self))
        self.names = []
        for (name, database) in databases.iteritems():
            self.putChild(name, DatabaseResource(database))
            self.names.append(name)
        self.names.sort()  # TODO reconsider case/locale


class _DbsIndexResource(resource.Resource):
    isLeaf = True
    
    def __init__(self, dbs_resource):
        resource.Resource.__init__(self)
        self.dbs_resource = dbs_resource
    
    def render_GET(self, request):
        request.setHeader('Content-Type', 'text/html')
        request.write(b'<html><title>Databases</title><ul>\n')
        for name in self.dbs_resource.names:
            request.write(b'<li><a href="%s/">%s</a>\n' % (str(cgi.escape(urllib.quote(name, ''))), str(cgi.escape(name))))
        request.write(b'</ul>\n')
        return b''


class DatabaseResource(resource.Resource):
    isLeaf = False
    
    def __init__(self, database):
        resource.Resource.__init__(self)
        
        def instantiate(rkey):
            self.putChild(str(rkey), _RecordResource(database, database.records[rkey]))
        
        self.putChild('', _DbIndexResource(database, instantiate))
        for rkey in database.records:
            instantiate(rkey)


class _DbIndexResource(resource.Resource):
    isLeaf = True
    
    def __init__(self, db, instantiate):
        resource.Resource.__init__(self)
        self.__database = db
        self.__instantiate = instantiate
    
    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'application/json')
        return json.dumps({
            u'records': self.__database.records,
            u'writable': self.__database.writable
        })
    
    def render_POST(self, request):
        desc = json.load(request.content)
        if not self.__database.writable:
            request.setResponseCode(http.FORBIDDEN)
            request.setHeader(b'Content-Type', b'text/plain')
            return b'This database is not writable.'
        record = normalize_record(desc['new'])

        dbdict = self.__database.records
        rkey = _LOWEST_RKEY
        while rkey in dbdict:
            rkey += 1
        dbdict[rkey] = record
        self.__database.dirty()  # TODO: There is no test that this is done.
        self.__instantiate(rkey)
        url = request.prePathURL() + str(rkey)
        request.setResponseCode(http.CREATED)
        request.setHeader(b'Content-Type', b'text/plain')
        request.setHeader(b'Location', url)
        return url


class _RecordResource(resource.Resource):
    isLeaf = True
    
    def __init__(self, database, record):
        resource.Resource.__init__(self)
        self.__database = database
        self.__record = record
    
    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'application/json')
        return json.dumps(self.__record)
    
    def render_POST(self, request):
        assert request.getHeader(b'Content-Type') == b'application/json'
        if not self.__database.writable:
            request.setResponseCode(http.FORBIDDEN)
            request.setHeader(b'Content-Type', b'text/plain')
            return 'The database containing this record is not writable.'
        patch = json.load(request.content)
        old = normalize_record(patch['old'])
        new = normalize_record(patch['new'])
        if old == self.__record:
            self.__record.clear()
            self.__record.update(new)
            self.__database.dirty()
            request.setResponseCode(http.NO_CONTENT)
            return b''
        else:
            request.setResponseCode(http.CONFLICT)
            request.setHeader(b'Content-Type', b'text/plain')
            return b'Old values did not match: %r vs %r' % (old, self.__record)


def _parse_csv_file(csvfile):
    records_assigned = {}
    records_unassigned = []
    free_rkey = _LOWEST_RKEY
    diagnostics = []
    reader = csv.DictReader(csvfile)
    for strcsvrec in reader:
        # csv does not deal in unicode itself
        csvrec = {}
        for k, v in strcsvrec.iteritems():
            if k is None:
                diagnostics.append(Warning(reader.line_num, 'Record contains extra columns; data discarded.'))
                continue
            if v is None:
                # too few columns, consider harmless and OK
                continue
            csvrec[unicode(k, 'utf-8')] = unicode(v, 'utf-8')
        if 'Frequency' not in csvrec:
            diagnostics.append(Warning(reader.line_num, 'Record contains no value for Frequency column; line discarded.'))
            continue
        record = {
            u'mode': csvrec.get('Mode', ''),
            u'label': csvrec.get('Name', ''),
            u'notes': csvrec.get('Comment', ''),
        }
        # TODO remove this conflation and add proper 2.5kHz support
        if record['mode'] == u'FM':
            record['mode'] = u'NFM'
        freq_str = csvrec['Frequency']
        try:
            if '-' in freq_str:
                # extension of format: bands
                record[u'type'] = u'band'
                record[u'lowerFreq'], record[u'upperFreq'] = map(_parse_freq, freq_str.split('-'))
            else:
                record[u'type'] = u'channel'
                record[u'lowerFreq'] = record[u'upperFreq'] = _parse_freq(freq_str)
        except ValueError:
            diagnostics.append(Warning(reader.line_num, 'Frequency value is not a decimal number or range; line discarded.'))
            continue
        # extension of format: location
        if csvrec.get('Latitude', '') != '' and csvrec.get('Longitude', '') != '':
            record[u'location'] = [float(csvrec['Latitude']), float(csvrec['Longitude'])]
        else:
            record[u'location'] = None
        # Give the record a key corresponding to Location if possible
        # TODO: error messages for bad Location
        rkey_str = csvrec.get('Location', '')
        try:
            rkey = int(rkey_str)
            if rkey < _LOWEST_RKEY: rkey = None
        except ValueError:
            rkey = None
        if rkey is not None:
            # TODO conflicts
            records_assigned[rkey] = record
        else:
            records_unassigned.append(record)
    for record in records_unassigned:
        while free_rkey in records_assigned:
            free_rkey += 1
        records_assigned[free_rkey] = record
        free_rkey += 1
    return records_assigned, diagnostics


def _parse_freq(freq_str):
    return 1e6 * float(freq_str)


def _format_freq(freq):
    return unicode(freq / 1e6)


def normalize_record(record):
    """Normalize and type-check a record dict.
    
    There is one 'syntax extension' beyond normalizing: the key 'freq' may be used in place of specifying both 'lowerFreq' and 'upperFreq'."""
    out = {}
    if u'freq' in record:
        if u'lowerFreq' in record or u'upperFreq' in record:
            raise ValueError('"freq" is mutually exclusive with lower/upper')
        record = dict(record)
        record[u'lowerFreq'] = record[u'upperFreq'] = float(record[u'freq'])
        del record[u'freq']
    for k in record:
        if k not in _json_columns:
            raise ValueError('record contains unknown key %r' % (k,))
    for k, (column_type, default) in _json_columns.iteritems():
        value = record.get(k, default)
        if value is _NO_DEFAULT:
            raise ValueError('record is missing key %r' % (k,))
        out[k] = column_type(value)
    return out


def write_csv_file(csvfile, records):
    """Write a database CSV file.
    
    csvfile: A file-like object.
    records: A list of records in the ShinySDR JSON format (TODO document that).
    """
    # This function exists to be the explicitly public version
    # TODO: validate input
    _write_csv_file(csvfile, records)


def _write_csv_file(csvfile, records):
    writer = csv.DictWriter(csvfile, [
        u'Location',
        u'Mode',
        u'Frequency',
        u'Name',
        u'Latitude',
        u'Longitude',
        u'Comment',
    ])
    writer.writeheader()
    for rkey, record in records.iteritems():
        csvrecord = {u'Location': str(rkey)}
        lf = uf = None
        for key, value in record.iteritems():
            if key == u'type':
                pass
            elif key == u'mode':
                csvrecord[u'Mode'] = value
            elif key == u'lowerFreq':
                lf = value
            elif key == u'upperFreq':
                uf = value
            elif key == u'location':
                if value is None:
                    csvrecord[u'Latitude'] = ''
                    csvrecord[u'Longitude'] = ''
                else:
                    csvrecord[u'Latitude'] = value[0]
                    csvrecord[u'Longitude'] = value[1]
            elif key == u'label':
                csvrecord[u'Name'] = value
            elif key == u'notes':
                csvrecord[u'Comment'] = value
            else:
                raise ValueError(u'Unhandled field in db record: %s' % key)
        if lf == uf:
            csvrecord[u'Frequency'] = _format_freq(lf)
        else:
            csvrecord[u'Frequency'] = _format_freq(lf) + '-' + _format_freq(uf)
        for key in csvrecord:
            csvrecord[key] = unicode(csvrecord[key]).encode('utf-8')
        writer.writerow(csvrecord)
