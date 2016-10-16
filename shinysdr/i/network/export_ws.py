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

"""Exports ExportedState/Cell object interfaces over WebSockets."""

from __future__ import absolute_import, division

import json
import struct
import time
import urllib

from twisted.internet import reactor as the_reactor  # TODO fix
from twisted.internet.protocol import Protocol
from twisted.python import log
from zope.interface import providedBy

from gnuradio import gr

from shinysdr.i.network.base import serialize
from shinysdr.i.poller import the_poller
from shinysdr.signals import SignalType
from shinysdr.values import BaseCell, BlockCell, ExportedState, StreamCell


class _StateStreamObjectRegistration(object):
    # TODO messy
    def __init__(self, ssi, poller, obj, serial, url, refcount):
        self.__ssi = ssi
        self.obj = obj
        self.serial = serial
        self.url = url
        self.has_previous_value = False
        self.previous_value = None
        self.value_is_references = False
        self.__dead = False
        if isinstance(obj, BaseCell):
            self.__obj_is_cell = True
            if isinstance(obj, StreamCell):  # TODO kludge
                self.__poller_registration = poller.subscribe(obj, self.__listen_binary_stream)
                self.send_now_if_needed = lambda: None
            else:
                self.__poller_registration = poller.subscribe(obj, self.__listen_cell)
                self.send_now_if_needed = self.__listen_cell
        else:
            self.__obj_is_cell = False
            self.__poller_registration = poller.subscribe_state(obj, self.__listen_state)
            self.send_now_if_needed = lambda: self.__listen_state(self.obj.state())
        self.__refcount = refcount
    
    def __str__(self):
        return self.url
    
    def set_previous(self, value, is_references):
        if is_references:
            for obj in value.itervalues():
                if obj not in self.__ssi._registered_objs:
                    raise Exception("shouldn't happen: previous value not registered", obj)
        self.has_previous_value = True
        self.previous_value = value
        self.value_is_references = is_references
    
    def send_initial_value(self):
        """kludge to get initial state sent"""
    
    def send_now_if_needed(self):
        # pylint: disable=method-hidden
        # should be overridden in instance
        raise Exception('This placeholder should never get called')
    
    def get_object_which_is_cell(self):
        if not self.__obj_is_cell:
            raise Exception('This object is not a cell')
        return self.obj
    
    def __listen_cell(self):
        if self.__dead:
            return
        obj = self.obj
        if isinstance(obj, StreamCell):
            raise Exception("shouldn't happen: StreamCell here")
        if obj.isBlock():
            block = obj.get()
            self.__ssi._lookup_or_register(block, self.url)
            self.__maybesend_reference({u'value': block}, True)
        else:
            value = obj.get()
            self.__maybesend(value, value)
    
    def __listen_binary_stream(self, value):
        if self.__dead:
            return
        self.__ssi._send1(True, struct.pack('I', self.serial) + value)
    
    def __listen_state(self, state):
        if self.__dead:
            return
        self.__maybesend_reference(state, False)
    
    # TODO fix private refs to ssi here
    def __maybesend(self, compare_value, update_value):
        if not self.has_previous_value or compare_value != self.previous_value[u'value']:
            self.set_previous({u'value': compare_value}, False)
            self.__ssi._send1(False, ('value', self.serial, update_value))
    
    def __maybesend_reference(self, objs, is_single):
        registrations = {
            k: self.__ssi._lookup_or_register(v, self.url + '/' + urllib.unquote(k))
            for k, v in objs.iteritems()
        }
        serials = {k: v.serial for k, v in registrations.iteritems()}
        if not self.has_previous_value or objs != self.previous_value:
            for reg in registrations.itervalues():
                reg.inc_refcount()
            if is_single:
                self.__ssi._send1(False, ('value', self.serial, serials[u'value']))
            else:
                self.__ssi._send1(False, ('value', self.serial, serials))
            if self.has_previous_value:
                refs = self.previous_value.values()
                refs.sort()  # ensure determinism
                for obj in refs:
                    if obj not in self.__ssi._registered_objs:
                        raise Exception("Shouldn't happen: previous value not registered", obj)
                    self.__ssi._registered_objs[obj].dec_refcount_and_maybe_notify()
            self.set_previous(objs, True)
    
    def drop(self):
        # TODO this should go away in refcount world
        if self.__poller_registration is not None:
            self.__poller_registration.unsubscribe()
    
    def inc_refcount(self):
        if self.__dead:
            raise Exception('incing dead reference')
        self.__refcount += 1
    
    def dec_refcount_and_maybe_notify(self):
        if self.__dead:
            raise Exception('decing dead reference')
        self.__refcount -= 1
        if self.__refcount == 0:
            self.__dead = True
            self.__ssi.do_delete(self)
            
            # capture refs to decrement
            if self.value_is_references:
                refs = self.previous_value.values()
                refs.sort()  # ensure determinism
            else:
                refs = []
            
            # drop previous value
            self.previous_value = None
            self.has_previous_value = False
            self.value_is_references = False
            
            # decrement refs
            for obj in refs:
                self.__ssi._registered_objs[obj].dec_refcount_and_maybe_notify()


# TODO: Better name for this category of object
class StateStreamInner(object):
    def __init__(self, send, root_object, root_url, noteDirty, poller=the_poller):
        self.__poller = poller
        self._send = send
        self.__root_object = root_object
        self._cell = BlockCell(self, '_root_object')
        self._lastSerial = 0
        root_registration = _StateStreamObjectRegistration(ssi=self, poller=self.__poller, obj=self._cell, serial=0, url=root_url, refcount=0)
        self._registered_objs = {self._cell: root_registration}
        self.__registered_serials = {root_registration.serial: root_registration}
        self._send_batch = []
        self.__batch_delay = None
        self.__root_url = root_url
        self.__noteDirty = noteDirty
        root_registration.send_now_if_needed()
    
    def connectionLost(self, reason):
        # pylint: disable=consider-iterating-dictionary
        # dict is mutated during iteration
        for obj in self._registered_objs.keys():
            self.__drop(obj)
    
    def dataReceived(self, data):
        # TODO: handle json parse failure or other failures meaningfully
        command = json.loads(data)
        op = command[0]
        if op == 'set':
            op, serial, value, message_id = command
            registration = self.__registered_serials[serial]
            cell = registration.get_object_which_is_cell()
            t0 = time.time()
            cell.set(value)
            registration.send_now_if_needed()
            self._send1(False, ['done', message_id])
            t1 = time.time()
            # TODO: Define self.__str__ or similar such that we can easily log which client is sending the command
            log.msg('set %s to %r (%1.2fs)' % (registration, value, t1 - t0))
            self.__noteDirty()  # TODO fix things so noteDirty is not needed
        else:
            log.msg('Unrecognized state stream op received: %r' % (command,))
            
    
    def get__root_object(self):
        """Accessor for implementing self._cell."""
        return self.__root_object
    
    def do_delete(self, reg):
        self._send1(False, ('delete', reg.serial))
        self.__drop(reg.obj)
    
    def __drop(self, obj):
        registration = self._registered_objs[obj]
        registration.drop()
        del self.__registered_serials[registration.serial]
        del self._registered_objs[obj]
    
    def _lookup_or_register(self, obj, url):
        if obj in self._registered_objs:
            return self._registered_objs[obj]
        else:
            self._lastSerial += 1
            serial = self._lastSerial
            registration = _StateStreamObjectRegistration(ssi=self, poller=self.__poller, obj=obj, serial=serial, url=url, refcount=0)
            self._registered_objs[obj] = registration
            self.__registered_serials[serial] = registration
            if isinstance(obj, BaseCell):
                self._send1(False, ('register_cell', serial, url, obj.description()))
                if isinstance(obj, StreamCell):  # TODO kludge
                    pass
                elif not obj.isBlock():  # TODO condition is a kludge due to block cell values being gook
                    registration.set_previous({u'value': obj.get()}, False)
            elif isinstance(obj, ExportedState):
                self._send1(False, ('register_block', serial, url, _get_interfaces(obj)))
            else:
                # TODO: not implemented on client (but shouldn't happen)
                self._send1(False, ('register', serial, url))
            registration.send_now_if_needed()
            return registration
    
    def _flush(self):  # exposed for testing
        self.__batch_delay = None
        if len(self._send_batch) > 0:
            # unicode() because JSONEncoder does not reliably return a unicode rather than str object
            self._send(unicode(serialize(self._send_batch)))
            self._send_batch = []
    
    def _send1(self, binary, value):
        if binary:
            # preserve order by flushing stored non-binary msgs
            # TODO: Implement batching for binary messages.
            self._flush()
            self._send(value)
        else:
            # Messages are batched in order to increase client-side efficiency since each incoming WebSocket message is always a separate JS event.
            self._send_batch.append(value)
            # TODO: Parameterize with reactor so we can test properly
            if not (self.__batch_delay is not None and self.__batch_delay.active()):
                self.__batch_delay = the_reactor.callLater(0, self._flush)


class AudioStreamInner(object):
    def __init__(self, reactor, send, block, audio_rate):
        self._send = send
        self._queue = gr.msg_queue(limit=100)
        self.__running = [True]
        self._block = block
        self._block.add_audio_queue(self._queue, audio_rate)
        
        # We don't actually benefit specifically from using a SignalType in this context but it avoids reinventing vocabulary.
        signal_type = SignalType(
            kind='STEREO' if self._block.get_audio_queue_channels() == 2 else 'MONO',
            sample_rate=audio_rate)
        
        send(serialize({
            # Not used to discriminate, but it seems worth applying the convention in general.
            u'type': u'audio_stream_metadata',
            u'signal_type': signal_type,
        }))
        
        reactor.callInThread(_AudioStream_read_loop, reactor, self._queue, self.__deliver, self.__running)
    
    def dataReceived(self, data):
        pass
    
    def connectionLost(self, reason):
        # pylint: disable=no-member
        self._block.remove_audio_queue(self._queue)
        self.__running[0] = False
        # Insert a dummy message to ensure the loop thread unblocks; otherwise it will sit around forever, including preventing process shutdown.
        self._queue.insert_tail(gr.message())
    
    def __deliver(self, data_string):
        self._send(data_string, safe_to_drop=True)


def _AudioStream_read_loop(reactor, queue, deliver, running):
    # RUNS IN A SEPARATE THREAD.
    while running[0]:
        buf = ''
        message = queue.delete_head()  # blocking call
        if message.length() > 0:  # avoid crash bug
            buf += message.to_string()
        # Collect more queue contents to batch data
        while not queue.empty_p():
            message = queue.delete_head()
            if message.length() > 0:  # avoid crash bug
                buf += message.to_string()
        reactor.callFromThread(deliver, buf)


def _lookup_block(block, path):
    for i, path_elem in enumerate(path):
        cell = block.state().get(path_elem)
        if cell is None:
            raise Exception('Not found: %r in %r' % (path[:i + 1], path))
        elif not cell.isBlock():
            raise Exception('Not a block: %r in %r' % (path[:i + 1], path))
        block = cell.get()
    return block


class OurStreamProtocol(Protocol):
    """Protocol implementing ShinySDR's WebSocket service.
    
    This protocol's transport should be a txWS WebSocket transport.
    """
    def __init__(self, caps, noteDirty):
        self._caps = caps
        self._seenValues = {}
        self.inner = None
        self.__noteDirty = noteDirty
    
    def dataReceived(self, data):
        """Twisted Protocol implementation.
        
        Additionally, txWS takes no care with exceptions here, so we catch and log."""
        # pylint: disable=broad-except
        try:
            if self.inner is None:
                # To work around txWS's lack of a notification when the URL is available, all clients send a dummy first message.
                self.__dispatch_url()
            else:
                self.inner.dataReceived(data)
        except Exception as e:
            log.err(e)
    
    def __dispatch_url(self):
        loc = self.transport.location
        log.msg('Stream connection to ', loc)
        path = [urllib.unquote(x) for x in loc.split('/')]
        assert path[0] == ''
        path[0:1] = []
        if path[0] in self._caps:
            root_object = self._caps[path[0]]
            path[0:1] = []
        elif None in self._caps:
            root_object = self._caps[None]
        else:
            raise Exception('Unknown cap')  # TODO better error reporting
        if len(path) == 1 and path[0].startswith('audio?rate='):
            rate = int(json.loads(urllib.unquote(path[0][len('audio?rate='):])))
            self.inner = AudioStreamInner(the_reactor, self.__send, root_object, rate)
        elif len(path) >= 1 and path[0] == 'radio':
            # note _lookup_block may throw. TODO: Better error reporting
            root_object = _lookup_block(root_object, path[1:])
            self.inner = StateStreamInner(self.__send, root_object, loc, self.__noteDirty)  # note reuse of loc as HTTP path; probably will regret this
        else:
            raise Exception('Unknown path: %r' % (path,))
    
    def connectionMade(self):
        """twisted Protocol implementation"""
        self.transport.setBinaryMode(True)
        # Unfortunately, txWS calls this too soon for transport.location to be available
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        """twisted Protocol implementation"""
        if self.inner is not None:
            self.inner.connectionLost(reason)
    
    def __send(self, message, safe_to_drop=False):
        if len(self.transport.transport.dataBuffer) > 1000000:
            # TODO: condition is horrible implementation-diving kludge
            # Don't accumulate indefinite buffer if we aren't successfully getting it onto the network.
            
            if safe_to_drop:
                log.err('Dropping data going to stream ' + self.transport.location)
            else:
                log.err('Dropping connection due to too much data on stream ' + self.transport.location)
                self.transport.close(reason='Too much data buffered')
        else:
            self.transport.write(message)


def _fqn(class_):
    # per http://stackoverflow.com/questions/2020014/get-fully-qualified-class-name-of-an-object-in-python
    return class_.__module__ + '.' + class_.__name__


# TODO: Interfaces are not exported from the HTTP interface at all. This is a missing feature, and when it is added this code should move.
def _get_interfaces(obj):
    return [_fqn(interface) for interface in providedBy(obj)]
