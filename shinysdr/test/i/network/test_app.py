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

from __future__ import absolute_import, division

import json
import urlparse

from twisted.trial import unittest
from twisted.internet import reactor
from twisted.web import http
from zope.interface import implements

from gnuradio import gr

from shinysdr.i.db import DatabaseModel
from shinysdr.i.network.base import CAP_OBJECT_PATH_ELEMENT, UNIQUE_PUBLIC_CAP
from shinysdr.i.network.app import WebService
from shinysdr.i.roots import IEntryPoint
from shinysdr.values import ExportedState
from shinysdr.test import testutil


class TestWebSite(unittest.TestCase):
    # note: this test has a subclass

    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap=u'ROOT',
            read_only_dbs={},
            writable_db=DatabaseModel(reactor, {}),
            cap_table={u'ROOT': SiteStateStub()},
            flowgraph_for_debug=gr.top_block(),
            title='test title')
        self._service.startService()
        self.url = str(self._service.get_url())
    
    def tearDown(self):
        return self._service.stopService()
    
    def test_expected_url(self):
        self.assertEqual('/ROOT/', self._service.get_host_relative_url())
    
    def test_common_root(self):
        return assert_common(self, self.url)
    
    def test_common_client_example(self):
        return assert_common(self, urlparse.urljoin(self.url, '/client/main.js'))
    
    def test_common_object(self):
        return assert_common(self, urlparse.urljoin(self.url, CAP_OBJECT_PATH_ELEMENT))
    
    def test_common_ephemeris(self):
        return assert_common(self, urlparse.urljoin(self.url, 'ephemeris'))
    
    def test_app_redirect(self):
        if 'ROOT' not in self.url:
            return  # test does not apply
            
        url_without_slash = self.url[:-1]
        
        def callback((response, data)):
            self.assertEqual(response.code, http.MOVED_PERMANENTLY)
            self.assertEqual(self.url,
                urlparse.urljoin(url_without_slash,
                    'ONLYONE'.join(response.headers.getRawHeaders('Location'))))
        
        return testutil.http_get(reactor, url_without_slash).addCallback(callback)
    
    def test_index_page(self):
        def callback((response, data)):
            self.assertEqual(response.code, http.OK)
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html'])
            self.assertIn('</html>', data)  # complete
            self.assertIn('<title>test title</title>', data)
            # TODO: Probably not here, add an end-to-end test for page title _default_.
        
        return testutil.http_get(reactor, self.url).addCallback(callback)
    
    def test_resource_page_html(self):
        # TODO: This ought to be a separate test of block-resources
        def callback((response, data)):
            self.assertEqual(response.code, http.OK)
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['text/html;charset=utf-8'])
            self.assertIn('</html>', data)
        return testutil.http_get(reactor, self.url + CAP_OBJECT_PATH_ELEMENT, accept='text/html').addCallback(callback)
    
    def test_resource_page_json(self):
        # TODO: This ought to be a separate test of block-resources
        def callback((response, data)):
            self.assertEqual(response.code, http.OK)
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['application/json'])
            description_json = json.loads(data)
            self.assertEqual(description_json, {
                u'kind': u'block',
                u'children': {},
            })
        return testutil.http_get(reactor, self.url + CAP_OBJECT_PATH_ELEMENT, accept='application/json').addCallback(callback)
    
    def test_flowgraph_page(self):
        def callback((response, data)):
            self.assertEqual(response.code, http.OK)
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['image/png'])
            # TODO ...
        return testutil.http_get(reactor, self.url + 'flow-graph').addCallback(callback)


class TestSiteWithoutRootCap(TestWebSite):
    """Like TestWebSite but with the 'public' configuration."""
    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap=UNIQUE_PUBLIC_CAP,
            read_only_dbs={},
            writable_db=DatabaseModel(reactor, {}),
            cap_table={UNIQUE_PUBLIC_CAP: SiteStateStub()},
            flowgraph_for_debug=gr.top_block(),
            title='test title')
        self._service.startService()
        self.url = str(self._service.get_url())
    
    def test_expected_url(self):
        self.assertEqual('/' + UNIQUE_PUBLIC_CAP + '/', self._service.get_host_relative_url())


def assert_common(self, url):
    """Common properties all HTTP resources should have."""
    def callback((response, data)):
        # If this fails, we probably made a mistake
        self.assertNotEqual(response.code, http.NOT_FOUND)
        
        self.assertEqual(
            [';'.join([
                "default-src 'self' 'unsafe-inline'",
                "connect-src 'self' ws://*:* wss://*:*",
                "img-src 'self' data: blob:",
                "object-src 'none'",
                "base-uri 'self'",
                "plugin-types 'none'",
                "block-all-mixed-content",
            ])],
            response.headers.getRawHeaders('Content-Security-Policy'))
        self.assertEqual(['no-referrer'], response.headers.getRawHeaders('Referrer-Policy'))
        self.assertEqual(['nosniff'], response.headers.getRawHeaders('X-Content-Type-Options'))
        
        content_type = response.headers.getRawHeaders('Content-Type')
        if data.startswith('{'):
            self.assertEqual(['application/json'], content_type)
        elif data.startswith('<'):
            self.assertEqual(['text/html'], content_type)
        else:
            raise Exception('Don\'t know what content type to expect', data[0], content_type)
    
    return testutil.http_get(reactor, self.url).addCallback(callback)


class SiteStateStub(ExportedState):
    implements(IEntryPoint)
