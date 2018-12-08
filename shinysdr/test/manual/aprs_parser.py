#!/usr/bin/env python

# Copyright 2014, 2016 Kevin Reid and the ShinySDR contributors
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
Test for APRS parser. Accepts lines and prints the parsed form.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import string
import sys
import time

from shinysdr.plugins import aprs


if __name__ == '__main__':
    for line in sys.stdin:
        print(string.rstrip(line, '\n'))
        parsed = aprs.parse_tnc2(line, time.time())
        for error in parsed.errors:
            print('--!--', error)
        for fact in parsed.facts:
            print('     ', fact)
        print()
