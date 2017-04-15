import unittest
try:
    from unittest import mock
except ImportError:
    import mock

from tornado import web
import opentracing


class SprocketsTracingTestCase(unittest.TestCase):

    def setUp(self):
        super(SprocketsTracingTestCase, self).setUp()
        self.saved_tracer = opentracing.tracer
        self.application = self.create_application()
        self.io_loop = mock.Mock()

    def tearDown(self):
        super(SprocketsTracingTestCase, self).tearDown()
        opentracing.tracer = self.saved_tracer

    def create_application(self):
        return web.Application(
            [],
            opentracing={'propagation_syntax': 'zipkin'})
