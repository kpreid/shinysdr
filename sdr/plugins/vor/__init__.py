# TODO: fully clean up this GRC-generated file

from twisted.web import static
from zope.interface import implements
from twisted.plugin import IPlugin

from gnuradio import gr
from gnuradio import blocks
from gnuradio import analog
from gnuradio import fft
from gnuradio import filter as grfilter  # don't shadow builtin
from gnuradio.filter import firdes

import math
import os.path

from sdr import filters
from sdr.receiver import ModeDef, IDemodulator
from sdr.plugins.basic_demod import SimpleAudioDemodulator
from sdr.values import exported_value, setter
from sdr.web import ClientResourceDef

audio_modulation_index = 0.07
fm_subcarrier = 9960
fm_deviation = 480


class VOR(SimpleAudioDemodulator):
	implements(IDemodulator)
	
	def __init__(self, mode='VOR', zero_point=59, **kwargs):
		self.channel_rate = channel_rate = 40000
		internal_audio_rate = 20000  # TODO over spec'd
		self.zero_point = zero_point

		transition = 5000
		SimpleAudioDemodulator.__init__(self,
			mode=mode,
			demod_rate=channel_rate,
			band_filter=fm_subcarrier * 1.25 + fm_deviation + transition / 2,
			band_filter_transition=transition,
			**kwargs)

		self.dir_rate = dir_rate = 10

		if internal_audio_rate % dir_rate != 0:
			raise ValueError('Audio rate %s is not a multiple of direction-finding rate %s' % (internal_audio_rate, dir_rate))
		self.dir_scale = dir_scale = int(internal_audio_rate / dir_rate)
		self.audio_scale = audio_scale = int(channel_rate / internal_audio_rate)

		self.zeroer = blocks.add_const_vff((zero_point * (math.pi / 180), ))
		
		self.dir_vector_filter = grfilter.fir_filter_ccf(1, firdes.low_pass(
			1, dir_rate, 1, 2, firdes.WIN_HAMMING, 6.76))
		self.am_channel_filter_block = grfilter.fir_filter_ccf(1, firdes.low_pass(
			1, channel_rate, 5000, 5000, firdes.WIN_HAMMING, 6.76))
		self.goertzel_fm = fft.goertzel_fc(channel_rate, dir_scale * audio_scale, 30)
		self.goertzel_am = fft.goertzel_fc(internal_audio_rate, dir_scale, 30)
		self.fm_channel_filter_block = grfilter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1.0, channel_rate, fm_subcarrier / 2, fm_subcarrier / 2, firdes.WIN_HAMMING)), fm_subcarrier, channel_rate)
		self.multiply_conjugate_block = blocks.multiply_conjugate_cc(1)
		self.complex_to_arg_block = blocks.complex_to_arg(1)
		self.am_agc_block = analog.feedforward_agc_cc(1024, 1.0)
		self.am_demod_block = analog.am_demod_cf(
			channel_rate=channel_rate,
			audio_decim=audio_scale,
			audio_pass=5000,
			audio_stop=5500,
		)
		self.fm_demod_block = analog.quadrature_demod_cf(1)
		self.phase_agc_fm = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0)
		self.phase_agc_am = analog.agc2_cc(1e-1, 1e-2, 1.0, 1.0)
		
		self.probe = blocks.probe_signal_f()
		
		self.resampler_block = filters.make_resampler(internal_audio_rate, self.audio_rate)

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
			self.am_agc_block,
			self.am_demod_block)
		# AM audio
		self.connect(
			self.am_demod_block,
			blocks.multiply_const_ff(1.0 / audio_modulation_index * 0.5),
			self.resampler_block)
		self.connect_audio_output(self.resampler_block, self.resampler_block)
		
		# AM phase
		self.connect(
			self.am_demod_block,
			self.goertzel_am,
			self.phase_agc_am,
			(self.multiply_conjugate_block, 0))
		# FM phase
		self.connect(
			self.band_filter_block,
			self.fm_channel_filter_block,
			self.fm_demod_block,
			self.goertzel_fm,
			self.phase_agc_fm,
			(self.multiply_conjugate_block, 1))
		# Phase comparison and output
		self.connect(
			self.multiply_conjugate_block,
			self.dir_vector_filter,
			self.complex_to_arg_block,
			blocks.multiply_const_ff(-1),  # opposite angle conventions
			self.zeroer,
			self.probe)

	@exported_value(ctor=float)
	def get_zero_point(self):
		return self.zero_point

	@setter
	def set_zero_point(self, zero_point):
		self.zero_point = zero_point
		self.zeroer.set_k((self.zero_point * (math.pi / 180), ))

	@exported_value(ctor=float)
	def get_angle(self):
		return self.probe.level()


# Twisted plugin exports
pluginMode = ModeDef('VOR', label='VOR', demodClass=VOR)
pluginClient = ClientResourceDef(
	key=__name__,
	resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
	loadURL='vor.js')
