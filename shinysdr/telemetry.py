# Copyright 2015 Kevin Reid <kpreid@switchb.org>
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
TODO: This doesn't actually deserve its own module; it's just not clear where to put it.

'''

from __future__ import absolute_import, division


from collections import namedtuple


from shinysdr.types import bare_type_registry


__all__ = []  # appended later


# Rpresentation of information about an object whose location is being tracked.
Track = namedtuple('Track', [
    'latitude',  # TelemetryItem(latitude in degrees north)
    'longitude',  # TelemetryItem(latitude in degrees east)

    'heading',  # TelemetryItem(angle of nominal forward-facing of vehicle in degrees east of north)
    'track_angle',  # TelemetryItem(angle of horizontal component of velocity in degrees east of north)
    'h_speed',  # TelemetryItem(magnitude of horizontal component of velocity in m/s)

    'altitude',  # TelemetryItem(altitude in meters above sea level)  TODO: Allow choice of reference? Barometric vs GPS vs other?
    'v_speed',  # TelemetryItem(vertical speed in m/s)
])


bare_type_registry[Track] = 'shinysdr.telemetry.Track'
__all__.append('Track')


# TODO awful name
TelemetryItem = namedtuple('TelemetryItem', [
    'value',  # may be None if unknown, or an actual value (usually but not alays a number).
    'timestamp',  # Unix time at which the value was last obtained, or None if no data.
])


__all__.append('TelemetryItem')


empty_item = TelemetryItem(None, None)


__all__.append('empty_item')


empty_track = Track(
    latitude=empty_item,
    longitude=empty_item,
    altitude=empty_item,
    track_angle=empty_item,
    h_speed=empty_item,
    v_speed=empty_item,
    heading=empty_item,
)

__all__.append('empty_track')
