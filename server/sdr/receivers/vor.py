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

class VOR(sdr.receiver.SimpleAudioReceiver):

	def __init__(self, name='VOR receiver', zero_point=-5, **kwargs):
		channel_halfbandwidth = 40000 # TODO: too wide, was fitting for original math
		self.channel_rate = channel_rate = 64000 # TODO: should be 40000, but we are constrained by decimation for the moment
		self.zero_point = zero_point

		sdr.receiver.SimpleAudioReceiver.__init__(self,
			name=name,
			demod_rate=channel_rate,
			band_filter=channel_halfbandwidth,
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
		self.low_pass_filter_0 = gr.fir_filter_ccf(1, firdes.low_pass(
			1, channel_rate, 10000, 4000, firdes.WIN_HAMMING, 6.76))
		self.goertzel_fm = fft.goertzel_fc(channel_rate, dir_scale*audio_scale, 30)
		self.goertzel_am = fft.goertzel_fc(audio_rate, dir_scale, 30)
		self.freq_xlating_fir_filter_xxx_0_0 = filter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1.0, channel_rate, 500, 100, firdes.WIN_HAMMING)), fm_subcarrier, channel_rate)
		self.dc_blocker_xx_0 = filter.dc_blocker_ff(128, True)
		self.blocks_multiply_conjugate_cc_0 = blocks.multiply_conjugate_cc(1)
		self.blocks_complex_to_arg_0 = blocks.complex_to_arg(1)
		self.blks2_am_demod_cf_0 = blks2.am_demod_cf(
			channel_rate=channel_rate,
			audio_decim=audio_scale,
			audio_pass=5000,
			audio_stop=5500,
		)
		self.analog_quadrature_demod_cf_0 = analog.quadrature_demod_cf(1)
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
			self.low_pass_filter_0,
			self.blks2_am_demod_cf_0)
		# AM audio
		self.connect(
			self.blks2_am_demod_cf_0,
			self.dc_blocker_xx_0,
			self.audio_gain_block,
			self)
		# AM phase
		self.connect((self.blks2_am_demod_cf_0, 0), (self.goertzel_am, 0))
		self.connect((self.goertzel_am, 0), (self.agc_am, 0))
		self.connect((self.agc_am, 0), (self.blocks_multiply_conjugate_cc_0, 0))
		# FM phase
		self.connect(
			self.band_filter_block,
			self.freq_xlating_fir_filter_xxx_0_0,
			self.analog_quadrature_demod_cf_0,
			self.goertzel_fm,
			self.agc_fm)
		# Phase comparison and output
		self.connect((self.agc_fm, 0), (self.blocks_multiply_conjugate_cc_0, 1))
		self.connect((self.blocks_multiply_conjugate_cc_0, 0), (self.dir_vector_filter, 0))
		self.connect((self.dir_vector_filter, 0), (self.blocks_complex_to_arg_0, 0))
		self.connect((self.blocks_complex_to_arg_0, 0), (self.zeroer, 0))
		self.connect(self.zeroer, self.probe)
		# TODO connect zeroer to display

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