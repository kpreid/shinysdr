#!/usr/bin/env python

# Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

from setuptools import setup, find_packages


# Mostly written on the advice of <http://www.scotttorborg.com/python-packaging/>.

setup(
    name='ShinySDR',
    #version='...',  # No versioning is defined yet
    description='Software-defined radio receiver application built on GNU Radio with a web-based UI and plugins.',
    url='https://github.com/kpreid/shinysdr/',
    author='Kevin Reid',
    author_email='kpreid@switchb.org',
    classifiers=[
        # TODO: review/improve; this list was made by browsing <https://pypi.python.org/pypi?%3Aaction=list_classifiers>; can we add new items?
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Framework :: Twisted',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Natural Language :: English',
        'Operating System :: OS Independent',  # will probably fail on notPOSIX due to lack of portability work, not fundamentally
        'Topic :: Communications :: Ham Radio',  # non-exclusively ham
    ],
    license='GPLv3+',
    packages=find_packages(exclude=['shinysdr.test']),
    include_package_data=True,
    install_requires=[
        #'gnuradio',  # Not PyPI
        #'osmosdr',  # Not PyPI
        'twisted',
        'txws',
        'ephem'
    ],
    dependency_links=[],
    # zip_safe: TODO: Investigate. I suspect unsafe due to serving web resources relative to __file__.
    zip_safe=False,
    entry_points={
        'console_scripts': {
            'shinysdr = shinysdr.main:main'
        }
    }
)
