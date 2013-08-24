#!/usr/bin/env python

import gnuradio.eng_option

import json
import os
import os.path
import shutil
import argparse
import sys

from twisted.internet import reactor

# Option parsing is done before importing the main modules so as to avoid the cost of initializing gnuradio.
argParser = argparse.ArgumentParser()
argParser.add_argument('configFile', metavar='CONFIG',
	help='path of configuration file')
argParser.add_argument('--create', dest='createConfig', action='store_true',
	help='write template configuration file to CONFIG and exit')
args = argParser.parse_args()

import sdr.top
import sdr.web
import sdr.source

# Load config file
if args.createConfig:
	with open(args.configFile, 'w') as f:
		f.write('''\
import sdr.plugins.osmosdr
sources = {
	# OsmoSDR generic device source; handles USRP, RTL-SDR, FunCube
	# Dongle, HackRF, etc.
	'osmo': sdr.plugins.osmosdr.OsmoSDRSource(''),

	# For hardware which uses a sound-card as its ADC or appears as an
	# audio device.
	'audio': sdr.source.AudioSource(''),
	
	# Locally generated RF signals for test purposes.
	'sim': sdr.source.SimulatedSource(),
}

stateFile = 'state.json'

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
	configEnv = {'sdr': sdr}
	execfile(args.configFile, __builtins__.__dict__, configEnv)
	sources = configEnv['sources']
	stateFile = str(configEnv['stateFile'])
	webConfig = {}
	for k in ['httpPort', 'wsPort', 'rootCap']:
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
	

# TODO: This should not be a file copy operation; we should do an overlay somehow inside the web server.
print 'Building web UI content...'
jasmineOut = os.path.join(sdr.web.staticResourcePath, 'test/jasmine/')
if os.path.exists(jasmineOut):
	shutil.rmtree(jasmineOut)
os.mkdir(jasmineOut)
for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
	shutil.copyfile('deps/jasmine/lib/jasmine-core/' + name, jasmineOut + name)

print 'Flow graph...'
top = sdr.top.Top(sources=sources)

print 'Restoring state...'
restore(top)

print 'Web server...'
url = sdr.web.listen(webConfig, top, noteDirty)

print 'Ready. Visit ' + url
reactor.run()
