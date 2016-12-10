# Copyright 2016 Kevin Reid <kpreid@switchb.org>
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

"""Tools for persisting ExportedState state to disk."""

from __future__ import absolute_import, division

from shinysdr.values import ExportedState


class PersistenceChangeDetector(object):
    """Wrap state_to_json() so as to be notified when its result would change.
    
    root_object: Object to call .state_to_json() on.
    callback: Called exactly once after each .get() when the result changes.
    """
    
    # This is not itself a cell because we want to be able to be lazy and not do the potentially expensive state_to_json() immediately every time there is a change, whereas subscribe2 requires that the callback be given the current value. TODO revisit.
    
    def __init__(self, root_object, callback, subscription_context):
        assert isinstance(root_object, ExportedState)
        self.__root = root_object
        self.__callback = callback
        self.__subscription_context = subscription_context
        self.__subscriptions = []
    
    def get(self):
        self.__clear_subscriptions()
        return self.__root.state_to_json(subscriber=self.__add_subscription)
    
    def __clear_subscriptions(self):
        subs = self.__subscriptions
        self.__subscriptions = []
        for subscription in subs:
            subscription.unsubscribe()
    
    def __add_subscription(self, subscribe_fn):
        # TODO: It would be a reasonable strengthening to arrange so that even if the subscriptions misbehave, we do not ever 
        self.__subscriptions.append(subscribe_fn(self.__do_callback, self.__subscription_context))
    
    def __do_callback(self, _value):
        # ignore value because it is from an arbitrary element
        self.__clear_subscriptions()
        self.__callback()


