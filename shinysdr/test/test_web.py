import unittest
import json

from shinysdr.values import ExportedState, BlockCell, CollectionState, exported_value, setter
# TODO: StateStreamInner is an implementation detail; arrange a better interface to test
from shinysdr.web import StateStreamInner

class StateStreamTestCase(unittest.TestCase):
	def setUp(self):
		self.updates = []
		def send(value):
			self.updates.extend(json.loads(value))
		self.stream = StateStreamInner(send, self.object, 'urlroot')
	
	def getUpdates(self):
		self.stream.poll()
		u = self.updates
		self.updates = []
		return u

class TestStateStream(StateStreamTestCase):
	def setUp(self):
		self.object = StateSpecimen()
		StateStreamTestCase.setUp(self)
	
	def test_init_mutate(self):
		self.assertEqual(self.getUpdates(), [
			['register_block', 1, 'urlroot'],
			['register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description()],
			['value', 1, {'rw': 2}],
			['value', 0, 1],
		])
		self.assertEqual(self.getUpdates(), [])
		self.object.set_rw(2.0)
		self.assertEqual(self.getUpdates(), [
			['value', 2, self.object.get_rw()],
		])


class StateSpecimen(ExportedState):
	'''Helper for TestStateStream'''
	def __init__(self):
		self.rw = 1.0
	
	@exported_value(ctor=float)
	def get_rw(self):
		return self.rw
	
	@setter
	def set_rw(self, value):
		self.rw = value


class TestCollectionStream(StateStreamTestCase):
	def setUp(self):
		self.d = {'a': ExportedState()}
		self.object = CollectionState(self.d, dynamic=True)
		StateStreamTestCase.setUp(self)
	
	def test_delete(self):
		self.assertEqual(self.getUpdates(), [
			['register_block', 1, 'urlroot'],
			['register_cell', 2, 'urlroot/a', self.object.state()['a'].description()],
			['register_block', 3, 'urlroot/a'],
			['value', 3, {}],
			['value', 2, 3],
			['value', 1, {'a': 2}],
			['value', 0, 1],
		])
		self.assertEqual(self.getUpdates(), [])
		del self.d['a']
		self.assertEqual(self.getUpdates(), [
			['value', 1, {}],
			['delete', 3],
			['delete', 2],
		])


