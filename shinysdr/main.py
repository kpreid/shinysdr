#!/usr/bin/env python

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

import argparse
import base64
import json
import os
import os.path
import shutil
import sys
import webbrowser
import __builtin__

from twisted.internet import reactor


def main(args_strings=sys.argv, _abort_for_test=False):
	# Option parsing is done before importing the main modules so as to avoid the cost of initializing gnuradio if we are aborting early. TODO: Make that happen for createConfig too.
	argParser = argparse.ArgumentParser()
	argParser.add_argument('configFile', metavar='CONFIG',
		help='path of configuration file')
	argParser.add_argument('--create', dest='createConfig', action='store_true',
		help='write template configuration file to CONFIG and exit')
	argParser.add_argument('-g, --go', dest='openBrowser', action='store_true',
		help='open the UI in a web browser')
	argParser.add_argument('--force-run', dest='force_run', action='store_true',
		help='Run DSP even if no client is connected (for debugging).')
	args = argParser.parse_args(args=args_strings)

	import shinysdr.top
	import shinysdr.web
	import shinysdr.source

	# Load config file
	if args.createConfig:
		with open(args.configFile, 'w') as f:
			f.write('''\
import shinysdr.plugins.osmosdr
import shinysdr.plugins.simulate

sources = {
	# OsmoSDR generic device source; handles USRP, RTL-SDR, FunCube
	# Dongle, HackRF, etc.
	# If desired, add sample_rate=<n> parameter.
	# Use shinysdr.plugins.osmosdr.OsmoSDRProfile to set more parameters
	# to make the best use of your specific hardware's capabilities.
	'osmo': shinysdr.plugins.osmosdr.OsmoSDRSource(''),
	
	# For hardware which uses a sound-card as its ADC or appears as an
	# audio device.
	'audio': shinysdr.source.AudioSource(''),
	
	# Locally generated RF signals for test purposes.
	'sim': shinysdr.plugins.simulate.SimulatedSource(),
}

stateFile = 'state.json'

databasesDir = 'dbs/'

# These are in Twisted endpoint description syntax:
# <http://twistedmatrix.com/documents/current/api/twisted.internet.endpoints.html#serverFromString>
# Note: wsPort must currently be 1 greater than httpPort; if one is SSL
# then both must be. These restrictions will be relaxed later.
httpPort = 'tcp:8100'
wsPort = 'tcp:8101'

# A secret placed in the URL as simple access control. Does not
# provide any real security unless using HTTPS. The default value
# in this file has been automatically generated from 128 random bits.
# Set to None to not use any secret.
rootCap = '%(rootCap)s'
''' % {'rootCap': base64.urlsafe_b64encode(os.urandom(128 // 8)).replace('=','')})
			sys.exit(0)
	else:
		# TODO: better ways to manage the namespaces?
		configEnv = {'shinysdr': shinysdr}
		execfile(args.configFile, __builtin__.__dict__, configEnv)
		sources = configEnv['sources']
		stateFile = str(configEnv['stateFile'])
		webConfig = {}
		for k in ['httpPort', 'wsPort', 'rootCap', 'databasesDir']:
			webConfig[k] = configEnv[k]
	
	def noteDirty():
		# just immediately write (revisit this when more performance is needed)
		with open(stateFile, 'w') as f:
			json.dump(top.state_to_json(), f)
		pass
	
	def restore(root, get_defaults):
		if os.path.isfile(stateFile):
			root.state_from_json(json.load(open(stateFile, 'r')))
			# make a backup in case this code version misreads the state and loses things on save (but only if the load succeeded, in case the file but not its backup is bad)
			shutil.copyfile(stateFile, stateFile + '~')
		else:
			root.state_from_json(get_defaults(root))
	
	
	print 'Flow graph...'
	top = shinysdr.top.Top(sources=sources)
	
	print 'Restoring state...'
	restore(top, top_defaults)
	
	print 'Web server...'
	(stop, url) = shinysdr.web.listen(webConfig, top, noteDirty)
	
	if args.openBrowser:
		print 'Ready. Opening ' + url
		webbrowser.open(url=url, new=1, autoraise=True)
	else:
		print 'Ready. Visit ' + url
	
	if args.force_run:
		print 'force_run'
		from gnuradio.gr import msg_queue
		top.add_audio_queue(msg_queue(limit=2), 44100)
		top.set_unpaused(True)
	
	if _abort_for_test:
		stop()
	else:
		reactor.run()


def top_defaults(top):
	'''Return a friendly initial state for the top block using knowledge of the default config file.'''
	state = {}
	
	# TODO: fix fragility of assumptions
	sources = top.state()['source_name'].type().values()
	restricted = dict(sources)
	if 'audio' in restricted: del restricted['audio']  # typically not RF
	if 'sim' in restricted: del restricted['sim']  # would prefer the real thing
	if 'osmo' in restricted:
		state['source_name'] = 'osmo'
	elif len(restricted.keys()) > 0:
		state['source_name'] = restricted.keys()[0]
	else:
		# out of ideas, let top block pick
		pass
	
	return state


if __name__ == '__main__':
	main()
