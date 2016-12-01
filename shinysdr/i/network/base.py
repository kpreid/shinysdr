# Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

from __future__ import absolute_import, division

import json
import os
import urllib

from twisted.application import strports
from twisted.web import http
from twisted.web import template
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET

from shinysdr.types import IJsonSerializable


# TODO: Change this constant to something more generic, but save that for when we're changing the URL layout for other reasons anyway.
CAP_OBJECT_PATH_ELEMENT = 'radio'


static_resource_path = os.path.join(os.path.dirname(__file__), '../webstatic')
template_path = os.path.join(os.path.dirname(__file__), '../webparts')
deps_path = os.path.join(os.path.dirname(__file__), '../../deps')


def serialize(obj):
    """JSON-encode values for clients, both HTTP and state stream WebSocket."""
    structure = transform_for_json(obj)
    return _json_encoder_for_serial.encode(structure)


# JSONEncoder configured for ShinySDR API use.
# Do not use this directly; use serialize() instead.
_json_encoder_for_serial = json.JSONEncoder(
    ensure_ascii=False,
    check_circular=False,
    allow_nan=True,
    sort_keys=True,
    separators=(',', ':'))


def transform_for_json(obj):
    """Replaces serializable objects in a data structure with JSON-compatible representations.

    Use serialize() to produce a JSON string instead of this, unless this is what you need."""
    # Cannot implement this using the default hook in JSONEncoder because we want to override the behavior for namedtuples (normally treated as tuples), which cannot be done otherwise.
    if IJsonSerializable.providedBy(obj):
        return transform_for_json(obj.to_json())
    elif isinstance(obj, tuple) and hasattr(obj, '_asdict'):  # namedtuple
        # TODO: Consider replreplacing all uses of this generic namedtuple handling with IJsonSerializable now that we have that.
        return {k: transform_for_json(v) for k, v in obj._asdict().iteritems()}
    elif isinstance(obj, dict):
        return {k: transform_for_json(v) for k, v in obj.iteritems()}
    elif isinstance(obj, (list, tuple)):
        return map(transform_for_json, obj)
    else:
        return obj


class SlashedResource(Resource):
    """Redirects /.../this to /.../this/."""
    
    def render(self, request):
        request.setHeader('Location', request.childLink(''))
        request.setResponseCode(http.MOVED_PERMANENTLY)
        return ''


def strport_to_url(desc, scheme='http', hostname='localhost', path='/', socket_port=0):
    """Construct a URL from a twisted.application.strports string."""
    # TODO: strports.parse is deprecated but nothing seems to replace it for this purpose
    (method, args, _) = strports.parse(desc, None)
    if socket_port == 0:
        socket_port = args[0]
    if method == 'TCP':
        return scheme + '://' + hostname + ':' + str(socket_port) + path
    elif method == 'SSL':
        return scheme + 's://' + hostname + ':' + str(socket_port) + path
    else:
        # TODO better error return
        return '???'


def renderElement(request, element):
    # per http://stackoverflow.com/questions/8160061/twisted-web-resource-resource-with-twisted-web-template-element-example
    # should be replaced with twisted.web.template.renderElement once we have Twisted >= 12.1.0 available in MacPorts.
    
    # TODO: Instead of this kludge (here because it would be a syntax error in the XHTML template}, serve XHTML and fix the client-side issues that pop up due to element-name capitalization.
    request.write('<!doctype html>')
    
    d = template.flatten(request, element, request.write)
    
    def done(ignored):
        request.finish()
        return ignored
    
    d.addBoth(done)
    return NOT_DONE_YET


def prepath_escaped(request):
    """Like request.prePathURL() but without the scheme and hostname."""
    return '/' + '/'.join([urllib.quote(x, safe='') for x in request.prepath])
