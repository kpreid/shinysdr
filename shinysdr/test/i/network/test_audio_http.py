# -*- coding: utf-8 -*-
# Copyright 2018 Kevin Reid <kpreid@switchb.org>
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

import struct

from twisted.internet import defer
from twisted.internet import reactor as the_reactor
from twisted.internet.protocol import Protocol
from twisted.trial import unittest
from twisted.web.resource import Resource
from twisted.web import client

from shinysdr.i.network.base import SiteWithDefaultHeaders
from shinysdr.i.network.audio_http import AudioStreamResource
from shinysdr.i.pycompat import bytes_or_ascii
from shinysdr.test.testutil import assert_http_resource_properties, http_head


class TestAudioStreamResource(unittest.TestCase):
    # TODO: Have less boilerplate "set up a local web server".
    
    def setUp(self):
        tree = Resource()
        tree.putChild('mono', AudioStreamResource(_FakeSession(1)))
        tree.putChild('stereo', AudioStreamResource(_FakeSession(2)))
        self.port = the_reactor.listenTCP(0, SiteWithDefaultHeaders(tree), interface="127.0.0.1")  # pylint: disable=no-member

    def tearDown(self):
        return self.port.stopListening()

    def __url(self, path):
        return 'http://127.0.0.1:%i%s' % (self.port.getHost().port, path)
    
    def test_common(self):
        return assert_http_resource_properties(self, self.__url('/mono?rate=1'), dont_read_entire_body=True)
    
    @defer.inlineCallbacks
    def test_head(self):
        response = yield http_head(the_reactor, self.__url('/mono?rate=1'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['audio/wav'])
        self.assertEqual(response.headers.getRawHeaders('Cache-Control'), ['no-cache, no-store, must-revalidate'])
    
    @defer.inlineCallbacks
    def test_get_http_headers(self):
        response, prefix_reader = yield get_stream_head(self, self.__url('/stereo?rate=1'))
        self.assertEqual(response.headers.getRawHeaders('Content-Type'), ['audio/wav'])
        self.assertEqual(response.headers.getRawHeaders('Cache-Control'), ['no-cache, no-store, must-revalidate'])
        yield prefix_reader.done
    
    @defer.inlineCallbacks
    def test_wav_header_mono_2(self):
        _response, prefix_reader = yield get_stream_head(self, self.__url('/mono?rate=22050'))
        yield prefix_reader.done
        self.assertEqual(prefix_reader.data, _generate_wav_header(sample_rate=22050, channels=1))
    
    @defer.inlineCallbacks
    def test_wav_header_stereo_2(self):
        _response, prefix_reader = yield get_stream_head(self, self.__url('/stereo?rate=22050'))
        yield prefix_reader.done
        self.assertEqual(prefix_reader.data, _generate_wav_header(sample_rate=22050, channels=2))
    
    @defer.inlineCallbacks
    def test_wav_header_stereo_4(self):
        _response, prefix_reader = yield get_stream_head(self, self.__url('/stereo?rate=44100'))
        yield prefix_reader.done
        self.assertEqual(prefix_reader.data, _generate_wav_header(sample_rate=44100, channels=2))
    
    @defer.inlineCallbacks
    def test_bad_options(self):
        response = yield http_head(the_reactor, self.__url('/mono?rate=asdf'))
        self.assertEqual(response.code, 400)


class _FakeSession(object):
    def __init__(self, channels):
        self.__channels = channels
    
    def add_audio_callback(self, callback, sample_rate):
        pass
    
    def remove_audio_callback(self, callback):
        pass
    
    def get_audio_callback_channels(self):
        return self.__channels


# TODO: Add this functionality to shinysdr.test.testutil.http_get
@defer.inlineCallbacks
def get_stream_head(test_case, url):
    agent = client.Agent(the_reactor)
    response = yield agent.request(
        method=b'GET',
        uri=bytes_or_ascii(url))
    prefix_reader = _PrefixReaderProtocol()
    response.deliverBody(prefix_reader)
    defer.returnValue((response, prefix_reader))


class _PrefixReaderProtocol(Protocol):
    def __init__(self):
        self.data = b''
        self.done = defer.Deferred()

    def dataReceived(self, data):
        self.data += data
        self.transport.loseConnection()
    
    def connectionLost(self, reason=None):
        self.done.callback(None)


def _generate_wav_header(sample_rate, channels):
    # This was originally a copy of the code under test. The point of it being a copy is that as the test and the tested code evolve they may eventually become different due to their differing usage patterns, and if so that makes a better test than reusing the same generator in both places. Or at least, that's what I'm telling myself right now.
    fake_max_size = 2 ** 32 - 1
    number_size = 4  # 32-bit float
    riff_header_chunk = struct.pack('<4sI4s', 
        b'RIFF',
        fake_max_size,
        b'WAVE')
    
    audio_format_chunk = struct.pack('<4sIHHIIHH', 
        b'fmt ',
        16,  # this chunk size
        3,  # float format
        channels,  # number of channels interleaved in a block
        sample_rate,  # sample rate per channel / block rate
        channels * sample_rate * number_size,  # byte rate
        channels * number_size,  # bytes per block
        number_size * 8)  # bits per sample
    
    incomplete_data_chunk = struct.pack('<4sI', b'data', fake_max_size)
    
    return riff_header_chunk + audio_format_chunk + incomplete_data_chunk
