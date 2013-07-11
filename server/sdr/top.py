#!/usr/bin/env python

import gnuradio
from gnuradio import audio
from gnuradio import blks2
from gnuradio import blocks
from gnuradio import gr
from gnuradio.eng_option import eng_option
from gnuradio.gr import firdes
from optparse import OptionParser
import sdr
from sdr import Cell, BlockCell, Enum
import sdr.receiver
import sdr.receivers.vor


class SpectrumTypeStub:
	pass


class Top(gr.top_block, sdr.ExportedState):

	def __init__(self, sources={}):
		gr.top_block.__init__(self, "SDR top block")
		self._running = False

		# Configuration
		self._sources = dict(sources)
		self.source_name = 'audio'  # placeholder - TODO be nothing instead
		self.audio_rate = audio_rate = 32000
		self.spectrum_resolution = 4096
		self.spectrum_rate = 30
		self._mode = 'AM'

		# Blocks
		self.source = None
		self.receiver = None
		self.audio_sink = None
		
		# State flags
		self.last_receiver_is_valid = False
		self.__needs_audio_restart = True
		self.__needs_spectrum = True
		self.__needs_reconnect = True
		self.input_rate = None
		
		self._do_connect()

	def _do_connect(self):
		"""Do all reconfiguration operations in the proper order."""
		if self.__needs_audio_restart:
			print 'Rebuilding audio blocks'
			self.__needs_reconnect = True

		rate_changed = False
		if self.source is not self._sources[self.source_name] or self.__needs_audio_restart:
			print 'Switching source'
			self.__needs_reconnect = True
			
			def tune_hook():
				if self.source is this_source:
					self._update_receiver_validity()
					self.receiver.set_input_center_freq(self.source.get_freq())

			this_source = self._sources[self.source_name]
			this_source.set_tune_hook(tune_hook)
			self.source = this_source
			this_rate = this_source.get_sample_rate()
			rate_changed = self.input_rate != this_rate
			self.input_rate = this_rate
		
		# clear separately because used twice above
		self.__needs_audio_restart = False
		
		if self.__needs_spectrum or rate_changed:
			print 'Rebuilding spectrum FFT'
			self.__needs_spectrum = False
			self.__needs_reconnect = True
			
			self.spectrum_probe = blocks.probe_signal_vf(self.spectrum_resolution)
			self.spectrum_fft = blks2.logpwrfft_c(
				sample_rate=self.input_rate,
				fft_size=self.spectrum_resolution,
				ref_scale=2,
				frame_rate=self.spectrum_rate,
				avg_alpha=1.0,
				average=False,
			)

		if rate_changed:
			print 'Rebuilding receiver'
			self.receiver = self._make_receiver(self.get_mode())
			self.__needs_reconnect = True

		if self.__needs_reconnect and self.source.needs_renew():
			print 'Renewing source'
			self.source = self.source.renew()
			self._sources[self.source_name] = self.source

		if self.__needs_reconnect:
			print 'Reconnecting'
			self.__needs_reconnect = False
			
			self.lock()
			self.disconnect_all()

			# workaround problem with restarting audio sinks on Mac OS X
			self.audio_sink = audio.sink(self.audio_rate, "", False)

			self.connect(self.source, self.spectrum_fft, self.spectrum_probe)

			self.last_receiver_is_valid = self.receiver.get_is_valid()
			if self.receiver is not None and self.last_receiver_is_valid and self.audio_sink is not None:
				self.connect(self.source, self.receiver)
				self.connect((self.receiver, 0), (self.audio_sink, 0))
				self.connect((self.receiver, 1), (self.audio_sink, 1))
		
			self.unlock()

	def _update_receiver_validity(self):
		if self.receiver.get_is_valid() != self.last_receiver_is_valid:
			self.__needs_reconnect = True
			self._do_connect()

	def state_def(self, callback):
		super(Top, self).state_def(callback)
		callback(Cell(self, 'running', writable=True, ctor=bool))
		callback(Cell(self, 'source_name', writable=True, ctor=Enum(self._sources.keys())))
		callback(Cell(self, 'mode', writable=True, ctor=Enum(['IQ', 'NFM', 'WFM', 'AM', 'USB', 'LSB', 'VOR'])))
		callback(Cell(self, 'input_rate', ctor=int))
		callback(Cell(self, 'audio_rate', ctor=int))
		callback(Cell(self, 'spectrum_resolution', True, ctor=int))
		callback(Cell(self, 'spectrum_rate', True, ctor=float))
		callback(Cell(self, 'spectrum_fft', ctor=SpectrumTypeStub))
		callback(BlockCell(self, 'source'))
		callback(BlockCell(self, 'receiver'))

	def start(self):
		self.__needs_audio_restart = True
		self._do_connect()  # audio sink workaround
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
		self._sources[value]  # raise if not found
		self.source_name = value
		self._do_connect()

	def get_mode(self):
		return self._mode

	def set_mode(self, kind):
		if kind == self._mode:
			return
		self.receiver = self._make_receiver(kind)  # may raise on invalid arg
		self.__needs_reconnect = True
		self._do_connect()
		self._mode = kind  # only if succeeded
	
	def _make_receiver(self, kind):
		'''Returns the receiver.'''
		if kind == 'IQ':
			clas = sdr.receiver.IQReceiver
		elif kind == 'NFM':
			clas = sdr.receiver.NFMReceiver
		elif kind == 'WFM':
			clas = sdr.receiver.WFMReceiver
		elif kind == 'AM':
			clas = sdr.receiver.AMReceiver
		elif kind == 'USB' or kind == 'LSB':
			clas = sdr.receiver.SSBReceiver
		elif kind == 'VOR':
			clas = sdr.receivers.vor.VOR
		else:
			raise ValueError('Unknown mode: ' + kind)
		if self.receiver is not None:
			options = {
				'audio_gain': self.receiver.get_audio_gain(),
				'rec_freq': self.receiver.get_rec_freq(),
				'squelch_threshold': self.receiver.get_squelch_threshold(),
			}
		else:
			options = {
				'audio_gain': 0.25,
				'rec_freq': 97.7e6,
				'squelch_threshold': -100
			}
		if kind == 'LSB':
			options['lsb'] = True
		return clas(
			input_rate=self.input_rate,
			input_center_freq=self.source.get_freq(),
			audio_rate=self.audio_rate,
			revalidate_hook=lambda: self._update_receiver_validity(),
			**options
		)

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
		self.spectrum_fft.set_vec_rate(value)

	def get_spectrum_fft(self):
		return (self.source.get_freq(), self.spectrum_probe.level())
