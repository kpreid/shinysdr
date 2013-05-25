class ExportedState(object):
	def state_keys(self, callback):
		pass
	def state_to_json(self):
		state = {}
		def callback(key):
			state[key] = self.state_get(key)
		self.state_keys(callback)
		return state
	def state_from_json(self, state):
		for key in state:
			self.state_set(key, state[key])
	def state_get(self, key):
		# TODO: accept only exported keys
		return getattr(self, 'get_' + key)()
	def state_set(self, key, value):
		# TODO: accept only exported keys
		return getattr(self, 'set_' + key)(value)
