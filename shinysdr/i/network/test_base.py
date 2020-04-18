# Copyright 2020 Kevin Reid and the ShinySDR contributors
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

from twisted.trial import unittest
from twisted.internet import reactor as the_reactor

from shinysdr.i.network.base import WebServiceCommon


class TestWebServiceCommon(unittest.TestCase):
    def test_make_websocket_url_without_base_url(self):
        wcommon = WebServiceCommon(
            reactor=the_reactor,
            title='',
            ws_endpoint_string='tcp:1234')
        request = FakeRequest()
        self.assertEqual(
            'ws://fake-request-hostname:1234/testpath',
            wcommon.make_websocket_url(request, '/testpath'))
        
    def test_make_websocket_url_with_base_url(self):
        wcommon = WebServiceCommon(
            reactor=the_reactor,
            title='',
            ws_endpoint_string='tcp:1234',
            ws_base_url='wss://wshost:5678/')
        request = FakeRequest()
        self.assertEqual(
            'wss://wshost:5678/testpath',
            wcommon.make_websocket_url(request, '/testpath'))


class FakeRequest(object):
    """Pretends to be a twisted.web.http.Request. Isn't because that would need more setup."""
    def getRequestHostname(self):
        return 'fake-request-hostname'


# TODO: test render_error_page
# TODO: test endpoint_string_to_url
# TODO: test prepath_escaped
# TODO: test parse_audio_stream_options
