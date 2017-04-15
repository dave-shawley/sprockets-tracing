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
    classifiers=['Intended Audience :: Developers',
                 'License :: OSI Approved :: BSD License',
                 'Operating System :: OS Independent',
                 'Programming Language :: Python',
                 'Programming Language :: Python :: 2',
                 'Programming Language :: Python :: 2.7',
                 'Programming Language :: Python :: 3',
                 'Programming Language :: Python :: 3.4',
                 'Programming Language :: Python :: 3.5',
                 'Development Status :: 1 - Planning',
                 'Environment :: Web Environment'],
)
