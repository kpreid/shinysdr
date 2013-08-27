import unittest

from sdr.values import ExportedState, CollectionState


class InsertFailSpecimen(CollectionState):
	def __init__(self):
		self.table = {}
		CollectionState.__init__(self, self.table, dynamic=True)
	
	def state_insert(self, key, desc):
		if desc['fail']:
			raise ValueError('Should be handled')
		else:
			self.table[key] = ExportedState()
			self.table[key].state_from_json(desc)


class TestStateInsert(unittest.TestCase):
	def setUp(self):
		self.object = InsertFailSpecimen()
	
	def test_success(self):
		self.object.state_from_json({'foo': {'fail': False}})
		self.assertEquals(['foo'], self.object.state().keys())
			
	def test_failure(self):
		self.object.state_from_json({'foo': {'fail': True}})
		# throws but exception is caught
		self.assertEquals([], self.object.state().keys())
