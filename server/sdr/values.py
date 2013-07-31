import array

class BaseCell(object):
	def __init__(self, target, key, persists=True, writable=False):
		# The exact relationship of target and key depends on the subtype
		self._target = target
		self._key = key
		self._persists = persists
		self._writable = writable
	
	def isBlock(self):
		raise NotImplementedError()
	
	def key(self):
		return self._key

	def ctor(self):
		# TODO where should this actually apply
		return None

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
	
	def ctor(self):
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
	
	def ctor(self):
		return self._ctor
	
	def get(self):
		return self._getter()
	
	def set(self, value):
		if not self.isWritable():
			raise Exception('Not writable.')
		return self._setter(value)


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
	
	def get(self):
		if self._splitting is not None:
			(string, itemsize, count, index) = self._splitting
		else:
			queue = self._qgetter()
			# we would use .delete_head_nowait() but it returns a crashy wrapper instead of a sensible value like None. So implement a test (which is safe as long as we're the only reader)
			if queue.empty_p():
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
		valueStr = string[itemsize * index : itemsize * (index + 1)]
		# TODO: allow caller to provide format info (nontrivial in case of runtime variable length)
		unpacker = array.array('f')
		unpacker.fromstring(valueStr)
		value = (self._igetter(), unpacker.tolist())
		if self._fill:
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
		return self._target[self._key]


class ExportedState(object):
	def state_def(self, callback):
		pass
	
	def state(self):
		if not hasattr(self, '_ExportedState__cache'):
			cache = {}
			self.__cache = cache

			def callback(cell):
				cache[cell.key()] = cell
			self.state_def(callback)
		return self.__cache
	
	def state_to_json(self):
		state = {}
		for key, cell in self.state().iteritems():
			if cell.persists():
				state[key] = cell.get()
		return state
	
	def state_from_json(self, state):
		cells = self.state()
		defer = []
		for key in state:
			def err(adjective, suffix):
				# TODO better printing/logging, ship to client
				print 'Warning: Discarding ' + adjective + ' state', str(self) + '.' + key, '=', state[key], suffix
			cell = cells.get(key, None)
			if cell is None:
				err('nonexistent', '')
			elif cell.isBlock():
				defer.append(key)
			elif not cell.isWritable():
				err('non-writable', '')
			else:
				try:
					cells[key].set(state[key])
				except (LookupError, TypeError, ValueError) as e:
					# a plausible set of exceptions, so we don't catch implausible ones
					err('erroneous', '(' + str(e) + ')')
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
	def __init__(self, collection):
		self.__collection = collection
	
	# TODO: We will eventually want to allow for changes in the collection, which means disabling ExportedState's internal cache
	def state_def(self, callback):
		super(CollectionState, self).state_def(callback)
		for key in self.__collection:
			callback(CollectionMemberCell(self.__collection, key))
	

class NoneESType(ExportedState):
	'''Used like None but implementing ExportedState.'''
	def state_def(self, callback):
		super(NoneESType, self).state_def(callback)


NoneES = NoneESType()


def type_to_json(t):
	if str(t) == 'sdr.top.SpectrumTypeStub':
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
	
	def type_to_json(self):
		return {'type': 'enum', 'values': self.__values}
	
	def __call__(self, specimen):
		if specimen not in self.__values:
			raise ValueError('Not a permitted value: ' + repr(specimen))
		return specimen


class Range(ValueType):
	def __init__(self, min, max, strict=True, logarithmic=False, integer=False):
		self.__min = min
		self.__max = max
		self.__strict = strict
		self.__logarithmic = logarithmic
		self.__integer = integer
	
	def type_to_json(self):
		return {
			'type': 'range',
			'min': self.__min,
			'max': self.__max,
			'logarithmic': self.__logarithmic,
			'integer': self.__integer
		}
	
	def __call__(self, specimen):
		specimen = float(specimen)
		if self.__integer:
			specimen = int(round(specimen))
		if self.__strict:
			if specimen < self.__min:
				specimen = self.__min
			if specimen > self.__max:
				specimen = self.__max
		return specimen
