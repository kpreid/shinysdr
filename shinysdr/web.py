# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

from twisted.web import static, server, resource
from twisted.internet import protocol
from twisted.internet import task
from twisted.application import strports
from twisted.plugin import IPlugin, getPlugins
from zope.interface import Interface, implements  # available via Twisted

from gnuradio import gr

import txws

import array
import json
import urllib
import os.path
import struct
import weakref

import shinysdr.top
import shinysdr.plugins
import shinysdr.db
from shinysdr.values import ExportedState, BaseCell, BlockCell, MsgQueueCell


class CellResource(resource.Resource):
	isLeaf = True

	def __init__(self, cell, noteDirty):
		self._cell = cell
		# TODO: instead of needing this hook, main should reuse traverseUpdates
		self._noteDirty = noteDirty

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


class JSONResource(CellResource):
	defaultContentType = 'application/json'

	def __init__(self, cell, noteDirty):
		CellResource.__init__(self, cell, noteDirty)

	def grparse(self, value):
		return json.loads(value)

	def grrender(self, value, request):
		print repr(value)
		return json.dumps(value)


def notDeletable():
	raise "Attempt to delete top block"


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
		if not self._dynamic: # currently dynamic blocks can only have block children
			self._blockCells = {}
			for key, cell in block.state().iteritems():
				if cell.isBlock():
					self._blockCells[key] = cell
				else:
					self.putChild(key, JSONResource(cell, self._noteDirty))
	
	def getChild(self, name, request):
		if self._dynamic:
			curstate = self._block.state()
			if name in curstate:
				cell = curstate[name]
				if cell.isBlock():
					return self.__getBlockChild(name, cell.getBlock())
		else:
			if name in self._blockCells:
				return self.__getBlockChild(name, self._blockCells[name].getBlock())
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
			self._block.delete_child(name)
		return BlockResource(block, self._noteDirty, deleter)
	
	def render_GET(self, request):
		return json.dumps(self.resourceDescription())
	
	def render_POST(self, request):
		'''currently only meaningful to create children of CollectionResources'''
		block = self._block
		assert request.getHeader('Content-Type') == 'application/json'
		reqjson = json.load(request.content)
		key = block.create_child(reqjson)  # note may fail
		self._noteDirty()
		url = request.prePathURL() + '/receivers/' + urllib.quote(key, safe='')
		request.setResponseCode(201) # Created
		request.setHeader('Location', url)
		# TODO consider a more useful response
		return json.dumps(url)
	
	def render_DELETE(self, request):
		self._deleteSelf()
		self._noteDirty()
		request.setResponseCode(204) # No Content
		return ''
	
	def resourceDescription(self):
		return self._block.state_description()
	
	def isForBlock(self, block):
		return self._block is block

# TODO: Better name for this category of object
class StateStreamInner(object):
	def __init__(self, send, block, rootURL):
		self._send = send
		self._block = block
		self._cell = BlockCell(self, '_block')
		self._previousValues = {}
		self._lastSerial = 0
		self._registered = {self._cell: 0}
		self._urls = {self._cell: rootURL}
		self._send_batch = []
	
	def connectionLost(self, reason):
		pass
	
	def _checkUpdates(self):
		seen_this_time = set([self._cell])
		def maybesend(obj, compare_value, update_value):
			if obj not in self._previousValues or compare_value != self._previousValues[obj]:
				self._previousValues[obj] = compare_value
				self.__send1(False, ('value', self._registered[obj], update_value))
		def traverse(obj):
			#print 'traverse', obj, self._registered.get(obj, None)
			if isinstance(obj, ExportedState):
				#print '  is block'
				url = self._urls[obj]
				for key, cell in obj.state().iteritems():
					#print '  child: ', key, cell
					meet(cell, url + '/' + urllib.unquote(key))
				if obj.state_is_dynamic() or obj not in self._previousValues:
					# functions as (current) signature of object
					state = obj.state()
					maybesend(obj, state, {k: self._registered[v] for k, v in state.iteritems()})
				else:
					state = None
			elif isinstance(obj, BaseCell):   # TODO: be an interface type?
				#print '  is cell'
				if obj.isBlock():
					block = obj.getBlock()
					meet(block, self._urls[obj])
					maybesend(obj, block, self._registered[block])
				elif isinstance(obj, MsgQueueCell):  # TODO kludge
					b = obj.get(binary=True)
					if b is not None:
						self.__send1(True, struct.pack('I', self._registered[obj]) + b)
				else:
					value = obj.get()
					maybesend(obj, value, value)
			else:
				#print '  unrecognized'
				# TODO: warn unrecognized
				return
		def meet(obj, url):
			#print 'meet', obj, url
			seen_this_time.add(obj)
			if obj not in self._registered:
				self._lastSerial += 1
				serial = self._lastSerial
				#print 'registering', obj, serial
				self._registered[obj] = serial
				self._urls[obj] = url
				if isinstance(obj, BaseCell):
					self.__send1(False, ('register_cell', serial, url, obj.description()))
					self._previousValues[obj] = obj.get()
				elif isinstance(obj, ExportedState):
					# let traverse send the details
					self.__send1(False, ('register_block', serial, url))
				else:
					self.__send1(False, ('register', serial, url))
			traverse(obj)
		# walk
		traverse(self._cell)
		# delete not seen
		for obj in self._registered.keys():
			if obj not in seen_this_time:
				self.__send1(False, ('delete', self._registered[obj]))
				del self._registered[obj]
				del self._previousValues[obj]
				del self._urls[obj]
	
	def __flush(self):
		if len(self._send_batch) > 0:
			self._send(unicode(json.dumps(self._send_batch, ensure_ascii=False)))
			self._send_batch = []
	
	def __send1(self, binary, value):
		if binary:
			self.__flush()
			self._send(value)
		else:
			self._send_batch.append(value)
	
	def poll(self):
		self._checkUpdates()
		self.__flush()


class AudioStreamInner(object):
	def __init__(self, send, block, audio_rate):
		self._send = send
		self._queue = gr.msg_queue(limit=100)
		self._block = block
		self._block.add_audio_queue(self._queue, audio_rate)
	
	def connectionLost(self, reason):
		self._block.remove_audio_queue(self._queue)
	
	def poll(self):
		queue = self._queue
		buf = ''
		while not queue.empty_p():
			message = queue.delete_head()
			if message.length() > 0: # avoid crash bug
				buf += message.to_string()
		if len(buf) > 0:
			self._send(buf)


class OurStreamProtocol(protocol.Protocol):
	def __init__(self, block, rootCap):
		#protocol.Protocol.__init__(self)
		self._block = block
		self._sendLoop = task.LoopingCall(self.__poll)
		self._seenValues = {}
		self._rootCap = rootCap
		self.inner = None
	
	def dataReceived(self, data):
		"""twisted Protocol implementation"""
		if self.inner is not None:
			return
		loc = self.transport.location
		print 'WebSocket connection to', loc
		path = [urllib.unquote(x) for x in loc.split('/')]
		assert path[0] == ''
		path[0:1] = []
		if self._rootCap is not None:
			if path[0] != self._rootCap:
				raise Exception('Unknown cap')
			else:
				path[0:1] = []
		if len(path) == 1 and path[0].startswith('audio?rate='):
			rate = int(json.loads(urllib.unquote(path[0][len('audio?rate='):])))
			self.inner = AudioStreamInner(self.__send, self._block, rate)
		elif len(path) == 1 and path[0] == 'state':
			self.inner = StateStreamInner(self.__send, self._block, 'radio')
		else:
			# TODO: does this close connection?
			raise Exception('Unrecognized path: ' + repr(path))
		# TODO: slow/stop when radio not running, and determine suitable update rate based on querying objects
		self._sendLoop.start(1.0 / 61)
	
	def connectionMade(self):
		"""twisted Protocol implementation"""
		self.transport.setBinaryMode(True)
		# Unfortunately, txWS calls this too soon for transport.location to be available
		pass
	
	def connectionLost(self, reason):
		"""twisted Protocol implementation"""
		if self._sendLoop.running:
			self._sendLoop.stop()
		if self.inner is not None:
			self.inner.connectionLost(reason)
	
	def __send(self, message):
		if len(self.transport.transport.dataBuffer) > 1000000:
			# TODO: condition is horrible implementation-diving kludge
			# Don't accumulate indefinite buffer if we aren't successfully getting it onto the network.
			print 'Dropping data ' + self.transport.location
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


# used externally
staticResourcePath = os.path.join(os.path.dirname(__file__), 'webstatic')


def _make_static(filePath):
	r = static.File(filePath)
	r.contentTypes['.csv'] = 'text/csv'
	r.indexNames = ['index.html']
	return r


def _reify(parent, name):
	'''
	Construct an explicit twisted.web.static.File child identical to the implicit one so that non-filesystem children can be added to it.
	'''
	r = parent.createSimilarFile(parent.child(name).path)
	parent.putChild(name, r)
	return r


def _strport_to_url(desc, scheme='http', path='/'):
	'''Construct a URL from a twisted.application.strports string.'''
	# TODO: need to know canonical domain name, not localhost; can we extract from the ssl cert?
	# TODO: strports.parse is deprecated
	(method, args, kwargs) = strports.parse(desc, None)
	if method == 'TCP':
		return scheme + '://localhost:' + str(args[0]) + path
	elif method == 'SSL':
		return scheme + 's://localhost:' + str(args[0]) + path
	else:
		# TODO better error return
		return '???'


def listen(config, top, noteDirty):
	rootCap = config['rootCap']
	
	strports.listen(config['wsPort'], txws.WebSocketFactory(OurStreamFactory(top, rootCap)))
	
	appRoot = _make_static(staticResourcePath)
	appRoot.putChild('radio', BlockResource(top, noteDirty, notDeletable))
	
	# Frequency DB
	appRoot.putChild('dbs', shinysdr.db.DatabasesResource(config['databasesDir']))
	
	# Construct explicit resources for merge.
	test = _reify(appRoot, 'test')
	jasmine = _reify(test, 'jasmine')
	for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
		jasmine.putChild(name, static.File(os.path.join(
				os.path.dirname(__file__), 'deps/jasmine/lib/jasmine-core/', name)))
	
	client = _reify(appRoot, 'client')
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
			loadList.append('client/plugins/' + urllib.quote(resourceDef.key, safe='') + '/' + resourceDef.loadURL)
	
	# Client plugin list
	client.putChild('plugin-index.json', static.Data(json.dumps(loadList), 'application/json'))
	
	if rootCap is None:
		root = appRoot
		visitPath = '/'
	else:
		root = resource.Resource()
		root.putChild(rootCap, appRoot)
		visitPath = '/' + urllib.quote(rootCap, safe='') + '/'
	
	strports.listen(config['httpPort'], server.Site(root))
	
	return _strport_to_url(config['httpPort'], path=visitPath)
