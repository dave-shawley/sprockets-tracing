#!/usr/bin/env python
#

import os.path

import setuptools

import sprocketstracing


setuptools.setup(
    name='sprockets-tracing',
    version=sprocketstracing.version,
    description='Implementation of opentracing.io for sprockets',
    long_description='\n'+open('README.rst').read(),
    url='https://github.com/dave-shawley/sprockets-tracing',
    install_requires=['opentracing>=1.1,<2', 'tornado>=4.2,<5'],
    packages=['sprocketstracing'],
    author='Dave Shawley',
    author_email='daveshawley@gmail.com',
)
