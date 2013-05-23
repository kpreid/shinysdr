#!/usr/bin/env python

from twisted.web import static, server, resource
from twisted.internet import reactor

import wfm  # temporary name to be improved

class NumberResource(resource.Resource):
    isLeaf = True
    defaultContentType = 'text/plain'
    def __init__(self, target, field):
        '''Uses GRC-generated accessors.'''
        self.target = target
        self.field = field
    def render_GET(self, request):
        print 'GET number'
        return str(getattr(self.target, 'get_' + self.field)())
    def render_PUT(self, request):
        data = request.content.read()
        print 'PUT number', data
        getattr(self.target, 'set_' + self.field)(float(data))
        request.setResponseCode(204)
        return ''

# Create SDR component
print 'Flow graph...'
block = wfm.wfm()

# Initialize web server first so we start accepting
print 'Web server...'
root = static.File('static/')
root.indexNames = ['index.html']
root.putChild('rec_freq', NumberResource(block, 'rec_freq'))
reactor.listenTCP(8100, server.Site(root))

# Initialize SDR (slow)
print 'Starting...'
block.start()

# Actually process requests.
print 'Ready.'
reactor.run()