ShinySDR
========

This is the software component of a software-defined radio receiver. When combined with hardware devices such as the USRP, RTL-SDR, or HackRF, it can be used to listen to a wide variety of radio transmissions, and can be extended via plugins to support even more modes.

What's shiny about it?
----------------------

I (Kevin Reid) created ShinySDR out of dissatisfaction with the user interface of other SDR applications that were available to me. The overall goal is to make, not necessarily the most capable or efficient SDR application, but rather one which is, shall we say, *not clunky*.

Here's some reasons for you to use ShinySDR:

* **Remote operation via browser-based UI:** The receiver can be listened to and remotely controlled over a LAN or the Internet, as well as from the same machine the actual hardware is connected to. Required network bandwidth: 3 Mb/s to 8 Mb/s, depending on settings.

  Phone/tablet compatible (though not pretty yet). Internet access is not required for local or LAN operation.

* **Persistent waterfall display**: You can zoom, pan, and retune without losing any of the displayed history, whereas many other programs will discard anything which is temporarily offscreen, or the whole thing if the window is resized. If you zoom in to get a look at one signal, you can zoom out again.

* **Frequency database**: Jump to favorite stations; catalog signals you hear; import published tables of band, channel, and station info; take notes. (Note: Saving changes to disk is not yet well-tested.)

* **Map**: Plot station locations from the frequency database, position data from APRS and ADS-B, and mark your own location on the map. (Caveat: No basemap, i.e. streets and borders, is currently present.)

Supported modes:

* Audio: AM, FM, WFM, SSB, CW.
* Other: APRS, Mode S/ADS-B, VOR.

If you're a developer, here's why you should consider working on ShinySDR (or: here's why I wrote my own rather than contributing to another application):

* **All server code is Python**, and has **no mandatory build or install step**.

* **Plugin system** allows adding support for new modes (types of modulation) and hardware devices.

* **Demodulators** prototyped in GNU Radio Companion can be turned into plugins with very little additional code. Control UI can be automatically generated or customized and is based on a generic networking layer.

On the other hand, you may find that the shiny thing is lacking substance: if you're looking for functional features, we do not have the most modes, the best filters, or the lowest CPU usage. Many features are half-implemented (though I try not to have things that blatantly don't work). There's probably lots of code that will make a real DSP expert cringe.

Requirements and Installation
-----------------------------

ShinySDR operates as a specialized web server, running on the machine which has your SDR hardware attached. ShinySDR is known to be compatible with Mac OS X and Linux; in principle, anything which can also run GNU Radio and Python is suitable.

The only web browser currently supported as a ShinySDR client is [Google Chrome](https://www.google.com/chrome/) (excluding Chrome for iPhone or iPad).
While it is not *intended* to be Chrome-only, no attempt has been made to avoid using facilities which are *not yet* implemented in other browsers.
Safari (Mac, 7.0.4) is known to work functionally but with broken flexbox UI layout, and Firefox (29) doesn't work at all (WebSocket fails to connect).

Currently, the client must have the same endianness and floating-point format as the server.
This may be fixed in the future (if I ever hear of this actually being a problem, or if the data in question is switched to fixed-point to reduce data rate).

Installation procedure:

1. Install the following software on the server machine:

    * [Python](http://www.python.org/) 2.7 or later compatible version.
    * [GNU Radio](http://gnuradio.org/) 3.7.4 or later.
    * [`gr-osmosdr`](http://sdr.osmocom.org/trac/wiki/GrOsmoSDR), and any applicable hardware drivers such as `librtlsdr`. (Plugins may be written to use other RF sources, but the only built-in support is for `gr-osmosdr`.)

2. Optionally install these programs/libraries:

    * [`gr-air-modes`](https://github.com/bistromath/gr-air-modes) (for receiving ADS-B, aircraft transponders).
    * [`multimon-ng`](https://github.com/EliasOenal/multimon-ng) (for receiving APRS).
    * `gr-dsd` (for receiving digital voice modes supported by DSD).
    
    (If any of these are not installed, ShinySDR will simply hide the corresponding mode options.)

    <!-- TODO: Mention hamlib once that is better-supported and more useful -->

3. There are two different ways you can go about installing and running ShinySDR, and now you need to know which ones you are planning to use.
The first way is to use the standard Python module/application install process, `setup.py`; this will copy it to an appropriate location on your system and add a command-line program `shinysdr`.
The second way is to run it directly from the source tree, skipping the install step; this is convenient for development because changes take effect immediately.
You can do both, if you want.

    If you are planning to run from source, you must install the following Python libraries:

    * [Twisted](http://twistedmatrix.com/) 12.3.0 or later.
    * [txWS](https://github.com/MostAwesomeDude/txWS) 0.8 or later.
    * [PyEphem](http://rhodesmill.org/pyephem/) 3.7.5.1 or later.

4. Either run the script `fetch-js-deps.sh`, or copy or symlink the following items into the `shinysdr/deps/` directory:

    * `jasmine/` ([Jasmine](https://github.com/pivotal/jasmine/) 1.3.1 or later)
    * `require.js` ([RequireJS](http://requirejs.org/) 2.1.8 or later)

    [TODO: Integrate fetch-js-deps or equivalent effects into setup.py.]

5. If you wish to _install_ ShinySDR on your system, run `python setup.py install`.
   (There are options to control the installation prefix and such; please read a guide on installing Python libraries for more information.)

6. To run ShinySDR as installed, use the command `shinysdr ...`

    To run ShinySDR from the source tree, use the command `python -m shinysdr.main ...` while the current directory is the source tree.
   
    In either case, you must specify a configuration file, as described below.
    The examples show `shinysdr`; substitute `python -m shinysdr.main` if appropriate.

Setup
-----

The server uses a configuration file, which is Python code.
Run this command to create an example file:

<pre>shinysdr --create <var>filename</var></pre>

Edit it to specify your available hardware and other desired configuration (such as a HTTPS server certificate and the location of the state persistence file); instructions are provided in the comments in the example file.

For further documentation on the configuration file, see the manual, which can be accessed at `/manual/configuration` on the running server (there is a link in the UI); or open the file directly at `shinysdr/webstatic/client/manual/configuration.html`.

Running the server
------------------

Once you have prepared a configuration file, you can run the server using

<pre>shinysdr <var>filename</var></pre>

and access it using your browser at the displayed URL. (The `--go` option will attempt to open it in your default browser, but this is unlikely to be helpful if said browser is not Chrome.)

Usage
-----

For information on using and programming ShinySDR, see the manual, which can be accessed at `/manual/` on the running server (there is a link in the UI).

A very brief summary of basic operation:

1. Adjust the “Center frequency” to tune your RF hardware to the band you want to observe.

   You can zoom in on the spectrum by using either a scroll-wheel or two-finger touch (whichever you have; there is unfortunately not yet support for zooming without either function).

2. Click on a signal of interest. This will create a *receiver*, which will be marked on the spectrum as well as displaying controls. Use the controls to select the appropriate mode (type of demodulation).

   Multiple signals can be received at once by shift-clicking in the spectrum view. To stop, click the X button by the receiver.

Copyright and License
---------------------

Copyright 2013, 2014, 2015 Kevin Reid &lt;kpreid@switchb.org&gt;

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

### Additional information

* The file `shinysdr/webstatic/client/basemap.geojson` was derived from [the Natural Earth data set `ne_50m_admin_0_countries`, version 2.0.0](http://www.naturalearthdata.com/downloads/50m-cultural-vectors/).
    This data set [is in the public domain](http://www.naturalearthdata.com/about/terms-of-use/).