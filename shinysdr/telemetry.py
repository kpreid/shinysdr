# Copyright 2015, 2016 Kevin Reid and the ShinySDR contributors
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
TODO: This doesn't actually deserve its own module; it's just not clear where to put it.

"""

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple

import six

from twisted.internet import reactor as the_reactor
from twisted.internet.interfaces import IReactorTime
from zope.interface import Interface, implementer

from shinysdr.types import python_type_registry
from shinysdr.values import CellDict, CollectionState


__all__ = []  # appended later


# See Track below.
_TrackNT = namedtuple('Track', [
    'latitude',  # TelemetryItem(latitude in degrees north)
    'longitude',  # TelemetryItem(latitude in degrees east)

    'heading',  # TelemetryItem(angle of nominal forward-facing of vehicle in degrees east of north)
    'track_angle',  # TelemetryItem(angle of horizontal component of velocity in degrees east of north)
    'h_speed',  # TelemetryItem(magnitude of horizontal component of velocity in m/s)

    'altitude',  # TelemetryItem(altitude in meters above sea level)  TODO: Allow choice of reference? Barometric vs GPS vs other?
    'v_speed',  # TelemetryItem(vertical speed in m/s)
])


# Representation of information about an object whose location is being tracked.
class Track(_TrackNT):
    def __new__(cls, *args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0:
            # convert dict argument, possibly pure JSON (instead of TelemetryItems), to kwargs
            args_in = dict(args[0])
            args_out = {}
            for k, v in six.iteritems(args_in):
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


python_type_registry[Track] = 'shinysdr.telemetry.Track'
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


class ITelemetryObject(Interface):
    """
    An object that can be in an TelemetryStore.

    Examples: an APRS station, aircraft, etc. The state of an ITelemetryObject
    is updated through receiving ITelemetryMessage.
    """

    def receive(message):
        """
        Update state according to the received ITelemetryMessage.
        """

    def is_interesting():
        """
        Return whether this object should be shown to the client. The value
        should change only when a message is receive()d.
        """

    def get_object_expiry():
        """
        Return the absolute time (seconds since epoch) after which this object
        should be deleted from the store.
        """


__all__.append('ITelemetryObject')


class ITelemetryMessage(Interface):
    """
    A message that can be delivered to an ITelemetryObject or TelemetryStore.
    """

    def get_object_id():
        """
        Return a string identifying the object this message is about. It must be unique among all objects, not just within a particular telemetry mode.
        """

    def get_object_constructor():
        """
        Return a constructor function for this type of telemetry object.
        """


__all__.append('ITelemetryMessage')


class ITelemetryStore(Interface):
    """
    Marker interface for client. Only implementation is TelemetryStore.
    """


__all__.append('ITelemetryStore')


@implementer(ITelemetryStore)
class TelemetryStore(CollectionState):
    """
    Accepts telemetry messages and exports the accumulated information obtained from them.
    """

    def __init__(self, time_source=the_reactor):
        self.__interesting_objects = CellDict(dynamic=True)
        CollectionState.__init__(self, self.__interesting_objects)
        self.__objects = {}
        self.__expiry_times = {}
        self.__time_source = IReactorTime(time_source)
        self.__flush_call = None

    # not exported
    def receive(self, message):
        """Store the supplied telemetry message object."""
        message = ITelemetryMessage(message)
        object_id = six.text_type(message.get_object_id())

        if object_id in self.__objects:
            obj = self.__objects[object_id]
        else:
            obj = self.__objects[object_id] = ITelemetryObject(
                # TODO: Should probably have a context object supplying last message time and delete_me()
                message.get_object_constructor()(object_id=object_id))

        obj.receive(message)
        expiry = obj.get_object_expiry()
        self.__expiry_times[object_id] = expiry
        if obj.is_interesting():
            self.__interesting_objects[object_id] = obj

        self.__maybe_schedule_flush()

    def __flush_expired(self):
        current_time = self.__time_source.seconds()
        deletes = []
        for object_id, expiry in six.iteritems(self.__expiry_times):
            if expiry <= current_time:
                deletes.append(object_id)
        for object_id in deletes:
            del self.__objects[object_id]
            del self.__expiry_times[object_id]
            if object_id in self.__interesting_objects:
                del self.__interesting_objects[object_id]

        self.__maybe_schedule_flush()

    def __maybe_schedule_flush(self):
        """Schedule a call to __flush_expired if there is not one already."""
        if self.__flush_call and self.__flush_call.active():
            # Could need to schedule one earlier than already scheduled.
            self.__flush_call.cancel()

        if self.__expiry_times:
            now = self.__time_source.seconds()
            next_expiry = min(six.itervalues(self.__expiry_times))
            sec_until_expiry = max(0, next_expiry - now)
            self.__flush_call = self.__time_source.callLater(
                sec_until_expiry,
                self.__flush_expired)


__all__.append('TelemetryStore')
