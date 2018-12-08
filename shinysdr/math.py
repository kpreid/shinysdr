# Copyright 2013, 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

"""Mathematical algorithms."""

from __future__ import absolute_import, division, print_function, unicode_literals

from math import log10, pi
import time


__all__ = []  # appended later


def dB(x):
    """Convert dB value to multiplicative value."""
    return 10 ** (0.1 * x)


__all__.append('dB')


def to_dB(x):
    """Convert multiplicative value to dB value."""
    return 10 * log10(x)


__all__.append('to_dB')


def rotator_inc(rate, shift):
    """
    Calculation for using gnuradio.blocks.rotator_cc or other interfaces wanting radians/sample input.
    
    rate: sample rate in Hz
    shift: frequency shift in Hz
    """
    return (2 * pi) * (shift / rate)


__all__.append('rotator_inc')


class LazyRateCalculator(object):
    # TODO: Not strictly a math thing, should be moved.
    """
    Given a monotonically increasing value, allow polling its rate of increase.
    """
    def __init__(self, value_getter, min_interval=0.5):
        self.__value_getter = value_getter
        self.__min_interval = min_interval
        
        self.__time = time.time()
        self.__last_value = value_getter()
        self.__last_rate = 0

    def get(self):
        cur_wall_time = time.time()
        elapsed_wall = cur_wall_time - self.__time
        if elapsed_wall > self.__min_interval:
            cur_value = self.__value_getter()
            delta = cur_value - self.__last_value
            self.__time = cur_wall_time
            self.__last_value = cur_value
            self.__last_rate = round(delta / elapsed_wall, 2)
        return self.__last_rate


__all__.append('LazyRateCalculator')
