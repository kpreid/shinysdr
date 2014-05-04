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
import struct

from twisted.python import log
from zope.interface import Interface  # available via Twisted

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
	
	def isBlock(self):
		return False
	
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
		return self.getBlock().state_to_json()
	
	def set(self, value):
		self.getBlock().state_from_json(value)
	
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
				state[key] = cell.get()
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


class Poller(object):
	'''
	Polls cells for new values.
	'''
	
	def __init__(self):
		self._subscriptions = set()
		self._subscriptions_sorted = []
	
	def subscribe(self, cell, callback):
		if not isinstance(cell, BaseCell):
			# we're not actually against duck typing here; this is a sanity check
			raise TypeError('Poller given a non-cell %r' % (cell,))
		if isinstance(cell, StreamCell):  # TODO kludge; use generic interface
			return _PollerStreamSubscription(self, cell, callback)
		else:
			return _PollerValueSubscription(self, cell, callback)
	
	# TODO: consider replacing this with a special derived cell
	def subscribe_state(self, obj, callback):
		if not isinstance(obj, ExportedState):
			# we're not actually against duck typing here; this is a sanity check
			raise TypeError('Poller given a non-ES %r' % (obj,))
		return _PollerStateSubscription(self, obj, callback)
	
	def _add_subscription(self, subscription):
		self._subscriptions.add(subscription)
		# sorting provides determinism for testing etc.
		self._subscriptions_sorted.append(subscription)
		self._subscriptions_sorted.sort()
	
	def _remove_subscription(self, subscription):
		self._subscriptions.remove(subscription)
		self._subscriptions_sorted = list(self._subscriptions)
		self._subscriptions_sorted.sort()
	
	def poll(self):
		for subscription in self._subscriptions_sorted:
			subscription._poll()


class _PollerSubscription(object):
	def __init__(self, poller, cell, callback):
		self._cell = cell
		self._callback = callback
		self._poller = poller
		poller._add_subscription(self)
	
	def poll_now(self):
		self._poll()
	
	def _poll(self):
		raise NotImplementedError()
	
	def unsubscribe(self):
		if self not in self._poller._subscriptions:
			raise Exception('This subscription already unsubscribed')
		self._poller._remove_subscription(self)


class _PollerValueSubscription(_PollerSubscription):
	def __init__(self, poller, cell, callback):
		_PollerSubscription.__init__(self, poller, cell, callback)
		self.__previous_value = object()  # arbitrary unequal value, should never be seen

	def _poll(self):
		# TODO not fully implemented
		if self._cell.isBlock():  # TODO kill this distinction
			value = self._cell.getBlock()
		else:
			value = self._cell.get()
		if value != self.__previous_value:
			self.__previous_value = value
			# TODO should pass value in to avoid redundant gets
			self._callback()


class _PollerStateSubscription(_PollerSubscription):
	def __init__(self, poller, obj, callback):
		_PollerSubscription.__init__(self, poller, obj, callback)
		self.__previous_structure = None  # unequal to any state dict
		self.__dynamic = obj.state_is_dynamic()

	def _poll(self):
		obj = self._cell  # TODO unfortunate naming
		if self.__dynamic or self.__previous_structure is None:
			now = obj.state()
			if now != self.__previous_structure:
				self.__previous_structure = now
				self._callback(now)


class _PollerStreamSubscription(_PollerSubscription):
	# TODO there are no tests for stream subscriptions
	def __init__(self, poller, cell, callback):
		_PollerSubscription.__init__(self, poller, cell, callback)
		self.__subscription = cell.subscribe()

	def _poll(self):
		subscription = self.__subscription
		while True:
			value = subscription.get(binary=True)  # TODO inflexible
			if value is None: break
			self._callback(value)
	
	def unsubscribe(self):
		super(_PollerStreamSubscription, self).unsubscribe()
		self.__subscription.close()

