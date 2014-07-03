# Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

# pylint: disable=unpacking-non-sequence, undefined-loop-variable, attribute-defined-outside-init, no-init
# (pylint is confused by our tuple-or-None in MessageSplitter and by our only-used-immediately closures over loop variables in state_from_json)


from __future__ import absolute_import, division

import array
import bisect
import struct

from twisted.internet import task, reactor as the_reactor
from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import gr

from shinysdr.types import type_to_json


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

	def isBlock(self):  # TODO underscore naming
		raise NotImplementedError()
	
	def key(self):
		return self._key

	def get(self):
		'''Return the value/object held by this cell.'''
		raise NotImplementedError()
	
	def set(self, value):
		'''Set the value held by this cell.'''
		raise NotImplementedError()
	
	def get_state(self):
		'''Return the value, or state of the object, held by this cell.'''
		raise NotImplementedError()
	
	def set_state(self, state):
		'''Set the value held by this cell, or set the state of the object held by this cell, as appropriate.'''
		raise NotImplementedError()
	
	def isWritable(self):  # TODO underscore naming
		return self._writable
	
	def persists(self):
		return self._persists
		
	def description(self):
		raise NotImplementedError()


class ValueCell(BaseCell):
	def __init__(self, target, key, ctor=None, **kwargs):
		BaseCell.__init__(self, target, key, **kwargs)
		self._ctor = ctor
	
	def isBlock(self):
		return False
	
	# implement abstract
	def get_state(self):
		return self.get()
	
	# implement abstract
	def set_state(self, value):
		return self.set(value)
	
	def type(self):
		return self._ctor
	
	def description(self):
		return {
			'kind': 'value',
			'type': type_to_json(self._ctor),
			'writable': self.isWritable(),
			'current': self.get()
		}


# TODO this name is historical and should be changed
class Cell(ValueCell):
	def __init__(self, target, key, writable=False, persists=None, ctor=None):
		if persists is None: persists = writable
		ValueCell.__init__(self, target, key, writable=writable, persists=persists, ctor=ctor)
		self._getter = getattr(self._target, 'get_' + key)
		if writable:
			self._setter = getattr(self._target, 'set_' + key)
		else:
			self._setter = None
	
	def get(self):
		return self._getter()
	
	def set(self, value):
		if not self.isWritable():
			raise Exception('Not writable.')
		return self._setter(self._ctor(value))


sizeof_float = 4


class MessageSplitter(object):
	def __init__(self, queue, info_getter, close):
		self.__queue = queue
		self.__igetter = info_getter
		self.__splitting = None
		self.close = close  # provided as method
	
	def get(self, binary=False):
		if self.__splitting is not None:
			(string, itemsize, count, index) = self.__splitting
		else:
			queue = self.__queue
			# we would use .delete_head_nowait() but it returns a crashy wrapper instead of a sensible value like None. So implement a test (which is safe as long as we're the only reader)
			if queue.empty_p():
				return None
			else:
				message = queue.delete_head()
			if message.length() > 0:
				string = message.to_string()  # only interface available
			else:
				string = ''  # avoid crash bug
			itemsize = int(message.arg1())
			count = int(message.arg2())
			index = 0
		assert index < count
		
		# update state
		if index == count - 1:
			self.__splitting = None
		else:
			self.__splitting = (string, itemsize, count, index + 1)
		
		# extract value
		# TODO: this should be a separate concern, refactor
		itemStr = string[itemsize * index:itemsize * (index + 1)]
		if binary:
			# TODO: for general case need to have configurable format string
			value = struct.pack('dd', *self.__igetter()) + itemStr
		else:
			# TODO: allow caller to provide format info (nontrivial in case of runtime variable length)
			unpacker = array.array('f')
			unpacker.fromstring(itemStr)
			value = (self.__igetter(), unpacker.tolist())
		return value


class StreamCell(ValueCell):
	def __init__(self, target, key, ctor=None):
		ValueCell.__init__(self, target, key, writable=False, persists=False, ctor=ctor)
		self._dgetter = getattr(self._target, 'get_' + key + '_distributor')
		self._igetter = getattr(self._target, 'get_' + key + '_info')
	
	def subscribe(self):
		queue = gr.msg_queue()
		self._dgetter().subscribe(queue)
		
		def close():
			self._dgetter().unsubscribe(queue)
		
		return MessageSplitter(queue, self._igetter, close)
	
	def get(self):
		# TODO does not do proper value transformation here
		return self._dgetter().get()
	
	def set(self, value):
		raise Exception('StreamCell is not writable.')


class BaseBlockCell(BaseCell):
	def __init__(self, target, key, persists=True):
		BaseCell.__init__(self, target, key, writable=False, persists=persists)
	
	def isBlock(self):
		return True
	
	def get(self):
		# TODO middle of refactoring
		return self.getBlock()
	
	def set(self, value):
		# TODO middle of refactoring
		raise Exception('BaseBlockCell is not writable.')
	
	def get_state(self):
		# TODO middle of refactoring
		return self.getBlock().state_to_json()
	
	def set_state(self, value):
		return self.getBlock().state_from_json(value)
	
	def description(self):
		return self.getBlock().state_description()

	def getBlock(self):
		raise NotImplementedError()


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
		# fallback to nullExportedState so that if we become invalid in a dynamic collection we don't break
		return self._target._collection.get(self._key, nullExportedState)


class ISubscribableCell(Interface):
	def subscribe(callback):
		'''
		(TODO main doc)
		
		Note that the callback may be called _immediately_ upon value change; the callback should therefore avoid taking significant actions until later.
		'''
		pass


class LooseCell(ValueCell):
	'''
	A cell which stores a value and does not get it from another object; it can therefore reliably provide update notifications.
	'''
	implements(ISubscribableCell)
	
	# TODO: the 'ctor' name is historic and wrong
	def __init__(self, key, value, ctor, persists=True, writable=False, post_hook=None):
		'''
		The key is not used by the cell itself.
		'''
		ValueCell.__init__(
			self,
			target=object(),
			key=key,
			ctor=ctor,
			persists=persists,
			writable=writable)
		self.__value = value
		self.__subscriptions = set()
		self.__post_hook = post_hook

	def get(self):
		return self.__value
	
	def set(self, value):
		value = self._ctor(value)
		self.__value = value
		
		# triggers before the subscriptions to allow for updating related internal state
		if self.__post_hook is not None:
			self.__post_hook(value)
		
		self._fire()
	
	def set_internal(self, value):
		# TODO: More cap-ish strategy to handle this
		'''For use only by the "owner" to report updates.'''
		self.__value = value
		self._fire()
	
	def _fire(self):
		for subscription in self.__subscriptions:
			# TODO: in sync with Poller, add passing the value in here
			subscription._fire()
	
	def subscribe(self, callback):
		subscription = _LooseCellSubscription(self, callback)
		self.__subscriptions.add(subscription)
		return subscription
	
	def _unsubscribe(self, subscription):
		'''for use by the subscription only'''
		self.__subscriptions.remove(subscription)


class _LooseCellSubscription(object):
	def __init__(self, cell, callback):
		self._fire = callback
		self.__cell = cell

	def unsubscribe(self):
		self.__cell._unsubscribe(self)



class ExportedState(object):
	def state_def(self, callback):
		'''Override this to call the callback with additional cells.'''
		pass
	
	def state_insert(self, key, desc):
		raise ValueError('state_insert not defined on %r' % self)
	
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
						raise LookupError('Bad getter name', k)
					else:
						k = k[len('get_'):]
					cache[k] = v.make_cell(self, k)
			
		return self.__cache
	
	def state_to_json(self):
		state = {}
		for key, cell in self.state().iteritems():
			if cell.persists():
				state[key] = cell.get_state()
		return state
	
	def state_from_json(self, state):
		cells = self.state()
		dynamic = self.state_is_dynamic()
		defer = []
		for key in state:
			def err(adjective, suffix):
				# TODO ship to client
				log.msg('Warning: Discarding ' + adjective + ' state', str(self) + '.' + key, '=', state[key], suffix)
			
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
				doTry(lambda: cells[key].set_state(state[key]))
		# blocks are deferred because the specific blocks may depend on other keys
		for key in defer:
			cells[key].set_state(state[key])

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


class NullExportedState(ExportedState):
	'''An ExportedState object containing no cells, for use analogously to None.'''
	pass


nullExportedState = NullExportedState()


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


class IWritableCollection(Interface):
	'''
	Marker that a dynamic state object should expose create/delete operations
	'''


def exported_value(**cell_kwargs):
	'''Decorator for exported state; takes Cell's kwargs.'''
	def decorator(f):
		return ExportedGetter(f, cell_kwargs)
	return decorator


def setter(f):
	'''Decorator for setters of exported state; must be paired with a getter'''
	return ExportedSetter(f)


class ExportedGetter(object):
	'''Descriptor for a getter exported using @exported_value.'''
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
			kwargs = kwargs.copy()
			kwargs['ctor'] = kwargs['ctor_fn'](obj)
			del kwargs['ctor_fn']
		# TODO kludgy introspection, figure out what is better
		writable = hasattr(obj, 'set_' + attr) and isinstance(getattr(type(obj), 'set_' + attr), ExportedSetter)
		return Cell(obj, attr, writable=writable, **kwargs)


class ExportedSetter(object):
	'''Descriptor for a setter exported using @setter.'''
	def __init__(self, f):
		# TODO: Coerce value with ctor?
		self.__function = f
	
	def __get__(self, obj, type=None):
		'''implements method binding'''
		if obj is None:
			return self
		else:
			return self.__function.__get__(obj, type)


class _SortedMultimap(object):
	'''
	Support for Poller.
	Properties not explained by the name:
	* Values must be unique within a given key.
	* Keys are iterated in sorted order (values are not)
	'''
	def __init__(self):
		# key -> set(values)
		self.__dict = {}
		# keys in sorted order
		self.__sorted = []
		# count of values (= count of pairs)
		self.__value_count = 0
	
	def iter_snapshot(self):
		# TODO: consider not exposing the value sets directly, especially as this allows noticing mutation
		return ((key, self.__dict[key]) for key in self.__sorted)
	
	def add(self, key, value):
		if key in self.__dict:
			values = self.__dict[key]
		else:
			values = set()
			self.__dict[key] = values
			bisect.insort(self.__sorted, key)
		if value in values:
			raise KeyError('Duplicate add: %r' % ((key, value),))
		values.add(value)
		self.__value_count += 1
	
	def remove(self, key, value):
		'''Returns true if the value was the last value for that key'''
		if key not in self.__dict:
			raise KeyError('No key to remove: %r' % ((key, value),))
		values = self.__dict[key]
		if value not in values:
			raise KeyError('No value to remove: %r' % ((key, value),))
		values.remove(value)
		self.__value_count -= 1
		last_out = len(values) == 0
		if last_out:
			sorted = self.__sorted
			del self.__dict[key]
			index = bisect.bisect_left(sorted, key)
			if sorted[index] != key:
				raise Exception("can't happen")
			sorted[index:index + 1] = []
		return last_out
	
	def count_keys(self):
		return len(self.__dict)
	
	def count_values(self):
		return self.__value_count


class Poller(object):
	'''
	Polls cells for new values.
	'''
	
	def __init__(self):
		# sorting provides determinism for testing etc.
		self.__targets = _SortedMultimap()
		self.__functions = []
	
	def subscribe(self, cell, callback):
		if not isinstance(cell, BaseCell):
			# we're not actually against duck typing here; this is a sanity check
			raise TypeError('Poller given a non-cell %r' % (cell,))
		if ISubscribableCell.providedBy(cell):
			return _NonPollingSubscription(self, cell, callback)
		if isinstance(cell, StreamCell):  # TODO kludge; use generic interface
			return _PollerSubscription(self, _PollerStreamTarget(cell), callback)
		else:
			return _PollerSubscription(self, _PollerValueTarget(cell), callback)
	
	# TODO: consider replacing this with a special derived cell
	def subscribe_state(self, obj, callback):
		if not isinstance(obj, ExportedState):
			# we're not actually against duck typing here; this is a sanity check
			raise TypeError('Poller given a non-ES %r' % (obj,))
		return _PollerSubscription(self, _PollerStateTarget(obj), callback)
	
	def _add_subscription(self, target, subscription):
		self.__targets.add(target, subscription)
	
	def _remove_subscription(self, target, subscription):
		last_out = self.__targets.remove(target, subscription)
		if last_out:
			target.unsubscribe()
	
	def poll(self):
		for target, subscriptions in self.__targets.iter_snapshot():
			def fire(*args, **kwargs):
				for s in subscriptions:
					s._fire(*args, **kwargs)
			
			target.poll(fire)
		
		functions = self.__functions
		if len(functions) > 0:
			self.__functions = []
			for function in functions:
				function()
	
	def queue_function(self, function, *args, **kwargs):
		'''Queue a function to be called on the same schedule as the poller would.'''
		def thunk():
			function(*args, **kwargs)
		
		self.__functions.append(thunk)


class AutomaticPoller(Poller):
	def __init__(self):
		# not paramterized with reactor because LoopingCall isn't anyway
		Poller.__init__(self)
		self.__loop = task.LoopingCall(self.poll)
		self.__started = False
	
	def _add_subscription(self, target, subscription):
		# Hook to start call
		super(AutomaticPoller, self)._add_subscription(target, subscription)
		if not self.__started:
			self.__started = True
			# TODO: eventually there should be selectable schedules for different cells / clients
			# using callLater because start will call _immediately_ :(
			the_reactor.callLater(0, self.__loop.start, 1.0 / 61)


the_poller = AutomaticPoller()


class _PollerSubscription(object):
	def __init__(self, poller, target, callback):
		self._fire = callback
		self._target = target
		self._poller = poller
		poller._add_subscription(target, self)
	
	def unsubscribe(self):
		self._poller._remove_subscription(self._target, self)


class _NonPollingSubscription(object):
	def __init__(self, poller, cell, callback):
		self._poller = poller
		self._callback = callback
		self._cell_subscription = cell.subscribe(self._fire)
	
	def unsubscribe(self):
		self._cell_subscription.unsubscribe()
	
	def _fire(self):
		self._poller.queue_function(self._callback)


class _PollerTarget(object):
	def __init__(self, obj):
		self._obj = obj
		self._subscriptions = []
	
	def __eq__(self, other):
		return type(self) == type(other) and self._obj == other._obj
	
	def __hash__(self):
		return hash(self._obj)
	
	def poll(self, fire):
		'''Call fire (with arbitrary info in args) if the thing polled has changed.'''
		raise NotImplementedError()
	
	def unsubscribe(self):
		pass


class _PollerValueTarget(_PollerTarget):
	def __init__(self, cell):
		_PollerTarget.__init__(self, cell)
		self.__previous_value = self.__get()

	def __get(self):
		if self._obj.isBlock():  # TODO kill this distinction
			return  self._obj.getBlock()
		else:
			return self._obj.get()

	def poll(self, fire):
		value = self.__get()
		if value != self.__previous_value:
			self.__previous_value = value
			# TODO should pass value in to avoid redundant gets
			fire()


class _PollerStateTarget(_PollerTarget):
	def __init__(self, block):
		_PollerTarget.__init__(self, block)
		self.__previous_structure = None  # unequal to any state dict
		self.__dynamic = block.state_is_dynamic()

	def poll(self, fire):
		obj = self._obj
		if self.__dynamic or self.__previous_structure is None:
			now = obj.state()
			if now != self.__previous_structure:
				self.__previous_structure = now
				fire(now)


class _PollerStreamTarget(_PollerTarget):
	# TODO there are no tests for stream subscriptions
	def __init__(self, cell):
		_PollerTarget.__init__(self, cell)
		self.__subscription = cell.subscribe()

	def poll(self, fire):
		subscription = self.__subscription
		while True:
			value = subscription.get(binary=True)  # TODO inflexible
			if value is None: break
			fire(value)

	def unsubscribe(self):
		self.__subscription.close()
		super(_PollerStreamTarget, self).unsubscribe()

