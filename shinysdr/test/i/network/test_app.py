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

from __future__ import absolute_import, division, print_function, unicode_literals

import json

from six.moves.urllib.parse import urljoin

from twisted.trial import unittest
from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.web import http
from zope.interface import implementer

from gnuradio import gr

from shinysdr.i.db import DatabaseModel
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, IWebEntryPoint, UNIQUE_PUBLIC_CAP
from shinysdr.i.network.app import _make_cap_url, WebService
from shinysdr.i.network.session_http import SessionResource
from shinysdr.values import ExportedState
from shinysdr.test import testutil


class TestWebSite(unittest.TestCase):
    # note: this test has a subclass

    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=the_reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap=u'ROOT',
            cap_table={u'ROOT': SiteStateStub()},
            title='test title')
        self._service.startService()
        self.url = str(self._service.get_url())
    
    def tearDown(self):
        return self._service.stopService()
    
    def test_expected_url(self):
        self.assertEqual('/ROOT/', self._service.get_host_relative_url())
    
    def test_common_root(self):
        return testutil.assert_http_resource_properties(self, self.url)
    
    def test_common_client_example(self):
        return testutil.assert_http_resource_properties(self, urljoin(self.url, '/client/main.js'))
    
    def test_common_object(self):
        return testutil.assert_http_resource_properties(self, urljoin(self.url, CAP_OBJECT_PATH_ELEMENT))
    
    def test_common_ephemeris(self):
        return testutil.assert_http_resource_properties(self, urljoin(self.url, 'ephemeris'))
    
    @defer.inlineCallbacks
    def test_app_redirect(self):
        if 'ROOT' not in self.url:
            return  # test does not apply
            
        url_without_slash = self.url[:-1]
        
        response, _data = yield testutil.http_get(the_reactor, url_without_slash)
        self.assertEqual(response.code, http.MOVED_PERMANENTLY)
        self.assertEqual(self.url,
            urljoin(url_without_slash,
                'ONLYONE'.join(response.headers.getRawHeaders('Location'))))
    
    @defer.inlineCallbacks
    def test_index_page(self):
        response, data = yield testutil.http_get(the_reactor, self.url)
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html;charset=utf-8'])
        self.assertIn(b'</html>', data)  # complete
        self.assertIn(b'<title>test title</title>', data)
        # TODO: Probably not here, add an end-to-end test for page title _default_.
    
    @defer.inlineCallbacks
    def test_resource_page_html(self):
        # TODO: This ought to be a separate test of block-resources
        response, data = yield testutil.http_get(the_reactor, self.url + CAP_OBJECT_PATH_ELEMENT, accept='text/html')
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html;charset=utf-8'])
        self.assertIn(b'</html>', data)
    
    @defer.inlineCallbacks
    def test_resource_page_json(self):
        # TODO: This ought to be a separate test of block-resources
        response, data = yield testutil.http_get(the_reactor, self.url + CAP_OBJECT_PATH_ELEMENT, accept='application/json')
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        description_json = json.loads(data)
        self.assertEqual(description_json, {
            u'kind': u'block',
            u'children': {},
        })
    
    @defer.inlineCallbacks
    def test_flowgraph_page(self):
        response, _data = yield testutil.http_get(the_reactor, self.url + b'flow-graph')
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['image/png'])
        # TODO ...
    
    @defer.inlineCallbacks
    def test_manifest(self):
        response, data = yield testutil.http_get(the_reactor, urljoin(self.url, b'/client/web-app-manifest.json'))
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/manifest+json'])
        manifest = json.loads(data)
        self.assertEqual(manifest['name'], 'test title')
    
    @defer.inlineCallbacks
    def test_plugin_index(self):
        response, data = yield testutil.http_get(the_reactor, urljoin(self.url, b'/client/plugin-index.json'))
        self.assertEqual(response.code, http.OK)
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
        index = json.loads(data)
        self.assertIn('css', index)
        self.assertIn('js', index)
        self.assertIn('modes', index)


class TestSiteWithoutRootCap(TestWebSite):
    """Like TestWebSite but with the 'public' configuration."""
    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=the_reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap=UNIQUE_PUBLIC_CAP,
            cap_table={UNIQUE_PUBLIC_CAP: SiteStateStub()},
            title='test title')
        self._service.startService()
        self.url = str(self._service.get_url())
    
    def test_expected_url(self):
        self.assertEqual(_make_cap_url(UNIQUE_PUBLIC_CAP), self._service.get_host_relative_url())


@implementer(IWebEntryPoint)
class SiteStateStub(ExportedState):
    def get_entry_point_resource(self, wcommon):
        return SessionResource(self,
            read_only_dbs={},
            writable_db=DatabaseModel(the_reactor, {}, writable=True),
            wcommon=wcommon)
    
    def flowgraph_for_debug(self):
        # called by SessionResource
        return gr.top_block()
