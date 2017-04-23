import unittest
try:
    from unittest import mock
except ImportError:
    import mock

from tornado import web
import opentracing

import sprocketstracing.reporting
import tests.helpers


class InstallationTests(tests.helpers.SprocketsTracingTestCase):

    def setUp(self):
        super(InstallationTests, self).setUp()
        self.settings = {'something': mock.sentinel}
        self.application.settings['opentracing'] = self.settings.copy()

    def test_that_opentracing_tracer_is_set(self):
        sprocketstracing.install(self.application, self.io_loop)
        self.assertIsNot(opentracing.tracer, self.saved_tracer)

    def test_that_opentracing_settings_are_passed_to_tracer(self):
        with mock.patch('sprocketstracing.tracing.Tracer') as tracer_cls:
            sprocketstracing.install(self.application, self.io_loop)
            tracer_cls.assert_called_once_with(mock.ANY, **self.settings)

    def test_that_opentracing_tracer_is_stored_on_application(self):
        sprocketstracing.install(self.application, self.io_loop)
        self.assertIs(self.application.opentracing, opentracing.tracer)

    def test_that_span_queue_is_created(self):
        with mock.patch('tornado.queues.Queue') as queue_cls:
            with mock.patch('sprocketstracing.tracing.Tracer') as tracer_cls:
                sprocketstracing.install(self.application, self.io_loop)
                queue_cls.assert_called_once_with()
                tracer_cls.assert_called_once_with(
                    queue_cls.return_value, **self.settings)

    def test_that_reporter_is_launched(self):
        with mock.patch('tornado.queues.Queue') as queue_cls:
            with mock.patch('sprocketstracing.reporting') as reporting_module:
                sprocketstracing.install(self.application, self.io_loop)
                self.io_loop.spawn_callback.assert_called_once_with(
                    sprocketstracing.reporting.report_spans,
                    reporting_module.get_reporter.return_value,
                    queue_cls.return_value)

    def test_that_opentracing_settings_are_passed_to_reporter(self):
        with mock.patch('sprocketstracing.reporting') as reporting_module:
            sprocketstracing.install(self.application, self.io_loop)
            reporting_module.get_reporter.assert_called_once_with(
                **self.settings)


class ShutdownTests(unittest.TestCase):

    def setUp(self):
        super(ShutdownTests, self).setUp()
        self.saved_tracer = opentracing.tracer
        self.application = web.Application(
            [], opentracing={'propagation_syntax': 'zipkin'})
        self.io_loop = mock.Mock()

    def tearDown(self):
        super(ShutdownTests, self).tearDown()
        opentracing.tracer = self.saved_tracer

    def test_that_shutdown_stops_tracer(self):
        tracer = mock.Mock()
        opentracing.tracer = tracer
        sprocketstracing.shutdown(self.application)
        tracer.stop.assert_called_once_with()

    def test_that_shutdown_returns_future_from_stop(self):
        tracer = mock.Mock()
        opentracing.tracer = tracer
        result = sprocketstracing.shutdown(self.application)
        self.assertIs(result, tracer.stop.return_value)

    def test_that_shutdown_resets_opentracing_tracer(self):
        sprocketstracing.install(self.application, self.io_loop)
        tracer = opentracing.tracer

        sprocketstracing.shutdown(self.application)
        self.assertIsNot(opentracing.tracer, tracer)
        self.assertIs(self.application.opentracing, opentracing.tracer)
