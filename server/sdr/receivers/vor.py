#!/usr/bin/env python

# TODO: fully clean up this GRC-generated file

from gnuradio import analog
from gnuradio import blks2
from gnuradio import blocks
from gnuradio import fft
from gnuradio import filter
from gnuradio import gr
from gnuradio.gr import firdes
import math

import sdr.receiver
from sdr.receiver import Receiver
from sdr import Cell

fm_subcarrier = 9960
fm_deviation = 480

class VOR(sdr.receiver.SimpleAudioReceiver):

	def __init__(self, name='VOR receiver', zero_point=-5, **kwargs):
		self.channel_rate = channel_rate = 64000 # TODO: should be 40000, but we are constrained by decimation for the moment
		self.zero_point = zero_point

		transition=10000
		sdr.receiver.SimpleAudioReceiver.__init__(self,
			name=name,
			demod_rate=channel_rate,
			band_filter=fm_subcarrier + fm_deviation + transition/2,
			band_filter_transition=transition,
			**kwargs)

		audio_rate = self.audio_rate
		self.dir_rate = dir_rate = 10

		if audio_rate % dir_rate != 0:
			raise ValueError, 'Audio rate %s is not a multiple of direction-finding rate %s' % (audio_rate, dir_rate)
		self.dir_scale = dir_scale = int(audio_rate/dir_rate)
		self.audio_scale = audio_scale = int(channel_rate/audio_rate)
		

		self.zeroer = blocks.add_const_vff((zero_point*(math.pi/180), ))
		  
		self.dir_vector_filter = gr.fir_filter_ccf(1, firdes.low_pass(
			1, dir_rate, 1, 2, firdes.WIN_HAMMING, 6.76))
		self.am_channel_filter_block = gr.fir_filter_ccf(1, firdes.low_pass(
			1, channel_rate, 10000, 4000, firdes.WIN_HAMMING, 6.76))
		self.goertzel_fm = fft.goertzel_fc(channel_rate, dir_scale*audio_scale, 30)
		self.goertzel_am = fft.goertzel_fc(audio_rate, dir_scale, 30)
		self.fm_channel_filter_block = filter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1.0, channel_rate, 500, 100, firdes.WIN_HAMMING)), fm_subcarrier, channel_rate)
		self.dc_blocker_block = filter.dc_blocker_ff(128, True)
		self.multiply_conjugate_block = blocks.multiply_conjugate_cc(1)
		self.complex_to_arg_block = blocks.complex_to_arg(1)
		self.am_demod_block = blks2.am_demod_cf(
			channel_rate=channel_rate,
			audio_decim=audio_scale,
			audio_pass=5000,
			audio_stop=5500,
		)
		self.fm_demod_block = analog.quadrature_demod_cf(1)
		self.agc_fm = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0, 100)
		self.agc_am = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0, 100)
		
		self.probe = blocks.probe_signal_f()

		##################################################
		# Connections
		##################################################
		# Input
		self.connect(
			self,
			self.band_filter_block)
		# AM chain
		self.connect(
			self.band_filter_block,
			self.am_channel_filter_block,
			self.am_demod_block)
		# AM audio
		self.connect(
			self.am_demod_block,
			self.dc_blocker_block,
			self.audio_gain_block,
			self)
		# AM phase
		self.connect(
			self.am_demod_block,
			self.goertzel_am,
			self.agc_am,
			(self.multiply_conjugate_block, 0))
		# FM phase
		self.connect(
			self.band_filter_block,
			self.fm_channel_filter_block,
			self.fm_demod_block,
			self.goertzel_fm,
			self.agc_fm,
			(self.multiply_conjugate_block, 1))
		# Phase comparison and output
		self.connect(
			self.multiply_conjugate_block,
			self.dir_vector_filter,
			self.complex_to_arg_block,
			self.zeroer,
			self.probe)

	def state_def(self, callback):
		super(sdr.receiver.SimpleAudioReceiver, self).state_def(callback)
		callback(Cell(self, 'zero_point', writable=True))
		callback(Cell(self, 'angle'))

	def get_zero_point(self):
		return self.zero_point

	def set_zero_point(self, zero_point):
		self.zero_point = zero_point
		self.zeroer.set_k((self.zero_point*(math.pi/180), ))

	def get_angle(self):
		return self.probe.level()