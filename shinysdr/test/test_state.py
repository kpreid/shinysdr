import unittest

from shinysdr.values import ExportedState, CollectionState, exported_value, setter, Range


class TestDecorator(unittest.TestCase):
	def setUp(self):
		self.object = DecoratorSpecimen()
	
	def test_state(self):
		keys = self.object.state().keys()
		keys.sort()
		self.assertEqual(['inherited', 'rw'], keys)
		rw_cell = self.object.state()['rw']
		self.assertEqual(rw_cell.get(), 0.0)
		rw_cell.set(1.0)
		self.assertEqual(rw_cell.get(), 1.0)


class DecoratorSpecimenSuper(ExportedState):
	'''Helper for TestDecorator'''
	@exported_value(ctor=float)
	def get_inherited(self):
		return 9


class DecoratorSpecimen(DecoratorSpecimenSuper):
	'''Helper for TestDecorator'''
	def __init__(self):
		self.rw = 0.0
	
	@exported_value(ctor=Range([(0.0, 10.0)]))
	def get_rw(self):
		return self.rw
	
	@setter
	def set_rw(self, value):
		self.rw = value


class TestStateInsert(unittest.TestCase):
	def setUp(self):
		self.object = InsertFailSpecimen()
	
	def test_success(self):
		self.object.state_from_json({'foo': {'fail': False}})
		self.assertEqual(['foo'], self.object.state().keys())
			
	def test_failure(self):
		self.object.state_from_json({'foo': {'fail': True}})
		# throws but exception is caught
		self.assertEqual([], self.object.state().keys())


class InsertFailSpecimen(CollectionState):
	'''Helper for TestStateInsert'''
	def __init__(self):
		self.table = {}
		CollectionState.__init__(self, self.table, dynamic=True)
	
	def state_insert(self, key, desc):
		if desc['fail']:
			raise ValueError('Should be handled')
		else:
			self.table[key] = ExportedState()
			self.table[key].state_from_json(desc)
