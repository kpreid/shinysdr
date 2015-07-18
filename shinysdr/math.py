# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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
Mathematical algorithms.

This module is not an external API and not guaranteed to have a stable
interface.
'''

from __future__ import absolute_import, division

from math import log10
import time


__all__ = []  # appended later


def factorize(n):
    '''
    Return a list of the factors of an integer, including repeated factors, in ascending order.
    '''
    # I wish there was a nice standard library function for this...
    # Wrote the simplest thing I could think of
    if n <= 0:
        raise ValueError()
    primes = []
    while n > 1:
        for i in xrange(2, n // 2 + 1):
            if n % i == 0:
                primes.append(i)
                n //= i
                break
        else:
            primes.append(n)
            break
    return primes


__all__.append('factorize')


def small_factor_at_least(n, limit, _force_approx=False):
    '''
    Find a factor of 'n' which is at least 'limit' but not too much larger.

    A rough approximation is used if 'n' nas many factors; finding the smallest such factor is equivalent to the knapsack problem. Ref: http://mathoverflow.net/q/79322/57423 (TODO: Better ref / check claim)
    '''
    if n % limit == 0:
        # a better answer in easy case; e.g. for (100, 10) we'd return 25 otherwise
        return limit
    factors = factorize(n)
    if len(factors) < 12 and not _force_approx:
        # not too many factors, use brute force exact computation
        def product_selected(mask):
            candidate = 1
            for i, factor in enumerate(factors):
                if mask & (1 << i) != 0:
                    candidate *= factor
            if candidate >= limit:
                return candidate
            else:
                return n + 1  # "don't pick me"
        
        return min(map(product_selected, xrange(0, 1 << len(factors))))
    else:
        # many factors, use cheap approximation. TODO: Maybe optimize very last step
        factors.reverse()
        answer = 1
        for factor in factors:
            answer *= factor
            if answer >= limit:
                break
        return answer


__all__.append('small_factor_at_least')


def dB(x):
    '''Convert dB value to multiplicative value.'''
    return 10 ** (0.1 * x)


__all__.append('dB')


def todB(x):
    '''Convert multiplicative value to dB value.'''
    return 10 * log10(x)


__all__.append('todB')


class LazyRateCalculator(object):
    # TODO: Not strictly a math thing.
    '''
    Given a monotonically increasing value, allow polling its rate of increase.
    '''
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