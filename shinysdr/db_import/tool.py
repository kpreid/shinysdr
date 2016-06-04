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

import argparse
import sys

from twisted.plugin import getPlugins

from shinysdr.db import normalize_record, write_csv_file
from shinysdr.db_import import GeoFilter, IImporter, _IImporterDef
from shinysdr import plugins


def _general_warning_callback(msg):
    print >>sys.stderr, msg


def _add_file_wrapper(importer, filename, open_file):
    def warning_callback(msg):
        print >>sys.stderr, u'%s:%s' % (filename, msg)
    
    importer.add_file(filename, open_file, warning_callback)


_importer_defs = {p.name: p for p in getPlugins(_IImporterDef, plugins) if p.available}


def _importer_list_msg():
    out = 'Known importers:\n'
    for name, idef in _importer_defs.iteritems():
        out += '  %s: %s\n' % (name, idef.description)
    return out


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog=argv[0],
        epilog=_importer_list_msg(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('importer_name', metavar='IMPORTER',
        help='importer to use')
    parser.add_argument('filenames', metavar='FILE', nargs='*',
        help='files to import (standard input if omitted)')
    parser.add_argument('--near', metavar='LAT,LON,RADIUS',
        help='include only records within RADIUS (in meters) of LAT,LON')
    return parser.parse_args(args=argv[1:])


def import_main():
    # NOTE: This function is referenced from setup.py entry_points
    """Entry point for the offline import command."""
    options = _parse_args(sys.argv)
    importer_name = options.importer_name
    filenames = options.filenames
    
    if importer_name not in _importer_defs:
        print >>sys.stderr, 'Unknown importer: %r.\n%s' % (importer_name, _importer_list_msg())
        sys.exit(1)
    importer = IImporter(_importer_defs[importer_name].importer_class())
    
    if options.near:
        geo_filter_parts = [int(s.strip()) for s in options.near.split(',')]
        importer = GeoFilter(
            importer=importer,
            latitude=geo_filter_parts[0],
            longitude=geo_filter_parts[2],
            radius=geo_filter_parts[2])
    
    if filenames:
        for filename in filenames:
            with open(filename, 'r') as open_file:
                _add_file_wrapper(importer, filename, open_file)
    else:
        _add_file_wrapper(importer, "-", sys.stdin)
    
    records = []
    def add_record(record):
        records.append(normalize_record(record))
    
    importer.create_database(
        add_record,
        warning_callback=_general_warning_callback)
    write_csv_file(sys.stdout, records)


if __name__ == '__main__':
    import_main()
