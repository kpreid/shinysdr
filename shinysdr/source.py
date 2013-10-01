from gnuradio import gr
from gnuradio import blocks
from gnuradio import audio

from shinysdr.values import Range, ExportedState, exported_value, setter


class Source(gr.hier_block2, ExportedState):
	'''Generic wrapper for multiple source types, yielding complex samples.'''
	def __init__(self, name):
		gr.hier_block2.__init__(
			self, name,
			gr.io_signature(0, 0, 0),
			gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
		)
		self.tune_hook = lambda: None

	def set_tune_hook(self, value):
		self.tune_hook = value

	@exported_value(ctor=float)
	def get_sample_rate(self):
		raise NotImplementedError()

	@exported_value(ctor=float)
	def get_freq(self):
		raise NotImplementedError()

	def notify_reconnecting_or_restarting(self):
		pass


class AudioSource(Source):
	def __init__(self,
			name='Audio Device Source',
			device_name='',
			quadrature_as_stereo=False,
			**kwargs):
		Source.__init__(self, name=name, **kwargs)
		self.__name = name  # for reinit only
		self.__device_name = device_name
		self.__sample_rate = 44100
		self.__quadrature_as_stereo = quadrature_as_stereo
		self.__complex = blocks.float_to_complex(1)
		self.__source = None
		
		self.__do_connect()
	
	def __str__(self):
		return 'Audio ' + self.__device_name
	
	def get_sample_rate(self):
		return self.__sample_rate

	def notify_reconnecting_or_restarting(self):
		# work around OSX audio source bug; does not work across flowgraph restarts
		self.__do_connect()

	@exported_value(ctor=float)
	def get_freq(self):
		return 0.0

	def get_tune_delay(self):
		return 0.0

	def __do_connect(self):
		self.disconnect_all()
		
		# work around OSX audio source bug; does not work across flowgraph restarts
		self.__source = audio.source(
			self.__sample_rate,
			device_name=self.__device_name,
			ok_to_block=True)
		
		self.connect(self.__source, self.__complex, self)
		if self.__quadrature_as_stereo:
			# if we don't do this, the imaginary component is 0 and the spectrum is symmetric
			self.connect((self.__source, 1), (self.__complex, 1))


