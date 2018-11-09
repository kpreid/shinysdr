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

"""Audio streaming over HTTP."""

from __future__ import absolute_import, division, print_function, unicode_literals

import struct

from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET

from shinysdr.i.network.base import parse_audio_stream_options, render_error_page


_BYTES_PER_NUMBER = 4  # 32-bit float samples


class AudioStreamResource(Resource):
    """A resource which is a WAV audio stream."""
    isLeaf = True
    
    def __init__(self, session):
        Resource.__init__(self)
        self.__audio_source = session
    
    # We implement HEAD because Twisted default behavior is to implement HEAD directly in terms of GET, and we'd rather not start up a short-lived stream.
    
    def render_HEAD(self, request):
        return self.__render_head_or_get(request)
    
    def render_GET(self, request):
        return self.__render_head_or_get(request)
    
    def __render_head_or_get(self, request):
        try:
            options = parse_audio_stream_options(request.args)
        except ValueError as e:
            return render_error_page(request, str(e))
        
        # TODO: If there are any other audio formats that are easy to support, do an Accept header
        request.setHeader(b'Content-Type', b'audio/wav')
        request.setHeader(b'Cache-Control', b'no-cache, no-store, must-revalidate')
        
        if request.method == b'GET':
            _HTTPWavStreamGlue(request, self.__audio_source, options.sample_rate)
            return NOT_DONE_YET
        elif request.method == b'HEAD':
            return b''
        else:
            raise Exception('unexpected HTTP method')


class _HTTPWavStreamGlue(object):
    """Generates WAV header and connects ShinySDR audio stream callback to Twisted HTTP response."""
    def __init__(self, request, audio_source, sample_rate):
        channels = audio_source.get_audio_callback_channels()
        
        self.__request = request
        self.__audio_source = audio_source
        # we're going to be reusing this so don't reconstruct it
        self.__callback = self.__callback        
        # byte length of 1 second of buffered audio
        self.__max_buffered_bytes = sample_rate * _BYTES_PER_NUMBER * channels
        
        # write header
        request.write(_generate_wav_header(sample_rate, channels))
        
        # hook up streaming
        request.notifyFinish().addBoth(self.__stop)
        self.__audio_source.add_audio_callback(self.__callback, sample_rate)
        
    def __callback(self, data_bytes):  # pylint: disable=method-hidden
        if self.__request is None:
            return
            
        # Drop data when not being delivered to the client
        # TODO: detection condition is horrible implementation-diving kludge
        if len(self.__request.channel.transport.dataBuffer) > self.__max_buffered_bytes:
            return
        
        try:
            # Everybody's little-endian, right?
            self.__request.write(data_bytes)
        except Exception:
            # Stop a possible infinite loop of error spam
            self.__stop()
            raise
    
    def __stop(self, _=None):
        if self.__request is not None:
            self.__audio_source.remove_audio_callback(self.__callback)
            self.__request = None
            self.__audio_source = None


def _generate_wav_header(sample_rate, channels):
    # Sources used to understand the header format:
    #   http://soundfile.sapp.org/doc/WaveFormat/
    #   http://www-mmsp.ece.mcgill.ca/Documents/AudioFormats/WAVE/WAVE.html
    
    fake_max_size = 2 ** 32 - 1
    
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
        channels * sample_rate * _BYTES_PER_NUMBER,  # byte rate
        channels * _BYTES_PER_NUMBER,  # bytes per block
        _BYTES_PER_NUMBER * 8)  # bits per sample
    
    incomplete_data_chunk = struct.pack('<4sI', b'data', fake_max_size)
    
    return riff_header_chunk + audio_format_chunk + incomplete_data_chunk
