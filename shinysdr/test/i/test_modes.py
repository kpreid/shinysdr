# Copyright 2018 Kevin Reid <kpreid@switchb.org>
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

from shinysdr.test.i import test_modes_cases as package
from shinysdr.i.modes import _ModeTable


class TestModeTable(unittest.TestCase):
    table = _ModeTable(package)
    
    def test_list_all(self):
        self.assertEqual(
            {d.mode for d in self.table.get_modes(include_unavailable=True)},
            {'available', 'unavailable'})
    
    def test_list_available(self):
        self.assertEqual(
            {d.mode for d in self.table.get_modes(include_unavailable=False)},
            {'available'})
