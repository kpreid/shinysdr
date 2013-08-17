#!/usr/bin/env python

import gnuradio
import gnuradio.fft.logpwrfft
from gnuradio import blocks
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from optparse import OptionParser
from sdr.values import ExportedState, Cell, CollectionState, BlockCell, MsgQueueCell, Enum, Range, NoneES
from sdr.filters import make_resampler
from sdr.receiver import Receiver

from twisted.internet import reactor

import time


class SpectrumTypeStub:
	pass


num_audio_channels = 2


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
		self._running = False
		self.__lock_count = 0

		# Configuration
		self._sources = dict(sources)
		self.source_name = 'audio'  # placeholder - TODO be nothing instead
		self.audio_rate = audio_rate = 32000
		self.spectrum_resolution = 4096
		self.spectrum_rate = 30

		# Blocks etc.
		self.source = None
		self.spectrum_queue = None
		self.spectrum_sink = None
		self.spectrum_fft_block = None
		
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
		self.__needs_spectrum = True
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
			gr.sizeof_float * num_audio_channels,
			queue,
			True)
		interleaver = blocks.streams_to_vector(gr.sizeof_float, num_audio_channels)
		# TODO: bundle the interleaver and sink in a hier block so it doesn't have to be reconnected
		self.audio_queue_sinks[queue] = (queue_rate, interleaver, sink)
		self.__needs_reconnect = True
		self._do_connect()
	
	def remove_audio_queue(self, queue):
		del self.audio_queue_sinks[queue]
		self.__needs_reconnect = True
		self._do_connect()

	def _do_connect(self):
		"""Do all reconfiguration operations in the proper order."""
		rate_changed = False
		if self.source is not self._sources[self.source_name]:
			print 'Switching source'
			self.__needs_reconnect = True
			
			def tune_hook():
				reactor.callLater(self.source.get_tune_delay(), tune_hook_actual)
			def tune_hook_actual():
				if self.source is not this_source:
					return
				freq = this_source.get_freq()
				self.input_freq = freq
				for key, receiver in self._receivers.iteritems():
					receiver.set_input_center_freq(freq)
					self._update_receiver_validity(key)

			this_source = self._sources[self.source_name]
			this_source.set_tune_hook(tune_hook)
			self.source = this_source
			this_rate = this_source.get_sample_rate()
			rate_changed = self.input_rate != this_rate
			self.input_rate = this_rate
			self.input_freq = this_source.get_freq()
		
		if self.__needs_spectrum or rate_changed:
			print 'Rebuilding spectrum FFT'
			self.__needs_spectrum = False
			self.__needs_reconnect = True
			
			self.spectrum_queue = gr.msg_queue(limit=10)
			self.spectrum_sink = blocks.message_sink(
				self.spectrum_resolution * gr.sizeof_float,
				self.spectrum_queue,
				True) # dont_block
			self.spectrum_fft_block = gnuradio.fft.logpwrfft.logpwrfft_c(
				sample_rate=self.input_rate,
				fft_size=self.spectrum_resolution,
				ref_scale=2,
				frame_rate=self.spectrum_rate,
				avg_alpha=1.0,
				average=False,
			)

		if rate_changed:
			print 'Changing sample rate'
			for receiver in self._receivers.itervalues():
				receiver.set_input_rate(self.input_rate)

		if self.__needs_reconnect:
			print 'Reconnecting'
			self.__needs_reconnect = False
			
			self._recursive_lock()
			self.disconnect_all()


			# recreated each time because reusing an add_ff w/ different
			# input counts fails; TODO: report/fix bug
			audio_sum_l = blocks.add_ff()
			audio_sum_r = blocks.add_ff()

			self.connect(self.source, self.spectrum_fft_block, self.spectrum_sink)

			audio_sum_index = 0
			for key, receiver in self._receivers.iteritems():
				self._receiver_valid[key] = receiver.get_is_valid()
				if self._receiver_valid[key]:
					if audio_sum_index >= 6:
						# Sanity-check to avoid burning arbitrary resources
						# TODO: less arbitrary constant; communicate this restriction to client
						print 'Refusing to connect more than 6 receivers'
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
							self.connect(self.audio_stream_join, sink)
						else:
							if queue_rate not in self.audio_resampler_cache:
								# Moderately expensive due to the internals using optfir
								print 'Constructing resampler for audio rate', queue_rate
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
			print 'Done reconnecting'

	def _update_receiver_validity(self, key):
		receiver = self._receivers[key]
		if receiver.get_is_valid() != self._receiver_valid[key]:
			self.__needs_reconnect = True
			self._do_connect()

	def state_def(self, callback):
		super(Top, self).state_def(callback)
		callback(Cell(self, 'running', writable=True, ctor=bool))
		callback(Cell(self, 'source_name', writable=True,
			ctor=Enum(dict([(k, str(v)) for (k, v) in self._sources.iteritems()]))))
		callback(Cell(self, 'input_rate', ctor=int))
		callback(Cell(self, 'audio_rate', ctor=int))
		callback(Cell(self, 'spectrum_resolution', writable=True, ctor=
			Range(2, 4096, logarithmic=True, integer=True)))
		callback(Cell(self, 'spectrum_rate', writable=True, ctor=
			Range(1, 60, logarithmic=True, integer=False)))
		callback(MsgQueueCell(self, 'spectrum_fft', fill=True, ctor=SpectrumTypeStub))
		callback(BlockCell(self, 'sources'))
		callback(BlockCell(self, 'source', persists=False))
		callback(BlockCell(self, 'receivers'))
		callback(Cell(self, 'cpu_use', ctor=float))

	def start(self):
		# trigger reconnect/restart notification
		self._recursive_lock()
		self._recursive_unlock()
		
		super(Top, self).start()

	def get_running(self):
		return self._running
	
	def set_running(self, value):
		if value != self._running:
			self._running = value
			if value:
				self.start()
			else:
				self.stop()
				self.wait()

	def get_source_name(self):
		return self.source_name
	
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

	def get_input_rate(self):
		return self.input_rate

	def get_audio_rate(self):
		return self.audio_rate
	
	def get_spectrum_resolution(self):
		return self.spectrum_resolution

	def set_spectrum_resolution(self, spectrum_resolution):
		self.spectrum_resolution = spectrum_resolution
		self.__needs_spectrum = True
		self._do_connect()

	def get_spectrum_rate(self):
		return self.spectrum_rate

	def set_spectrum_rate(self, value):
		self.spectrum_rate = value
		self.spectrum_fft_block.set_vec_rate(value)
	
	def get_spectrum_fft_info(self):
		return self.input_freq
	
	def get_spectrum_fft_queue(self):
		return self.spectrum_queue
	
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


class ContextForReceiver(object):
	def __init__(self, top, key):
		self._top = top
		self._key = key
		self._enabled = False # assigned outside

	def revalidate(self):
		if self._enabled:
			self._top._update_receiver_validity(self._key)
	
	def lock(self):
		self._top._recursive_lock()
	
	def unlock(self):
		self._top._recursive_unlock()


def base26(x):
	'''not quite base 26, actually, because it has no true zero digit'''
	if x < 26:
		return 'abcdefghijklmnopqrstuvwxyz'[x]
	else:
		return base26(x // 26 - 1) + base26(x % 26)
