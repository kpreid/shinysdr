# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

"""Foundational ShinySDR HTTP/WebSocket API components."""

from __future__ import absolute_import, division, unicode_literals

import urllib

from twisted.web import http
from twisted.web import template
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.internet import endpoints
from twisted.python.util import sibpath

# TODO: Change this constant to something more generic, but save that for when we're changing the URL layout for other reasons anyway.
CAP_OBJECT_PATH_ELEMENT = b'radio'
UNIQUE_PUBLIC_CAP = 'public'


static_resource_path = sibpath(__file__, '../webstatic')
template_path = sibpath(__file__, '../webparts')
deps_path = sibpath(__file__, '../../deps')


class SlashedResource(Resource):
    """Redirects /.../this to /.../this/."""
    
    def render(self, request):
        request.setHeader(b'Location', request.childLink(b''))
        request.setResponseCode(http.MOVED_PERMANENTLY)
        return b''


def endpoint_string_to_url(desc, scheme='http', hostname='localhost', path='/', listening_port=None):
    """Construct a URL from a twisted.internet.endpoints string.
    
    If listening_port is supplied then it is used to obtain the actual port number."""
    (method, args, _) = endpoints._parseServer(desc, None)
    if listening_port:
        # assuming that this is a TCP port object
        port_number = listening_port.getHost().port
    else:
        port_number = args[0]
    if method == 'TCP':
        return scheme + '://' + hostname + ':' + str(port_number) + path
    elif method == 'SSL':
        return scheme + 's://' + hostname + ':' + str(port_number) + path
    else:
        # TODO better error return
        return '???'


def renderElement(request, element):
    # per http://stackoverflow.com/questions/8160061/twisted-web-resource-resource-with-twisted-web-template-element-example
    # should be replaced with twisted.web.template.renderElement once we have Twisted >= 12.1.0 available in MacPorts.
    
    # TODO: Instead of this kludge (here because it would be a syntax error in the XHTML template}, serve XHTML and fix the client-side issues that pop up due to element-name capitalization.
    request.write(b'<!doctype html>')
    
    d = template.flatten(request, element, request.write)
    
    def done(ignored):
        request.finish()
        return ignored
    
    d.addBoth(done)
    return NOT_DONE_YET


def prepath_escaped(request):
    """Like request.prePathURL() but without the scheme and hostname."""
    return '/' + '/'.join([urllib.quote(x, safe='') for x in request.prepath])
