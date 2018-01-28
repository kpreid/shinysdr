# -*- coding: utf-8 -*-
# Copyright 2018 Kevin Reid and the ShinySDR contributors
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

"""Provides the Plumber, a dependency layer on top of GR flow graphs."""

from __future__ import absolute_import, division, print_function, unicode_literals

from twisted.internet import defer
from twisted.internet.task import deferLater
from twisted.logger import Logger
from zope.interface import Interface, implementer

from gnuradio import gr


__all__ = []  # appended later


class IFittingFactory(Interface):
    """Represents something that needs to be done or created by the plumber.
    
    Instances should be stateless and, except where moot, implement structural equality."""

    # (cannot declare this usefully, so just documenting it:)
    # def __call__(fitting_context):
    #     """Return a new fitting (implementing IFitting) or a Deferred for same."""


__all__.append('IFittingFactory')


class IFitting(Interface):
    def open():
        """Called with the flow graph locked when the fitting begins being used."""
    
    def close():
        """Called with the flow graph locked when the fitting will no longer be used."""
    
    def deps():
        """Returns an iterable of IFittingFactory to also include in the graph.
        
        If this changes, then the context's reevaluate() method should be called.
        """


__all__.append('IFitting')


class Plumber(object):
    """Connect GR blocks and other information processing elements according to specified dependencies."""
    
    __log = Logger()
    
    def __init__(self, reactor, top_block=None):
        """
        reactor: an IReactorTime, used to schedule reconnections asynchronously.
        top_block: a gnuradio.gr.top_block or None/absent to create one. The top block's running status (start/stop/wait) will be managed by Plumber, and should be initially stopped (as a freshly created top block).
        """
        # Constant
        self.__top_block = top_block or gr.top_block()
        self.__top_block.start()  # for now, always running; later we will auto-stop
        
        # Explicit configuration state
        self.__explicit_candidate_factories = set()  # members are IFittingFactory
        
        # maps IFittingFactory to _ActiveFittingHolder when the fitting has not yet been put in the graph
        # if this overlaps with __active_holders then the previous fitting is to be replaced
        self.__pending_holders = {}
        
        # maps IFittingFactory to _ActiveFittingHolder when the fitting is in the graph
        self.__active_holders = {}
        
        self.__do_not_reuse = set()
        
        self.__scheduled_change = _RepeatingAsyncTask(reactor, self.__change)
    
    def add_explicit_candidate(self, ff):
        ff = IFittingFactory(ff)
        self.__explicit_candidate_factories.add(ff)
        self._schedule_change('add_explicit_candidate')
    
    def remove_explicit_candidate(self, ff):
        raise NotImplementedError()
        # TODO test
        # self.__explicit_candidate_nodes.remove(ff)
        # self._schedule_change()
    
    def wait_and_resume(self):
        # For testing with finite source blocks.
        self.__top_block.wait()
        self.__top_block.stop()
        self.__top_block.start()
    
    def get_fitting(self, other_ff, requester_ff=None):
        if requester_ff:
            # TODO: check if requester put other_ff in its deps list
            pass
        other_holder = self.__active_holders.get(other_ff) or self.__pending_holders[other_ff]
        return other_holder.fitting
    
    def _schedule_change(self, reason):
        """Internal for _ActiveFittingHolder -- asynchronously trigger a reevaluation of the graph"""
        self.__log.debug('scheduled change ({reason})', reason=unicode(reason))
        self.__scheduled_change.start()
    
    def _mark_for_rebuild(self, fitting_factory):
        """Internal for _ActiveFittingHolder"""
        self.__do_not_reuse.add(fitting_factory)
        self.__scheduled_change.start()
    
    @defer.inlineCallbacks
    def __change(self):
        self.__log.debug('CHANGE: analyzing')
        # raise Exception('hmm')

        active_ffs = set()
        newly_active_ffs = set()
        
        @defer.inlineCallbacks
        def add_factory(ff, reason):
            self.__log.debug('  add_factory({ff}) because {reason}', ff=ff, reason=reason)
            active_ffs.add(ff)
            if ff not in self.__active_holders or ff in self.__do_not_reuse:
                newly_active_ffs.add(ff)
                holder = _ActiveFittingHolder(ff, self, self.__top_block, log=self.__log)
                self.__pending_holders[ff] = holder
                yield holder.deferred()
            else:
                holder = self.__active_holders[ff]
            # traverse all deps even if this fitting is already active, because deps may have changed
            for dep_ff in holder.fitting.deps():
                # TODO: could do in parallel
                yield add_factory(dep_ff, ff)
        
        # traverse dependency graph from roots
        for ff in self.__explicit_candidate_factories:
            yield add_factory(ff, 'root')
        
        self.__log.debug('CHANGE: ...completed analysis')
        
        newly_inactive_ffs = (set(self.__active_holders.iterkeys())
            .difference(active_ffs)
            .union(self.__do_not_reuse))
        needs_configuration = newly_active_ffs or newly_inactive_ffs
        
        if not needs_configuration:
            self.__log.debug('CHANGE: no reconfiguration')
        else:
            self.__log.debug('CHANGE: locking for reconfiguration')
            try:
                self.__top_block.lock()
                # remove old fittings
                for ff in newly_inactive_ffs:
                    holder = self.__active_holders[ff]
                    self.__log.debug('  closing {ff} → {fitting}', ff=ff, fitting=holder.fitting)
                    holder.close()
                    del self.__active_holders[ff]
                # add new fittings
                for ff in newly_active_ffs:
                    holder = self.__pending_holders[ff]
                    del self.__pending_holders[ff]
                    self.__active_holders[ff] = holder
                    self.__log.debug('  opening {ff} → {fitting}', ff=ff, fitting=holder.fitting)
                    holder.open()
            finally:
                self.__top_block.unlock()
                self.__log.debug('CHANGE: ...unlocked')
                
                self.__do_not_reuse.clear()


__all__.append('Plumber')


@implementer(IFitting)
class BlockFitting(object):
    def __init__(self, fitting_context, block, input_ff=None):
        self.__context = fitting_context
        self.block = block
        self.__input_ff = IFittingFactory(input_ff) if input_ff else None
        self.__input_block = None
    
    def open(self):
        if self.__input_ff:
            input_fitting = self.__context.get_fitting(self.__input_ff)
            assert isinstance(input_fitting, BlockFitting), input_fitting  # TODO: better protocol
            self.__input_block = input_fitting.block
            self.__context.connect(self.__input_block, self.block)
    
    def close(self):
        if self.__input_block:
            self.__context.disconnect(self.__input_block, self.block)
    
    def deps(self):
        return [self.__input_ff] if self.__input_ff else []


__all__.append('BlockFitting')


class _ActiveFittingHolder(object):
    # pylint: disable=broad-except
    
    def __init__(self, ff, plumber, top_block, log=Logger()):
        self.__ff = IFittingFactory(ff)
        self.__state = 'instantiating'
        self.__log = log
        self.fitting = None
        
        context = FittingContext(
            fitting_factory=self.__ff,
            plumber=plumber,
            top_block=top_block,
            active=self.__context_active,
            log=self.__log)
        self.__fitting_deferred = defer.maybeDeferred(self.__ff, context)
        self.__fitting_deferred.addCallback(self.__ready)
    
    def __ready(self, fitting):
        assert self.__state == 'instantiating', self.__state
        try:
            self.fitting = IFitting(fitting)
        except Exception:
            self.__state = 'broken'
            self.__log.failure('Fitting factory {fitting_factory} did not return an IFitting, but {fitting}',
                fitting_factory=self.__ff,
                fitting=fitting)
            return
        self.__state = 'ready'
    
    def open(self):
        assert self.__state == 'ready', self.__state
        self.__state = 'open'
        try:
            self.fitting.open()
        except Exception:
            # TODO: go to broken? review exception behavior
            self.__log.failure('Fitting {fitting} raised during open',
                fitting=self.fitting)
    
    def close(self):
        assert self.__state == 'open', self.__state
        fitting = self.fitting
        self.fitting = None
        try:
            fitting.close()
        except Exception:
            self.__log.failure('Fitting {fitting} raised during close',
                fitting=fitting)
        finally:
            self.__state = 'closed'
    
    def deferred(self):
        # we don't mind if callers add callbacks because we've gotten in first
        return self.__fitting_deferred
    
    def __context_active(self):
        return self.__state == 'open'


# TODO: reconcile this and shinysdr.i.blocks.Context; maybe that goes away
class FittingContext(object):
    def __init__(self, fitting_factory, plumber, top_block, active, log=Logger()):
        self.__fitting_factory = fitting_factory
        self.__plumber = plumber
        self.__top_block = top_block
        self.__active_fn = active
        self.__log = log
    
    def rebuild_me(self):
        assert self.__active_fn()
        self.__plumber._mark_for_rebuild(self.__fitting_factory)
        self.__plumber._schedule_change('rebuild_me %r' % self.__fitting_factory)
    
    def connect(self, src, dst):
        assert self.__active_fn()
        self.__log.debug('connecting {src!r} → {dst!r}', src=src, dst=dst)
        self.__top_block.connect(src, dst)
    
    def disconnect(self, src, dst):
        assert self.__active_fn()
        self.__log.debug('disconnecting {src!r} → {dst!r}', src=src, dst=dst)
        self.__top_block.disconnect(src, dst)
    
    def get_fitting(self, other_ff):
        assert self.__active_fn()
        return self.__plumber.get_fitting(other_ff, requester_ff=self.__fitting_factory)


# not yet ready to graduate to shinysdr.twisted_ext. also find a better name?
class _RepeatingAsyncTask(object):
    """Calls the function later."""
    def __init__(self, reactor, function):
        """
        reactor: an IReactorTime
        function: Callable to call.
        """
        
        # Whether we should start another async task
        self.__active = False
        # Deferred for the completion of the current task if any
        self.__running_deferred = None
        # bundle reactor and function the way we will use them
        self.__async_task_impl = lambda: deferLater(reactor, 0, function)
    
    def start(self):
        """Ensure the async task is started, and return a Deferred for when it completes this repetition."""
        # print 'start'
        self.__active = True
        self.__maybe_run()
        d = defer.Deferred()
        do_and_continue(self.__running_deferred, lambda: d.callback(None))
        return d
    
    def __maybe_run(self):
        """Check if we should start an instance of the async task now."""
        # print 'maybe_run', self.__active, self.__running_deferred
        if self.__active and self.__running_deferred is None:
            self.__active = False
            d = self.__async_task_impl()
            do_and_continue(d, self.__async_finish)
            self.__running_deferred = d
    
    def __async_finish(self):
        """Clean up after the async task."""
        # print 'async_finish'
        self.__running_deferred = None
        self.__maybe_run()


def do_and_continue(d, f):
    def do_and_continue_wrapper(value):
        # print 'continuing with', value
        f()
        return value
    
    return d.addBoth(do_and_continue_wrapper)
