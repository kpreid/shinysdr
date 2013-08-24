from twisted.web import static, server, resource
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import task
from twisted.application import strports

from gnuradio import gr

import txws

import array
import json
import urllib
import os.path
import weakref

import sdr.top

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
		return self._cell.ctor()(json.loads(value))

	def grrender(self, value, request):
		return json.dumps(value)


class SpectrumResource(CellResource):
	defaultContentType = 'application/octet-stream'

	def grrender(self, value, request):
		(freq, fftdata) = value
		# TODO: Use a more structured response rather than putting data in headers
		request.setHeader('X-SDR-Center-Frequency', str(freq))
		return array.array('f', fftdata).tostring()


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
				ctor = cell.ctor()
				if cell.isBlock():
					self._blockCells[key] = cell
				elif ctor is sdr.top.SpectrumTypeStub:
					self.putChild(key, SpectrumResource(cell, self._noteDirty))
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


def traverseUpdates(seen, block):
	"""Recursive algorithm for StateStreamInner"""
	updates = {}
	cells = block.state()
	for key, cell in cells.iteritems():
		if cell.isBlock():
			subblock = cell.getBlock()
			if key not in seen or seen[key][1] is not subblock:
				seen[key] = ({}, subblock)  # TODO will give 1 redundant update since seen is empty
				updates[key] = subblock.state_description()
			else:
				subupdates = traverseUpdates(seen[key][0], subblock)
				if len(subupdates) > 0:
					updates[key] = {'kind': 'block_updates', 'updates': subupdates}
		else:
			value = cell.get()
			if not key in seen or value != seen[key]:
				updates[key] = seen[key] = value
	dels = []
	for key in seen:
		if key not in cells:
			updates[key] = {'kind': 'block_delete'}
			dels.append(key)
	for key in dels:
		del seen[key]
	return updates


# TODO: Better name for this category of object
class StateStreamInner(object):
	def __init__(self, block):
		self._block = block
		self._seenValues = {}
	
	def connectionLost(self, reason):
		pass
	
	def takeMessage(self):
		updates = traverseUpdates(self._seenValues, self._block)
		if len(updates) == 0:
			# Nothing to say
			return None
		return updates


class AudioStreamInner(object):
	def __init__(self, block, audio_rate):
		self._queue = gr.msg_queue(limit=100)
		self._block = block
		self._block.add_audio_queue(self._queue, audio_rate)
	
	def connectionLost(self, reason):
		self._block.remove_audio_queue(self._queue)
	
	def takeMessage(self):
		queue = self._queue
		unpacker = array.array('f')
		while not queue.empty_p():
			message = queue.delete_head()
			if message.length() > 0: # avoid crash bug
				unpacker.fromstring(message.to_string())
		l = unpacker.tolist()
		if len(l) == 0:
			return None
		return l



class OurStreamProtocol(protocol.Protocol):
	def __init__(self, block, rootCap):
		#protocol.Protocol.__init__(self)
		self._block = block
		self._sendLoop = task.LoopingCall(self.doSend)
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
			self.inner = AudioStreamInner(self._block, rate)
		elif len(path) == 1 and path[0] == 'state':
			self.inner = StateStreamInner(self._block)
		else:
			# TODO: does this close connection?
			raise Exception('Unrecognized path: ' + repr(path))
		# TODO: slow/stop when radio not running, and determine suitable update rate based on querying objects
		self._sendLoop.start(1.0 / 61)
	
	def connectionMade(self):
		"""twisted Protocol implementation"""
		# Unfortunately, txWS calls this too soon for transport.location to be available
		pass
	
	def connectionLost(self, reason):
		"""twisted Protocol implementation"""
		if self._sendLoop.running:
			self._sendLoop.stop()
		if self.inner is not None:
			self.inner.connectionLost(reason)
	
	def doSend(self):
		if self.inner is None:
			return
		m = self.inner.takeMessage()
		if m is None:
			return
		# Note: txWS currently does not support binary WebSockets messages. Therefore, we send everything as JSON text. This is merely inefficient, not broken, so it will do for now.
		if len(self.transport.transport.dataBuffer) > 1000000:
			# TODO: condition is horrible implementation-diving kludge
			# Don't send data if we aren't successfully getting it onto the network.
			print 'Dropping data ' + self.transport.location
			return
		self.transport.write(json.dumps(m))


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


# used externally
staticResourcePath = os.path.join(os.path.dirname(__file__), 'webstatic')


def listen(config, top, noteDirty):
	rootCap = config['rootCap']
	
	strports.listen(config['wsPort'], txws.WebSocketFactory(OurStreamFactory(top, rootCap)))
	
	appRoot = static.File(staticResourcePath)
	appRoot.contentTypes['.csv'] = 'text/csv'
	appRoot.indexNames = ['index.html']
	appRoot.putChild('radio', BlockResource(top, noteDirty, notDeletable))
	
	if rootCap is None:
		root = appRoot
	else:
		root = resource.Resource()
		root.putChild(rootCap, appRoot)
	
	strports.listen(config['httpPort'], server.Site(root))

	# kludge to construct URL from strports string
	(hmethod, hargs, hkwargs) = strports.parse(config['httpPort'], None)
	print hmethod
	if hmethod == 'TCP':
		return 'http://localhost:' + str(hargs[0]) + '/'
	elif hmethod == 'SSL':
		return 'https://localhost:' + str(hargs[0]) + '/'
	else:
		return '???'
