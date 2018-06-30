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

"""Exports ExportedState/Cell object interfaces over WebSockets."""

from __future__ import absolute_import, division, unicode_literals

import json
import struct
import time
import urllib

from twisted.internet import reactor as the_reactor  # TODO fix
from twisted.internet.protocol import Protocol
from twisted.logger import Logger
from zope.interface import implementer, providedBy

from shinysdr.i.json import serialize
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT
from shinysdr.signals import SignalType
from shinysdr.types import BulkDataT, ReferenceT
from shinysdr.values import BaseCell, ExportedState, IDeltaSubscriber, PollingCell


_NOT_A_VALUE = object()


class _StateStreamObjectRegistration(object):
    # TODO messy
    def __init__(self, ssi, subscription_context, obj, serial, url, refcount, send_registration=False):
        self.__ssi = ssi
        self.obj = obj
        self.serial = serial
        self.url = url
        self.__previous_references = []
        self.__previous_value_message = _NOT_A_VALUE
        self.__dead = False
        if isinstance(obj, BaseCell):
            self.__obj_is_cell = True
            subscriber = _StateStreamSubscriber(self.__listen_cell, self.__listen_cell_patch)
            initial_value, self.__subscription = obj.subscribe2(subscriber, subscription_context)
        elif isinstance(obj, ExportedState):
            self.__obj_is_cell = False
            if obj.state_is_dynamic():  # TODO: can we not bother checking? this may be a relic from polling
                initial_value, self.__subscription = obj.state_subscribe(self.__listen_state, subscription_context)
            else:
                initial_value = obj.state()
                self.__subscription = None
        else:
            raise TypeError('not a cell or ExportedState: {!r}'.format(obj))
        self.__refcount = refcount
        
        if send_registration:
            if isinstance(obj, BaseCell):
                if obj.type().is_reference():
                    # TODO refactor so we can send a reference as the initial value and do the right things
                    ssi._send1(False, ('register_cell', serial, url, obj.description(), None))
                    self.__listen_cell(initial_value)
                else:
                    ssi._send1(False, ('register_cell', serial, url, obj.description(), initial_value))
            elif isinstance(obj, ExportedState):
                ssi._send1(False, ('register_block', serial, url, _get_interfaces(obj)))
                self.__listen_state(initial_value)
            else:
                # TODO: not implemented on client (but shouldn't happen)
                ssi._send1(False, ('register', serial, url))
    
    def __str__(self):
        return self.url
    
    def __set_previous_references(self, references):
        assert isinstance(references, dict)
        for obj in references.itervalues():
            if obj not in self.__ssi._registered_objs:
                raise Exception("shouldn't happen: previous value not registered", obj)
        self.__previous_references = references.values()
    
    def force_send_current_value(self):
        """Ensure that the latest value has been put on the stream."""
        if self.__obj_is_cell:
            # TODO: not fully correct wrt streaming, but right now that won't happen because there are no writable and streaming cells
            self.__listen_cell(self.obj.get())
    
    def get_object_which_is_cell(self):
        if not self.__obj_is_cell:
            raise Exception('This object is not a cell')
        return self.obj
    
    def __listen_cell(self, value):
        if self.__dead:
            return
        value_type = self.obj.type()
        if value_type.is_reference():
            self.__ssi._lookup_or_register(value, self.url)
            self.__send_references_and_update_refcount({u'value': value}, True)
        elif isinstance(value_type, BulkDataT):
            for bulk in value:
                # TODO fix private ref to _send1
                self.__ssi._send1(True, struct.pack('I', self.serial) + value_type.pack(bulk))
        else:
            assert not self.__previous_references  # shouldn't happen, could be handled but unimplemented
            self.__send_value_message(value)
    
    def __listen_cell_patch(self, patch):
        if self.__dead:
            return
        value_type = self.obj.type()
        if value_type.is_reference():
            raise NotImplementedError()  # shouldn't happen
        elif isinstance(value_type, BulkDataT):
            for bulk in patch:
                # TODO fix private ref to _send1
                self.__ssi._send1(True, struct.pack('I', self.serial) + value_type.pack(bulk))
        else:
            self.__ssi._send1(False, (u'value_append', self.serial, patch))
            self.__previous_value_message = _NOT_A_VALUE
    
    def __listen_state(self, state):
        if self.__dead:
            return
        self.__send_references_and_update_refcount(state, False)
    
    def __send_references_and_update_refcount(self, objs, is_single):
        assert isinstance(objs, dict)
        registrations = {
            k: self.__ssi._lookup_or_register(v, self.url + '/' + urllib.unquote(k))
            for k, v in objs.iteritems()
        }
        serials = {k: v.serial for k, v in registrations.iteritems()}
        
        # Increment refcounts of new (or existing) references.
        for reg in registrations.itervalues():
            reg.inc_refcount()
        
        # Send message.
        if is_single:
            self.__send_value_message(serials[u'value'])
        else:
            self.__send_value_message(serials)
        
        # Decrement refcounts of old (or existing) references.
        refs = self.__previous_references
        refs.sort()  # ensure determinism
        for obj in refs:
            if obj not in self.__ssi._registered_objs:
                raise Exception("Shouldn't happen: previous value not registered", obj)
            self.__ssi._registered_objs[obj].dec_refcount_and_maybe_notify()
        
        # Record new references to be decremented later.
        self.__set_previous_references(objs)
    
    def __send_value_message(self, payload):
        if self.__previous_value_message == payload:
            return
        self.__previous_value_message = payload
        self.__ssi._send1(False, ('value', self.serial, payload))
    
    def drop(self):
        # TODO this should go away in refcount world
        if self.__subscription is not None:
            self.__subscription.unsubscribe()
    
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
            refs = self.__previous_references
            refs.sort()  # ensure determinism
            
            # drop previous value
            self.__set_previous_references({})
            
            # decrement recursively
            for obj in refs:
                self.__ssi._registered_objs[obj].dec_refcount_and_maybe_notify()


@implementer(IDeltaSubscriber)
class _StateStreamSubscriber(object):
    def __init__(self, handle_value, handle_append):
        self.__handle_value = handle_value
        self.__handle_append = handle_append
    
    def __call__(self, value):
        self.__handle_value(value)
    
    def append(self, patch):
        self.__handle_append(patch)
    
    def prepend(patch):
        pass  # unimplemented, unused


# TODO: Better name for this category of object
class StateStreamInner(object):
    __log = Logger()  # TODO maybe plumb this in instead
    
    def __init__(self, send, root_object, root_url, subscription_context):
        self.__subscription_context = subscription_context
        self._send = send
        self.__root_object = root_object
        self._cell = PollingCell(self, '_root_object', type=ReferenceT(), changes='never')
        self._lastSerial = 0
        root_registration = _StateStreamObjectRegistration(ssi=self, subscription_context=self.__subscription_context, obj=self._cell, serial=0, url=root_url, refcount=0)
        self._registered_objs = {self._cell: root_registration}
        self.__registered_serials = {root_registration.serial: root_registration}
        self._send_batch = []
        self.__batch_delay = None
        self.__root_url = root_url
        root_registration.force_send_current_value()
    
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
            registration.force_send_current_value()
            self._send1(False, ['done', message_id])
            t1 = time.time()
            # TODO: Define self.__str__ or similar such that we can easily log which client is sending the command
            self.__log.debug('set {registration} to {value!r} ({time_s:1.2f}s)', registration=registration, value=value, time_s=t1 - t0)
        else:
            self.__log.error('Unrecognized state stream op received: {command}', command=command)
    
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
            registration = _StateStreamObjectRegistration(ssi=self, subscription_context=self.__subscription_context, obj=obj, serial=serial, url=url, refcount=0, send_registration=True)
            self._registered_objs[obj] = registration
            self.__registered_serials[serial] = registration
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
            if not (self.__batch_delay is not None and self.__batch_delay.active()):
                self.__batch_delay = self.__subscription_context.reactor.callLater(0, self._flush)


class AudioStreamInner(object):
    def __init__(self, reactor, send, audio_source, audio_rate):
        self._send = send
        self.__audio_source = audio_source
        self.__callback = self.__deliver  # identical object just to avoid any confusion
        self.__audio_source.add_audio_callback(self.__callback, audio_rate)
        
        # We don't actually benefit specifically from using a SignalType in this context but it avoids reinventing vocabulary.
        signal_type = SignalType(
            kind='STEREO' if self.__audio_source.get_audio_callback_channels() == 2 else 'MONO',
            sample_rate=audio_rate)
        
        send(serialize({
            # Not used to discriminate, but it seems worth applying the convention in general.
            u'type': u'audio_stream_metadata',
            u'signal_type': signal_type,
        }))
    
    def dataReceived(self, data):
        pass
    
    def connectionLost(self, reason):
        # pylint: disable=no-member
        self.__audio_source.remove_audio_callback(self.__callback)
    
    def __deliver(self, data_numpy_array):
        self._send(data_numpy_array, safe_to_drop=True)


def _lookup_block(block, path):
    for i, path_elem in enumerate(path):
        cell = block.state().get(path_elem)
        if cell is None:
            raise Exception('Not found: %r in %r' % (path[:i + 1], path))
        elif not cell.type().is_reference():
            raise Exception('Not a reference: %r in %r' % (path[:i + 1], path))
        block = cell.get()
    return block


class OurStreamProtocol(Protocol):
    """Protocol implementing ShinySDR's WebSocket service.
    
    This protocol's transport should be a txWS WebSocket transport.
    """
    def __init__(self, caps, subscription_context):
        self.__log = Logger()
        self.__subscription_context = subscription_context
        self._caps = caps
        self._seenValues = {}
        self.inner = None
    
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
        except Exception:
            self.__log.failure('Error processing incoming WebSocket message')
    
    def __dispatch_url(self):
        loc = self.transport.location
        self.__log.info('Stream connection to {url}', url=loc)
        path = [urllib.unquote(x) for x in loc.split('/')]
        assert path[0] == ''
        path[0:1] = []
        cap_string = path[0].decode('utf-8')  # TODO centralize url decoding
        if cap_string in self._caps:
            root_object = self._caps[cap_string]
            path[0:1] = []
        else:
            raise Exception('Unknown cap')  # TODO better error reporting
        if len(path) == 1 and path[0].startswith(b'audio?rate='):
            rate = int(json.loads(urllib.unquote(path[0][len(b'audio?rate='):])))
            self.inner = AudioStreamInner(the_reactor, self.__send, root_object, rate)
        elif len(path) >= 1 and path[0] == CAP_OBJECT_PATH_ELEMENT:
            # note _lookup_block may throw. TODO: Better error reporting
            root_object = _lookup_block(root_object, path[1:])
            self.inner = StateStreamInner(self.__send, root_object, loc, self.__subscription_context)  # note reuse of loc as HTTP path; probably will regret this
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
            
            # TODO: There are no tests of this mechanism
            
            if safe_to_drop:
                self.__log.warn('Dropping data going to stream {url}', url=self.transport.location)
            else:
                self.__log.error('Dropping connection due to too much data on stream {url}', url=self.transport.location)
                self.transport.close(reason='Too much data buffered')
        else:
            self.transport.write(message)


def _fqn(class_):
    # per http://stackoverflow.com/questions/2020014/get-fully-qualified-class-name-of-an-object-in-python
    return class_.__module__ + '.' + class_.__name__


# TODO: Interfaces are not exported from the HTTP interface at all. This is a missing feature, and when it is added this code should move.
def _get_interfaces(obj):
    return [_fqn(interface) for interface in providedBy(obj)]
