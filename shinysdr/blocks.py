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

import math
import os
import subprocess

from gnuradio import gr
from gnuradio import blocks
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import pfb
from gnuradio.filter import firdes
from gnuradio.fft import logpwrfft

from shinysdr.values import ExportedState, exported_value, setter, Range, StreamCell, ValueType


class RecursiveLockBlockMixin(object):
	'''
	For top blocks needing recursive locking and/or a notification to restart parts.
	'''
	__lock_count = 0
	
	def _recursive_lock_hook(self):
		''' override'''
		pass
	
	def _recursive_lock(self):
		# gnuradio uses a non-recursive lock, which is not adequate for our purposes because we want to make changes locally or globally without worrying about having a single lock entry point
		if self.__lock_count == 0:
			self.lock()
			self._recursive_lock_hook()
		self.__lock_count += 1

	def _recursive_unlock(self):
		self.__lock_count -= 1
		if self.__lock_count == 0:
			self.unlock()


class Context(object):
	'''
	Client facet for RecursiveLockBlockMixin.
	'''
	def __init__(self, top):
		self.__top = top
	
	def lock(self):
		self.__top._recursive_lock()
	
	def unlock(self):
		self.__top._recursive_unlock()


def _factorize(n):
	# I wish there was a nice standard library function for this...
	# Wrote the simplest thing I could think of
	if n <= 0:
		raise ValueError()
	primes = []
	while n > 1:
		for i in xrange(2, n // 2 + 1):
			if n % i == 0:
				primes.append(i)
				n //= i
				break
		else:
			primes.append(n)
			break
	return primes


class MultistageChannelFilter(gr.hier_block2):
	'''
	Provides frequency translation, low-pass filtering, and arbitrary sample rate conversion.
	
	The multistage aspect improves CPU efficiency and also enables high decimations/sharp filters that would otherwise run into buffer length limits. Or at least, those were the problems I was seeing which I wrote this to fix.
	'''
	def __init__(self,
			name='Multistage Channel Filter',
			input_rate=0,
			output_rate=0,
			cutoff_freq=0,
			transition_width=0,
			center_freq=0):
		assert input_rate > 0
		assert output_rate > 0
		assert cutoff_freq > 0
		assert transition_width > 0
		# cf. firdes.sanity_check_1f (which is private)
		# TODO better errors for other cases
		if cutoff_freq > output_rate / 2:
			# early check for better errors since our cascaded filters might be cryptically nonsense
			raise ValueError('cutoff_freq (%s) is too high for output_rate (%s)' % (cutoff_freq, output_rate))
		
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		self.cutoff_freq = cutoff_freq
		self.transition_width = transition_width
		
		total_decimation = max(1, int(input_rate // output_rate))
		stage_decimations = _factorize(total_decimation)
		stage_decimations.reverse()
		
		self.stages = []
		
		# loop variables
		prev_block = self
		stage_input_rate = input_rate
		last_index = len(stage_decimations) - 1
		
		if len(stage_decimations) == 0:
			# interpolation or nothing -- don't put it in the stages
			# TODO: consider using rotator block instead (has different API)
			self.freq_filter_block = grfilter.freq_xlating_fir_filter_ccc(
				1,
				[1],
				center_freq,
				stage_input_rate)
			self.connect(prev_block, self.freq_filter_block)
			prev_block = self.freq_filter_block
		else:
			# decimation
			for i, stage_decimation in enumerate(stage_decimations):
				next_rate = stage_input_rate / stage_decimation
			
				if i == 0:
					stage_filter = grfilter.freq_xlating_fir_filter_ccc(
						stage_decimation,
						[0],  # placeholder
						center_freq,
						stage_input_rate)
					self.freq_filter_block = stage_filter
				else:
					taps = self.__stage_taps(i == last_index, stage_input_rate, next_rate)
					if len(taps) > 10:
						stage_filter = grfilter.fft_filter_ccc(stage_decimation, taps, 1)
					else:
						stage_filter = grfilter.fir_filter_ccc(stage_decimation, taps)
			
				self.stages.append((stage_filter, stage_input_rate, next_rate))
			
				self.connect(prev_block, stage_filter)
				prev_block = stage_filter
				stage_input_rate = next_rate
		
		# final connection and resampling
		if stage_input_rate == output_rate:
			# exact multiple, no fractional resampling needed
			#print 'direct connect %s/%s' % (output_rate, stage_input_rate)
			self.connect(prev_block, self)
		else:
			# TODO: combine resampler with final filter stage
			# TODO: cache filter computation as optfir is used and takes a noticeable time
			self.connect(
				prev_block,
				pfb.arb_resampler_ccf(float(output_rate) / stage_input_rate),
				self)
			#print 'resampling %s/%s = %s' % (output_rate, stage_input_rate, float(output_rate) / stage_input_rate)
		
		# TODO: Shouldn't be necessary since we compute the taps in the loop above...
		self.__do_taps()
	
	def __do_taps(self):
		'''Re-assign taps for all stages.'''
		last_index = len(self.stages) - 1
		for i, (stage_filter, stage_input_rate, stage_output_rate) in enumerate(self.stages):
			stage_filter.set_taps(self.__stage_taps(i == last_index, stage_input_rate, stage_output_rate))
	
	def __stage_taps(self, is_last, stage_input_rate, stage_output_rate):
		'''Compute taps for one stage.'''
		cutoff_freq = self.cutoff_freq
		transition_width = self.transition_width
		if is_last:
			return firdes.low_pass(
				1.0,
				stage_input_rate,
				cutoff_freq,
				transition_width,
				firdes.WIN_HAMMING)
		else:
			# TODO check for collision with user filter
			user_inner = cutoff_freq - transition_width / 2
			limit = stage_output_rate / 2
			return firdes.low_pass(
				1.0,
				stage_input_rate,
				(user_inner + limit) / 2,
				limit - user_inner,
				firdes.WIN_HAMMING)
	
	def explain(self):
		'''Return a description of the filter design.'''
		s = '%s stages from %i to %i' % (len(self.stages), self.stages[0][1], self.stages[-1][2])
		for stage_filter, stage_input_rate, stage_output_rate in self.stages:
			s += '\n  decimate by %i using %3i taps (%i) in %s' % (
				stage_input_rate // stage_output_rate,
				len(stage_filter.taps()),
				stage_output_rate * len(stage_filter.taps()),
				type(stage_filter).__name__)
		# TODO: Explain final resampler stage if present.
		return s
	
	def get_cutoff_freq(self):
		return self.cutoff_freq
	
	def set_cutoff_freq(self, value):
		self.cutoff_freq = float(value)
		self.__do_taps()
	
	def get_transition_width(self):
		return self.transition_width
	
	def set_transition_width(self, value):
		self.transition_width = float(value)
		self.__do_taps()
	
	def get_center_freq(self):
		return self.freq_filter_block.center_freq()
	
	def set_center_freq(self, freq):
		self.freq_filter_block.set_center_freq(freq)


def make_resampler(in_rate, out_rate):
	# magic numbers from gqrx
	resample_ratio = float(out_rate) / in_rate
	pfbsize = 32
	relative_bandwidth = min(resample_ratio, 1)  # for decimating or interpolating
	return pfb.arb_resampler_fff(
		resample_ratio,
		firdes.low_pass(pfbsize, pfbsize, 0.4 * relative_bandwidth, 0.2 * relative_bandwidth),
		pfbsize)


def rotator_inc(rate, shift):
	'''
	Calculation for using gnuradio.blocks.rotator_cc or other interfaces wanting radians/sample input.
	
	rate: sample rate
	shift: frequency shift in Hz
	'''
	return (2 * math.pi) * (shift / rate)


class SubprocessSink(gr.hier_block2):
	def __init__(self, args, itemsize=gr.sizeof_char):
		gr.hier_block2.__init__(
			self, 'subprocess ' + repr(args),
			gr.io_signature(1, 1, itemsize),
			gr.io_signature(0, 0, 0),
		)
		self.__p = subprocess.Popen(
			args=args,
			stdin=subprocess.PIPE,
			stdout=None,
			stderr=None,
			close_fds=True)
		# we dup the fd because the stdin object and file_descriptor_sink both expect to own it
		fd_owned_by_sink = os.dup(self.__p.stdin.fileno())
		self.__p.stdin.close()  # not going to use
		self.connect(
			self,
			blocks.file_descriptor_sink(itemsize, fd_owned_by_sink))
	
	# we may find this needed later...
	#def __del__(self):
	#	self.__p.kill()


def test_subprocess(args, substring, shell=False):
	'''Check the stdout or stderr of the specified command for a specified string.'''
	# TODO: establish resource and output size limits
	try:
		output = subprocess.check_output(
			args=args,
			shell=shell,
			stderr=subprocess.STDOUT)
		return substring in output
	except OSError:
		return False
	except subprocess.CalledProcessError:
		return False


class _NoContext(object):
	def lock(self):
		pass
	
	def unlock(self):
		pass


class MessageDistributorSink(gr.hier_block2):
	'''Like gnuradio.blocks.message_sink, but copies its messages to a dynamic set of queues and saves the most recent item.
	
	Never blocks.'''
	def __init__(self, itemsize, context, migrate=None):
		gr.hier_block2.__init__(
			self, self.__class__.__name__,
			gr.io_signature(1, 1, itemsize),
			gr.io_signature(0, 0, 0),
		)
		self.__itemsize = itemsize
		self.__context = _NoContext()
		self.__peek = blocks.probe_signal_vb(itemsize)
		self.__subscriptions = {}
		
		self.connect(self, self.__peek)
		
		if migrate is not None:
			assert isinstance(migrate, MessageDistributorSink)  # sanity check
			for queue in migrate.__subscriptions.keys():
				migrate.unsubscribe(queue)
				self.subscribe(queue)
		
		# set context now, not earlier, so as not to call it while migrating
		self.__context = context

	def get(self):
		return self.__peek.level()
	
	def subscribe(self, queue):
		assert queue not in self.__subscriptions
		sink = blocks.message_sink(self.__itemsize, queue, True)
		self.__subscriptions[queue] = sink
		try:
			self.__context.lock()
			self.connect(self, sink)
		finally:
			self.__context.unlock()
	
	def unsubscribe(self, queue):
		sink = self.__subscriptions[queue]
		del self.__subscriptions[queue]
		try:
			self.__context.lock()
			self.disconnect(self, sink)
		finally:
			self.__context.unlock()


_maximum_fft_rate = 120


class _OverlapGimmick(gr.hier_block2):
	'''
	Pure flowgraph kludge to cause a logpwrfft block to perform overlapped FFTs.
	
	The more correct solution would be to replace stream_to_vector_decimator (used inside of logpwrfft) with a block which takes arbitrarily-spaced vector chunks of the input rather than chunking and then decimating in terms of whole chunks. The cost of doing this instead is more scheduling steps and more data copies.
	
	To adjust for the data rate, the logpwrfft block's sample rate parameter must be multiplied by the factor parameter of this block; or equivalently, the frame rate must be divided by it.
	'''
	
	def __init__(self, size, factor, itemsize=gr.sizeof_gr_complex):
		'''
		size: (int) vector size (FFT size) of next block
		factor: (int) output will have this many more samples than input
		
		If size is not divisible by factor, then the output will necessarily have jitter.
		'''
		size = int(size)
		factor = int(factor)
		# assert size % factor == 0
		offset = size // factor

		gr.hier_block2.__init__(
			self, self.__class__.__name__,
			gr.io_signature(1, 1, itemsize),
			gr.io_signature(1, 1, itemsize),
		)
		
		if factor == 1:
			# No duplication needed; simplify flowgraph
			# GR refused to connect self to self, so insert a dummy block
			self.connect(self, blocks.copy(itemsize), self)
		else:
			interleave = blocks.interleave(itemsize * size)
			self.connect(
				interleave,
				blocks.vector_to_stream(itemsize, size),
				self)
		
			for i in xrange(0, factor):
				self.connect(
					self,
					blocks.delay(itemsize, (factor - 1 - i) * offset),
					blocks.stream_to_vector(itemsize, size),
					(interleave, i))


class SpectrumType(ValueType):
	def type_to_json(self):
		return u'spectrum'
	
	def __call__(self, specimen):
		raise Exception('Coerce not implemented for SpectrumType')
	
	# TODO implement coerce behavior, generally make this more well-defined


class MonitorSink(gr.hier_block2, ExportedState):
	'''
	Convenience wrapper around all the bits and pieces to display the signal spectrum to the client.
	
	The units of the FFT output are dB power/Hz (power spectral density) relative to unit amplitude (i.e. dBFS assuming the source clips at +/-1). Note this is different from the standard logpwrfft result of power _per bin_, which would be undesirably dependent on the sample rate and bin size.
	'''
	def __init__(self,
			sample_rate=None,
			complex_in=True,
			enable_scope=False,
			freq_resolution=4096,
			time_length=2048,
			frame_rate=30.0,
			input_center_freq=0.0,
			context=None):
		assert sample_rate > 0
		assert context is not None
		complex_in = bool(complex_in)
		if complex_in:
			itemsize = gr.sizeof_gr_complex
		else:
			itemsize = gr.sizeof_float
		
		gr.hier_block2.__init__(
			self, self.__class__.__name__,
			gr.io_signature(1, 1, itemsize),
			gr.io_signature(0, 0, 0),
		)
		
		# constant parameters
		self.__complex = complex_in
		self.__itemsize = itemsize
		self.__context = context
		self.__enable_scope = enable_scope
		
		# settable parameters
		self.__sample_rate = float(sample_rate)
		self.__freq_resolution = int(freq_resolution)
		self.__time_length = int(time_length)
		self.__frame_rate = float(frame_rate)
		self.__input_center_freq = float(input_center_freq)
		
		# blocks
		self.__fft_sink = None
		self.__scope_sink = None
		self.__scope_chunker = None
		self.__logpwrfft = None
		self.__overlapper = None
		
		self.__rebuild()
		self.__connect()
	
	def state_def(self, callback):
		super(MonitorSink, self).state_def(callback)
		# TODO make this possible to be decorator style
		callback(StreamCell(self, 'fft', ctor=SpectrumType()))
		callback(StreamCell(self, 'scope', ctor=SpectrumType()))  # TODO distinct type

	def __rebuild(self):
		overlap_factor = int(math.ceil(_maximum_fft_rate * self.__freq_resolution / self.__sample_rate))
		# sanity limit -- OverlapGimmick is not free
		overlap_factor = min(16, overlap_factor)
		
		self.__fft_sink = MessageDistributorSink(
			itemsize=self.__freq_resolution * gr.sizeof_float,
			context=self.__context,
			migrate=self.__fft_sink)
		self.__overlapper = _OverlapGimmick(
			size=self.__freq_resolution,
			factor=overlap_factor,
			itemsize=self.__itemsize)
		
		# Adjusts units so displayed level is independent of resolution and sample rate.
		compensation = 10 * math.log10(self.__freq_resolution / self.__sample_rate)
		# TODO: Consider not using the logpwrfft block
		
		self.__logpwrfft = [logpwrfft.logpwrfft_f, logpwrfft.logpwrfft_c][self.__complex](
			sample_rate=self.__sample_rate * overlap_factor,
			fft_size=self.__freq_resolution,
			ref_scale=10.0 ** (-compensation / 20.0) * 2,  # not actually using this as a reference scale value but avoiding needing to use a separate add operation to apply the unit change -- this expression is the inverse of what logpwrfft does internally
			frame_rate=self.__frame_rate,
			avg_alpha=1.0,
			average=False)
	
		self.__scope_sink = MessageDistributorSink(
			itemsize=self.__time_length * gr.sizeof_gr_complex,
			context=self.__context,
			migrate=self.__scope_sink)
		self.__scope_chunker = blocks.stream_to_vector_decimator(
			item_size=gr.sizeof_gr_complex,
			sample_rate=self.__sample_rate,
			vec_rate=self.__frame_rate,  # TODO doesn't need to be coupled
			vec_len=self.__time_length)

	def __connect(self):
		self.__context.lock()
		try:
			self.disconnect_all()
			self.connect(
				self,
				self.__overlapper,
				self.__logpwrfft,
				self.__fft_sink)
			if self.__enable_scope:
				self.connect(
					self,
					self.__scope_chunker,
					self.__scope_sink)
		finally:
			self.__context.unlock()
	
	# non-exported
	def set_sample_rate(self, value):
		self.__sample_rate = float(value)
		self.__rebuild()
		self.__connect()
	
	# non-exported
	def set_input_center_freq(self, value):
		self.__input_center_freq = float(value)	
	
	@exported_value(ctor=Range([(2, 4096)], logarithmic=True, integer=True))
	def get_freq_resolution(self):
		return self.__freq_resolution

	@setter
	def set_freq_resolution(self, freq_resolution):
		self.__freq_resolution = freq_resolution
		self.__rebuild()
		self.__connect()

	@exported_value(ctor=Range([(1, 4096)], logarithmic=True, integer=True))
	def get_time_length(self):
		return self.__time_length

	@setter
	def set_time_length(self, value):
		self.__time_length = value
		self.__rebuild()
		self.__connect()

	@exported_value(ctor=Range([(1, _maximum_fft_rate)], logarithmic=True, integer=False))
	def get_frame_rate(self):
		return self.__frame_rate

	@setter
	def set_frame_rate(self, value):
		self.__frame_rate = value
		self.__logpwrfft.set_vec_rate(value)
	
	# exported via state_def
	def get_fft_info(self):
		return (self.__input_center_freq, self.__sample_rate)
	
	def get_fft_distributor(self):
		return self.__fft_sink
	
	# exported via state_def
	def get_scope_info(self):
		return (0, self.__sample_rate)  # one field not used
	
	def get_scope_distributor(self):
		return self.__scope_sink
