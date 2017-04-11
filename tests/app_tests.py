import unittest
try:
    from unittest import mock
except ImportError:
    import mock

from tornado import web
import opentracing

import sprocketstracing.reporting


class InstallationTests(unittest.TestCase):

    def setUp(self):
        super(InstallationTests, self).setUp()
        self.saved_tracer = opentracing.tracer
        self.application = web.Application([])
        self.io_loop = mock.Mock()

    def tearDown(self):
        super(InstallationTests, self).tearDown()
        opentracing.tracer = self.saved_tracer

    def test_that_opentracing_tracer_is_set(self):
        sprocketstracing.install(self.application, self.io_loop)
        self.assertIsNot(opentracing.tracer, self.saved_tracer)

    def test_that_opentracing_settings_are_passed_to_tracer(self):
        self.application.settings['opentracing'] = {'something': mock.sentinel}
        with mock.patch('sprocketstracing.tracing.Tracer') as tracer_cls:
            sprocketstracing.install(self.application, self.io_loop)
            tracer_cls.assert_called_once_with(
                mock.ANY, **self.application.settings['opentracing'])

    def test_that_opentracing_tracer_is_stored_on_application(self):
        sprocketstracing.install(self.application, self.io_loop)
        self.assertIs(self.application.opentracing, opentracing.tracer)

    def test_that_span_queue_is_created(self):
        with mock.patch('tornado.queues.Queue') as queue_cls:
            with mock.patch('sprocketstracing.tracing.Tracer') as tracer_cls:
                sprocketstracing.install(self.application, self.io_loop)
                queue_cls.assert_called_once_with()
                tracer_cls.assert_called_once_with(queue_cls.return_value)
