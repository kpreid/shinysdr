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

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple
import six
from six.moves import urllib

from twisted.web import http
from twisted.web.resource import Resource
from twisted.internet import endpoints
from twisted.python.filepath import FilePath
from twisted.python.util import sibpath
from twisted.web import template
from twisted.web.server import Site

from shinysdr.i.json import serialize
from shinysdr.i.pycompat import defaultstr
from shinysdr.i.roots import IEntryPoint

# TODO: Change this constant to something more generic, but save that for when we're changing the URL layout for other reasons anyway.
CAP_OBJECT_PATH_ELEMENT = defaultstr('radio')
AUDIO_STREAM_PATH_ELEMENT = 'audio-stream'
UNIQUE_PUBLIC_CAP = 'public'


static_resource_path = sibpath(__file__, '../webstatic')
template_path = sibpath(__file__, '../webparts')
template_filepath = FilePath(template_path)
deps_path = sibpath(__file__, '../../deps')


class IWebEntryPoint(IEntryPoint):
    def get_entry_point_resource(wcommon):
        """Returns a twisted.web.resource.IResource."""


class EntryPointIndexElement(template.Element):
    """Useful base class for IWebEntryPoint's index (.../) resources.
    
    Subclasses should define the loader attribute and any additional template.renderers.
    """
    
    def __init__(self, wcommon):
        super(EntryPointIndexElement, self).__init__()
        self.entry_point_wcommon = wcommon
    
    @template.renderer
    def title(self, request, tag):
        return tag(self.entry_point_wcommon.title)

    @template.renderer
    def quoted_state_url(self, request, tag):
        return tag(serialize(self.entry_point_wcommon.make_websocket_url(request, prepath_escaped(request) + CAP_OBJECT_PATH_ELEMENT)))


class SlashedResource(Resource):
    """Redirects /.../this to /.../this/."""
    
    def render(self, request):
        request.setHeader(b'Location', request.childLink(b''))
        request.setResponseCode(http.MOVED_PERMANENTLY)
        return b''


class ElementRenderingResource(Resource):
    """Resource which just renders a specified template element."""
    def __init__(self, element):
        Resource.__init__(self)
        self.__element = element

    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'text/html;charset=utf-8')
        return template.renderElement(request, self.__element)


class ErrorPageElement(template.Element):
    loader = template.XMLFile(template_filepath.child('error-page.template.xhtml'))
    
    def __init__(self, details_text):
        super(ErrorPageElement, self).__init__()
        self.__details_text = details_text
    
    @template.renderer
    def details_text(self, request, tag):
        return tag(self.__details_text)


def render_error_page(request, details_text, code=http.BAD_REQUEST):
    request.setResponseCode(code)
    return template.renderElement(request, ErrorPageElement(details_text))


class WebServiceCommon(object):
    """Ugly collection of stuff web resources need which is not noteworthy authority."""
    
    @classmethod
    def stub(cls, reactor):
        return cls(
            reactor=reactor,
            title='[ShinySDR Test Server]',
            ws_endpoint_string='tcp:99999')  # parseable but nonsense
    
    def __init__(self, reactor, title, ws_endpoint_string):
        self.reactor = reactor
        self.title = six.text_type(title)
        self.__ws_endpoint_string = ws_endpoint_string
    
    def make_websocket_url(self, request, path):
        return endpoint_string_to_url(self.__ws_endpoint_string,
            hostname=request.getRequestHostname(),
            scheme=b'ws',
            path=path)


class SiteWithDefaultHeaders(Site):
    """Subclass of Site which provides some default security-improving headers for all resources."""
    
    def getResourceFor(self, request):
        """overrides Site"""
        # TODO remove unsafe-inline (not that it really matters as we are not doing sloppy templating)
        # TODO: Once we know our own hostname(s), or if we start using the same port for WebSockets, tighten the connect-src policy
        request.setHeader(b'Content-Security-Policy', b';'.join([
            b"default-src 'self' 'unsafe-inline'",
            b"connect-src 'self' ws://*:* wss://*:*",
            b"img-src 'self' data: blob:",
            b"media-src http: https: file: blob:",  # client audio tools wish to load user-specified audio
            b"object-src 'none'",
            b"base-uri 'self'",
        ]))
        request.setHeader(b'Referrer-Policy', b'no-referrer')
        request.setHeader(b'X-Content-Type-Options', b'nosniff')
        return Site.getResourceFor(self, request)


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


def prepath_escaped(request):
    """Like request.prePathURL() but without the scheme and hostname."""
    return '/' + '/'.join([urllib.parse.quote(x, safe='') for x in request.prepath])


def parse_audio_stream_options(args):
    """
    args: query parameters, dict of list of not-url-encoded strings format
    
    Raises ValueError with user-facing message if args has missing or misformatted elements.
    """
    # TODO: Can we find a library to do this parameter validation? Preferably already in Twisted?
    try:
        rate_bytes, = args[b'rate']
        rate_number = float(rate_bytes.decode('us-ascii', 'replace'))
    except (KeyError, ValueError):
        raise ValueError('?rate= not a number')
    if not 1 <= rate_number <= 192000:
        raise ValueError('?rate= must be between 1 and 192000')
    return ParsedAudioStreamOptions(
        sample_rate=rate_number,
    )


ParsedAudioStreamOptions = namedtuple('ParsedAudioStreamOptions', [
    'sample_rate',
])
