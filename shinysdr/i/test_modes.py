# Copyright 2018 Kevin Reid and the ShinySDR contributors
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

from twisted.trial import unittest

from shinysdr.i.modes import _ModeTable
from shinysdr.types import EnumRow
from . import test_modes_cases as package


class TestModeTable(unittest.TestCase):
    table = _ModeTable(package)
    
    def test_get_modes_all(self):
        self.assertEqual(
            {d.mode for d in self.table.get_modes(include_unavailable=True)},
            {'available', 'unavailable'})
    
    def test_get_modes_available(self):
        self.assertEqual(
            {d.mode for d in self.table.get_modes(include_unavailable=False)},
            {'available'})

    def test_lookup_and_list_contents(self):
        modes = self.table.get_modes(include_unavailable=False)
        mode_def = self.table.lookup_mode('available', include_unavailable=False)
        self.assertEqual(modes[0], mode_def)
        self.assertEqual(mode_def.mode, 'available')
        self.assertEqual(mode_def.info, EnumRow(label='expected available'))
        self.assertEqual(mode_def.mod_class, None)
        self.assertEqual(mode_def.unavailability, None)
