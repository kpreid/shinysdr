# -*- coding: utf-8 -*-
# Copyright 2016, 2017 Kevin Reid <kpreid@switchb.org>
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
Minimal units library.

Used only for expressing units for display. Does not provide calculation or dimensions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple as _namedtuple

from zope.interface import implementer as _implements

from shinysdr.i.json import IJsonSerializable as _IJsonSerializable


__all__ = []  # appended later


class Unit(_namedtuple('Unit', [
        'symbol',
        'si_prefix_ok'])):  # TODO allow requesting binary prefixes?
    _implements(_IJsonSerializable)
    
    def to_json(self):
        return {
            'type': 'Unit',
            'symbol': self.symbol,
            'si_prefix_ok': self.si_prefix_ok
        }
    
    def __str__(self):
        return self.symbol


__all__.append('Unit')


# TODO: reflectively put units into __all__

none = Unit('', True)
s = Unit('s', True)
degree = Unit('°', False)  # degree of angle
degC = Unit('°C', False)
degF = Unit('°F', False)
dB = Unit('dB', False)
dBm = Unit('dBm', False)
dBFS = Unit('dBFS', False)
Hz = Unit('Hz', True)
MHz = Unit('MHz', False)  # TODO: Remove or refine this when si_prefix_ok is actually used
ppm = Unit('ppm', False)
