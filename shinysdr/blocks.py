from gnuradio import gr
from gnuradio import blocks
from gnuradio import filter as grfilter
from gnuradio.filter import pfb
from gnuradio.filter import firdes

import subprocess
import os

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
	def __init__(self,
			name='Multistage Channel Filter',
			input_rate=None,
			output_rate=None,
			cutoff_freq=None,
			transition_width=None):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		
		total_decimation = max(1, input_rate // output_rate)
		stage_decimations = _factorize(total_decimation)
		stage_decimations.reverse()
		if len(stage_decimations) == 0:
			# We need at least one filter to do the frequency shift
			stage_decimations = [1]
		
		prev_block = self
		stage_input_rate = input_rate
		for i, stage_decimation in enumerate(stage_decimations):
			first = i == 0
			last = i == len(stage_decimations) - 1
			next_rate = stage_input_rate / stage_decimation
			
			# filter taps
			if last:
				taps = firdes.low_pass(
					1.0,
					stage_input_rate,
					cutoff_freq,
					transition_width,
					firdes.WIN_HAMMING)
			else:
				# TODO check for collision with user filter
				user_inner = cutoff_freq - transition_width / 2
				limit = next_rate / 2
				taps = firdes.low_pass(
					1.0,
					stage_input_rate,
					(user_inner + limit) / 2,
					limit - user_inner,
					firdes.WIN_HAMMING)
			
			#print 'Stage %i decimation %i rate %i taps %i' % (i, stage_decimation, stage_input_rate, len(taps))
			
			# filter block
			if first:
				stage_filter = grfilter.freq_xlating_fir_filter_ccc(
					stage_decimation,
					taps,
					0,  # default frequency
					stage_input_rate)
				self.freq_filter_block = stage_filter
			else:
				stage_filter = grfilter.fir_filter_ccc(stage_decimation, taps)
			
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
	
	def set_center_freq(self, freq):
		self.freq_filter_block.set_center_freq(freq)


def make_resampler(in_rate, out_rate):
	# magic numbers from gqrx
	resample_ratio = float(out_rate) / in_rate
	pfbsize = 32
	return pfb.arb_resampler_fff(
		resample_ratio,
		firdes.low_pass(pfbsize, pfbsize, 0.4 * resample_ratio, 0.2 * resample_ratio),
		pfbsize)


class SubprocessSink(gr.hier_block2):
	def __init__(self, args):
		gr.hier_block2.__init__(
			self, 'subprocess ' + repr(args),
			gr.io_signature(1, 1, gr.sizeof_char * 1),
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
			blocks.file_descriptor_sink(gr.sizeof_char, fd_owned_by_sink))
	
	# we may find this needed later...
	#def __del__(self):
	#	self.__p.kill()


