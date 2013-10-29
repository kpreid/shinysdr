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

import gnuradio.eng_option

import json
import os
import os.path
import shutil
import argparse
import sys
import webbrowser

from twisted.internet import reactor

# Option parsing is done before importing the main modules so as to avoid the cost of initializing gnuradio.
argParser = argparse.ArgumentParser()
argParser.add_argument('configFile', metavar='CONFIG',
	help='path of configuration file')
argParser.add_argument('--create', dest='createConfig', action='store_true',
	help='write template configuration file to CONFIG and exit')
argParser.add_argument('-g, --go', dest='openBrowser', action='store_true',
	help='open the UI in a web browser')
args = argParser.parse_args()

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
''')
		sys.exit(0)
else:
	# TODO: better ways to manage the namespaces?
	configEnv = {'shinysdr': shinysdr}
	execfile(args.configFile, __builtins__.__dict__, configEnv)
	sources = configEnv['sources']
	stateFile = str(configEnv['stateFile'])
	webConfig = {}
	for k in ['httpPort', 'wsPort', 'rootCap', 'databasesDir']:
		webConfig[k] = str(configEnv[k])


def noteDirty():
	# just immediately write (revisit this when more performance is needed)
	with open(stateFile, 'w') as f:
		json.dump(top.state_to_json(), f)
	pass


def restore(root):
	if os.path.isfile(stateFile):
		root.state_from_json(json.load(open(stateFile, 'r')))
		# make a backup in case this code version misreads the state and loses things on save (but only if the load succeeded, in case the file but not its backup is bad)
		shutil.copyfile(stateFile, stateFile + '~')


print 'Flow graph...'
top = shinysdr.top.Top(sources=sources)

print 'Restoring state...'
restore(top)

print 'Web server...'
url = shinysdr.web.listen(webConfig, top, noteDirty)

if args.openBrowser:
	print 'Ready. Opening ' + url
	webbrowser.open(url=url, new=1, autoraise=True)
else:
	print 'Ready. Visit ' + url

reactor.run()
