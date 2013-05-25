#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor

import array # for binary stuff

import wfm # temporary name to be improved

class GRResource(resource.Resource):
	isLeaf = True
	def __init__(self, target, field):
		'''Uses GNU Radio style accessors.'''
		self.target = target
		self.field = field
	def grrender(self, value, request):
		return str(value)
	def render_GET(self, request):
		return self.grrender(getattr(self.target, 'get_' + self.field)(), request)
	def render_PUT(self, request):
		data = request.content.read()
		getattr(self.target, 'set_' + self.field)(self.grparse(data))
		request.setResponseCode(204)
		return ''

class IntResource(GRResource):
	defaultContentType = 'text/plain'
	def grparse(self, value):
		return int(value)

class FloatResource(GRResource):
	defaultContentType = 'text/plain'
	def grparse(self, value):
		return float(value)

class SpectrumResource(GRResource):
	defaultContentType = 'application/octet-stream'
	def grrender(self, value, request):
		(freq, fftdata) = value
		# TODO: Use a more structured response rather than putting data in headers
		request.setHeader('X-SDR-Center-Frequency', str(freq))
		return array.array('f', fftdata).tostring()

# Create SDR component
print 'Flow graph...'
block = wfm.wfm()

# Initialize web server first so we start accepting
print 'Web server...'
root = static.File('static/')
root.indexNames = ['index.html']
root.putChild('hw_freq', FloatResource(block, 'hw_freq'))
root.putChild('rec_freq', FloatResource(block, 'rec_freq'))
root.putChild('audio_gain', FloatResource(block, 'audio_gain'))
root.putChild('input_rate', IntResource(block, 'input_rate'))
root.putChild('spectrum_fft', SpectrumResource(block, 'spectrum_fft'))
reactor.listenTCP(8100, server.Site(root))

# Initialize SDR (slow)
print 'Starting...'
block.start()

# Actually process requests.
print 'Ready.'
reactor.run()