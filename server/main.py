#!/usr/bin/env python

import gnuradio.eng_option

import json
import os
import shutil
import optparse

from twisted.internet import reactor

# Option parsing is done before importing the main modules so as to avoid the cost of initializing gnuradio.
optionParser = optparse.OptionParser(
	option_class=gnuradio.eng_option.eng_option)
optionParser.add_option('--sources', dest='sources', metavar='FILE',
	help='load Python code from FILE defining RF sources, e.g. ' +
	     '"sources = {\'example\': sdr.source.WhateverSource()}"')
(options, args) = optionParser.parse_args()
if len(args) > 0:
	optionParser.error('non-option parameters are not used: ' + ' '.join(map(repr, args)) + '')

import sdr.top
import sdr.web
import sdr.source

filename = 'state.json'


def noteDirty():
	# just immediately write (revisit this when more performance is needed)
	with open(filename, 'w') as f:
		json.dump(top.state_to_json(), f)
	pass


def restore(root):
	if os.path.isfile(filename):
		root.state_from_json(json.load(open(filename, 'r')))
		# make a backup in case this code version misreads the state and loses things on save (but only if the load succeeded, in case the file but not its backup is bad)
		shutil.copyfile(filename, filename + '~')
	

print 'Building web UI content...'
jasmineOut = 'static/test/jasmine/'
if os.path.exists(jasmineOut):
	shutil.rmtree(jasmineOut)
os.mkdir(jasmineOut)
for name in ['jasmine.css', 'jasmine.js', 'jasmine-html.js']:
	shutil.copyfile('deps/jasmine/lib/jasmine-core/' + name, jasmineOut + name)

print 'Flow graph...'
if options.sources is not None:
	# TODO: better ways to manage the namespaces?
	env = {'sdr': sdr}
	execfile(options.sources, __builtins__.__dict__, env)
	sources = env['sources']
else:
	# Note: This is slow as it triggers the OsmoSDR device initialization
	sources = {
		'audio': sdr.source.AudioSource(''),
		'rtl': sdr.source.OsmoSDRSource('rtl=0'),
		'sim': sdr.source.SimulatedSource(),
	}
top = sdr.top.Top(sources=sources)

print 'Restoring state...'
restore(top)

print 'Web server...'
url = sdr.web.listen(top, noteDirty)

print 'Ready. Visit ' + url
reactor.run()
