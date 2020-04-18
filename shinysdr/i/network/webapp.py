# Copyright 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020 Kevin Reid and the ShinySDR contributors
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

"""Code defining the API that is actually exposed over HTTP."""

from __future__ import absolute_import, division, print_function, unicode_literals

import os

import six
from six.moves import urllib
from six.moves.urllib.parse import urljoin

from twisted.application.service import Service
from twisted.internet import defer
from twisted.internet import endpoints
from twisted.plugin import getPlugins
from twisted.logger import Logger
from twisted.web import static
from twisted.web.resource import Resource
from twisted.web.util import Redirect

import txws

import shinysdr.i.db
from shinysdr.i.json import serialize
from shinysdr.i.modes import get_modes
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, IWebEntryPoint, SiteWithDefaultHeaders, SlashedResource, UNIQUE_PUBLIC_CAP, WebServiceCommon, deps_path, static_resource_path, endpoint_string_to_url
from shinysdr.i.network.export_http import CapAccessResource
from shinysdr.i.network.export_ws import WebSocketDispatcherProtocol
from shinysdr.i.poller import the_poller
from shinysdr.i.pycompat import defaultstr
from shinysdr.i.shared_test_objects import SHARED_TEST_OBJECTS_CAP
from shinysdr.interfaces import _IClientResourceDef
from shinysdr.twisted_ext import FactoryWithArgs
from shinysdr.values import SubscriptionContext


def _make_static_resource(pathname):
    # str() because if we happen to pass unicode as the pathname then directory listings break (discovered with Twisted 16.4.1).
    r = static.File(str(pathname),
        defaultType=b'text/plain',
        ignoredExts=[b'.html'])
    r.contentTypes[b'.csv'] = b'text/csv'
    r.indexNames = [b'index.html']
    return r


class WebService(Service):
    __log = Logger()
    
    def __init__(self,
            reactor,
            cap_table,
            http_endpoint,
            ws_endpoint,
            http_base_url,
            ws_base_url,
            root_cap,
            title):
        # Constants
        self.__http_endpoint_string = str(http_endpoint)
        self.__http_endpoint = endpoints.serverFromString(reactor, self.__http_endpoint_string)
        self.__ws_endpoint = endpoints.serverFromString(reactor, str(ws_endpoint))
        self.__visit_path = _make_cap_url(root_cap)
        self.__http_base_url_if_explicit = http_base_url
        
        wcommon = WebServiceCommon(
            reactor=reactor,
            title=title,
            ws_endpoint_string=ws_endpoint,
            ws_base_url=ws_base_url)
        # TODO: Create poller actually for the given reactor w/o redundancy -- perhaps there should be a one-poller-per-reactor map
        subscription_context = SubscriptionContext(reactor=reactor, poller=the_poller)
        
        def resource_factory(entry_point):
            # TODO: If not an IWebEntryPoint, return a generic result
            return IWebEntryPoint(entry_point).get_entry_point_resource(wcommon=wcommon)  # pylint: disable=redundant-keyword-arg
        
        server_root = CapAccessResource(cap_table=cap_table, resource_factory=resource_factory)
        _put_root_static(wcommon, server_root)
        
        if UNIQUE_PUBLIC_CAP in cap_table:
            # TODO: consider factoring out "generate URL for cap"
            server_root.putChild('', Redirect(_make_cap_url(UNIQUE_PUBLIC_CAP)))
            
        self.__ws_protocol = txws.WebSocketFactory(
            FactoryWithArgs.forProtocol(WebSocketDispatcherProtocol, cap_table, subscription_context))
        self.__site = SiteWithDefaultHeaders(server_root)
        
        self.__ws_port_obj = None
        self.__http_port_obj = None
    
    @defer.inlineCallbacks
    def startService(self):
        Service.startService(self)
        if self.__ws_port_obj is not None:
            raise Exception('Already started')
        self.__http_port_obj = yield self.__http_endpoint.listen(self.__site)
        self.__ws_port_obj = yield self.__ws_endpoint.listen(self.__ws_protocol)
    
    def stopService(self):
        Service.stopService(self)
        if self.__ws_port_obj is None:
            raise Exception('Not started, cannot stop')
        # TODO: Does Twisted already have something to bundle up a bunch of ports for shutdown?
        return defer.DeferredList([
            self.__http_port_obj.stopListening(),
            self.__ws_port_obj.stopListening()])
    
    def get_host_relative_url(self):
        """Get the host-relative URL of the service.
        
        This method exists primarily for testing purposes."""
        return self.__visit_path
    
    def get_url(self):
        """Get the absolute URL of the service. Cannot be used before startService is called.
        
        This method exists primarily for testing purposes."""
        # TODO: This logic is duplicated with wcommon.make_websocket_url
        if self.__http_base_url_if_explicit is not None:
            return urljoin(self.__http_base_url_if_explicit, self.get_host_relative_url())
        else:
            # TODO: need to know canonical domain name (endpoint_string_to_url defaults to localhost); can we extract the information from the certificate when applicable?
            return endpoint_string_to_url(
                self.__http_endpoint_string,
                listening_port=self.__http_port_obj,
                path=self.get_host_relative_url())

    def announce(self, open_client):
        """interface used by shinysdr.main"""
        url = self.get_url()
        if open_client:
            self.__log.info('Opening {url}', url=url)
            import webbrowser  # lazy load
            webbrowser.open(url, new=1, autoraise=True)
        else:
            self.__log.info('Visit {url}', url=url)


def _put_root_static(wcommon, container_resource):
    """Place all the simple resources, that are not necessarily sourced from files but at least are unchanging and public."""
    
    for name in ['', 'client', 'test', 'manual', 'tools']:
        container_resource.putChild(name, _make_static_resource(os.path.join(static_resource_path, name if name != '' else 'index.html')))
    
    # Link deps into /client/.
    client = container_resource.children['client']
    for name in ['require.js', 'text.js']:
        client.putChild(name, _make_static_resource(os.path.join(deps_path, name)))
    for name in ['measviz.js', 'measviz.css']:
        client.putChild(name, _make_static_resource(os.path.join(deps_path, 'measviz/src', name)))
    
    # Link deps into /test/.
    test = container_resource.children['test']
    jasmine = SlashedResource()
    test.putChild('jasmine', jasmine)
    for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
        jasmine.putChild(name, _make_static_resource(os.path.join(
            deps_path, 'jasmine/lib/jasmine-core/', name)))
    
    # Special resources
    container_resource.putChild('favicon.ico',
        _make_static_resource(os.path.join(static_resource_path, 'client/icon/icon-32.png')))
    client.putChild('web-app-manifest.json',
        WebAppManifestResource(wcommon))
    _put_plugin_resources(wcommon, client)


def _put_plugin_resources(wcommon, client_resource):
    """Plugin-defined resources and client-configuration."""
    load_list_css = []
    load_list_js = []
    mode_table = {}
    plugin_resources = Resource()
    client_resource.putChild('plugins', plugin_resources)
    for resource_def in getPlugins(_IClientResourceDef, shinysdr.plugins):
        # Add the plugin's resource to static serving
        plugin_resources.putChild(resource_def.key, resource_def.resource)
        plugin_resource_url = '/client/plugins/' + urllib.parse.quote(resource_def.key, safe='') + '/'
        # Tell the client to load the plugins
        # TODO constrain path values to be relative (not on a different origin, to not leak urls)
        if resource_def.load_css_path is not None:
            load_list_css.append(plugin_resource_url + resource_def.load_cs_path)
        if resource_def.load_js_path is not None:
            # TODO constrain value to be in the directory
            load_list_js.append(plugin_resource_url + resource_def.load_js_path)
    for mode_def in get_modes():
        mode_table[mode_def.mode] = {
            u'info_enum_row': mode_def.info.to_json(),
            u'can_transmit': mode_def.mod_class is not None
        }
    
    plugin_index = {
        'css': load_list_css,
        'js': load_list_js,
        'modes': mode_table,
    }
    client_resource.putChild('client-configuration', ClientConfigurationResource(wcommon, plugin_index))


class ClientConfigurationResource(Resource):
    """Info about plugins and other not-strictly-static data."""
    isLeaf = True
    
    def __init__(self, wcommon, plugin_index):
        Resource.__init__(self)
        self.__wcommon = wcommon
        self.__plugin_index = plugin_index

    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'application/json')
        configuration = {
            'plugins': self.__plugin_index,
            # TODO: oughta be a shorter path to this -- normally websocket url is constructed from a http url gotten from the request so we don't have this exact path
            'shared_test_objects_url': self.__wcommon.make_websocket_url(request, 
                _make_cap_url(SHARED_TEST_OBJECTS_CAP) + CAP_OBJECT_PATH_ELEMENT),
        }
        return serialize(configuration).encode('utf-8')


class WebAppManifestResource(Resource):
    """
    Per https://www.w3.org/TR/appmanifest/
    """
    
    isLeaf = True
    
    def __init__(self, wcommon):
        Resource.__init__(self)
        self.__title = wcommon.title

    def render_GET(self, request):
        request.setHeader(b'Content-Type', b'application/manifest+json')
        manifest = {
            'lang': 'en-US',
            'name': self.__title,
            'short_name': self.__title if len(self.__title) <= 12 else 'ShinySDR',
            'scope': '/',
            'icons': [
                {
                    'src': '/client/icon/icon-32.png',
                    'type': 'image/png',
                    'sizes': '32x32',
                },
                {
                    'src': '/client/icon/icon.svg',
                    'type': 'image/svg',
                    'sizes': 'any',
                },
            ],
            'display': 'minimal-ui',
            'orientation': 'any',
            'theme_color': '#B9B9B9',  # same as gray.css --shinysdr-theme-column-bgcolor
            'background_color': '#2F2F2F',  # note this is our loading screen color
        }
        return serialize(manifest).encode('utf-8')


def _make_cap_url(cap):
    assert isinstance(cap, six.text_type)
    return defaultstr('/' + urllib.parse.quote(cap.encode('utf-8'), safe='') + '/')
