# Copyright 2017 Phil Frost <indigo@bitglue.com>
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

"""ShinySDR telemetry for WSPR"""

from __future__ import absolute_import, division, unicode_literals

import time
from collections import namedtuple

from zope.interface import implementer, Interface

from shinysdr.telemetry import (
    ITelemetryMessage, ITelemetryObject, Track, TelemetryItem)
from shinysdr.types import TimestampT
from shinysdr.values import ExportedState, exported_value


MINUTES = 60


@implementer(ITelemetryMessage)
class WSPRSpot(namedtuple('WSPRSpot', [
    'time',
    'snr',
    'dt',
    'frequency',
    'drift',
    'call',
    'grid',
    'txpower',
])):
    def get_object_id(self):
        return 'wsprspot_%s_%s' % (self.call, self.grid)

    def get_object_constructor(self):
        return WSPRStation


class IWSPRStation(Interface):
    pass


@implementer(ITelemetryObject, IWSPRStation)
class WSPRStation(ExportedState):
    __snr = None
    __frequency = None
    __call = None
    __grid = None
    __txpower = None

    def __init__(self, object_id):
        self.__object_id = object_id

    def receive(self, message):
        self.__last_heard = message.time
        self.__snr = message.snr
        self.__frequency = message.frequency
        self.__call = message.call
        self.__grid = message.grid
        self.__txpower = message.txpower

    def is_interesting(self):
        """Every WSPR message is about as interesting as another, I suppose."""
        return True

    def get_object_expiry(self):
        return self.__last_heard + 30 * MINUTES

    @exported_value(type=TimestampT(), changes='explicit', label='Last heard')
    def get_last_heard(self):
        return self.__last_heard

    @exported_value(type=unicode, changes='explicit', label='SNR')
    def get_snr(self):
        return '%s dB' % (self.__snr,)

    @exported_value(type=unicode, changes='explicit', label='Frequency')
    def get_frequency(self):
        return '%s MHz' % (self.__frequency,)

    @exported_value(type=unicode, changes='explicit', label='Call')
    def get_call(self):
        return self.__call

    @exported_value(type=unicode, changes='explicit', label='Grid')
    def get_grid(self):
        return self.__grid

    @exported_value(type=unicode, changes='explicit', label='Tx Power')
    def get_txpower(self):
        return '%s dBm' % (self.__txpower,)

    @exported_value(type=Track, changes='explicit', label='Track')
    def get_track(self):
        latitude, longitude = grid_to_lat_long(self.__grid)
        track = Track(
            latitude=TelemetryItem(latitude, time.time()),
            longitude=TelemetryItem(longitude, time.time()))
        return track


def grid_to_lat_long(grid):
    if len(grid) not in [4, 6]:
        raise ValueError('Maidenhead locators must be 4 or 6 characters')

    grid = grid.upper()
    field_chars = list('ABCDEFGHIJKLMNOPQR')
    square_chars = list('0123456789')
    subsquare_chars = list('ABCDEFGHIJKLMNOPQRSTUVWX')

    lon = -180.0
    lat = -90.0

    lon_increment = 360
    lat_increment = 180

    for chars in [field_chars, square_chars, subsquare_chars]:
        lon_increment /= len(chars)
        lat_increment /= len(chars)

        lon += chars.index(grid[0]) * lon_increment
        lat += chars.index(grid[1]) * lat_increment

        if len(grid) == 2:
            # move to the center
            lon += lon_increment / 2
            lat += lat_increment / 2
            break

        grid = grid[2:]

    return lat, lon


__all__ = ['WSPRSpot', 'WSPRStation', 'grid_to_lat_long']
