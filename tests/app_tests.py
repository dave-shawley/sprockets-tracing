try:
    from unittest import mock
except ImportError:
    import mock

from tornado import concurrent, testing, web
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


class ShutdownTests(testing.AsyncTestCase):

    def setUp(self):
        super(ShutdownTests, self).setUp()
        self.saved_tracer = opentracing.tracer

        self.application = web.Application([])

        sprocketstracing.install(self.application, self.io_loop)
        state = self.application.settings['opentracing']['state']

        self.stop_future = concurrent.Future()
        self.tracer = state['tracer']
        self.tracer.stop = mock.Mock(return_value=self.stop_future)

        self.flush_future = concurrent.Future()
        self.reporter = state['reporter']
        self.reporter.flush = mock.Mock(return_value=self.flush_future)

    def tearDown(self):
        super(ShutdownTests, self).tearDown()
        opentracing.tracer = self.saved_tracer

    def test_that_shutdown_stops_tracer(self):
        self.stop_future.set_result(None)
        self.flush_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.tracer.stop.assert_called_once_with()

    def test_that_shutdown_stops_tracer_without_reporter(self):
        del self.application.settings['opentracing']['state']['reporter']
        self.stop_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.tracer.stop.assert_called_once_with()

    def test_that_shutdown_flushes_reporter(self):
        self.stop_future.set_result(None)
        self.flush_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.reporter.flush.assert_called_once_with()

    def test_that_shutdown_flushes_reporter_when_tracer_fails(self):
        self.stop_future.set_exception(RuntimeError())
        self.flush_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.reporter.flush.assert_called_once_with()

    def test_that_shutdown_flushes_reporter_without_tracer(self):
        del self.application.settings['opentracing']['state']['tracer']
        self.flush_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.reporter.flush.assert_called_once_with()

    def test_that_shutdown_finishes_when_tracer_and_reporter_fail(self):
        self.stop_future.set_exception(RuntimeError())
        self.flush_future.set_exception(RuntimeError())

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()
        self.tracer.stop.assert_called_once_with()
        self.reporter.flush.assert_called_once_with()

    def test_that_shutdown_resets_opentracing_tracer(self):
        self.assertIs(opentracing.tracer, self.tracer)

        self.stop_future.set_result(None)
        self.flush_future.set_result(None)

        future = sprocketstracing.shutdown(self.application)
        self.io_loop.add_future(future, lambda _: self.io_loop.stop())
        self.io_loop.start()

        self.assertIsNot(opentracing.tracer, self.tracer)
        self.assertIs(self.application.opentracing, opentracing.tracer)

    def test_that_shutdown_runs_without_state(self):
        self.application.settings['opentracing'].pop('state')
        maybe_future = sprocketstracing.shutdown(self.application)
        self.assertIsNone(maybe_future)

    def test_that_shutdown_finishes_without_tracer_or_reporter(self):
        self.application.settings['opentracing']['state'].pop('reporter')
        self.application.settings['opentracing']['state'].pop('tracer')
        maybe_future = sprocketstracing.shutdown(self.application)
        self.assertIsNone(maybe_future)
