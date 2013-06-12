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
	def __init__(self, targetThunk, field):
		'''Uses GNU Radio style accessors.'''
		self.targetThunk = targetThunk
		self.field = field
	def grrender(self, value, request):
		return str(value)
	def render_GET(self, request):
		return self.grrender(getattr(self.targetThunk(), 'get_' + self.field)(), request)
	def render_PUT(self, request):
		data = request.content.read()
		getattr(self.targetThunk(), 'set_' + self.field)(self.grparse(data))
		request.setResponseCode(204)
		noteDirty()
		return ''

class JSONResource(GRResource):
	defaultContentType = 'application/json'
	def __init__(self, targetThunk, field, ctor):
		GRResource.__init__(self, targetThunk, field)
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
	def __init__(self, blockThunk):
		# TODO: blockThunk is a kludge; arrange to swap out resources as needed instead
		resource.Resource.__init__(self)
		def callback(key, persistent, ctor):
			print 'Would put: ', key
			if ctor is sdr.top.SpectrumTypeStub:
				self.putChild(key, SpectrumResource(blockThunk, key))
			else:
				self.putChild(key, JSONResource(blockThunk, key, ctor))
		blockThunk().state_keys(callback)

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
radio = BlockResource(lambda: top)
radio.putChild('receiver', BlockResource(lambda: top.receiver))
root.putChild('radio', radio)
reactor.listenTCP(port, server.Site(root))

# Actually process requests.
print 'Ready. Visit http://localhost:' + str(port) + '/'
reactor.run()
