import unittest

from shinysdr.values import ExportedState, BlockCell, CollectionState, exported_value, setter
# TODO: StateStreamInner is an implementation detail; arrange a better interface to test
from shinysdr.web import StateStreamInner

class TestStateStream(unittest.TestCase):
	def setUp(self):
		self.object = StateSpecimen()
		self.stream = StateStreamInner(self.object, 'urlroot')
	
	def test_init_mutate(self):
		self.assertEqual(self.stream._getUpdates(), [
			('register_block', 1, 'urlroot'),
			('register_cell', 2, 'urlroot/rw', self.object.state()['rw'].description()),
			('value', 1, {'rw': 2}),
			('value', 0, 1),
		])
		self.assertEqual(self.stream._getUpdates(), [])
		self.object.set_rw(2.0)
		self.assertEqual(self.stream._getUpdates(), [
			('value', 2, self.object.get_rw()),
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


class TestCollectionStream(unittest.TestCase):
	def setUp(self):
		self.d = {'a': ExportedState()}
		self.object = CollectionState(self.d, dynamic=True)
		self.stream = StateStreamInner(self.object, 'urlroot')
	
	def test_delete(self):
		self.assertEqual(self.stream._getUpdates(), [
			('register_block', 1, 'urlroot'),
			('register_cell', 2, 'urlroot/a', self.object.state()['a'].description()),
			('register_block', 3, 'urlroot/a'),
			('value', 3, {}),
			('value', 2, 3),
			('value', 1, {'a': 2}),
			('value', 0, 1),
		])
		self.assertEqual(self.stream._getUpdates(), [])
		del self.d['a']
		self.assertEqual(self.stream._getUpdates(), [
			('value', 1, {}),
			('delete', 3),
			('delete', 2),
		])


