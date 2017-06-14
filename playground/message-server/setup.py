#!/usr/bin/env python
#

import setuptools

setuptools.setup(
    name='message-server',
    py_modules=['messageserver'],
    install_requires=['tornado',
                      'sprockets.http',
                      'sprockets.mixins.amqp',
                      'sprockets.mixins.mediatype',
                      'sprockets-tracing']
)
