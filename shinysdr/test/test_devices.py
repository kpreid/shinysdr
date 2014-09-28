# Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

from twisted.trial import unittest

# Note: not testing _ConstantVFOCell, it's just a useful utility
from shinysdr.devices import _ConstantVFOCell, Device, IDevice, merge_devices
from shinysdr.types import Range
from shinysdr.values import ExportedState, LooseCell


class TestDevice(unittest.TestCase):
	def test_name(self):
		self.assertEqual(u'x', Device(name='x').get_name())
		self.assertEqual(None, Device().get_name())


class TestMergeDevices(unittest.TestCase):
	def test_name(self):
		self.assertEqual('a', merge_devices([Device(), Device(name='a')]).get_name())
		self.assertEqual('a', merge_devices([Device(name='a'), Device()]).get_name())
		self.assertEqual('a+b', merge_devices([Device(name='a'), Device(name='b')]).get_name())

	def test_components_disjoint(self):
		d = merge_devices([
			Device(components={'a':ExportedState()}),
			Device(components={'b':ExportedState()})
		])
		self.assertEqual(d, IDevice(d))
		self.assertEqual(sorted(d.get_components().keys()), ['a', 'b'])

	def test_components_conflict(self):
		d = merge_devices([
			Device(components={'a':ExportedState()}),
			Device(components={'a':ExportedState()})
		])
		self.assertEqual(d, IDevice(d))
		self.assertEqual(sorted(d.get_components().keys()), ['0-a', '1-a'])

	def test_vfos(self):
		d = merge_devices([
			Device(vfo_cell=_ConstantVFOCell(1)),
			Device(vfo_cell=LooseCell(key='freq', value=0, ctor=Range([(10, 20)]), writable=True))
		])
		self.assertTrue(d.get_vfo_cell().isWritable())
		# TODO more testing
