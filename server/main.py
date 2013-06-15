#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import task

import txws

import array # for binary stuff
import json
import os
import shutil

import sdr.top
import sdr.wfm

filename = 'state.json'
def noteDirty():
	with open(filename, 'w') as f:
		json.dump(top.state_to_json(), f)
	pass
def restore(root):
	if os.path.isfile(filename):
		root.state_from_json(json.load(open(filename, 'r')))
		# make a backup in case this code version misreads the state and loses things on save (but only if the load succeeded, in case the file but not its backup is bad)
		shutil.copyfile(filename, filename + '~')
	

class GRResource(resource.Resource):
	isLeaf = True
	def __init__(self, block, field):
		'''Uses GNU Radio style accessors.'''
		self._block = block
		self.field = field
	def grrender(self, value, request):
		return str(value)
	def render_GET(self, request):
		return self.grrender(getattr(self._block, 'get_' + self.field)(), request)
	def render_PUT(self, request):
		data = request.content.read()
		getattr(self._block, 'set_' + self.field)(self.grparse(data))
		request.setResponseCode(204)
		noteDirty()
		return ''
	
	def resourceDescription(self):
		return {'kind': 'value'}

class JSONResource(GRResource):
	defaultContentType = 'application/json'
	def __init__(self, block, field, ctor):
		GRResource.__init__(self, block, field)
		self.parseCtor = ctor
	def grparse(self, value):
		return self.parseCtor(json.loads(value))
	def grrender(self, value, request):
		return json.dumps(value)

class SpectrumResource(GRResource):
	defaultContentType = 'application/octet-stream'
	def grrender(self, value, request):
		(freq, fftdata) = value
		# TODO: Use a more structured response rather than putting data in headers
		request.setHeader('X-SDR-Center-Frequency', str(freq))
		return array.array('f', fftdata).tostring()

class BlockResource(resource.Resource):
	defaultContentType = 'application/json'
	isLeaf = False
	def __init__(self, block):
		resource.Resource.__init__(self)
		self._blockResources = {}
		self._block = block
		for key, cell in block.state().iteritems():
			ctor = cell.ctor()
			if key.endswith('_state'): # TODO: kludge
				self._blockResources[key[:-len('_state')]] = None
			if ctor is sdr.top.SpectrumTypeStub:
				self.putChild(key, SpectrumResource(block, key))
			else:
				self.putChild(key, JSONResource(block, key, ctor))
	
	def getChild(self, name, request):
		if name in self._blockResources:
			currentResource = self._blockResources[name]
			currentBlock = getattr(self._block, name)
			if currentResource is None or not currentResource.isForBlock(currentBlock):
				self._blockResources[name] = currentResource = BlockResource(currentBlock)
			return currentResource
		else:
			return resource.Resource.getChild(self, name, request)
	
	def render_GET(self, request):
		return json.dumps(self.resourceDescription())
	
	def resourceDescription(self):
		childDescs = {}
		description = {
			'kind': 'block',
			'children': childDescs
		}
		for key in self.children:
			# TODO: include URLs
			childDescs[key] = self.children[key].resourceDescription()
		return description
	
	def isForBlock(self, block):
		return self._block is block


def traverseUpdates(seen, block):
	updates = {}
	for key, cell in block.state().iteritems():
		if key.endswith('_state'): # TODO: kludge
			subkey = key[:-len('_state')]
			subblock = getattr(block, subkey)
			if subkey not in seen:
				seen[subkey] = {}
			subupdates = traverseUpdates(seen[subkey], subblock)
			if len(subupdates) > 0:
				updates[subkey] = subupdates
		else:
			value = getattr(block, 'get_' + key)()
			if not key in seen or value != seen[key]:
				updates[key] = seen[key] = value
	return updates

class StateStreamProtocol(protocol.Protocol):
	def __init__(self, block):
		#protocol.Protocol.__init__(self)
		self._block = block
		self._stateLoop = task.LoopingCall(self.sendState)
		# TODO: slow/stop when radio not running
		self._stateLoop.start(1.0/30)
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

print 'Flow graph...'
# Note: This is slow as it triggers the OsmoSDR device initialization
top = sdr.top.Top()
restore(top)

print 'WebSockets server...'
wsport = 8101
reactor.listenTCP(wsport, txws.WebSocketFactory(StateStreamFactory(top)))

print 'Web server...'
port = 8100
root = static.File('static/')
root.contentTypes['.csv'] = 'text/csv'
root.indexNames = ['index.html']
root.putChild('radio', BlockResource(top))
reactor.listenTCP(port, server.Site(root))

print 'Ready. Visit http://localhost:' + str(port) + '/'
reactor.run()
