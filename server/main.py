#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor

import array # for binary stuff
import json
import os

import sdr.top
import sdr.wfm

filename = 'state.json'
def noteDirty():
	with open(filename, 'w') as f:
		json.dump(top.state_to_json(), f)
	pass

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

class IntResource(GRResource):
	defaultContentType = 'text/plain'
	def grparse(self, value):
		return int(value)

class FloatResource(GRResource):
	defaultContentType = 'text/plain'
	def grparse(self, value):
		return float(value)

class StringResource(GRResource):
	defaultContentType = 'text/plain'
	def grparse(self, value):
		return value

class SpectrumResource(GRResource):
	defaultContentType = 'application/octet-stream'
	def grrender(self, value, request):
		(freq, fftdata) = value
		# TODO: Use a more structured response rather than putting data in headers
		request.setHeader('X-SDR-Center-Frequency', str(freq))
		return array.array('f', fftdata).tostring()

class StartStop(resource.Resource):
	isLeaf = True
	def __init__(self, targetThunk, junk_field):
		self.target = targetThunk()
		self.running = False
	def render_GET(self, request):
		return json.dumps(self.running)
	def render_PUT(self, request):
		value = bool(json.load(request.content))
		if value != self.running:
			self.running = value
			if value:
				self.target.start()
			else:
				self.target.stop()
				self.target.wait()
		request.setResponseCode(204)
		return ''

# Create SDR component (slow)
print 'Flow graph...'
top = sdr.top.Top()
if os.path.isfile(filename):
	top.state_from_json(json.load(open(filename, 'r')))

# Initialize web server first so we start accepting
print 'Web server...'
root = static.File('static/')
root.indexNames = ['index.html']
def export(blockThunk, field, ctor):
	root.putChild(field, ctor(blockThunk, field))
def gtop(): return top
def grec(): return top.receiver
export(gtop, 'running', StartStop)
export(gtop, 'hw_freq', FloatResource)
export(gtop, 'mode', StringResource)
export(grec, 'band_filter', FloatResource)
export(grec, 'rec_freq', FloatResource)
export(grec, 'audio_gain', FloatResource)
export(grec, 'squelch_threshold', FloatResource)
export(gtop, 'input_rate', IntResource)
export(gtop, 'spectrum_fft', SpectrumResource)
reactor.listenTCP(8100, server.Site(root))

# Actually process requests.
print 'Ready.'
reactor.run()