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

import bisect

from twisted.internet import task, reactor as the_reactor
from zope.interface import implementer

from shinysdr.values import BaseCell, ISubscription, StreamCell, SubscriptionContext

__all__ = []  # appended later


class Poller(object):
    """
    Polls cells for new values.
    """
    
    def __init__(self):
        # first level key is polling speed (True=fast)
        # sorting provides determinism for testing etc.
        self.__targets = {
            False: _SortedMultimap(),
            True: _SortedMultimap()
        }
        self.__functions = []
    
    def subscribe(self, cell, callback, fast):
        if not isinstance(cell, BaseCell):
            # we're not actually against duck typing here; this is a sanity check
            raise TypeError('Poller given a non-cell %r' % (cell,))
        if isinstance(cell, StreamCell):  # TODO kludge; use generic interface
            target = _PollerStreamTarget(cell)
        else:
            target = _PollerValueTarget(cell)
        return _PollerSubscription(self, target, callback, fast)
    
    def _add_subscription(self, target, subscription):
        self.__targets[subscription.fast].add(target, subscription)
    
    def _remove_subscription(self, target, subscription):
        table = self.__targets[subscription.fast]
        last_out = table.remove(target, subscription)
        if last_out:
            target.unsubscribe()
    
    def poll(self, rate_key):
        for target, subscriptions in self.__targets[rate_key].iter_snapshot():
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
    
    def poll_all(self):
        self.poll(False)
        self.poll(True)
    
    def queue_function(self, function, *args, **kwargs):
        """Queue a function to be called on the same schedule as the poller would."""
        def thunk():
            function(*args, **kwargs)
        
        self.__functions.append(thunk)
    
    def count_subscriptions(self):
        return sum(multimap.count_values() for multimap in self.__targets.itervalues())


__all__.append('Poller')


class AutomaticPoller(Poller):
    def __init__(self, reactor):
        Poller.__init__(self)
        self.__loop_slow = task.LoopingCall(self.poll, False)
        self.__loop_slow.clock = reactor
        self.__loop_fast = task.LoopingCall(self.poll, True)
        self.__loop_fast.clock = reactor
        self.__running = False
    
    def _add_subscription(self, target, subscription):
        # Hook to start call
        super(AutomaticPoller, self)._add_subscription(target, subscription)
        if not self.__running:
            print 'Poller starting'
            self.__running = True
            # using callLater because start() will do the first call _immediately_ :(
            self.__loop_fast.clock.callLater(0, self.__loop_fast.start, 1.0 / 61)
            self.__loop_slow.clock.callLater(0, self.__loop_slow.start, 0.5)
    
    def _remove_subscription(self, target, subscription):
        # Hook to stop call
        super(AutomaticPoller, self)._remove_subscription(target, subscription)
        if self.__running and self.count_subscriptions() == 0:
            print 'Poller stopping'
            self.__running = False
            self.__loop_fast.stop()
            self.__loop_slow.stop()


@implementer(ISubscription)
class _PollerSubscription(object):
    def __init__(self, poller, target, callback, fast):
        self._fire = callback
        self._target = target
        self._poller = poller
        self.fast = fast
        poller._add_subscription(target, self)
    
    def unsubscribe(self):
        self._poller._remove_subscription(self._target, self)


class _PollerTarget(object):
    def __init__(self, obj):
        self._obj = obj
        self._subscriptions = []
    
    def __cmp__(self, other):
        return cmp(type(self), type(other)) or cmp(self._obj, other._obj)
    
    def __hash__(self):
        return hash(self._obj)
    
    def poll(self, fire):
        """Call fire (with arbitrary info in args) if the thing polled has changed."""
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
            fire(value)


class _PollerStreamTarget(_PollerTarget):
    # TODO there are no tests for stream subscriptions
    def __init__(self, cell):
        _PollerTarget.__init__(self, cell)
        self.__subscription = cell.subscribe_to_stream()

    def poll(self, fire):
        subscription = self.__subscription
        while True:
            value = subscription.get(binary=True)  # TODO inflexible
            if value is None: break
            fire(value)

    def unsubscribe(self):
        self.__subscription.close()
        super(_PollerStreamTarget, self).unsubscribe()


class _SortedMultimap(object):
    """
    Support for Poller.
    Properties not explained by the name:
    * Values must be unique within a given key.
    * Keys are iterated in sorted order (values are not)
    """
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
        """Returns true if the value was the last value for that key"""
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


# this is done last for load order
the_poller = AutomaticPoller(reactor=the_reactor)
__all__.append('the_poller')

the_subscription_context = SubscriptionContext(reactor=the_reactor, poller=the_poller)
__all__.append('the_subscription_context')
