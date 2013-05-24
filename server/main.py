#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor

import array # for binary stuff

import wfm  # temporary name to be improved

class GRResource(resource.Resource):
    isLeaf = True
    def __init__(self, target, field):
        '''Uses GNU Radio style accessors.'''
        self.target = target
        self.field = field
    def grrender(self, value):
        return str(value)
    def render_GET(self, request):
        return self.grrender(getattr(self.target, 'get_' + self.field)())
    def render_PUT(self, request):
        data = request.content.read()
        getattr(self.target, 'set_' + self.field)(self.grparse(data))
        request.setResponseCode(204)
        return ''

class NumberResource(GRResource):
    defaultContentType = 'text/plain'
    def grparse(self, value):
        return float(value)

class FloatsResource(GRResource):
    defaultContentType = 'application/octet-stream'
    def grrender(self, value):
        return array.array('f', value).tostring()

# Create SDR component
print 'Flow graph...'
block = wfm.wfm()

# Initialize web server first so we start accepting
print 'Web server...'
root = static.File('static/')
root.indexNames = ['index.html']
root.putChild('hw_freq', NumberResource(block, 'hw_freq'))
root.putChild('rec_freq', NumberResource(block, 'rec_freq'))
root.putChild('audio_gain', NumberResource(block, 'audio_gain'))
root.putChild('spectrum_fft', FloatsResource(block, 'spectrum_fft'))
reactor.listenTCP(8100, server.Site(root))

# Initialize SDR (slow)
print 'Starting...'
block.start()

# Actually process requests.
print 'Ready.'
reactor.run()