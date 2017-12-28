# Copyright 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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

"""Session-specific HTTP-specific code.

TODO: Not sure whether this module makes sense.
"""

from __future__ import absolute_import, division, unicode_literals

from twisted.web import template

import shinysdr.i.db
from shinysdr.i.ephemeris import EphemerisResource
from shinysdr.i.json import serialize
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, ElementRenderingResource, EntryPointIndexElement, SlashedResource, prepath_escaped, template_filepath
from shinysdr.i.network.export_http import BlockResource, FlowgraphVizResource


class SessionResource(SlashedResource):
    # TODO ask the session for the dbs
    def __init__(self, session, wcommon, read_only_dbs, writable_db):
        SlashedResource.__init__(self)
        
        # UI entry point
        self.putChild('', ElementRenderingResource(_RadioIndexHtmlElement(wcommon)))
        
        # Exported radio control objects
        self.putChild(CAP_OBJECT_PATH_ELEMENT, BlockResource(session, wcommon, _not_deletable))
        
        # Frequency DB
        self.putChild('dbs', shinysdr.i.db.DatabasesResource(read_only_dbs))
        self.putChild('wdb', shinysdr.i.db.DatabaseResource(writable_db))
        
        # Debug graph
        self.putChild('flow-graph', FlowgraphVizResource(wcommon.reactor, session.flowgraph_for_debug()))
        
        # Ephemeris
        self.putChild('ephemeris', EphemerisResource())


class _RadioIndexHtmlElement(EntryPointIndexElement):
    loader = template.XMLFile(template_filepath.child('index.template.xhtml'))
    
    @template.renderer
    def title(self, request, tag):
        return tag(self.entry_point_wcommon.title)

    @template.renderer
    def quoted_audio_url(self, request, tag):
        return tag(serialize(self.entry_point_wcommon.make_websocket_url(request, prepath_escaped(request) + 'audio')))


def _not_deletable():
    # TODO audit uses of this function
    # TODO plumb up a user-friendly (proper HTTP code) error
    raise Exception('Attempt to delete session root')
