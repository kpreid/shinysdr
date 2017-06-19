# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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
from zope.interface import Interface, implementer  # available via Twisted

from gnuradio import gr

from shinysdr.gr_ext import safe_delete_head_nowait
from shinysdr.types import BulkDataT, EnumRow, ReferenceT, to_value_type


class CellMetadata(namedtuple('CellMetadata', [
    'value_type',  # ValueType
    'persists',  # boolean
    'naming',  # EnumRow  (TODO rename EnumRow given this is the third alternate use)
])):
    """Information about a cell object.
    
    value_type: a ValueType object defining the possible values of the cell.
    The type may also be relevant to interpreting the value.
    
    persists: a boolean.
    Whether the value of this cell will be considered as part of the persistent state of the containing object for use across server restarts and such.
    
    naming: an EnumRow giving the 'human-readable' name of the cell and related information.
    """


class SubscriptionContext(namedtuple('SubscriptionContext', ['reactor', 'poller'])):
    """A SubscriptionContext is used when subscribing to a cell.
    
    The context's reactor and poller determine how and when the subscription callback is invoked once the cell value has changed.
    """


class BaseCell(object):
    def __init__(self,
            target,
            key,
            type,
            persists=True,
            writable=False,
            label=None,
            description=None,
            sort_key=None):
        # The exact relationship of target and key depends on the subtype
        self._target = target
        self._key = key
        self._writable = writable
        # TODO: Also allow specifying metadata object directly.
        self.__metadata = CellMetadata(
            value_type=to_value_type(type),
            persists=bool(persists),
            naming=EnumRow(
                associated_key=key,
                label=label,
                description=description,
                sort_key=sort_key))
    
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

    def metadata(self):
        return self.__metadata

    def type(self):
        return self.__metadata.value_type
    
    def key(self):
        return self._key

    def get(self):
        """Return the value/object held by this cell."""
        raise NotImplementedError()
    
    def set(self, value):
        """Set the value held by this cell."""
        raise NotImplementedError()
    
    def get_state(self, subscriber=lambda _: None):
        """Return the value, or state of the object, held by this cell.
        
        If 'subscriber' is provided, then it will be called with each relevant 'subscribe2' or 'state_subscribe' method as a parameter."""
        subscriber(self.subscribe2)
        if self.type().is_reference():
            return self.get().state_to_json(subscriber=subscriber)
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
    
    def poll_for_change(self, specific_cell):
        pass
    
    def isWritable(self):  # TODO underscore naming
        return self._writable
    
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
            u'type': u'value_cell',
            u'metadata': self.metadata(),
            u'writable': self.isWritable()
        }
        if not self.type().is_reference():  # TODO kludge
            d[u'current'] = self.get()
        return d


# The possible values of the 'changes' parameter to a cell of type Cell, which determine when the cell's getter is polled to check for changes.
_cell_value_change_schedules = [
    u'never',  # never changes at all for the lifetime of the cell
    u'continuous',  # a different value almost every time
    u'explicit',  # implementation will self-report via ExportedState.state_changed
    u'this_setter',  # changes when and only when the setter for this cell is called
]


# TODO this name is historical and should be changed
class Cell(ValueCell):
    def __init__(self, target, key, changes, type=object, writable=False, persists=None, **kwargs):
        assert changes in _cell_value_change_schedules  # TODO actually use value
        type = to_value_type(type)
        if persists is None:
            persists = writable or type.is_reference()
        
        if changes == u'continuous' and persists:
            raise ValueError('persists=True changes={!r} is not allowed'.format(changes))
        if changes == u'never' and writable:
            raise ValueError('writable=True changes={!r} doesn\'t make sense'.format(changes))
        
        ValueCell.__init__(self,
            target,
            key,
            type=type,
            persists=persists,
            writable=writable,
            **kwargs)
        
        self.__changes = changes
        if changes == u'explicit' or changes == u'this_setter':
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
        return self._setter(self.metadata().value_type(value))
    
    def subscribe2(self, callback, context):
        changes = self.__changes
        if changes == u'never':
            return _NeverSubscription()
        elif changes == u'continuous':
            return context.poller.subscribe(self, lambda: callback(self.get()), fast=True)
        elif changes == u'explicit' or changes == u'this_setter':
            return _SimpleSubscription(callback, context, self.__explicit_subscriptions)
        else:
            raise ValueError('shouldn\'t happen unrecognized changes value: {!r}'.format(changes))

    def poll_for_change(self, specific_cell):
        if not hasattr(self, '_Cell__explicit_subscriptions'):
            return
        value = self.get()
        if value != self.__last_polled_value:
            self.__last_polled_value = value
            for subscription in self.__explicit_subscriptions:
                subscription._fire(value)
    
    def poll_for_change_from_setter(self):
        if self.__changes == u'this_setter':
            self.poll_for_change(specific_cell=True)


class _MessageSplitter(object):
    """Wraps a gr.msg_queue, whose arg1 and arg2 are as in blocks.message_sink, to allow extracting one data item at a time by polling."""
    def __init__(self, queue, info_getter, close, type):
        """
        queue: a gr.msg_queue
        info_getter: function () -> anything; returned with data
        close: function () -> None; provided as a method
        type: a BulkDataT
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
            message = safe_delete_head_nowait(queue)
            if not message:
                return None
            string = message.to_string()
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
    def __init__(self, target, key, type, **kwargs):
        assert isinstance(type, BulkDataT)
        ValueCell.__init__(self, target, key, type=type, writable=False, persists=False, **kwargs)
        self.__dgetter = getattr(self._target, 'get_' + key + '_distributor')
        self.__igetter = getattr(self._target, 'get_' + key + '_info')
    
    def subscribe2(self, callback, context):
        # poller does StreamCell-specific things, including passing a value where most subscriptions don't. TODO: make Poller uninvolved
        return context.poller.subscribe(self, callback, fast=True)
    
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


class LooseCell(ValueCell):
    """
    A cell which stores a value and does not get it from another object; it can therefore reliably provide update notifications.
    """
    
    def __init__(self, key, value, post_hook=None, **kwargs):
        """
        The key is not used by the cell itself.
        """
        ValueCell.__init__(
            self,
            target=object(),
            key=key,
            **kwargs)
        self.__value = value
        self.__subscriptions = set()
        self.__post_hook = post_hook

    def get(self):
        return self.__value
    
    def set(self, value):
        value = self.metadata().value_type(value)
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
        value = self.get()
        for subscription in self.__subscriptions:
            subscription._fire(value)
    
    def subscribe2(self, callback, context):
        subscription = _SimpleSubscription(callback, context, self.__subscriptions)
        return subscription
    
    def _subscribe_immediate(self, callback):
        """for use by ViewCell only"""
        # TODO: replace this with a better mechanism
        subscription = _LooseCellImmediateSubscription(callback, self.__subscriptions)
        return subscription


class _SimpleSubscription(object):
    def __init__(self, callback, context, subscription_set):
        self.__callback = callback
        self.__reactor = context.reactor
        self.__subscription_set = subscription_set
        subscription_set.add(self)
    
    def _fire(self, value):
        # TODO: This is calling with a maybe-stale-when-it-arrives value. Do we want to tighten up and prohibit that in the specification of subscribe2?
        self.__reactor.callLater(0, self.__callback, value)
    
    def unsubscribe(self):
        self.__subscription_set.remove(self)
    
    def __repr__(self):
        return u'<{} calling {}>'.format(type(self).__name__, self.__callback)


class _LooseCellImmediateSubscription(object):
    def __init__(self, callback, subscription_set):
        self._fire = callback
        self.__subscription_set = subscription_set
        subscription_set.add(self)
    
    def unsubscribe(self):
        self.__subscription_set.remove(self)


def ViewCell(base, get_transform, set_transform, **kwargs):
    """
    A Cell whose value is always a transformation of another.
    
    TODO: Stop implementing this as LooseCell.
    """
    
    def forward(view_value):
        base_value = set_transform(view_value)
        base.set(base_value)
        actual_base_value = base.get()
        if base_value != actual_base_value:
            reverse(actual_base_value)
    
    def reverse(base_value):
        self.set(get_transform(base_value))
    
    self = LooseCell(
        value=get_transform(base.get()),
        post_hook=forward,
        **kwargs)
    
    sub = base._subscribe_immediate(reverse)
    weakref.ref(self, lambda: sub.unsubscribe())

    # Allows the cell to be put back in sync if the transform changes.
    # Not intended to be called except by the creator of the cell, but mostly harmless.
    def changed_transform():
        reverse(base.get())
    
    self.changed_transform = changed_transform  # pylint: disable=attribute-defined-outside-init
    
    return self


class Command(BaseCell):
    """A Cell which does not primarily produce a value, but is a side-effecting operation that can be invoked.
    
    This is a Cell for reasons of convenience in the existing architecture, and because it has several similarities.
    
    Its value is (TODO should be something generically useful).
    """
    
    def __init__(self, target, key, function, **kwargs):
        # TODO: remove writable=true when we have a proper invoke path
        BaseCell.__init__(self,
            target=target,
            key=key,
            type=type(None),
            persists=False,
            writable=True,
            **kwargs)
        self.__function = function
    
    def description(self):
        """implements BaseCell"""
        # TODO: This is identicalish to ValueCell.description except for the kind.
        return {
            u'type': 'command_cell',
            u'metadata': self.metadata(),
            u'writable': self.isWritable(),
            u'current': self.get(),
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
    __cache = None
    __setter_cells = None
    __shape_subscriptions = None
    
    def state_def(self):
        """Yields tuples of (key, cell) which are to be part of the object's exported state.
        
        These cells are in addition to to those defined by decorators, not replacing them.
        """
        return iter([])
    
    def state_insert(self, key, desc):
        raise ValueError('state_insert not defined on %r' % self)
    
    def state_is_dynamic(self):
        return False
    
    def state(self):
        # pylint: disable=attribute-defined-outside-init
        if self.state_is_dynamic() or self.__cache is None:
            cells = dict(self.__decorator_cells())
            
            def insert(key, cell):
                if key in cells:
                    raise KeyError('Cannot redefine {!r} from {!r} to {!r}'.format(key, cell, cells[key]))
                cells[key] = cell
            
            for key, cell in self.state_def():
                insert(key, cell)
            
            self.__cache = cells
            
        return self.__cache
    
    def __decorator_cells(self):
        # pylint: disable=attribute-defined-outside-init, access-member-before-definition
        # this is separate from state_def so that if state_is_dynamic we don't recreate these every time, forgetting subscriptions
        if hasattr(self, '_ExportedState__decorator_cells_cache'):
            return self.__decorator_cells_cache
        self.__decorator_cells_cache = {}
        self.__setter_cells = {}
        class_obj = type(self)
        for k in dir(class_obj):
            if not hasattr(self, k): continue
            v = getattr(class_obj, k)
            # TODO use an interface here and move the check inside
            if isinstance(v, ExportedGetter):
                if not k.startswith('get_'):
                    # TODO factor out attribute name usage in Cell so this restriction is moot for non-settable cells
                    raise LookupError('Bad getter name', k)
                else:
                    k = k[len('get_'):]
                setter_descriptor = getattr(class_obj, 'set_' + k, None)
                if not isinstance(setter_descriptor, ExportedSetter):
                    # e.g. a non-exported setter method
                    setter_descriptor = None
                cell = v.make_cell(self, k, writable=setter_descriptor is not None)
                if setter_descriptor is not None:
                    self.__setter_cells[setter_descriptor] = cell
                self.__decorator_cells_cache[k] = cell
            elif isinstance(v, ExportedCommand):
                self.__decorator_cells_cache[k] = v.make_cell(self, k)
        return self.__decorator_cells_cache
    
    def state_subscribe(self, callback, context):
        # pylint: disable=attribute-defined-outside-init, access-member-before-definition
        if self.__shape_subscriptions is None:
            self.__shape_subscriptions = set()
        if self.state_is_dynamic():
            return _SimpleSubscription(callback, context, self.__shape_subscriptions)
        else:
            return _NeverSubscription()
    
    def state__setter_called(self, setter_descriptor):
        """Called by ExportedSetter when the setter method is called."""
        table = self.__setter_cells
        if table is None:
            # state() has not yet been called, so the cell has not been created, so there are no possible subscriptions to notify, so we don't need to do anything.
            return
        table[setter_descriptor].poll_for_change_from_setter()
    
    def state_changed(self, key=None):
        """To be called by the object's implementation when a cell value has been changed.
        
        if key is given, it is the key of the relevant cell; otherwise all cells are polled.
        """
        state = self.state()
        if key is None:
            for cell in state.itervalues():
                cell.poll_for_change(specific_cell=False)
        else:
            state[key].poll_for_change(specific_cell=True)
    
    def state_shape_changed(self):
        """To be called by the object's implementation when it has gained, lost, or replaced a cell.
        
        This only applies to objects which return True from state_is_dynamic().
        """
        new_state = self.state()
        subscriptions = self.__shape_subscriptions
        if subscriptions is None:
            return
        for subscription in subscriptions:
            subscription._fire(new_state)
    
    def state_to_json(self, subscriber=lambda _: None):
        subscriber(self.state_subscribe)
        state = {}
        for key, cell in self.state().iteritems():
            if cell.metadata().persists:
                state[key] = cell.get_state(subscriber=subscriber)
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


@implementer(INull)
class NullExportedState(ExportedState):
    """An ExportedState object containing no cells, for use analogously to None."""


nullExportedState = NullExportedState()


class CellDict(object):
    """A dictionary-like object which holds its contents in cells."""
    
    def __init__(self, initial_state={}, dynamic=False, member_type=ReferenceT()):
        # pylint: disable=dangerous-default-value
        self.__member_type = member_type
        self.__cells = {}
        self._shape_subscription = lambda: None
        
        self._dynamic = True
        for key in initial_state:
            self[key] = initial_state[key]
        self._dynamic = dynamic
    
    def __len__(self):
        return len(self.__cells)
    
    def __contains(self, key):
        return key in self.__cells
    
    def __getitem__(self, key):
        return self.__cells[key].get()
    
    def __setitem__(self, key, value):
        if key in self.__cells:
            self.__cells[key].set_internal(value)
        else:
            assert self._dynamic
            self.__cells[key] = LooseCell(
                key=key,
                value=value,
                type=self.__member_type,
                persists=True,
                writable=False)
            self._shape_subscription()
    
    def __delitem__(self, key):
        assert self._dynamic
        if key in self.__cells:
            del self.__cells[key]
            self._shape_subscription()
    
    def __iter__(self):
        return self.iterkeys()
    
    def iterkeys(self):
        return self.__cells.iterkeys()
    
    def itervalues(self):
        for key in self:
            yield self[key]
    
    def iteritems(self):
        for key in self:
            yield key, self[key]
    
    def get_cell(self, key):
        return self.__cells[key]


class CollectionState(ExportedState):
    """Wrapper around a CellDict which exports its contents.
    
    Suitable for use as a superclass or mixin as well as by itself."""
    
    def __init__(self, cell_dict):
        self.__collection = cell_dict
        self.__dynamic = cell_dict._dynamic
        
        cell_dict._shape_subscription = self.state_shape_changed
    
    def state_is_dynamic(self):
        return self.__dynamic
    
    def state_def(self):
        for d in super(CollectionState, self).state_def():
            yield d
        for key in self.__collection:
            yield key, self.__collection.get_cell(key)


class IWritableCollection(Interface):
    """
    Marker that a dynamic state object should expose create/delete operations
    """


def exported_value(parameter=None, **cell_kwargs):
    """Returns a decorator for exported state; takes Cell's kwargs."""
    def decorator(f):
        return ExportedGetter(f, parameter, cell_kwargs)
    return decorator


def setter(f):
    """Decorator for setters of exported state; must be paired with an @exported_value getter."""
    return ExportedSetter(f)


def command(**cell_kwargs):
    """Returns a decorator for command methods."""
    def decorator(f):
        return ExportedCommand(f, cell_kwargs)
    return decorator


class ExportedGetter(object):
    """Descriptor for a getter exported using @exported_value."""
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
    
    def make_cell(self, obj, attr, writable):
        kwargs = self.__cell_kwargs
        if 'type_fn' in kwargs:
            kwargs = kwargs.copy()
            kwargs['type'] = kwargs['type_fn'](obj)
            del kwargs['type_fn']
        return Cell(obj, attr, writable=writable, **kwargs)
    
    def state_to_kwargs(self, value):
        # clunky: invoked by unserialize_exported_state via a type test
        if self.__parameter is not None:
            return {self.__parameter: self.__cell_kwargs['type'](value)}


class ExportedSetter(object):
    """Descriptor for a setter exported using @setter."""
    
    # This has no relevant behavior of its own; it is merely searched for by its paired ExportedGetter.
    
    def __init__(self, f):
        self.__function = f
    
    def __get__(self, obj, type=None):
        """implements method binding"""
        if obj is None:
            return self
        else:
            bound_method = self.__function.__get__(obj, type)
            
            def exported_setter_wrapper(value):
                # TODO: Also coerce with value type? Requires tighter association with cell, may be overly restrictive in some cases.
                bound_method(value)
                obj.state__setter_called(self)
            
            return exported_setter_wrapper


class ExportedCommand(object):
    """Descriptor for a command method exported using @command."""
    def __init__(self, f, cell_kwargs):
        self.__function = f
        self.__cell_kwargs = cell_kwargs
    
    def __get__(self, obj, type=None):
        """implements method binding"""
        if obj is None:
            return self
        else:
            return self.__function.__get__(obj, type)
    
    def make_cell(self, obj, attr):
        return Command(obj, attr, self.__get__(obj), **self.__cell_kwargs)
