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

# TODO write module documentation, or revisit whether this module needs to exist

from __future__ import absolute_import, division, unicode_literals

from twisted.plugin import getPlugins
from zope.interface import Interface

from shinysdr import plugins


__all__ = []  # appended later


class IModeDef(Interface):
    """
    Demodulator plugin description interface.
    
    See shinysdr.interfaces.ModeDef for the actual type.
    """
    # Only needed to make the plugin system work
    # TODO write interface methods anyway


# TODO: Refactor _ModeTable so that it can be tested (does not hardcode getPlugins)


# Object for memoizing results of getPlugins(IModeDef)
class _ModeTable(object):
    def __init__(self):
        self.__all_modes = {d.mode: d
            for d in getPlugins(IModeDef, plugins)}
        self.__available_modes = {d.mode: d
             for d in self.__all_modes.itervalues()
             if d.available}
    
    def get_modes(self, include_unavailable):
        if include_unavailable:
            return self.__all_modes.values()
        else:
            return self.__available_modes.values()
    
    def lookup_mode(self, mode, include_unavailable):
        if include_unavailable:
            return self.__all_modes.get(mode)
        else:
            return self.__available_modes.get(mode)


# pylint: disable=global-statement
# This is memoizing what is global anyway and mostly-immutable. namely getPlugins() results (which ultimately depend on module imports).
_mode_table = None


def _get_mode_table():
    global _mode_table
    if _mode_table is None:
        _mode_table = _ModeTable()
    return _mode_table


def get_modes(include_unavailable=False):
    return _get_mode_table().get_modes(include_unavailable=include_unavailable)


__all__.append('get_modes')


def lookup_mode(mode, include_unavailable=False):
    return _get_mode_table().lookup_mode(mode, include_unavailable=include_unavailable)


__all__.append('lookup_mode')
