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
_TrackNT = namedtuple('Track', [
    'latitude',  # TelemetryItem(latitude in degrees north)
    'longitude',  # TelemetryItem(latitude in degrees east)

    'heading',  # TelemetryItem(angle of nominal forward-facing of vehicle in degrees east of north)
    'track_angle',  # TelemetryItem(angle of horizontal component of velocity in degrees east of north)
    'h_speed',  # TelemetryItem(magnitude of horizontal component of velocity in m/s)

    'altitude',  # TelemetryItem(altitude in meters above sea level)  TODO: Allow choice of reference? Barometric vs GPS vs other?
    'v_speed',  # TelemetryItem(vertical speed in m/s)
])
class Track(_TrackNT):
    def __new__(cls, *args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0:
            # convert dict argument, possibly pure JSON (instead of TelemetryItems), to kwargs
            args_in = dict(args[0])
            args_out = {}
            for k, v in args_in.iteritems():
                if isinstance(v, TelemetryItem):
                    args_out[k] = args_in[k]
                else:
                    args_out[k] = TelemetryItem(**args_in[k])
            return cls.__new__(cls, **args_out)
        elif len(args) == 0:
            assert cls == Track
            try:
                # allow partial init args
                return empty_track._replace(**kwargs)
            except NameError:  # empty_track not yet initialized
                return _TrackNT.__new__(cls, **kwargs)
        else:
            raise TypeError('Track constructor takes 1 dict or kwargs')
                


bare_type_registry[Track] = 'shinysdr.telemetry.Track'
__all__.append('Track')


# TODO awful name
TelemetryItem = namedtuple('TelemetryItem', [
    'value',  # may be None if unknown, or an actual value (usually but not always a number).
    'timestamp',  # Unix time at which the value was last obtained, or None if no data or undefined time.
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
