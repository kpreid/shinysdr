# Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

"""
This is a adapter to allow ghpsdr3-alex clients such as "glSDR" for
Android to connect to ShinySDR as a "dspserver"; references:
<http://openhpsdr.org/wiki/index.php?title=Ghpsdr3_protocols>.
<https://github.com/alexlee188/ghpsdr3-alex/tree/master/trunk/src/dspserver/client.c>
<https://github.com/alexlee188/ghpsdr3-alex/tree/master/trunk/src/dspserver/audiostream.c>

DOES NOT YET WORK: some messages we send have the wrong length as judged
by the glSDR client, resulting in the following messages being
misparsed. No success yet in figuring out where the discrepancy is.
Patches welcome.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import array
import struct

from twisted.application.service import Service
from twisted.internet import defer
from twisted.internet import endpoints
from twisted.internet import protocol
from twisted.internet import task
from twisted.logger import Logger

from shinysdr.twisted_ext import FactoryWithArgs


__all__ = ['DspserverService']


_CLIENT_MSG_LENGTH = 64


def _cmd_noop(self, argstr):
    """stub command implementation"""
    pass


def _cmd_setFPS(self, argstr):
    width, rate = [int(x) for x in argstr.split(' ')]
    self._req_width = width
    self._top.monitor.set_freq_resolution(width)
    self._top.monitor.set_frame_rate(rate)
    self._poller.start(1.0 / (rate * 2.0))
    self._top.monitor.set_paused(False)


def _cmd_setFrequency(self, argstr):
    pass
    # TODO: reenable this
    # freq = int(argstr)
    # self._get_receiver().set_rec_freq(freq)
    # self._top.source.set_freq(freq)


_dspserver_commands = {
    'q-master': _cmd_noop,  # don't know what this means
    'setFPS': _cmd_setFPS,
    'setFrequency': _cmd_setFrequency,
}


class _DspserverProtocol(protocol.Protocol):
    def __init__(self, top):
        self._top = top
        self._req_width = None
        self.__msgbuf = b''
        self._poller = task.LoopingCall(self.__poll)
        self.__splitter = top.monitor.state()['fft'].subscribe_to_stream()
        self.__audio_buffer = b''
        self._top.add_audio_callback(self.__audio_callback, 8000)

    def dataReceived(self, data):
        """twisted Protocol implementation"""
        self.__msgbuf += data
        while len(self.__msgbuf) >= _CLIENT_MSG_LENGTH:
            # TODO: efficient buffering
            msg = self.__msgbuf[:_CLIENT_MSG_LENGTH]
            self.__msgbuf = self.__msgbuf[_CLIENT_MSG_LENGTH:]
            self.__messageReceived(msg)
    
    def _get_receiver(self):
        receiver_cells = self._top.receivers.state().values()
        if len(receiver_cells) > 0:
            receiver = receiver_cells[0].get()
        else:
            _, receiver = self._top.add_receiver('AM')
        return receiver
    
    def __messageReceived(self, data):
        null = data.find(b'\0')
        if null > -1:
            data = data[:null]
        print(b'Message received: ' + data)
        sep = data.find(b' ')
        if sep > -1:
            cmd = data[0:sep]
            argstr = data[sep + 1:]
        else:
            cmd = data
            argstr = ''
        impl = _dspserver_commands.get(cmd)
        if impl is not None:
            impl(self, argstr)
    
    def connectionLost(self, reason):
        # pylint: disable=signature-differs
        self._top.remove_audio_callback(self.__audio_callback)
        self._poller.stop()
        self.__splitter.close()
    
    def __audio_callback(self, numpy_array):
        self.__audio_buffer += numpy_array.tobytes()
    
    def __poll(self):
        receiver = self._get_receiver()
        while True:
            frame = self.__splitter.get()
            if frame is None:
                break
            ((freq, sample_rate), fft) = frame
            if self._req_width is None:
                break
            print('Sending frame', self._req_width, sample_rate)  # TODO: Remove debugging
            msg = struct.pack('BBBHHHIh' + str(self._req_width) + 's',
                0,
                2,
                1,
                self._req_width,  # short
                0,  # meter
                0,  # subrx meter
                sample_rate,
                receiver.get_rec_freq() - freq,  # lo_offset
                ''.join([chr(int(max(1, min(255, -(x - 20))))) for x in fft]))
            self.transport.write(msg)

        # audio
        size_in_bytes = 2000 * 4
        if len(self.__audio_buffer) > size_in_bytes:
            abuf = self.__audio_buffer[:size_in_bytes]
            self.__audio_buffer = self.__audio_buffer[size_in_bytes:]
            print('Sending audio', len(abuf))  # TODO: Remove debugging
            # b'' is for Python 2.7.6 compatibility (array.array module requires a str rather than unicode string)
            unpacker = array.array(b'f')
            unpacker.fromstring(abuf)
            nsamples = len(unpacker)
            msg = struct.pack('BBBH' + str(nsamples) + 'B',
                1,
                2,
                1,
                nsamples,
                # TODO tweak
                *[int(max(0, min(255, x * 127 + 127))) for x in unpacker.tolist()])
            # TODO: Disabled until we fix fft messages
            # self.transport.write(msg)


class DspserverService(Service):
    def __init__(self, reactor, top, endpoint_string):
        self.__top = top
        self.__endpoint = endpoints.serverFromString(reactor, endpoint_string)
        self.__port_obj = None
    
    @defer.inlineCallbacks
    def startService(self):
        self.__port_obj = yield self.__endpoint.listen(
            FactoryWithArgs.forProtocol(_DspserverProtocol, self.__top))
    
    def stopService(self):
        return self.__port_obj.stopListening()

    def announce(self, open_client):
        """interface used by shinysdr.main"""
        # TODO: pass message back instead, this is all sorts of wrong
        Logger().info('GHPSDR-compatible server at port %s' % self.__port_obj.getHost().port)
