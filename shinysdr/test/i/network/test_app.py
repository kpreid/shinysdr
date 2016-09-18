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

from __future__ import absolute_import, division

import json
import urlparse

from zope.interface import Interface, implements  # available via Twisted

from twisted.trial import unittest
from twisted.internet import reactor
from twisted.web import http

from gnuradio import gr

from shinysdr.i.db import DatabaseModel
from shinysdr.i.network.app import WebService
from shinysdr.i.poller import Poller
from shinysdr.signals import SignalType
from shinysdr.values import ExportedState, CollectionState, NullExportedState, exported_block, exported_value, nullExportedState, setter
from shinysdr.test import testutil


class TestWebSite(unittest.TestCase):
    # note: this test has a subclass

    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap='ROOT',
            read_only_dbs={},
            writable_db=DatabaseModel(reactor, {}),
            root_object=SiteStateStub(),
            flowgraph_for_debug=gr.top_block(),
            title='test title',
            note_dirty=_noop)
        self._service.startService()
        self.url = self._service.get_url()
    
    def tearDown(self):
        return self._service.stopService()
    
    def test_expected_url(self):
        self.assertEqual('/ROOT/', self._service.get_host_relative_url())
    
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
        return testutil.http_get(reactor, self.url + 'radio', accept='text/html').addCallback(callback)
    
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
        return testutil.http_get(reactor, self.url + 'radio', accept='application/json').addCallback(callback)
    
    def test_flowgraph_page(self):
        def callback((response, data)):
            self.assertEqual(response.code, http.OK)
            self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['image/png'])
            # TODO ...
        return testutil.http_get(reactor, self.url + 'flow-graph').addCallback(callback)


class TestSiteWithoutRootCap(TestWebSite):
    """Like TestWebSite but with root_cap set to None."""
    def setUp(self):
        # TODO: arrange so we don't need to pass as many bogus strings
        self._service = WebService(
            reactor=reactor,
            http_endpoint='tcp:0',
            ws_endpoint='tcp:0',
            root_cap=None,
            read_only_dbs={},
            writable_db=DatabaseModel(reactor, {}),
            root_object=SiteStateStub(),
            flowgraph_for_debug=gr.top_block(),
            title='test title',
            note_dirty=_noop)
        self._service.startService()
        self.url = self._service.get_url()
    
    def test_expected_url(self):
        self.assertEqual('/', self._service.get_host_relative_url())


def _noop():
    pass


class SiteStateStub(ExportedState):
    pass


