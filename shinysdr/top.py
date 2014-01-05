# Copyright 2013 Kevin Reid <kpreid@switchb.org>
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

import time

from twisted.internet import reactor
from twisted.python import log

from gnuradio import blocks
from gnuradio import gr
from shinysdr.values import ExportedState, CollectionState, exported_value, setter, BlockCell, Enum
from shinysdr.blocks import make_resampler, MonitorSink
from shinysdr.receiver import Receiver


_num_audio_channels = 2


class ReceiverCollection(CollectionState):
	def __init__(self, table, top):
		CollectionState.__init__(self, table, dynamic=True)
		self.__top = top
	
	def state_insert(self, key, desc):
		(key, receiver) = self.__top.add_receiver(desc['mode'], key=key)
		receiver.state_from_json(desc)
	
	def create_child(self, desc):
		(key, receiver) = self.__top.add_receiver(desc['mode'])
		receiver.state_from_json(desc)
		return key
		
	def delete_child(self, key):
		self.__top.delete_receiver(key)


class Top(gr.top_block, ExportedState):

	def __init__(self, sources={}):
		gr.top_block.__init__(self, "SDR top block")
		self.__unpaused = True  # user state
		self.__running = False  # actually started
		self.__lock_count = 0

		# Configuration
		self._sources = dict(sources)
		self.source_name = self._sources.keys()[0]  # arbitrary valid initial value
		self.audio_rate = audio_rate = 44100

		# Blocks etc.
		self.source = None
		self.monitor = MonitorSink(
			sample_rate=10000, # dummy value will be updated in _do_connect
			complex_in=True,
			context=Context(self))
		
		# Receiver blocks (multiple, eventually)
		self._receivers = {}
		self._receiver_valid = {}

		# kludge for using collection like block - TODO: better architecture
		self.sources = CollectionState(self._sources)
		self.receivers = ReceiverCollection(self._receivers, self)
		
		# Audio stream bits
		self.audio_resampler_cache = {}
		self.audio_queue_sinks = {}
		
		# Flags, other state
		self.__needs_reconnect = True
		self.input_rate = None
		self.input_freq = None
		self.receiver_key_counter = 0
		self.receiver_default_state = {}
		self.last_wall_time = time.time()
		self.last_cpu_time = time.clock()
		self.last_cpu_use = 0
		
		self._do_connect()

	def add_receiver(self, mode, key=None):
		if len(self._receivers) >= 100:
			# Prevent storage-usage DoS attack
			raise Error('Refusing to create more than 100 receivers')
		
		if key is not None:
			assert key not in self._receivers
		else:
			while True:
				key = base26(self.receiver_key_counter)
				self.receiver_key_counter += 1
				if key not in self._receivers:
					break
		
		if len(self._receivers) > 0:
			arbitrary = self._receivers.itervalues().next()
			defaults = arbitrary.state_to_json()
		else:
			defaults = self.receiver_default_state
		
		receiver = self._make_receiver(mode, defaults, key)
		
		self._receivers[key] = receiver
		self._receiver_valid[key] = False
		
		self.__needs_reconnect = True
		self._do_connect()
		
		return (key, receiver)

	def delete_receiver(self, key):
		assert key in self._receivers
		receiver = self._receivers[key]
		
		# save defaults for use if about to become empty
		if len(self._receivers) == 1:
			self.receiver_default_state = receiver.state_to_json()
		
		del self._receivers[key]
		del self._receiver_valid[key]
		self.__needs_reconnect = True
		self._do_connect()

	def add_audio_queue(self, queue, queue_rate):
		# TODO: place limit on maximum requested sample rate
		sink = blocks.message_sink(
			gr.sizeof_float * _num_audio_channels,
			queue,
			True)
		interleaver = blocks.streams_to_vector(gr.sizeof_float, _num_audio_channels)
		# TODO: bundle the interleaver and sink in a hier block so it doesn't have to be reconnected
		self.audio_queue_sinks[queue] = (queue_rate, interleaver, sink)
		
		self.__needs_reconnect = True
		self._do_connect()
		self.__start_or_stop()
	
	def remove_audio_queue(self, queue):
		del self.audio_queue_sinks[queue]
		
		self.__start_or_stop()
		self.__needs_reconnect = True
		self._do_connect()

	def _do_connect(self):
		"""Do all reconfiguration operations in the proper order."""
		rate_changed = False
		if self.source is not self._sources[self.source_name]:
			log.msg('Flow graph: Switching RF source')
			self.__needs_reconnect = True
			
			def tune_hook():
				reactor.callLater(self.source.get_tune_delay(), tune_hook_actual)
			def tune_hook_actual():
				if self.source is not this_source:
					return
				freq = this_source.get_freq()
				self.input_freq = freq
				self.monitor.set_input_center_freq(freq)
				for key, receiver in self._receivers.iteritems():
					receiver.set_input_center_freq(freq)
					self._update_receiver_validity(key)
					# TODO: If multiple receivers change validity we'll do redundant reconnects in this loop; avoid that.

			this_source = self._sources[self.source_name]
			this_source.set_tune_hook(tune_hook)
			self.source = this_source
			this_rate = this_source.get_sample_rate()
			rate_changed = self.input_rate != this_rate
			self.input_rate = this_rate
			self.input_freq = this_source.get_freq()
			for key, receiver in self._receivers.iteritems():
				receiver.set_input_center_freq(self.input_freq)
		
		if rate_changed:
			log.msg('Flow graph: Changing sample rates')
			self.monitor.set_sample_rate(self.input_rate)
			for receiver in self._receivers.itervalues():
				receiver.set_input_rate(self.input_rate)

		if self.__needs_reconnect:
			log.msg('Flow graph: Rebuilding connections')
			self.__needs_reconnect = False
			
			self._recursive_lock()
			self.disconnect_all()
			
			self.connect(
				self.source,
				self.monitor)
			
			# recreated each time because reusing an add_ff w/ different
			# input counts fails; TODO: report/fix bug
			audio_sum_l = blocks.add_ff()
			audio_sum_r = blocks.add_ff()
			
			audio_sum_index = 0
			for key, receiver in self._receivers.iteritems():
				self._receiver_valid[key] = receiver.get_is_valid()
				if self._receiver_valid[key]:
					if audio_sum_index >= 6:
						# Sanity-check to avoid burning arbitrary resources
						# TODO: less arbitrary constant; communicate this restriction to client
						log.err('Flow graph: Refusing to connect more than 6 receivers')
						break
					self.connect(self.source, receiver)
					self.connect((receiver, 0), (audio_sum_l, audio_sum_index))
					self.connect((receiver, 1), (audio_sum_r, audio_sum_index))
					audio_sum_index += 1
			
			if audio_sum_index > 0:
				# connect audio output only if there is at least one input
				if len(self.audio_queue_sinks) > 0:
					used_resamplers = set()
					for (queue_rate, interleaver, sink) in self.audio_queue_sinks.itervalues():
						if queue_rate == self.audio_rate:
							self.connect(audio_sum_l, (interleaver, 0))
							self.connect(audio_sum_r, (interleaver, 1))
						else:
							if queue_rate not in self.audio_resampler_cache:
								# Moderately expensive due to the internals using optfir
								log.msg('Flow graph: Constructing resampler for audio rate %i' % queue_rate)
								self.audio_resampler_cache[queue_rate] = (
									make_resampler(self.audio_rate, queue_rate),
									make_resampler(self.audio_rate, queue_rate)
								)
							resamplers = self.audio_resampler_cache[queue_rate]
							used_resamplers.add(resamplers)
							self.connect(resamplers[0], (interleaver, 0))
							self.connect(resamplers[1], (interleaver, 1))
						self.connect(interleaver, sink)
					for resamplers in used_resamplers:
						self.connect(audio_sum_l, resamplers[0])
						self.connect(audio_sum_r, resamplers[1])
				else:
					# no stream sinks, gnuradio requires a dummy sink
					self.connect(audio_sum_l, blocks.null_sink(gr.sizeof_float))
					self.connect(audio_sum_r, blocks.null_sink(gr.sizeof_float))
		
			self._recursive_unlock()
			log.msg('Flow graph: ...done reconnecting.')

	def _update_receiver_validity(self, key):
		receiver = self._receivers[key]
		if receiver.get_is_valid() != self._receiver_valid[key]:
			self.__needs_reconnect = True
			self._do_connect()

	def state_def(self, callback):
		super(Top, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(BlockCell(self, 'monitor'))
		callback(BlockCell(self, 'sources'))
		callback(BlockCell(self, 'source', persists=False))
		callback(BlockCell(self, 'receivers'))

	def start(self):
		# trigger reconnect/restart notification
		self._recursive_lock()
		self._recursive_unlock()
		
		super(Top, self).start()
		self.__running = True

	def stop(self):
		super(Top, self).stop()
		self.__running = False

	@exported_value(ctor=bool)
	def get_unpaused(self):
		return self.__unpaused
	
	@setter
	def set_unpaused(self, value):
		self.__unpaused = bool(value)
		self.__start_or_stop()
	
	def __start_or_stop(self):
		# TODO: We should also run if at least one client is watching the spectrum or demodulators' cell-based outputs, but there's no good way to recognize that yet.
		should_run = self.__unpaused and len(self.audio_queue_sinks) > 0
		if should_run != self.__running:
			if should_run:
				self.start()
			else:
				self.stop()
				self.wait()

	@exported_value(ctor_fn=lambda self:
		Enum({k: str(v) for (k, v) in self._sources.iteritems()}))
	def get_source_name(self):
		return self.source_name
	
	@setter
	def set_source_name(self, value):
		if value == self.source_name:
			return
		if value not in self._sources:
			raise ValueError('Source %r does not exist' % (value,))
		self.source_name = value
		self._do_connect()

	def _make_receiver(self, mode, state, key):
		facet = ContextForReceiver(self, key)
		receiver = Receiver(
			mode=mode,
			input_rate=self.input_rate,
			input_center_freq=self.input_freq,
			audio_rate=self.audio_rate,
			context=facet,
		)
		receiver.state_from_json(state)
		# until _enabled, ignore any callbacks resulting from the state_from_json initialization
		facet._enabled = True
		return receiver

	@exported_value(ctor=int)
	def get_input_rate(self):
		return self.input_rate

	@exported_value(ctor=int)
	def get_audio_rate(self):
		return self.audio_rate
	
	@exported_value(ctor=float)
	def get_cpu_use(self):
		cur_wall_time = time.time()
		elapsed_wall = cur_wall_time - self.last_wall_time
		if elapsed_wall > 0.5:
			cur_cpu_time = time.clock()
			elapsed_cpu = cur_cpu_time - self.last_cpu_time
			self.last_wall_time = cur_wall_time
			self.last_cpu_time = cur_cpu_time
			self.last_cpu_use = round(elapsed_cpu / elapsed_wall, 2)
		return self.last_cpu_use

	def _recursive_lock(self):
		# gnuradio uses a non-recursive lock, which is not adequate for our purposes because we want to make changes locally or globally without worrying about having a single lock entry point
		if self.__lock_count == 0:
			self.lock()
			for source in self._sources.itervalues():
				source.notify_reconnecting_or_restarting()
		self.__lock_count += 1

	def _recursive_unlock(self):
		self.__lock_count -= 1
		if self.__lock_count == 0:
			self.unlock()


class Context(object):
	def __init__(self, top):
		self._top = top
	
	def lock(self):
		self._top._recursive_lock()
	
	def unlock(self):
		self._top._recursive_unlock()


class ContextForReceiver(Context):
	def __init__(self, top, key):
		Context.__init__(self, top)
		self._key = key
		self._enabled = False # assigned outside

	def revalidate(self):
		if self._enabled:
			self._top._update_receiver_validity(self._key)


def base26(x):
	'''not quite base 26, actually, because it has no true zero digit'''
	if x < 26:
		return 'abcdefghijklmnopqrstuvwxyz'[x]
	else:
		return base26(x // 26 - 1) + base26(x % 26)
