# Copyright 2017 Kevin Reid and the ShinySDR contributors
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

from __future__ import absolute_import, division, print_function, unicode_literals

from twisted.python.util import sibpath
from twisted.web import static

from shinysdr.interfaces import ModeDef, ClientResourceDef

from .demodulator import WSPRDemodulator, find_wsprd

plugin_mode = ModeDef(mode='WSPR',
    info='WSPR',
    demod_class=WSPRDemodulator,
    unavailability=None if find_wsprd() else 'wsprd not found.')

plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(sibpath(__file__, 'client')),
    load_js_path='wspr.js')

__all__ = []
