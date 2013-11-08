ShinySDR
========

This is the software component of a software-defined radio receiver. When combined with hardware devices such as the USRP, RTL-SDR, or HackRF, it can be used to listen to a wide variety of radio transmissions, and can be extended via plugins to support even more modes.

What's shiny about it?
----------------------

I (Kevin Reid) created ShinySDR out of dissatisfaction with the user interface of other SDR applications that were available to me. The overall goal is to make, not necessarily the most capable or efficient SDR application, but rather one which is, shall we say, *not clunky*.

For example, the earliest technical feature of note is its **persistent waterfall display**: You can zoom, pan, and retune without losing any of the displayed history, whereas many other programs will discard anything which is temporarily offscreen, or the whole thing if the window is resized. This isn't especially hard to implement, but it's a far better user interface; your action is reversible. If you zoom in to get a look at one signal, you can zoom out again.

Some other notable features:

* **Browser-based UI:** The receiver can be listened to and remotely controlled over a network or the Internet, as well as from the same machine the actual hardware is connected to. (Required bandwidth: 3 Mb/s to 11 Mb/s, depending on selected spectrum frame rate. This may be improved in future versions by using more compact data formats.)

* **Modularity**: plugin system allows adding support for new modes (types of modulation) and hardware devices.

* **“Hackability”**: All server code is Python, and has no mandatory build or install step. Demodulators prototyped in GNU Radio Companion can be turned into plugins with very little additional code. Control UI can be automatically generated or customized and is based on a generic networking layer.

* **Frequency database**: Jump to favorite stations; catalog signals you hear; import published tables of band, channel, and station info; take notes. (Note: Writing changes to disk is **not yet implemented**, unfortunately.)

On the other hand, you may find that the shiny thing is lacking substance: if you're looking for functional features, we do not have the most modes, the best filters, or the lowest CPU usage. There's probably lots of code that will make a real DSP expert cringe.

Requirements and Installation
-----------------------------

Install the following software on the machine which has your SDR hardware attached and will run the ShinySDR server:

* [Python](http://www.python.org/) 2.7 or later compatible version.
* [Twisted](http://twistedmatrix.com/) 12.0.0 or later.
* [txWS](https://github.com/MostAwesomeDude/txWS) with my [binary message support patch](https://github.com/kpreid/txWS/tree/binary) (hopefully to be included upstream).
* [GNU Radio](http://gnuradio.org/) 3.7.1 or later.
* [`gr-osmosdr`](http://sdr.osmocom.org/trac/wiki/GrOsmoSDR), and any applicable hardware drivers such as `librtlsdr`. (Plugins may be written to use other RF sources, but the only built-in support is for `gr-osmosdr`.)

In the `shinysdr/deps/` directory, copy or symlink the following items:

* `jasmine/` ([Jasmine](https://github.com/pivotal/jasmine/) 1.3.1 or later)
* `openlayers/` ([OpenLayers](http://openlayers.org/) 2.13.1 or later)
* `require.js` ([RequireJS](http://requirejs.org/) 2.1.8 or later)

[TODO: Have a way to automatically download these dependencies.]

The web UI currently supports only [Google Chrome](https://www.google.com/chrome/) (including Chrome OS and Chrome for Android; no testing has been done on Chromium).
While it is not *intended* to be Chrome-only, no attempt has been made to avoid using facilities which are *not yet* implemented in other browsers.

Currently, the client must have the same endianness and floating-point format as the server.
This may be fixed in the future.

Setup
-----

The server uses a configuration file, which is Python code.
Run

<pre>python -m shinysdr.main --create <var>filename</var></pre>

to create an example file.
Edit it to specify your available hardware and other desired configuration (such as a HTTPS server certificate and the location of the state persistence file); instructions are provided in the comments in the example file.


Running the server
------------------

Once you have prepared a configuration file, you can run the server using

<pre>python -m shinysdr.main <var>filename</var></pre>

and access it using your browser at the displayed URL. (The `--go` option will attempt to open it in your default browser, but this is unlikely to be helpful if said browser is not Chrome.)

Usage
-----

Basic procedures:

1. Make sure the “Run” checkbox is checked.

2. Adjust the “Center frequency” to tune your RF hardware to the band you want to observe.

   You can zoom in on the spectrum by scrolling up and down. (Bug: No way to do this without a scrolling input device, particularly not on a touchscreen.)

3. Click on a signal of interest. This will create a *receiver*, which will be marked on the spectrum as well as displaying controls. Use the controls to select the appropriate mode (type of demodulation).

   Multiple signals can be received at once by shift-clicking in the spectrum view. To stop, click the X button by the receiver.


Ideally, the UI would be fully discoverable, but right now there are a number of things that are probably not obvious; here's a list of those that haven't already been mentioned:

* A receiver whose channel frequency is outside of the band around the center frequency will be stopped as long as this is the case.

* The UI is divided into several sections which can be hidden as desired by clicking on their headers. To show a hidden section, click on its name, which will appear on the right side of the header of the section to the left of it.

* The large-text frequency fields can be adjusted by scrolling or up and down arrows as well as by typing digits.

Creating plugins
----------------

ShinySDR plugins are defined based on [the Twisted plugin system](https://twistedmatrix.com/documents/12.0.0/core/howto/plugin.html). A plugin is a Python module or package which provides objects implementing a defined plugin interface. To be loaded, a plugin must be placed somewhere on your Python module search path (`PYTHONPATH`) in the `shinysdr.plugins` package.

Plugins can currently:

  * Add new RF source types. (This does not have a specific interface since sources are written explicitly in the configuration file.)
  * Add new demodulators (`ModeDef`).
  * Add JS code or other web resources to be loaded by the client (`ClientResourceDef`). This can be used to define new user interface elements.

The included VOR demodulator plugin (`shinysdr/plugins/vor/`) may be a useful example.

[TODO: formally document plugin interfaces]

Copyright and License
---------------------

Copyright 2013 Kevin Reid &lt;<kpreid@switchb.org>&gt;

ShinySDR is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

ShinySDR is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.
