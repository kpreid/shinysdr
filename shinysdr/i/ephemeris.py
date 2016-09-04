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

from __future__ import absolute_import, division

import json
import math
import time

from twisted.web.resource import Resource

import ephem

__all__ = []  # appended later


_RADIANS_TO_DEGREES = 180 / math.pi
t0 = time.time()

class EphemerisResource(Resource):
    isLeaf = True
    
    def __init__(self):
        pass
    
    def render_GET(self, request):
        # pylint: disable=no-member
        
        # This will eventually take satellite parameters and return current position/velocity. For now, it does the sun.
        o = ephem.Observer()
        o.date = ephem.now()
        o.lat = '0'
        o.lon = '0'
        sun = ephem.Sun()
        sun.compute(o)
        # az and alt are now relative to an observer on the surface at 0N 0E, which is a silly coordinate system but the best I could get reliably.
        x = math.sin(sun.az) * math.cos(sun.alt)
        y = math.cos(sun.az) * math.cos(sun.alt)
        z = -math.sin(sun.alt)
        
        request.setHeader('Content-Type', 'application/json')
        return json.dumps([x, y, z])


__all__.append('EphemerisResource')
