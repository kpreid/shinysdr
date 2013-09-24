import unittest

from osmosdr import range_t, meta_range_t
from shinysdr.values import Range
from shinysdr.plugins.osmosdr import convert_osmosdr_range


class TestOsmoSDRRange(unittest.TestCase):
	def test_convert_simple(self):
		self.do_convert_test([(1, 2, 0)])

	def test_convert_stepped(self):
		self.do_convert_test([(1, 2, 1)])

	def test_convert_point(self):
		self.do_convert_test([(1, 1, 0)])
	
	def test_convert_gapped(self):
		self.do_convert_test([(0, 0, 0), (1, 2, 0)])
	
	def do_convert_test(self, range_argses):
		orange = meta_range_t()
		for range_args in range_argses:
			orange.push_back(range_t(*range_args))
		myrange = convert_osmosdr_range(orange)
		self.assertEqual(
			[(min, max) for (min, max, step) in range_argses],
			myrange.type_to_json()['subranges'])
