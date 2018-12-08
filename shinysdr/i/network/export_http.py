# Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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

"""Exports ExportedState/Cell object interfaces over HTTP."""

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import weakref

import six
from six.moves import urllib

from twisted.internet.protocol import ProcessProtocol
from twisted.web.resource import IResource, Resource
from twisted.web.server import NOT_DONE_YET
from twisted.web import template

from shinysdr.i.json import serialize
from shinysdr.i.network.base import prepath_escaped, template_filepath
from shinysdr.i.pycompat import defaultstr
from shinysdr.values import IWritableCollection


class ValueCellResource(Resource):
    isLeaf = True
    
    def __init__(self, cell, wcommon):
        Resource.__init__(self)
        self._cell = cell
    
    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'application/json')
        return serialize(self._cell.get()).encode('utf-8')
    
    def render_PUT(self, request):
        data = request.content.read()
        self._cell.set(json.loads(data))
        request.setResponseCode(204)
        return ''


class BlockResource(Resource):
    isLeaf = False

    def __init__(self, block, wcommon, deleteSelf):
        Resource.__init__(self)
        self._block = block
        self.__wcommon = wcommon
        self._deleteSelf = deleteSelf
        self._dynamic = block.state_is_dynamic()
        # Weak dict ensures that we don't hold references to blocks that are no longer held by this block
        self._blockResourceCache = weakref.WeakKeyDictionary()
        if not self._dynamic:  # currently dynamic blocks can only have block children
            self._blockCells = {}
            for key, cell in six.iteritems(block.state()):
                if cell.type().is_reference():
                    self._blockCells[key] = cell
                else:
                    self.putChild(key, ValueCellResource(cell, self.__wcommon))
        self.__element = _BlockHtmlElement(wcommon)
    
    def getChild(self, path, request):
        if self._dynamic:
            curstate = self._block.state()
            if path in curstate:
                cell = curstate[path]
                if cell.type().is_reference():
                    return self.__getBlockChild(path, cell.get())
        else:
            if path in self._blockCells:
                return self.__getBlockChild(path, self._blockCells[path].get())
        # old-style-class super call
        return Resource.getChild(self, path, request)
    
    def __getBlockChild(self, name, block):
        r = self._blockResourceCache.get(block)
        if r is None:
            r = self.__makeChildBlockResource(name, block)
            self._blockResourceCache[block] = r
        return r
    
    def __makeChildBlockResource(self, name, block):
        def deleter():
            if not IWritableCollection.providedBy(self._block):
                raise Exception('Block is not a writable collection')
            self._block.delete_child(name)
        return BlockResource(block, self.__wcommon, deleter)
    
    def render_GET(self, request):
        accept = request.getHeader('Accept')
        if accept is not None and b'application/json' in accept:  # TODO: Implement or obtain correct Accept interpretation
            request.setHeader(b'Content-Type', b'application/json')
            return serialize(self.__describe_block()).encode('utf-8')
        else:
            request.setHeader(b'Content-Type', b'text/html;charset=utf-8')
            return template.renderElement(request, self.__element)
    
    def render_POST(self, request):
        """currently only meaningful to create children of CollectionResources"""
        block = self._block
        if not IWritableCollection.providedBy(block):
            raise Exception('Block is not a writable collection')
        assert request.getHeader(b'Content-Type') == b'application/json'
        reqjson = json.load(request.content)
        key = block.create_child(reqjson)  # note may fail
        url = request.prePathURL() + defaultstr('/receivers/') + urllib.parse.quote(key, safe='')
        request.setResponseCode(201)  # Created
        request.setHeader(b'Location', url)
        # TODO consider a more useful response
        return serialize(url).encode('utf-8')
    
    def render_DELETE(self, request):
        self._deleteSelf()
        request.setResponseCode(204)  # No Content
        return b''
    
    def __describe_block(self):
        # note: this JSON format is legacy and not actually used by anything (but occasionally useful for debugging)
        block = self._block
        childDescs = {}
        description = {
            'kind': 'block',
            'children': childDescs
        }
        for key, cell in six.iteritems(block.state()):
            # TODO: include URLs explicitly in desc format
            childDescs[key] = cell.description()
        return description
    
    def isForBlock(self, block):
        return self._block is block


class _BlockHtmlElement(template.Element):
    """
    Template element for HTML page for an arbitrary block.
    """
    loader = template.XMLFile(template_filepath.child('block.template.xhtml'))
    
    def __init__(self, wcommon):
        super(_BlockHtmlElement, self).__init__()
        self.__wcommon = wcommon
    
    @template.renderer
    def title(self, request, tag):
        return tag(request.prepath)
    
    @template.renderer
    def quoted_state_url(self, request, tag):
        return tag(serialize(self.__wcommon.make_websocket_url(request,
            prepath_escaped(request))))


class CapAccessResource(Resource):
    def __init__(self, cap_table, resource_factory):
        Resource.__init__(self)
        self.__cap_table = cap_table
        self.__resource_factory = resource_factory
    
    def getChild(self, path, request):
        """override Resource"""
        # TODO: Either add a cache here or throw out the cache in BlockResource which this is defeating, depending on a performance comparison
        path = path.decode('utf-8')  # TODO centralize this 'urls are utf-8'
        if path in self.__cap_table:
            return IResource(self.__resource_factory(self.__cap_table[path]))
        else:
            # old-style-class super call
            return Resource.getChild(self, path, request)


class FlowgraphVizResource(Resource):
    """A resource which is an image of the given flow graph's dot_graph() visualization."""
    isLeaf = True
    
    def __init__(self, reactor, block):
        Resource.__init__(self)
        self.__reactor = reactor
        self.__block = block
    
    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'image/png')
        process = self.__reactor.spawnProcess(
            _DotProcessProtocol(request),
            b'/usr/bin/env',
            env=None,  # inherit environment
            args=[b'env', b'dot', b'-Tpng'],
            childFDs={
                0: 'w',
                1: 'r',
                2: 2
            })
        process.pipes[0].write(self.__block.dot_graph())
        process.pipes[0].loseConnection()
        return NOT_DONE_YET


class _DotProcessProtocol(ProcessProtocol):
    def __init__(self, request):
        self.__request = request
    
    def outReceived(self, data):
        self.__request.write(data)
    
    def outConnectionLost(self):
        self.__request.finish()
