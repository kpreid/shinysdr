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
from zope.interface import implements  # available via Twisted

from gnuradio import gr

# Note: not testing _ConstantVFOCell, it's just a useful utility
from shinysdr.devices import _ConstantVFOCell, Device, IDevice, IRXDriver, ITXDriver, merge_devices
from shinysdr.signals import SignalType
from shinysdr.types import Range
from shinysdr.values import ExportedState, LooseCell, nullExportedState


class TestDevice(unittest.TestCase):
	def test_name(self):
		self.assertEqual(u'x', Device(name='x').get_name())
		self.assertEqual(None, Device().get_name())
	
	def test_rx_none(self):
		d = Device()
		self.assertEqual(False, d.can_receive())
		self.assertEqual(nullExportedState, d.get_rx_driver())
	
	def test_rx_some(self):
		rxd = _TestRXDriver()
		d = Device(rx_driver=rxd)
		self.assertEqual(True, d.can_receive())
		self.assertEqual(rxd, d.get_rx_driver())
	
	def test_tx_none(self):
		d = Device()
		self.assertEqual(False, d.can_receive())
		self.assertEqual(nullExportedState, d.get_tx_driver())
	
	def test_tx_some(self):
		txd = _TestTXDriver()
		d = Device(tx_driver=txd)
		self.assertEqual(True, d.can_transmit())
		self.assertEqual(txd, d.get_tx_driver())
	
	# TODO VFO tests
	# TODO components tests


class _TestRXDriver(ExportedState):
	implements(IRXDriver)
	
	def get_output_type(self):
		return SignalType('IQ', 1)

	def get_tune_delay(self):
		return 0.0
	
	def notify_reconnecting_or_restarting(self):
		pass


class _TestTXDriver(ExportedState):
	implements(ITXDriver)
	
	def get_input_type(self):
		return SignalType('IQ', 1)


class TestMergeDevices(unittest.TestCase):
	def test_name(self):
		self.assertEqual('a', merge_devices([Device(), Device(name='a')]).get_name())
		self.assertEqual('a', merge_devices([Device(name='a'), Device()]).get_name())
		self.assertEqual('a+b', merge_devices([Device(name='a'), Device(name='b')]).get_name())

	def test_components_disjoint(self):
		d = merge_devices([
			Device(components={'a': ExportedState()}),
			Device(components={'b': ExportedState()})
		])
		self.assertEqual(d, IDevice(d))
		self.assertEqual(sorted(d.get_components().keys()), ['a', 'b'])

	def test_components_conflict(self):
		d = merge_devices([
			Device(components={'a': ExportedState()}),
			Device(components={'a': ExportedState()})
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
