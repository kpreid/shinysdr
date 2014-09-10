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

# pylint: disable=maybe-no-member, attribute-defined-outside-init, no-init
# (maybe-no-member is incorrect)
# (attribute-defined-outside-init is a Twisted convention for protocol objects)
# (no-init is pylint being confused by interfaces)


from __future__ import absolute_import, division

from twisted.application import strports
from twisted.application.service import Service
from twisted.internet import defer
from twisted.internet import protocol
from twisted.internet import reactor as the_reactor  # TODO fix
from twisted.internet import task
from twisted.plugin import IPlugin, getPlugins
from twisted.python import log
from twisted.web import http, static, server, resource, template
from zope.interface import Interface, implements, providedBy  # available via Twisted

from gnuradio import gr

import txws

import json
import urllib
import os.path
import struct
import weakref

import shinysdr.top
import shinysdr.plugins
import shinysdr.db
from shinysdr.signals import SignalType
from shinysdr.values import ExportedState, BaseCell, BlockCell, StreamCell, IWritableCollection, the_poller


# temporary kludge until upstream takes our patch
if hasattr(txws, 'WebSocketProtocol') and not hasattr(txws.WebSocketProtocol, 'setBinaryMode'):
	raise ImportError('The installed version of txWS does not support sending binary messages and cannot be used.')


# used externally
staticResourcePath = os.path.join(os.path.dirname(__file__), 'webstatic')


_templatePath = os.path.join(os.path.dirname(__file__), 'webparts')


def _json_encoder_special_cases(obj):
	# TODO consider a more general strategy once we have a second example
	if isinstance(obj, SignalType):
		return {
			u'kind': obj.get_kind(),
			u'sample_rate': obj.get_sample_rate(),
		}
	else:
		raise TypeError('Not serializable: ' + repr(obj))


# encoder which is set up for the way we want to deliver values to clients, including in the state stream
_json_encoder_for_values = json.JSONEncoder(
	ensure_ascii=False,
	check_circular=False,
	allow_nan=True,
	sort_keys=True,
	separators=(',', ':'),
	default=_json_encoder_special_cases)


class _SlashedResource(resource.Resource):
	'''Redirects /.../this to /.../this/.'''
	
	def render(self, request):
		request.setHeader('Location', request.childLink(''))
		request.setResponseCode(http.MOVED_PERMANENTLY)
		return ''


class CellResource(resource.Resource):
	isLeaf = True

	def __init__(self, cell, noteDirty):
		self._cell = cell
		# TODO: instead of needing this hook, main should use poller
		self._noteDirty = noteDirty

	def grparse(self, value):
		raise NotImplementedError()

	def grrender(self, value, request):
		return str(value)

	def render_GET(self, request):
		return self.grrender(self._cell.get(), request)

	def render_PUT(self, request):
		data = request.content.read()
		self._cell.set(self.grparse(data))
		request.setResponseCode(204)
		self._noteDirty()
		return ''
	
	def resourceDescription(self):
		return self._cell.description()


class ValueCellResource(CellResource):
	defaultContentType = 'application/json'

	def __init__(self, cell, noteDirty):
		CellResource.__init__(self, cell, noteDirty)

	def grparse(self, value):
		return json.loads(value)

	def grrender(self, value, request):
		return _json_encoder_for_values.encode(value).encode('utf-8')


def notDeletable():
	raise Exception('Attempt to delete top block')


class BlockResource(resource.Resource):
	defaultContentType = 'application/json'
	isLeaf = False

	def __init__(self, block, noteDirty, deleteSelf):
		resource.Resource.__init__(self)
		self._block = block
		self._noteDirty = noteDirty
		self._deleteSelf = deleteSelf
		self._dynamic = block.state_is_dynamic()
		# Weak dict ensures that we don't hold references to blocks that are no longer held by this block
		self._blockResourceCache = weakref.WeakKeyDictionary()
		if not self._dynamic:  # currently dynamic blocks can only have block children
			self._blockCells = {}
			for key, cell in block.state().iteritems():
				if cell.isBlock():
					self._blockCells[key] = cell
				else:
					self.putChild(key, ValueCellResource(cell, self._noteDirty))
		self.__element = _BlockHtmlElement()
	
	def getChild(self, name, request):
		if self._dynamic:
			curstate = self._block.state()
			if name in curstate:
				cell = curstate[name]
				if cell.isBlock():
					return self.__getBlockChild(name, cell.get())
		else:
			if name in self._blockCells:
				return self.__getBlockChild(name, self._blockCells[name].get())
		# old-style-class super call
		return resource.Resource.getChild(self, name, request)
	
	def __getBlockChild(self, name, block):
		r = self._blockResourceCache.get(block)
		if r is None:
			r = self.__makeChildBlockResource(name, block)
			self._blockResourceCache[block] = r
		return r
	
	def __makeChildBlockResource(self, name, block):
		def deleter():
			if not IWritableCollection.providedBy(self._block):
				raise Exception('Block is not a writable collection')
			self._block.delete_child(name)
		return BlockResource(block, self._noteDirty, deleter)
	
	def render_GET(self, request):
		accept = request.getHeader('Accept')
		if accept is not None and 'application/json' in accept:  # TODO: Implement or obtain correct Accept interpretation
			request.setHeader('Content-Type', 'application/json')
			return _json_encoder_for_values.encode(self.resourceDescription()).encode('utf-8')
		else:
			request.setHeader('Content-Type', 'text/html;charset=utf-8')
			return renderElement(request, self.__element)
	
	def render_POST(self, request):
		'''currently only meaningful to create children of CollectionResources'''
		block = self._block
		if not IWritableCollection.providedBy(block):
			raise Exception('Block is not a writable collection')
		assert request.getHeader('Content-Type') == 'application/json'
		reqjson = json.load(request.content)
		key = block.create_child(reqjson)  # note may fail
		self._noteDirty()
		url = request.prePathURL() + '/receivers/' + urllib.quote(key, safe='')
		request.setResponseCode(201)  # Created
		request.setHeader('Location', url)
		# TODO consider a more useful response
		return _json_encoder_for_values.encode(url).encode('utf-8')
	
	def render_DELETE(self, request):
		self._deleteSelf()
		self._noteDirty()
		request.setResponseCode(204)  # No Content
		return ''
	
	def resourceDescription(self):
		return self._block.state_description()
	
	def isForBlock(self, block):
		return self._block is block


class _BlockHtmlElement(template.Element):
	'''
	Template element for HTML page for an arbitrary block.
	'''
	loader = template.XMLFile(os.path.join(_templatePath, 'block.template.xhtml'))

	@template.renderer
	def _block_url(self, request, tag):
		return tag('/' + '/'.join([urllib.quote(x, safe='') for x in request.prepath]))


def _fqn(class_):
	# per http://stackoverflow.com/questions/2020014/get-fully-qualified-class-name-of-an-object-in-python
	return class_.__module__ + '.' + class_.__name__


def _get_interfaces(obj):
	return [_fqn(interface) for interface in providedBy(obj)]


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
			if isinstance(obj, StreamCell):  # TODO kludge
				self.__poller_registration = poller.subscribe(obj, self.__listen_binary_stream)
				self.initial_nudge = lambda: None
			else:
				self.__poller_registration = poller.subscribe(obj, self.__listen_cell)
				self.initial_nudge = self.__listen_cell
		else:
			self.__poller_registration = poller.subscribe_state(obj, self.__listen_state)
			self.initial_nudge = lambda: self.__listen_state(self.obj.state())
		self.__refcount = refcount
	
	def set_previous(self, value, is_references):
		if is_references:
			for obj in value.itervalues():
				if obj not in self.__ssi._registered:
					raise Exception("shouldn't happen: previous value not registered", obj)
		self.has_previous_value = True
		self.previous_value = value
		self.value_is_references = is_references
	
	def send_initial_value(self):
		'''kludge to get initial state sent'''
		
	
	def initial_nudge(self):
		raise NotImplementedError()  # should be overridden in instance
	
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
					if obj not in self.__ssi._registered:
						raise Exception("Shouldn't happen: previous value not registered", obj)
					self.__ssi._registered[obj].dec_refcount_and_maybe_notify()
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
			#print 'deleting', self.obj
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
				self.__ssi._registered[obj].dec_refcount_and_maybe_notify()


# TODO: Better name for this category of object
class StateStreamInner(object):
	def __init__(self, send, block, root_url, poller=the_poller):
		self.__poller = poller
		self._send = send
		self._block = block
		self._cell = BlockCell(self, '_block')
		self._lastSerial = 0
		root_registration = _StateStreamObjectRegistration(ssi=self, poller=self.__poller, obj=self._cell, serial=0, url=root_url, refcount=0)
		self._registered = {self._cell: root_registration}
		self._send_batch = []
		self.__batch_delay = None
		self.__root_url = root_url
		root_registration.initial_nudge()
	
	def connectionLost(self, reason):
		for obj in self._registered.keys():
			self.__drop(obj)
	
	def do_delete(self, reg):
		self._send1(False, ('delete', reg.serial))
		self.__drop(reg.obj)
	
	def __drop(self, obj):
		self._registered[obj].drop()
		del self._registered[obj]
	
	def _lookup_or_register(self, obj, url):
		if obj in self._registered:
			return self._registered[obj]
		else:
			self._lastSerial += 1
			serial = self._lastSerial
			#print 'registering', obj, serial
			registration = _StateStreamObjectRegistration(ssi=self, poller=self.__poller, obj=obj, serial=serial, url=url, refcount=0)
			self._registered[obj] = registration
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
			registration.initial_nudge()
			return registration
	
	def _flush(self):  # exposed for testing
		self.__batch_delay = None
		if len(self._send_batch) > 0:
			# unicode() because JSONEncoder does not reliably return a unicode rather than str object
			self._send(unicode(_json_encoder_for_values.encode(self._send_batch)))
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
	def __init__(self, send, block, audio_rate):
		self._send = send
		self._queue = gr.msg_queue(limit=100)
		self._block = block
		self._block.add_audio_queue(self._queue, audio_rate)
		# TODO: slow/stop when stream is not running. Better yet, use something that twisted can wait on like a pipe.
		self.__poll_loop = task.LoopingCall(self.__poll)
		self.__poll_loop.start(1.0 / 61)
	
	def connectionLost(self, reason):
		self._block.remove_audio_queue(self._queue)
		if self.__poll_loop.running:
			self.__poll_loop.stop()
	
	def __poll(self):
		queue = self._queue
		buf = ''
		while not queue.empty_p():
			message = queue.delete_head()
			if message.length() > 0:  # avoid crash bug
				buf += message.to_string()
		if len(buf) > 0:
			self._send(buf, safe_to_drop=True)


def _lookup_block(block, path):
	for i, path_elem in enumerate(path):
		cell = block.state().get(path_elem)
		if cell is None:
			raise Exception('Not found: %r in %r' % (path[:i+1], path))
		elif not cell.isBlock():
			raise Exception('Not a block: %r in %r' % (path[:i+1], path))
		block = cell.get()
	return block


class OurStreamProtocol(protocol.Protocol):
	def __init__(self, block, rootCap):
		#protocol.Protocol.__init__(self)
		self._block = block
		self._seenValues = {}
		self._rootCap = rootCap
		self.inner = None
	
	def dataReceived(self, data):
		"""twisted Protocol implementation"""
		if self.inner is not None:
			return
		loc = self.transport.location
		log.msg('Stream connection to ', loc)
		path = [urllib.unquote(x) for x in loc.split('/')]
		assert path[0] == ''
		path[0:1] = []
		# TODO: Better path dispatching
		if self._rootCap is not None:
			if path[0] != self._rootCap:
				raise Exception('Unknown cap')
			else:
				path[0:1] = []
		if len(path) == 1 and path[0].startswith('audio?rate='):
			rate = int(json.loads(urllib.unquote(path[0][len('audio?rate='):])))
			self.inner = AudioStreamInner(self.__send, self._block, rate)
		elif len(path) >= 1 and path[0] == 'radio':
			# note _lookup_block may throw. TODO: Better error reporting
			block = _lookup_block(self._block, path[1:])
			self.inner = StateStreamInner(self.__send, block, loc)  # note reuse of loc as HTTP path; probably will regret this
		else:
			raise Exception('Unknown path: %r' % (path,))
	
	def connectionMade(self):
		"""twisted Protocol implementation"""
		self.transport.setBinaryMode(True)
		# Unfortunately, txWS calls this too soon for transport.location to be available
	
	def connectionLost(self, reason):
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
	
	def __poll(self):
		if self.inner is not None:
			self.inner.poll()


class OurStreamFactory(protocol.Factory):
	protocol = OurStreamProtocol
	
	def __init__(self, block, rootCap):
		#protocol.Factory.__init__(self)
		self._block = block
		self._rootCap = rootCap
	
	def buildProtocol(self, addr):
		"""twisted Factory implementation"""
		p = self.protocol(self._block, self._rootCap)
		p.factory = self
		return p


class IClientResourceDef(Interface):
	'''
	Client plugin interface object
	'''
	# Only needed to make the plugin system work
	# TODO write interface methods anyway


class ClientResourceDef(object):
	implements(IPlugin, IClientResourceDef)
	
	def __init__(self, key, resource, loadURL=None):
		self.key = key
		self.resource = resource
		self.loadURL = loadURL


def _make_static(filePath):
	r = static.File(filePath)
	r.contentTypes['.csv'] = 'text/csv'
	r.indexNames = ['index.html']
	r.ignoreExt('.html')
	return r


def _reify(parent, name):
	'''
	Construct an explicit twisted.web.static.File child identical to the implicit one so that non-filesystem children can be added to it.
	'''
	r = parent.createSimilarFile(parent.child(name).path)
	parent.putChild(name, r)
	return r


def _strport_to_url(desc, scheme='http', path='/', socket_port=0):
	'''Construct a URL from a twisted.application.strports string.'''
	# TODO: need to know canonical domain name, not localhost; can we extract from the ssl cert?
	# TODO: strports.parse is deprecated
	(method, args, _) = strports.parse(desc, None)
	if socket_port == 0:
		socket_port = args[0]
	if method == 'TCP':
		return scheme + '://localhost:' + str(socket_port) + path
	elif method == 'SSL':
		return scheme + 's://localhost:' + str(socket_port) + path
	else:
		# TODO better error return
		return '???'


class _RadioIndexHtmlElement(template.Element):
	loader = template.XMLFile(os.path.join(_templatePath, 'index.template.xhtml'))
	
	def __init__(self, title):
		self.__title = unicode(title)
	
	@template.renderer
	def title(self, request, tag):
		return tag(self.__title)


class _RadioIndexHtmlResource(resource.Resource):
	isLeaf = True

	def __init__(self, title):
		self.__element = _RadioIndexHtmlElement(title)

	def render_GET(self, request):
		return renderElement(request, self.__element)


def renderElement(request, element):
	# per http://stackoverflow.com/questions/8160061/twisted-web-resource-resource-with-twisted-web-template-element-example
	# should be replaced with twisted.web.template.renderElement once we have Twisted >= 12.1.0 available in MacPorts.
	d = template.flatten(request, element, request.write)
	
	def done(ignored):
		request.finish()
		return ignored
	
	d.addBoth(done)
	return server.NOT_DONE_YET
	

class WebService(Service):
	# TODO: Too many parameters
	def __init__(self, reactor, top, note_dirty, read_only_dbs, writable_db, http_endpoint, ws_endpoint, root_cap, title):
		self.__http_port = http_endpoint
		self.__ws_port = ws_endpoint
		
		self.__ws_protocol = txws.WebSocketFactory(OurStreamFactory(top, root_cap))
		
		# Roots of resource trees
		# - appRoot is everything stateful/authority-bearing
		# - serverRoot is the HTTP '/' and static resources are placed there
		serverRoot = _make_static(staticResourcePath)
		if root_cap is None:
			appRoot = serverRoot
			self.__visit_path = '/'
		else:
			serverRoot = _make_static(staticResourcePath)
			appRoot = _SlashedResource()
			serverRoot.putChild(root_cap, appRoot)
			self.__visit_path = '/' + urllib.quote(root_cap, safe='') + '/'
		
		# UI entry point
		appRoot.putChild('', _RadioIndexHtmlResource(title))
		
		# Exported radio control objects
		appRoot.putChild('radio', BlockResource(top, note_dirty, notDeletable))
		
		# Frequency DB
		appRoot.putChild('dbs', shinysdr.db.DatabasesResource(read_only_dbs))
		appRoot.putChild('wdb', shinysdr.db.DatabaseResource(writable_db))
		
		# Construct explicit resources for merge.
		test = _reify(serverRoot, 'test')
		jasmine = _reify(test, 'jasmine')
		for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
			jasmine.putChild(name, static.File(os.path.join(
					os.path.dirname(__file__), 'deps/jasmine/lib/jasmine-core/', name)))
		
		client = _reify(serverRoot, 'client')
		client.putChild('openlayers', static.File(os.path.join(
			os.path.dirname(__file__), 'deps/openlayers')))
		client.putChild('require.js', static.File(os.path.join(
			os.path.dirname(__file__), 'deps/require.js')))
		
		# Plugin resources
		loadList = []
		pluginResources = resource.Resource()
		client.putChild('plugins', pluginResources)
		for resourceDef in getPlugins(IClientResourceDef, shinysdr.plugins):
			pluginResources.putChild(resourceDef.key, resourceDef.resource)
			if resourceDef.loadURL is not None:
				# TODO constrain value
				loadList.append('/client/plugins/' + urllib.quote(resourceDef.key, safe='') + '/' + resourceDef.loadURL)
		
		# Client plugin list
		client.putChild('plugin-index.json', static.Data(_json_encoder_for_values.encode(loadList).encode('utf-8'), 'application/json'))
		
		self.__site = server.Site(serverRoot)
		self.__ws_port_obj = None
		self.__http_port_obj = None
	
	def startService(self):
		Service.startService(self)
		if self.__ws_port_obj is not None:
			raise Exception('Already started')
		self.__ws_port_obj = strports.listen(self.__ws_port, self.__ws_protocol)
		self.__http_port_obj = strports.listen(self.__http_port, self.__site)
	
	def stopService(self):
		Service.stopService(self)
		if self.__ws_port_obj is None:
			raise Exception('Not started, cannot stop')
		# TODO: Does Twisted already have something to bundle up a bunch of ports for shutdown?
		return defer.DeferredList([
			self.__http_port_obj.stopListening(),
			self.__ws_port_obj.stopListening()])
	
	def get_url(self):
		port_num = self.__http_port_obj.socket.getsockname()[1]  # TODO touching implementation, report need for a better way (web_port_obj.port is 0 if specified port is 0, not actual port)
	
		return _strport_to_url(self.__http_port, socket_port=port_num, path=self.__visit_path)

	def announce(self, open_client):
		'''interface used by shinysdr.main'''
		url = self.get_url()
		if open_client:
			log.msg('Opening ' + url)
			import webbrowser  # lazy load
			webbrowser.open(url, new=1, autoraise=True)
		else:
			log.msg('Visit ' + url)
