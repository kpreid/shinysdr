import unittest

from shinysdr.values import ExportedState, BlockCell, CollectionState, Range, exported_value, setter


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


class TestCellIdentity(unittest.TestCase):
	def setUp(self):
		self.object = CellIdentitySpecimen()

	def assertConsistent(self, f):
		self.assertEqual(f(), f())
		self.assertEqual(f().__hash__(), f().__hash__())

	def test_value_cell(self):
		self.assertConsistent(lambda: self.object.state()['value'])
			
	def test_block_cell(self):
		self.assertConsistent(lambda: self.object.state()['block'])


class CellIdentitySpecimen(ExportedState):
	'''Helper for TestCellIdentity'''
	value = 1
	block = None
	def __init__(self):
		self.block = ExportedState()
	
	# force worst-case
	def state_is_dynamic(self):
		return True
	
	@exported_value()
	def get_value(self):
		return 9

	def state_def(self, callback):
		super(CellIdentitySpecimen, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(BlockCell(self, 'block'))
