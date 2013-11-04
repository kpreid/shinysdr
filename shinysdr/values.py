# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

import array
import bisect
import struct

class BaseCell(object):
	def __init__(self, target, key, persists=True, writable=False):
		# The exact relationship of target and key depends on the subtype
		self._target = target
		self._key = key
		self._persists = persists
		self._writable = writable
	
	def __eq__(self, other):
		if not isinstance(other, BaseCell):
			return NotImplemented
		elif self._target == other._target and self._key == other._key:
			if type(self) != type(other):
				# No two cells should have the same target and key but different details.
				# This is not a perfect test
				raise Exception("Shouldn't happen")
			return True
		else:
			return False
	
	def __ne__(self, other):
		return not self.__eq__(other)
	
	def __hash__(self):
		return hash(self._target) ^ hash(self._key)

	def isBlock(self):
		raise NotImplementedError()
	
	def key(self):
		return self._key

	def get(self):
		raise NotImplementedError()
	
	def set(self, value):
		raise NotImplementedError()
	
	def isWritable(self):
		return self._writable
	
	def persists(self):
		return self._persists
		
	def description(self):
		raise NotImplementedError()


class ValueCell(BaseCell):
	def __init__(self, target, key, ctor=None, **kwargs):
		BaseCell.__init__(self, target, key, **kwargs)
		self._ctor = ctor
	
	def type(self):
		return self._ctor
	
	def description(self):
		return {
			'kind': 'value',
			'type': type_to_json(self._ctor),
			'writable': self.isWritable(),
			'current': self.get()
		}


class Cell(ValueCell):
	def __init__(self, target, key, writable=False, ctor=None):
		ValueCell.__init__(self, target, key, writable=writable, persists=writable, ctor=ctor)
		self._getter = getattr(self._target, 'get_' + key)
		if writable:
			self._setter = getattr(self._target, 'set_' + key)
		else:
			self._setter = None
	
	def isBlock(self):
		return False
	
	def get(self):
		return self._getter()
	
	def set(self, value):
		if not self.isWritable():
			raise Exception('Not writable.')
		return self._setter(self._ctor(value))


sizeof_float = 4


class MsgQueueCell(ValueCell):
	def __init__(self, target, key, fill=True, ctor=None):
		ValueCell.__init__(self, target, key, writable=False, persists=False, ctor=ctor)
		self._qgetter = getattr(self._target, 'get_' + key + '_queue')
		self._igetter = getattr(self._target, 'get_' + key + '_info')
		self._splitting = None
		self._fill = fill
		if fill:
			self._prev = None
	
	def isBlock(self):
		return False
	
	def get(self, binary=False):
		if self._splitting is not None:
			(string, itemsize, count, index) = self._splitting
		else:
			queue = self._qgetter()
			# we would use .delete_head_nowait() but it returns a crashy wrapper instead of a sensible value like None. So implement a test (which is safe as long as we're the only reader)
			if queue.empty_p():
				if binary:  # TODO kludge
					return None
				else:
					return self._doFill()
			else:
				message = queue.delete_head()
			if message.length() > 0:
				string = message.to_string() # only interface available
			else:
				string = '' # avoid crash bug
			itemsize = int(message.arg1())
			count = int(message.arg2())
			index = 0
		assert index < count
		
		# update state
		if index == count - 1:
			self._splitting = None
		else:
			self._splitting = (string, itemsize, count, index + 1)
		
		# extract value
		itemStr = string[itemsize * index : itemsize * (index + 1)]
		if binary:
			# TODO: for general case need to have configurable format string
			value = struct.pack('dd', *self._igetter()) + itemStr
		else:
			# TODO: allow caller to provide format info (nontrivial in case of runtime variable length)
			unpacker = array.array('f')
			unpacker.fromstring(itemStr)
			value = (self._igetter(), unpacker.tolist())
		if self._fill and not binary:  # TODO: fill should work for binary too
			self._prev = value
		return value
	
	def _doFill(self):
		if self._fill:
			return self._prev
		else:
			return None
	
	def set(self, value):
		raise Exception('MsgQueueCell is not writable.')


class BaseBlockCell(BaseCell):
	def __init__(self, target, key, persists=True):
		BaseCell.__init__(self, target, key, writable=False, persists=persists)
	
	def isBlock(self):
		return True
	
	def get(self):
		return self.getBlock().state_to_json()
	
	def set(self, value):
		self.getBlock().state_from_json(value)
	
	def description(self):
		return self.getBlock().state_description()


class BlockCell(BaseBlockCell):
	def __init__(self, target, key, persists=True):
		BaseBlockCell.__init__(self, target, key, persists=persists)
	
	def getBlock(self):
		# TODO method-based access
		return getattr(self._target, self._key)

# TODO: It's unclear whether or not the Cell design makes sense in light of this. We seem to have conflated the index in the container and the type of the contained into one object.
class CollectionMemberCell(BaseBlockCell):
	def __init__(self, target, key, persists=True):
		BaseBlockCell.__init__(self, target, key, persists=persists)
	
	def getBlock(self):
		return self._target._collection[self._key]


class ExportedState(object):
	def state_def(self, callback):
		pass
	
	def state_is_dynamic(self):
		return False
	
	def state(self):
		if self.state_is_dynamic() or not hasattr(self, '_ExportedState__cache'):
			cache = {}
			self.__cache = cache

			def callback(cell):
				cache[cell.key()] = cell
			self.state_def(callback)
			
			# decorator support
			# TODO kludgy introspection, figure out what is better
			for k in dir(type(self)):
				if not hasattr(self, k): continue
				v = getattr(type(self), k)
				if isinstance(v, ExportedGetter):
					if not k.startswith('get_'):
						# TODO factor out attribute name usage in Cell so this restriction is moot
						raise Error('Bad getter name', k)
					else:
						k = k[len('get_'):]
					cache[k] = v.make_cell(self, k)
			
		return self.__cache
	
	def state_to_json(self):
		state = {}
		for key, cell in self.state().iteritems():
			if cell.persists():
				state[key] = cell.get()
		return state
	
	def state_from_json(self, state):
		cells = self.state()
		dynamic = self.state_is_dynamic()
		defer = []
		for key in state:
			def err(adjective, suffix):
				# TODO better printing/logging, ship to client
				print 'Warning: Discarding ' + adjective + ' state', str(self) + '.' + key, '=', state[key], suffix
			def doTry(f):
				try:
					f()
				except (LookupError, TypeError, ValueError) as e:
					# a plausible set of exceptions, so we don't catch implausible ones
					err('erroneous', '(' + type(e).__name__ + ': ' + str(e) + ')')
			cell = cells.get(key, None)
			if cell is None:
				if dynamic:
					doTry(lambda: self.state_insert(key, state[key]))
				else:
					err('nonexistent', '')
			elif cell.isBlock():
				defer.append(key)
			elif not cell.isWritable():
				err('non-writable', '')
			else:
				doTry(lambda: cells[key].set(state[key]))
		# blocks are deferred because the specific blocks may depend on other keys
		for key in defer:
			cells[key].set(state[key])

	def state_description(self):
		childDescs = {}
		description = {
			'kind': 'block',
			'children': childDescs
		}
		for key, cell in self.state().iteritems():
			# TODO: include URLs explicitly in desc format
			childDescs[key] = cell.description()
		return description


class CollectionState(ExportedState):
	'''Wrapper around a plain Python collection.'''
	def __init__(self, collection, dynamic=False):
		self._collection = collection  # accessed by CollectionMemberCell
		self.__keys = collection.keys()
		self.__cells = {}
		self.__dynamic = dynamic
	
	def state_is_dynamic(self):
		return self.__dynamic
	
	def state_def(self, callback):
		super(CollectionState, self).state_def(callback)
		for key in self._collection:
			if key not in self.__cells:
				self.__cells[key] = CollectionMemberCell(self, key)
			callback(self.__cells[key])


def exported_value(**cell_kwargs):
	'''Decorator for exported state; takes Cell's kwargs.'''
	def decorator(f):
		return ExportedGetter(f, cell_kwargs)
	return decorator


def setter(f):
	'''Decorator for setters of exported state; must be paired with a getter'''
	return ExportedSetter(f)


class ExportedGetter(object):
	def __init__(self, f, cell_kwargs):
		self.__function = f
		self._cell_kwargs = cell_kwargs
	
	def __get__(self, obj, type=None):
		'''implements method binding'''
		if obj is None:
			return self
		else:
			return self.__function.__get__(obj, type)
	
	def make_cell(self, obj, attr):
		kwargs = self._cell_kwargs
		if 'ctor_fn' in kwargs:
			if 'ctor' in kwargs:
				raise ValueError('cannot specify both ctor and ctor_fn')
			kwargs['ctor'] = kwargs['ctor_fn'](obj)
			del kwargs['ctor_fn']
		# TODO kludgy introspection, figure out what is better
		writable = hasattr(obj, 'set_' + attr) and isinstance(getattr(type(obj), 'set_' + attr), ExportedSetter)
		return Cell(obj, attr, writable=writable, **kwargs)


class ExportedSetter(object):
	def __init__(self, f):
		# TODO: Coerce value with ctor?
		self.__function = f
	
	def __get__(self, obj, type=None):
		'''implements method binding'''
		if obj is None:
			return self
		else:
			return self.__function.__get__(obj, type)


def type_to_json(t):
	if str(t) == 'shinysdr.top.SpectrumTypeStub':
		# TODO: make this into a ValueType?
		return u'spectrum'
	elif isinstance(t, ValueType):
		return t.type_to_json()
	elif t is bool: # TODO can we generalize this?
		return u'boolean'
	else:
		return None


class ValueType(object):
	def type_to_json():
		raise NotImplementedError()
	
	def __call__(self, specimen):
		raise NotImplementedError()


class Enum(ValueType):
	def __init__(self, values):
		"""values: dict of {value: description}"""
		self.__values = dict(values)  # paranoid copy
	
	def values(self):
		return self.__values
	
	def type_to_json(self):
		return {'type': 'enum', 'values': self.__values}
	
	def __call__(self, specimen):
		if specimen not in self.__values:
			raise ValueError('Not a permitted value: ' + repr(specimen))
		return specimen


class Range(ValueType):
	def __init__(self, subranges, strict=True, logarithmic=False, integer=False):
		# TODO validate subranges are sorted
		self.__mins = [min for (min, max) in subranges]
		self.__maxes = [max for (min, max) in subranges]
		self.__strict = strict
		self.__logarithmic = logarithmic
		self.__integer = integer
	
	def type_to_json(self):
		return {
			'type': 'range',
			'subranges': zip(self.__mins, self.__maxes),
			'logarithmic': self.__logarithmic,
			'integer': self.__integer
		}
	
	def __call__(self, specimen):
		specimen = float(specimen)
		if self.__integer:
			specimen = int(round(specimen))
		if self.__strict:
			mins = self.__mins
			maxes = self.__maxes
			i = bisect.bisect_right(mins, specimen)
			if i >= len(mins): i = len(mins) - 1
			# i is now the index of the highest subrange which is not too high to contain specimen
			# TODO: Round to nearest range instead of lower one. For now, the client handles all user-visible rounding.
			if specimen < mins[i]:
				specimen = mins[i]
			if specimen > maxes[i]:
				specimen = maxes[i]
		return specimen
