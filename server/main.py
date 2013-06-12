#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor

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
	isLeaf = False
	def __init__(self, block):
		resource.Resource.__init__(self)
		self._blockResources = {}
		self._block = block
		def callback(key, persistent, ctor):
			if key.endswith('_state'): # TODO: kludge
				self._blockResources[key[:-len('_state')]] = None
			if ctor is sdr.top.SpectrumTypeStub:
				self.putChild(key, SpectrumResource(block, key))
			else:
				self.putChild(key, JSONResource(block, key, ctor))
		block.state_keys(callback)
	
	def getChild(self, name, request):
		if name in self._blockResources:
			currentResource = self._blockResources[name]
			currentBlock = getattr(self._block, name)
			if currentResource is None or not currentResource.isForBlock(currentBlock):
				self._blockResources[name] = currentResource = BlockResource(currentBlock)
			return currentResource
		else:
			return resource.Resource.getChild(self, name, request)
	
	def isForBlock(self, block):
		return self._block is block

# Create SDR component (slow)
print 'Flow graph...'
top = sdr.top.Top()
restore(top)

# Initialize web server first so we start accepting
print 'Web server...'
port = 8100
root = static.File('static/')
root.contentTypes['.csv'] = 'text/csv'
root.indexNames = ['index.html']
root.putChild('radio', BlockResource(top))
reactor.listenTCP(port, server.Site(root))

# Actually process requests.
print 'Ready. Visit http://localhost:' + str(port) + '/'
reactor.run()
