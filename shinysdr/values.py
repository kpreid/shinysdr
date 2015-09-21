# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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


# pylint: disable=unpacking-non-sequence, undefined-loop-variable, attribute-defined-outside-init, no-init, abstract-method, redefined-builtin, arguments-differ
# (pylint is confused by our tuple-or-None in _MessageSplitter and by our only-used-immediately closures over loop variables in state_from_json)
# (abstract-method: pylint is confused by the cell type hierarchy)
# (redefined-builtin: we want named args named "type")
# (arguments-differ: pylint is confused, don't know why)

from __future__ import absolute_import, division

import array
import bisect
import struct
import weakref

from twisted.internet import task, reactor as the_reactor
from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import gr

from shinysdr.types import BulkDataType, to_value_type


class BaseCell(object):
    def __init__(self, target, key, persists=True, writable=False):
        # The exact relationship of target and key depends on the subtype
        self._target = target
        self._key = key
        self._persists = persists
        self._writable = writable
    
    def __cmp__(self, other):
        if not isinstance(other, BaseCell):
            return cmp(id(self), id(other))  # dummy
        elif self._target == other._target and self._key == other._key:
            # pylint: disable=unidiomatic-typecheck
            if type(self) != type(other):
                # No two cells should have the same target and key but different details.
                # This is not a perfect test
                raise Exception("Shouldn't happen")
            return 0
        else:
            return cmp(self._key, other._key) or cmp(self._target, other._target)
    
    def __hash__(self):
        return hash(self._target) ^ hash(self._key)

    def isBlock(self):  # TODO underscore naming
        # TODO this should be moved into the type
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
    def __init__(self, target, key, type, **kwargs):
        BaseCell.__init__(self, target, key, **kwargs)
        self._value_type = to_value_type(type)
    
    def isBlock(self):
        return False
    
    # implement abstract
    def get_state(self):
        return self.get()
    
    # implement abstract
    def set_state(self, value):
        return self.set(value)
    
    def type(self):
        return self._value_type
    
    def description(self):
        return {
            'kind': 'value',
            'type': self._value_type.type_to_json(),
            'writable': self.isWritable(),
            'current': self.get()
        }


# TODO this name is historical and should be changed
class Cell(ValueCell):
    def __init__(self, target, key, type=to_value_type(object), writable=False, persists=None):
        if persists is None: persists = writable
        ValueCell.__init__(self, target, key, writable=writable, persists=persists, type=type)
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
        return self._setter(self._value_type(value))


class _MessageSplitter(object):
    def __init__(self, queue, info_getter, close, type):
        '''
        info_format: format string as used by the struct module
        array_format: type code as used by the array module
        '''
        # config
        self.__queue = queue
        self.__igetter = info_getter
        self.__type = type
        self.close = close  # provided as method
        
        # state
        self.__splitting = None
    
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
        item_string = string[itemsize * index:itemsize * (index + 1)]
        if binary:
            # In binary mode, pack info with already-binary data.
            value = struct.pack(self.__type.get_info_format(), *self.__igetter()) + item_string
        else:
            # In python-value mode, unpack binary data.
            unpacker = array.array(self.__type.get_array_format())
            unpacker.fromstring(item_string)
            value = (self.__igetter(), unpacker.tolist())
        return value


class StreamCell(ValueCell):
    def __init__(self, target, key, type=None):
        assert isinstance(type, BulkDataType)
        ValueCell.__init__(self, target, key, writable=False, persists=False, type=type)
        self.__dgetter = getattr(self._target, 'get_' + key + '_distributor')
        self.__igetter = getattr(self._target, 'get_' + key + '_info')
    
    def subscribe(self):
        queue = gr.msg_queue()
        self.__dgetter().subscribe(queue)
        
        def close():
            self.__dgetter().unsubscribe(queue)
        
        return _MessageSplitter(queue, self.__igetter, close, self.type())
    
    def get(self):
        # TODO does not do proper value transformation here
        return self.__dgetter().get()
    
    def set(self, value):
        raise Exception('StreamCell is not writable.')


class BaseBlockCell(BaseCell):
    def __init__(self, target, key, persists=True):
        BaseCell.__init__(self, target, key, writable=False, persists=persists)
    
    def isBlock(self):
        return True
    
    # get() is still abstract
    
    def set(self, value):
        raise Exception('BaseBlockCell is not writable.')
    
    def get_state(self):
        return self.get().state_to_json()
    
    def set_state(self, value):
        return self.get().state_from_json(value)
    
    def description(self):
        return self.get().state_description()


# TODO: get() code is same as Cell (value-type cell). Refactoring in progress to make block cells less magic.
class BlockCell(BaseBlockCell):
    def __init__(self, target, key, persists=True):
        BaseBlockCell.__init__(self, target, key, persists=persists)
        self._getter = getattr(self._target, 'get_' + key)
    
    def get(self):
        block = self._getter()
        assert isinstance(block, ExportedState), (self._target, self._key)
        return block


# TODO: It's unclear whether or not the Cell design makes sense in light of this. We seem to have conflated the index in the container and the type of the contained into one object.
class CollectionMemberCell(BaseBlockCell):
    def __init__(self, target, key, persists=True):
        BaseBlockCell.__init__(self, target, key, persists=persists)
        self.__last_seen = nullExportedState
    
    def get(self):
        # fallback to old value so that if we become invalid in a dynamic collection we don't break
        value = self._target._collection.get(self._key, self.__last_seen)
        self.__last_seen = value
        return value


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
    
    def __init__(self, key, value, type, persists=True, writable=False, post_hook=None):
        '''
        The key is not used by the cell itself.
        '''
        ValueCell.__init__(
            self,
            target=object(),
            key=key,
            type=type,
            persists=persists,
            writable=writable)
        self.__value = value
        self.__subscriptions = set()
        self.__post_hook = post_hook

    def get(self):
        return self.__value
    
    def set(self, value):
        value = self._value_type(value)
        if self.__value == value:
            return
        
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


def ViewCell(base, get_transform, set_transform, **kwargs):
    '''
    A Cell whose value is always a transformation of another.
    
    TODO: Stop implementing this as LooseCell.
    '''
    
    def forward(view_value):
        base_value = set_transform(view_value)
        base.set(base_value)
        if base_value != base.get():
            reverse()
    
    def reverse():
        self.set(get_transform(base.get()))
    
    self = LooseCell(
        value=get_transform(base.get()),
        post_hook=forward,
        **kwargs)
    
    sub = base.subscribe(reverse)
    weakref.ref(self, lambda: sub.unsubscribe())
        
    return self


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
            # pylint: disable=cell-var-from-loop
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


def unserialize_exported_state(ctor, kwargs=None, state=None):
    all_kwargs = {}
    if kwargs is not None:
        # note that persistence overrides provided kwargs
        all_kwargs.update(kwargs)
    not_yet_set_state = {}
    if state is not None:
        not_yet_set_state.update(state)
    for key, value in not_yet_set_state.items():
        getter_name = 'get_' + key  # TODO centralize or eliminate naming scheme
        if not hasattr(ctor, getter_name): continue
        getter = getattr(ctor, getter_name)
        if not isinstance(getter, ExportedGetter): continue
        this_kwargs = getter.state_to_kwargs(value)
        if this_kwargs is None: continue
        all_kwargs.update(this_kwargs)
        del not_yet_set_state[key]
    obj = ctor(**all_kwargs)
    if len(not_yet_set_state) > 0:
        obj.state_from_json(not_yet_set_state)
    return obj


class INull(Interface):
    '''Marker for nullExportedState.'''


class NullExportedState(ExportedState):
    '''An ExportedState object containing no cells, for use analogously to None.'''
    implements(INull)


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


def exported_value(parameter=None, **cell_kwargs):
    '''Decorator for exported state; takes Cell's kwargs.'''
    def decorator(f):
        return ExportedGetter(f, parameter, False, cell_kwargs)
    return decorator


# TODO: @exported_block() maybe should become @exported_value(type=block), depending on how cell types get refactored.
def exported_block(parameter=None, **cell_kwargs):
    '''Decorator for exported state; takes BlockCell's kwargs.'''
    def decorator(f):
        return ExportedGetter(f, parameter, True, cell_kwargs)
    return decorator


def setter(f):
    '''Decorator for setters of exported state; must be paired with an @exported_value getter.'''
    return ExportedSetter(f)


class ExportedGetter(object):
    '''Descriptor for a getter exported using @exported_value.'''
    def __init__(self, f, parameter, is_block, cell_kwargs):
        self.__function = f
        self.__parameter = parameter
        self.__is_block = is_block
        self.__cell_kwargs = cell_kwargs
    
    def __get__(self, obj, type=None):
        '''implements method binding'''
        if obj is None:
            return self
        else:
            return self.__function.__get__(obj, type)
    
    def make_cell(self, obj, attr):
        kwargs = self.__cell_kwargs
        if 'type_fn' in kwargs:
            if 'type' in kwargs:
                raise ValueError('cannot specify both type and type_fn')
            kwargs = kwargs.copy()
            kwargs['type'] = kwargs['type_fn'](obj)
            del kwargs['type_fn']
        # TODO kludgy introspection, figure out what is better
        writable = hasattr(obj, 'set_' + attr) and isinstance(getattr(type(obj), 'set_' + attr), ExportedSetter)
        if self.__is_block:
            assert not writable
            return BlockCell(obj, attr, **kwargs)
        else:
            return Cell(obj, attr, writable=writable, **kwargs)
    
    def state_to_kwargs(self, value):
        if self.__parameter is not None:
            return {self.__parameter: self.__cell_kwargs['type'](value)}


class ExportedSetter(object):
    '''Descriptor for a setter exported using @setter.'''
    def __init__(self, f):
        # TODO: Coerce with value type?
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
            sorted_list = self.__sorted
            del self.__dict[key]
            index = bisect.bisect_left(sorted_list, key)
            if sorted_list[index] != key:
                # TODO: This has been observed to happen. Need to diagnose.
                raise Exception("can't happen: while removing last value %r for key %r from %r, %r was found instead of the key at index %r in the sorted list" % (value, key, self, sorted_list[index], index))
            sorted_list[index:index + 1] = []
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
            # pylint: disable=cell-var-from-loop
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
    
    def __cmp__(self, other):
        return cmp(type(self), type(other)) or cmp(self._obj, other._obj)
    
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
