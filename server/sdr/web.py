from twisted.web import static, server, resource
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import task

import txws

import array
import json

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


class BlockResource(resource.Resource):
	defaultContentType = 'application/json'
	isLeaf = False

	def __init__(self, block, noteDirty):
		resource.Resource.__init__(self)
		self._blockResources = {}
		self._blockCells = {}
		self._block = block
		self._noteDirty = noteDirty
		for key, cell in block.state().iteritems():
			ctor = cell.ctor()
			if cell.isBlock():
				self._blockResources[key] = None
				self._blockCells[key] = cell
			elif ctor is sdr.top.SpectrumTypeStub:
				self.putChild(key, SpectrumResource(cell, self._noteDirty))
			else:
				self.putChild(key, JSONResource(cell, self._noteDirty))
	
	def getChild(self, name, request):
		if name in self._blockResources:
			currentResource = self._blockResources[name]
			currentBlock = self._blockCells[name].getBlock()
			if currentResource is None or not currentResource.isForBlock(currentBlock):
				self._blockResources[name] = currentResource = BlockResource(currentBlock, self._noteDirty)
			return currentResource
		else:
			return resource.Resource.getChild(self, name, request)
	
	def render_GET(self, request):
		return json.dumps(self.resourceDescription())
	
	def resourceDescription(self):
		return self._block.state_description()
	
	def isForBlock(self, block):
		return self._block is block


def traverseUpdates(seen, block):
	updates = {}
	for key, cell in block.state().iteritems():
		if cell.isBlock():
			subblock = cell.getBlock()
			if key not in seen:
				seen[key] = ({}, subblock)
			if seen[key][1] is not subblock:
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
	return updates


class StateStreamProtocol(protocol.Protocol):
	def __init__(self, block):
		#protocol.Protocol.__init__(self)
		self._block = block
		self._stateLoop = task.LoopingCall(self.sendState)
		# TODO: slow/stop when radio not running
		self._stateLoop.start(1.0 / 30)
		self._seenValues = {}
	
	def dataReceived(self, data):
		"""twisted Protocol implementation"""
		pass
	
	def connectionLost(self, reason):
		"""twisted Protocol implementation"""
		self._stateLoop.stop()
	
	def sendState(self):
		# Note: txWS currently does not support binary WebSockets messages. Therefore, we send everything as JSON text. This is merely inefficient, not broken, so it will do for now.
		if self.transport is None:
			# seems to be missing first time
			return
		# Simplest thing that works: Obtain all the data, send it if it's different.
		updates = traverseUpdates(self._seenValues, self._block)
		if len(updates) == 0:
			# Nothing to say
			return
		data = json.dumps(updates)
		if len(self.transport.transport.dataBuffer) > 100000:
			# TODO: condition is horrible implementation-diving kludge
			# Don't send data if we aren't successfully getting it onto the network.
			return
		self.transport.write(data)


class StateStreamFactory(protocol.Factory):
	protocol = StateStreamProtocol
	
	def __init__(self, block):
		#protocol.Factory.__init__(self)
		self._block = block
	
	def buildProtocol(self, addr):
		"""twisted Factory implementation"""
		p = StateStreamProtocol(self._block)
		p.factory = self
		return p

def listen(top, noteDirty):
	wsport = 8101
	reactor.listenTCP(wsport, txws.WebSocketFactory(StateStreamFactory(top)))
	
	port = 8100
	root = static.File('static/')
	root.contentTypes['.csv'] = 'text/csv'
	root.indexNames = ['index.html']
	root.putChild('radio', BlockResource(top, noteDirty))
	reactor.listenTCP(port, server.Site(root))
	
	return 'http://localhost:' + str(port) + '/'