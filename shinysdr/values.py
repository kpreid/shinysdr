# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

# TODO: Document this module.

# pylint: disable=redefined-builtin
# (we have keyword args named 'type')

from __future__ import absolute_import, division

import array
from collections import namedtuple
import struct
import weakref

from twisted.python import log
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import gr

from shinysdr.types import BulkDataType, Reference, to_value_type


# TODO move this decl somewhere sensible once the code exists
_cell_value_change_schedules = [
    u'never',  # immutable value.
    u'continuous',  # a different value almost every time
    u'this_setter',  # the setter for this cell
    u'this_object',  # any setter for any cell on this object
    u'global',  # might depend on any other non-continuous cell in the system
    u'placeholder_slow',  # things we want to replace, but for now are polled slow
]


# TODO: probably not the right thing, placeholder till subscriptions are more worked out
SubscriptionContext = namedtuple('SubscriptionContext', ['reactor', 'poller'])


class BaseCell(object):
    def __init__(self, target, key, type, persists=True, writable=False):
        # The exact relationship of target and key depends on the subtype
        self._target = target
        self._key = key
        self._persists = persists
        self._writable = writable
        self._value_type = to_value_type(type)
    
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

    def type(self):
        return self._value_type
    
    def key(self):
        return self._key

    def get(self):
        """Return the value/object held by this cell."""
        raise NotImplementedError()
    
    def set(self, value):
        """Set the value held by this cell."""
        raise NotImplementedError()
    
    def get_state(self):
        """Return the value, or state of the object, held by this cell."""
        if self.type().is_reference():
            return self.get().state_to_json()
        else:
            return self.get()
    
    def set_state(self, state):
        """Set the value held by this cell, or set the state of the object held by this cell, as appropriate."""
        if self.type().is_reference():
            self.get().state_from_json(state)
        else:
            self.set(state)
    
    def subscribe2(self, callback, context):
        # TODO: 'subscribe2' name is temporary for easy distinguishing this from other 'subscribe' protocols.
        """Request to be notified when this cell's value changes.
        
        The 'callback' will be called repeatedly with successive new cell values; never immediately.
        
        The return value is an object with a 'unsubscribe' method which will remove the subscription.
        """
        raise NotImplementedError(self)
    
    def isWritable(self):  # TODO underscore naming
        return self._writable
    
    def persists(self):
        return self._persists
        
    def description(self):
        raise NotImplementedError()
    
    def __repr__(self):
        return '<{type} {self._target!r}.{self._key}>'.format(type=type(self).__name__, self=self)


class ValueCell(BaseCell):
    # pylint: disable=abstract-method
    # (we are also abstract)
    
    def __init__(self, target, key, type, **kwargs):
        BaseCell.__init__(self, target, key, type=type, **kwargs)
    
    def description(self):
        d = {
            'kind': 'value',
            'type': self.type().type_to_json(),
            'writable': self.isWritable()
        }
        if not self.type().is_reference():  # TODO kludge
            d[u'current'] = self.get()
        return d


# TODO this name is historical and should be changed
class Cell(ValueCell):
    def __init__(self, target, key, changes, type=object, writable=False, persists=None):
        assert changes in _cell_value_change_schedules  # TODO actually use value
        type = to_value_type(type)
        if persists is None:
            persists = writable or type.is_reference()
        
        if changes == u'continuous' and persists:
            raise ValueError('persists=True changes={!r} is not allowed'.format(changes))
        if changes == u'never' and writable:
            raise ValueError('writable=True changes={!r} doesn\'t make sense'.format(changes))
        
        ValueCell.__init__(self, target, key, writable=writable, persists=persists, type=type)
        
        self.__changes = changes
        if changes == u'explicit':
            self.__explicit_subscriptions = set()
            self.__last_polled_value = object()
        self._getter = getattr(self._target, 'get_' + key)
        if writable:
            self._setter = getattr(self._target, 'set_' + key)
        else:
            self._setter = None
    
    def get(self):
        value = self._getter()
        if self.type().is_reference():
            # informative-failure debugging aid
            assert isinstance(value, ExportedState), (self._target, self._key)
        return value
    
    def set(self, value):
        if not self.isWritable():
            raise Exception('Not writable.')
        return self._setter(self._value_type(value))
    
    def subscribe2(self, callback, context):
        return context.poller.subscribe(self, lambda: callback(self.get()))


class _MessageSplitter(object):
    def __init__(self, queue, info_getter, close, type):
        """
        type: must be a BulkDataType
        """
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
        ValueCell.__init__(self, target, key, type=type, writable=False, persists=False)
        self.__dgetter = getattr(self._target, 'get_' + key + '_distributor')
        self.__igetter = getattr(self._target, 'get_' + key + '_info')
    
    def subscribe2(self, callback, context):
        # poller does StreamCell-specific things, including passing a value where most subscriptions don't. TODO: make Poller uninvolved
        return context.poller.subscribe(self, callback)
    
    # TODO: eliminate this specialized protocol used by Poller
    def subscribe_to_stream(self):
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


class CollectionMemberCell(ValueCell):
    def __init__(self, target, key, type, persists=True):
        ValueCell.__init__(self, target, key, type=type, writable=False, persists=persists)
        self.__last_seen = nullExportedState  # TODO: no longer the best choice
    
    def get(self):
        # fallback to old value so that if we become invalid in a dynamic collection we don't break
        value = self._target._collection.get(self._key, self.__last_seen)
        self.__last_seen = value
        return value
    
    def set(self, value):
        raise Exception('CollectionMemberCell is not writable.')

    def subscribe2(self, callback, context):
        return context.poller.subscribe(self, lambda: callback(self.get()))


class LooseCell(ValueCell):
    """
    A cell which stores a value and does not get it from another object; it can therefore reliably provide update notifications.
    """
    
    def __init__(self, key, value, type, persists=True, writable=False, post_hook=None):
        """
        The key is not used by the cell itself.
        """
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
        """For use only by the "owner" to report updates."""
        self.__value = value
        self._fire()
    
    def _fire(self):
        for subscription in self.__subscriptions:
            # TODO: in sync with Poller, add passing the value in here
            subscription._fire()
    
    def subscribe2(self, callback, context):
        subscription = _LooseCellSubscription(self, callback, context.reactor)
        self.__subscriptions.add(subscription)
        return subscription
    
    def _subscribe_immediate(self, callback):
        """for use by ViewCell only"""
        # TODO: replace this with a better mechanism
        subscription = _LooseCellImmediateSubscription(self, callback)
        self.__subscriptions.add(subscription)
        return subscription
    
    def _unsubscribe(self, subscription):
        """for use by the subscription only"""
        self.__subscriptions.remove(subscription)


class _LooseCellSubscription(object):
    def __init__(self, cell, callback, reactor):
        self.__callback = callback
        self.__reactor = reactor
        self.__cell = cell
    
    def _fire(self):
        # TODO: This is calling with a stale value. Do we want to tighten up and prohibit that in the specification of subscribe?
        self.__reactor.callLater(0, self.__callback, self.__cell.get())
    
    def unsubscribe(self):
        self.__cell._unsubscribe(self)


class _LooseCellImmediateSubscription(object):
    def __init__(self, cell, callback):
        self._fire = callback
    
    def unsubscribe(self):
        self.__cell._unsubscribe(self)


def ViewCell(base, get_transform, set_transform, **kwargs):
    """
    A Cell whose value is always a transformation of another.
    
    TODO: Stop implementing this as LooseCell.
    """
    
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
    
    sub = base._subscribe_immediate(reverse)
    weakref.ref(self, lambda: sub.unsubscribe())

    # Allows the cell to be put back in sync if the transform changes.
    # Not intended to be called except by the creator of the cell, but mostly harmless.
    self.changed_transform = reverse  # pylint: disable=attribute-defined-outside-init
    
    return self


class Command(BaseCell):
    """A Cell which does not primarily produce a value, but is a side-effecting operation that can be invoked.
    
    This is a Cell for reasons of convenience in the existing architecture, and because it has several similarities.
    
    Its value is (TODO should be something generically useful).
    """
    
    def __init__(self, target, key, function):
        # TODO: remove writable=true when we have a proper invoke path
        BaseCell.__init__(self,
            target=target,
            key=key,
            type=type(None),
            persists=False,
            writable=True)
        self.__function = function
    
    def description(self):
        """implements BaseCell"""
        # TODO: This is identicalish to ValueCell.description except for the kind.
        return {
            'kind': 'command',
            'type': self.type().type_to_json(),
            'writable': self.isWritable(),
            'current': self.get(),
        }
    
    def get(self):
        """implements BaseCell"""
        return None
    
    def set(self, _dummy_value):
        # raise Exception('Not writable.')
        # TODO: Make a separate command-triggering path, because this is a HORRIBLE KLUDGE.
        self.__function()
    
    def subscribe2(self, callback, context):
        """implements BaseCell"""
        return _NeverSubscription()


class _NeverSubscription(object):
    def unsubscribe(self):
        pass


class ExportedState(object):
    def state_def(self, callback):
        """Override this to call the callback with additional cells."""
        pass
    
    def state_insert(self, key, desc):
        raise ValueError('state_insert not defined on %r' % self)
    
    def state_is_dynamic(self):
        return False
    
    def state(self):
        # pylint: disable=attribute-defined-outside-init
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
                # TODO use an interface here and move the check inside
                if isinstance(v, ExportedGetter):
                    if not k.startswith('get_'):
                        # TODO factor out attribute name usage in Cell so this restriction is moot
                        raise LookupError('Bad getter name', k)
                    else:
                        k = k[len('get_'):]
                    cache[k] = v.make_cell(self, k)
                elif isinstance(v, ExportedCommand):
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
            # pylint: disable=cell-var-from-loop, undefined-loop-variable
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
            elif cell.type().is_reference():
                defer.append(key)
            elif not cell.isWritable():
                err('non-writable', '')
            else:
                doTry(lambda: cells[key].set_state(state[key]))
        # blocks are deferred because the specific blocks may depend on other keys
        for key in defer:
            cells[key].set_state(state[key])


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
    """Marker for nullExportedState."""


class NullExportedState(ExportedState):
    """An ExportedState object containing no cells, for use analogously to None."""
    implements(INull)


nullExportedState = NullExportedState()


class CollectionState(ExportedState):
    """Wrapper around a plain Python collection."""
    def __init__(self, collection, member_type=Reference(), dynamic=False):
        self._collection = collection  # accessed by CollectionMemberCell
        self.__keys = collection.keys()
        self.__cells = {}
        self.__dynamic = dynamic
        self.__member_type = to_value_type(member_type)
    
    def state_is_dynamic(self):
        return self.__dynamic
    
    def state_def(self, callback):
        super(CollectionState, self).state_def(callback)
        for key in self._collection:
            if key not in self.__cells:
                self.__cells[key] = CollectionMemberCell(self, key, self.__member_type)
            callback(self.__cells[key])


class IWritableCollection(Interface):
    """
    Marker that a dynamic state object should expose create/delete operations
    """


def exported_value(parameter=None, **cell_kwargs):
    """Returns a decorator for exported state; takes Cell's kwargs."""
    def decorator(f):
        return ExportedGetter(f, parameter, cell_kwargs)
    return decorator


# TODO: Maybe inline uses of this
def exported_block(parameter=None, **cell_kwargs):
    """Returns a decorator for exported state; takes Cell's kwargs."""
    return exported_value(type=Reference(), **cell_kwargs)


def setter(f):
    """Decorator for setters of exported state; must be paired with an @exported_value getter."""
    return ExportedSetter(f)


def command():
    """Returns a decorator for command methods."""
    return ExportedCommand


class ExportedGetter(object):
    """Descriptor for a getter exported using @exported_value or @exported_block."""
    def __init__(self, f, parameter, cell_kwargs):
        # early error for debugging
        if 'changes' not in cell_kwargs:
            raise TypeError('changes parameter missing')
        assert cell_kwargs['changes'] in _cell_value_change_schedules, cell_kwargs['changes']
        
        if 'type_fn' in cell_kwargs and 'type' in cell_kwargs:
            raise ValueError('cannot specify both "type" and "type_fn"')
        if 'type_fn' in cell_kwargs and parameter:
            raise ValueError('"type_fn" is incompatible with "parameter"')
        
        self.__function = f
        self.__parameter = parameter
        self.__cell_kwargs = cell_kwargs
    
    def __get__(self, obj, type=None):
        """implements method binding"""
        if obj is None:
            return self
        else:
            return self.__function.__get__(obj, type)
    
    def make_cell(self, obj, attr):
        kwargs = self.__cell_kwargs
        if 'type_fn' in kwargs:
            kwargs = kwargs.copy()
            kwargs['type'] = kwargs['type_fn'](obj)
            del kwargs['type_fn']
        # TODO kludgy introspection, figure out what is better
        writable = hasattr(obj, 'set_' + attr) and isinstance(getattr(type(obj), 'set_' + attr), ExportedSetter)
        return Cell(obj, attr, writable=writable, **kwargs)
    
    def state_to_kwargs(self, value):
        # clunky: invoked by unserialize_exported_state via a type test
        if self.__parameter is not None:
            return {self.__parameter: self.__cell_kwargs['type'](value)}


class ExportedSetter(object):
    """Descriptor for a setter exported using @setter."""
    
    # This has no relevant behavior of its own; it is merely searched for by its paired ExportedGetter.
    
    def __init__(self, f):
        # TODO: Coerce with value type?
        self.__function = f
    
    def __get__(self, obj, type=None):
        """implements method binding"""
        if obj is None:
            return self
        else:
            return self.__function.__get__(obj, type)


class ExportedCommand(object):
    """Descriptor for a command method exported using @command."""
    def __init__(self, f):
        self.__function = f
    
    def __get__(self, obj, type=None):
        """implements method binding"""
        if obj is None:
            return self
        else:
            return self.__function.__get__(obj, type)
    
    def make_cell(self, obj, attr):
        return Command(obj, attr, self.__get__(obj))
