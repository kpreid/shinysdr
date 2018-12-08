# Copyright 2016 Kevin Reid and the ShinySDR contributors
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

# TODO write module documentation

from __future__ import absolute_import, division, print_function, unicode_literals

from twisted.plugin import IPlugin
from zope.interface import Interface, implementer  # available via Twisted

from shinysdr.i.math import geodesic_distance


__all__ = []  # appended later


class IImporter(Interface):
    """
    An Importer takes files in some format and produces a ShinySDR database.
    """
    
    # TODO: Bundle these args into an "input file" object. Note the regular DB CSV reader could also benefit from the same abstraction!
    def add_file(pathname, open_file, warning_callback):
        """Add a file to the set of files being imported.
        
        This operation may read the file immediately or later.
        
        Arguments:
        pathname: Pathname of the file; may be used to determine its type/role in the imported data.
        open_file: A file-like object providing the contents.
        warning_callback: A function taking an error message.
        """
    
    def create_database(callback, warning_callback):
        """For each record in the imported database consisting of all files added so far, call callback with the unnormalized JSON-structured record."""
        # The "callback with records" format is because the DatabaseModel class isn't really yet suitable for independent use.


__all__.append('Importer')


class _IImporterDef(Interface):
    """
    Object for declaring importer plugins.
    """
    # Only needed to make the plugin system work


@implementer(IPlugin, _IImporterDef)
class ImporterDef(object):
    def __init__(self,
            name,
            description,
            importer_class,
            available=True):
        """
        name: Short string uniquely identifying this importer, to specify on the command line.
        description: String explaining the type of input files this importer accepts.
        importer_class: The class that implements IImporter.
        available: If false, this definition will be ignored.
        """
        self.name = name
        self.description = description
        self.importer_class = importer_class
        self.available = available


__all__.append('ImporterDef')


@implementer(IImporter)
class ImporterFilter(object):
    def __init__(self, importer):
        self._importer = importer
    
    def add_file(self, pathname, open_file, warning_callback):
        self._importer.add_file(pathname, open_file, warning_callback)
    
    def create_database(self, callback, warning_callback):
        def filtering_callback(record):
            filtered = self._record_filter(record)
            if filtered is not None:
                callback(filtered)
        self._importer.create_database(filtering_callback, warning_callback=warning_callback)
    
    def _record_filter(self, record):
        """Subclasses should override this to filter individual records.
        
        It may return None to omit a record."""
        raise NotImplementedError()


__all__.append('ImporterFilter')


class GeoFilter(ImporterFilter):
    """Filter the results of an importer by location.
    """
    def __init__(self, importer, latitude, longitude, radius, include_no_location=False):
        """
        importer: Importer to filter the results of.
        latitude: Center of filter circle in degrees north.
        longitude: Center of filter circle in degrees east.
        radius: Radius of filter circle in meters.
        include_no_location: Whether to include records that have no location.
        """
        super(GeoFilter, self).__init__(importer)
        self.__center = (latitude, longitude)
        self.__radius = radius
        self.__include_no_location = include_no_location
    
    def _record_filter(self, record):
        loc = record.get(u'location')  # TODO this should be [] but we're working with unnormalized records
        if loc:
            if geodesic_distance(loc, self.__center) > self.__radius:
                return None
        else:
            if not self.__include_no_location:
                return None
        return record


__all__.append('GeoFilter')
