#!/usr/bin/env python
#

import setuptools

setuptools.setup(
    name='mail-poller',
    py_modules=['mailpoller'],
    install_requires=['tornado', 'motor',
                      'sprockets.http',
                      'sprockets.mixins.amqp',
                      'sprockets.mixins.mediatype',
                      'sprockets-tracing']
)
