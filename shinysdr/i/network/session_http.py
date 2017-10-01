# Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

# TODO: Unclear whether this module makes sense.

from __future__ import absolute_import, division, unicode_literals

from twisted.web import template
from twisted.web.resource import Resource

import shinysdr.i.db
from shinysdr.i.ephemeris import EphemerisResource
from shinysdr.i.json import serialize
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, SlashedResource, prepath_escaped, template_filepath
from shinysdr.i.network.export_http import BlockResource, FlowgraphVizResource


class SessionResource(SlashedResource):
    # TODO Too many parameters; some of this stuff shouldn't be per-session in the same way
    def __init__(self, session, wcommon, reactor, title, read_only_dbs, writable_db):
        SlashedResource.__init__(self)
        
        # UI entry point
        self.putChild('', _RadioIndexHtmlResource(wcommon=wcommon, title=title))
        
        # Exported radio control objects
        self.putChild(CAP_OBJECT_PATH_ELEMENT, BlockResource(session, wcommon, _not_deletable))
        
        # Frequency DB
        self.putChild('dbs', shinysdr.i.db.DatabasesResource(read_only_dbs))
        self.putChild('wdb', shinysdr.i.db.DatabaseResource(writable_db))
        
        # Debug graph
        self.putChild('flow-graph', FlowgraphVizResource(reactor, session.flowgraph_for_debug()))
        
        # Ephemeris
        self.putChild('ephemeris', EphemerisResource())


class _RadioIndexHtmlElement(template.Element):
    loader = template.XMLFile(template_filepath.child('index.template.xhtml'))
    
    def __init__(self, wcommon, title):
        super(_RadioIndexHtmlElement, self).__init__()
        self.__wcommon = wcommon
        self.__title = unicode(title)
    
    @template.renderer
    def title(self, request, tag):
        return tag(self.__title)

    @template.renderer
    def quoted_state_url(self, request, tag):
        return tag(serialize(self.__wcommon.make_websocket_url(request, prepath_escaped(request) + CAP_OBJECT_PATH_ELEMENT)))

    @template.renderer
    def quoted_audio_url(self, request, tag):
        return tag(serialize(self.__wcommon.make_websocket_url(request, prepath_escaped(request) + 'audio')))


class _RadioIndexHtmlResource(Resource):
    isLeaf = True

    def __init__(self, wcommon, title):
        Resource.__init__(self)
        self.__element = _RadioIndexHtmlElement(wcommon, title)

    def render_GET(self, request):
        return template.renderElement(request, self.__element)


def _not_deletable():
    # TODO audit uses of this function
    # TODO plumb up a user-friendly (proper HTTP code) error
    raise Exception('Attempt to delete session root')
