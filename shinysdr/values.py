# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division, unicode_literals

import codecs
from collections import namedtuple
import weakref

from twisted.logger import Logger
from twisted.python.failure import Failure
from zope.interface import Interface, implementer  # available via Twisted

from shinysdr.gr_ext import safe_delete_head_nowait
from shinysdr.types import BulkDataElement, BulkDataT, EnumRow, ReferenceT, to_value_type


_log = Logger()


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
    
    The context's reactor and poller determine how and when the subscriber is invoked once the cell value has changed.
    
    reactor: twisted.internet.interfaces.IReactorTime
    poller: shinysdr.i.poller.Poller
    """
    # TODO: Define an interface for the poller or hide it more.


class ISubscription(Interface):
    # pylint: disable=arguments-differ, signature-differs
    """Just a handle for unsubscribing."""
    
    def unsubscribe():
        pass


class ISubscriber(Interface):
    # pylint: disable=arguments-differ, signature-differs
    """The callback to be passed to cell.subscribe2().
    
    This interface exists for documentation purposes; subscribers are not required to explicitly provide it.
    """
    
    def __call__(value):
        """Be notified of a newer value.
        
        Beware that the value supplied is _not_ necessarily the most current value; it may be obsolete by the time this notification is delivered.
        """


class IDeltaSubscriber(ISubscriber):
    """Interface for subscribing to cells whose value can be partially updated.
    
    The exact meaning of partial updating is not defined by this interface; it is expected that the cell's value type will provide a suitable definition.
    """
    
    def append(patch):
        """Append this patch to the previously reported/accumulated value.
        
        This operation should be used for newly-arriving data.
        """
    
    def prepend(patch):
        """Prepend this patch to the previously reported/accumulated value.
        
        This operation should be used for backfilling old data. The subscriber may ignore it entirely if it already has enough history.
        """


class InterestTracker(object):
    """Collects expressions of interest in some cells' values to track whether there currently are any."""
    
    def __init__(self, listener):
        assert callable(listener)
        self.__listener = listener
        self.__tokens = set()
    
    def set(self, token, interested):
        # print 'set', token, interested
        if interested:
            was_empty = not self.__tokens
            self.__tokens.add(token)
            if was_empty:
                # print '-> firing true'
                # TODO: Need non-immediate callbacks
                self.__listener(True)
        else:
            was_nonempty = bool(self.__tokens)
            self.__tokens.remove(token)
            if was_nonempty and not self.__tokens:
                # print '-> firing false'
                self.__listener(False)


class NullInterestTracker(object):
    def set(self, token, interest):
        pass


nullInterestTracker = NullInterestTracker()


class TargetingMixin(object):
    # TODO explain/rename this
    # The exact relationship of target and key depends on the subclass
    def __init__(self, target, key):
        self._target = target
        self._key = key
    
    def __cmp__(self, other):
        if not isinstance(other, TargetingMixin):
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
    
    def __repr__(self):
        # bogus warning <https://github.com/PyCQA/pylint/issues/1676> pylint disable=redundant-keyword-arg
        return b'<{type} {self._target!r}.{self._key}>'.format(type=type(self).__name__, self=self)
    
    def key(self):  # TODO remove this
        return self._key


class BaseCell(object):
    def __init__(self,
            type,
            persists=True,
            writable=False,
            interest_tracker=nullInterestTracker,
            label=None,
            description=None,
            sort_key=None,
            associated_key=None):
        self._writable = writable
        # TODO: Also allow specifying metadata object directly.
        self.__metadata = CellMetadata(
            value_type=to_value_type(type),
            persists=bool(persists),
            naming=EnumRow(
                label=label,
                description=description,
                sort_key=sort_key,
                associated_key=associated_key))
        self.interest_tracker = interest_tracker

    def metadata(self):
        return self.__metadata

    def type(self):
        return self.__metadata.value_type

    def get(self):
        """Return the value/object held by this cell."""
        raise NotImplementedError(self)
    
    def set(self, value):
        """Set the value held by this cell."""
        raise NotImplementedError(self)
    
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
    
    def subscribe2(self, subscriber, context):
        # TODO: 'subscribe2' name is temporary for easy distinguishing this from other 'subscribe' protocols.
        """Request to be notified when this cell's value changes.
        
        subscriber: an ISubscriber (not necessarily explicitly) and optionally an IDeltaSubscriber; called repeatedly with successive new cell values; never immediately.
        context: a SubscriptionContext.

        Returns a tuple of the current value and an ISubscription, which has an `unsubscribe` method which will remove the subscription.
        """
        raise NotImplementedError(self)
    
    def poll_for_change(self, specific_cell):
        pass
    
    def isWritable(self):  # TODO underscore naming
        return self._writable
    
    def description(self):
        raise NotImplementedError(self)


class ValueCell(BaseCell):
    # pylint: disable=abstract-method
    # (we are also abstract)
    
    def __init__(self, type, **kwargs):
        BaseCell.__init__(self, type=type, **kwargs)
    
    def description(self):
        return {
            u'type': u'value_cell',
            u'metadata': self.metadata(),
            u'writable': self.isWritable()
        }


# The possible values of the 'changes' parameter to a cell of type PollingCell, which determine when the cell's getter is polled to check for changes.
_cell_value_change_schedules = [
    u'never',  # never changes at all for the lifetime of the cell
    u'continuous',  # a different value almost every time
    u'explicit',  # implementation will self-report via ExportedState.state_changed
    u'this_setter',  # changes when and only when the setter for this cell is called
]


class PollingCell(TargetingMixin, ValueCell):
    __explicit_subscriptions = None
    __last_polled_value = None
    __setter = None
    
    def __init__(self,
            target,
            key,
            changes,
            type=object,
            writable=False,
            persists=None,
            interest_tracker=nullInterestTracker,
            **kwargs):
        assert changes in _cell_value_change_schedules
        type = to_value_type(type)
        if persists is None:
            persists = writable or type.is_reference()
        if changes == u'never':
            # no need to track
            interest_tracker = nullInterestTracker
        
        if changes == u'continuous' and persists:
            raise ValueError('persists=True changes={!r} is not allowed'.format(changes))
        if changes == u'never' and writable:
            raise ValueError('writable=True changes={!r} doesn\'t make sense'.format(changes))
        
        TargetingMixin.__init__(self, target, key)
        ValueCell.__init__(self,
            type=type,
            persists=persists,
            writable=writable,
            associated_key=key,
            interest_tracker=interest_tracker,
            **kwargs)
        
        self.__changes = changes
        if changes == u'explicit' or changes == u'this_setter':
            self.__explicit_subscriptions = set()
            self.__last_polled_value = object()
        
        self.__getter = getattr(self._target, 'get_' + key)
        if writable:
            self.__setter = getattr(self._target, 'set_' + key)
    
    def get(self):
        value = self.__getter()
        if self.type().is_reference():
            # informative-failure debugging aid
            assert isinstance(value, ExportedState), ('Reference value was not an ExportedState', self._target, self._key)
        return value
    
    def set(self, value):
        if not self.isWritable():
            raise Exception('Not writable.')
        return self.__setter(self.metadata().value_type(value))
    
    def subscribe2(self, subscriber, context):
        changes = self.__changes
        if changes == u'never':
            subscription = never_subscription
        elif changes == u'continuous':
            subscription = context.poller.subscribe(self, subscriber, fast=True)
        elif changes == u'explicit' or changes == u'this_setter':
            subscription = _SimpleSubscription(subscriber, context, self.__explicit_subscriptions, self.interest_tracker)
        else:
            raise ValueError('shouldn\'t happen unrecognized changes value: {!r}'.format(changes))
        return self.get(), subscription

    def poll_for_change(self, specific_cell):
        if self.__explicit_subscriptions is None:
            # Note that this is "we are not a kind of cell that has explicit subscriptions", not "we have no subscriptions". Doing the latter would mean that a new subscription might fire after subscribing not because the value actually changed but only because poll_for_changed was called.
            return
        value = self.get()
        if value != self.__last_polled_value:
            self.__last_polled_value = value
            for subscription in self.__explicit_subscriptions:
                subscription._fire(value)
    
    def poll_for_change_from_setter(self):
        if self.__changes == u'this_setter':
            self.poll_for_change(specific_cell=True)


class GRMsgQueueCell(ValueCell):
    """A cell which consumes a gr.msg_queue, with items in the format blocks.message_sink generates, and provides its contents as the streaming cell value.
    
    Abstract; use ElementQueueCell or StringQueueCell directly.
    """
    
    def __init__(self,
            queue,
            type,
            history_length,
            info_getter=lambda: None,
            **kwargs):
        if not (type == unicode or isinstance(type, BulkDataT)):
            raise ValueError('Unsupported type for GRMsgQueueCell {}'.format(type))
        ValueCell.__init__(self,
            type=type,
            writable=False,
            persists=False,
            **kwargs)
        
        self.__queue = queue
        self.__info_getter = info_getter
        self.__buffer = type.create_buffer(history_length)
    
    def get(self):
        return self.__buffer.get()
    
    def set(self, value):
        """implement abstract"""
        # TODO: There should be a standard exception to raise, or base class should do it for us
        raise Exception('Not writable')
    
    def subscribe2(self, subscriber, context):
        """implement abstract"""
        return self.get(), context.poller.subscribe(self, subscriber, fast=True, delegate_polling_to_me=True)
    
    def _deliver_message(self, grmessage, info, fire):
        """Implement this method to handle the gr.message objects from the queue."""
        raise NotImplementedError(self)
    
    def _poll_from_poller(self, fire):
        """Extract all items currently in the queue and deliver them."""
        
        def append_patch(patch):
            self.__buffer.append(patch)
            fire.append(patch)
        
        got_info = False
        latest_info = None
        while True:
            message = safe_delete_head_nowait(self.__queue)
            if not message:
                break
            if not got_info:
                got_info = True
                latest_info = self.__info_getter()
            self._deliver_message(message, latest_info, append_patch)


class ElementQueueCell(GRMsgQueueCell):
    def __init__(self,
            queue,
            type,
            history_length=32,
            **kwargs):
        assert isinstance(type, BulkDataT)
        GRMsgQueueCell.__init__(self,
            queue=queue,
            type=type,
            history_length=history_length,
            **kwargs)
    
    def _deliver_message(self, grmessage, info, append_patch):
        string = grmessage.to_string()
        itemsize = int(grmessage.arg1())
        count = int(grmessage.arg2())
        if not count: return
        
        parsed_items = []
        for index in xrange(count):
            # extract value
            item_string = string[itemsize * index:itemsize * (index + 1)]
            parsed_items.append(BulkDataElement(
                data=item_string,
                info=info))
        
        append_patch(parsed_items)


class StringQueueCell(GRMsgQueueCell):
    def __init__(self,
            queue,
            encoding,
            history_length=1000,
            **kwargs):
        GRMsgQueueCell.__init__(self,
            queue=queue,
            type=unicode,
            history_length=history_length,
            **kwargs)
        
        self.__decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
    
    def _deliver_message(self, grmessage, info, append_patch):
        message_string = self.__decoder.decode(grmessage.to_string())
        if message_string:
            append_patch(message_string)


class LooseCell(ValueCell):
    """
    A cell which stores a value and does not get it from another object; it can therefore reliably provide update notifications.
    """
    
    def __init__(self, value, post_hook=None, **kwargs):
        ValueCell.__init__(
            self,
            **kwargs)
        self.__value = value
        self.__subscriptions = set()
        self.__post_hook = post_hook
    
    def __repr__(self):
        return '<{type} {value_type} {value}>'.format(
            type=type(self).__name__,
            value_type=self.metadata().value_type,
            value=self.get())
    
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
    
    def subscribe2(self, subscriber, context):
        return self.get(), _SimpleSubscription(subscriber, context, self.__subscriptions, self.interest_tracker)
    
    def _subscribe_immediate(self, subscriber):
        """for use by ViewCell only"""
        # TODO: replace this with a better mechanism
        subscription = _LooseCellImmediateSubscription(subscriber, self.__subscriptions, self.interest_tracker)
        return subscription


@implementer(ISubscription)
class _SimpleSubscription(object):
    def __init__(self, subscriber, context, subscription_set, interest_tracker):
        self.__subscriber = subscriber
        self.__reactor = context.reactor
        self.__subscription_set = subscription_set
        self.__interest_token = object()
        self.__interest_tracker = interest_tracker
        self.__interest_tracker.set(self.__interest_token, True)
        subscription_set.add(self)
    
    def _fire(self, value):
        # TODO: This is calling with a maybe-stale-when-it-arrives value. Do we want to tighten up and prohibit that in the specification of subscribe2?
        self.__reactor.callLater(0, self.__subscriber, value)
    
    def unsubscribe(self):
        self.__subscription_set.remove(self)
        self.__interest_tracker.set(self.__interest_token, False)
    
    def __repr__(self):
        return u'<{} calling {}>'.format(type(self).__name__, self.__subscriber)


@implementer(ISubscription)
class _LooseCellImmediateSubscription(object):
    def __init__(self, subscriber, subscription_set, interest_tracker):
        self._fire = subscriber
        self.__subscription_set = subscription_set
        self.__interest_token = object()
        self.__interest_tracker = interest_tracker
        self.__interest_tracker.set(self.__interest_token, True)
        subscription_set.add(self)
    
    def unsubscribe(self):
        self.__subscription_set.remove(self)
        self.__interest_tracker.set(self.__interest_token, False)


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
    
    def __init__(self, function, **kwargs):
        # TODO: remove writable=true when we have a proper invoke path
        BaseCell.__init__(self,
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
        }
    
    def get(self):
        """implements BaseCell"""
        return None
    
    def set(self, _dummy_value):
        # raise Exception('Not writable.')
        # TODO: Make a separate command-triggering path, because this is a HORRIBLE KLUDGE.
        self.__function()
    
    def subscribe2(self, subscriber, context):
        """implements BaseCell"""
        return self.get(), never_subscription


@implementer(ISubscription)
class _NeverSubscription(object):
    def unsubscribe(self):
        pass


never_subscription = _NeverSubscription()


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
                    # TODO factor out attribute name usage in PollingCell so this restriction is moot for non-settable cells
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
    
    def state_subscribe(self, subscriber, context):
        # pylint: disable=attribute-defined-outside-init, access-member-before-definition
        if self.__shape_subscriptions is None:
            self.__shape_subscriptions = set()
        if self.state_is_dynamic():
            return self.state(), _SimpleSubscription(subscriber, context, self.__shape_subscriptions, nullInterestTracker)
        else:
            return self.state(), _NeverSubscription()
    
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
    
    def state_from_json(self, state, log=_log):
        cells = self.state()
        dynamic = self.state_is_dynamic()
        defer = []
        for key in state:
            # pylint: disable=cell-var-from-loop, undefined-loop-variable
            def err(adjective, failure=None):
                # TODO ship to client
                log.warn('Discarding {problem} state {target}.{key} = {value}',
                    problem=adjective,
                    target=self,
                    key=key,
                    value=state[key],
                    **({'log_failure': failure} if failure else {}))
            
            def doTry(f):
                try:
                    f()
                except (LookupError, TypeError, ValueError):
                    # a plausible set of exceptions, so we don't catch implausible ones
                    err('erroneous', Failure())
            
            cell = cells.get(key, None)
            if cell is None:
                if dynamic:
                    doTry(lambda: self.state_insert(key, state[key]))
                else:
                    err('nonexistent')
            elif cell.type().is_reference():
                defer.append(key)
            elif not cell.isWritable():
                err('non-writable')
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
    """Returns a decorator for exported state; takes PollingCell's kwargs."""
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
        return PollingCell(obj, attr, writable=writable, **kwargs)
    
    def state_to_kwargs(self, value):
        # clunky: invoked by unserialize_exported_state via a type test
        if self.__parameter is not None:
            return {self.__parameter: self.__cell_kwargs['type'](value)}
        else:
            return None


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
        return Command(self.__get__(obj), associated_key=attr, **self.__cell_kwargs)
