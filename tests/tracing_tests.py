import socket
import unittest.mock

from tornado import concurrent, gen, httputil, netutil, testing, web
import iso8601
import maya
import opentracing

from sprocketstracing import install, reporting, shutdown, tracing
import sprocketstracing.testing
import tests.helpers


class SpanContextTests(tests.helpers.SprocketsTracingTestCase):

    def test_that_new_context_is_not_valid(self):
        context = tracing.SpanContext()
        self.assertFalse(bool(context))

    def test_that_128bit_trace_id_is_generated(self):
        context = tracing.SpanContext()
        self.assertEqual(len(context.trace_id), (128 / 8) * 2)

    def test_that_64bit_span_id_is_generated(self):
        context = tracing.SpanContext()
        self.assertEqual(len(context.span_id), (64 / 8) * 2)

    def test_that_trace_id_can_be_specified(self):
        context = tracing.SpanContext(trace_id='some-random-value')
        self.assertEqual(context.trace_id, 'some-random-value')

    def test_that_span_id_can_be_specified(self):
        context = tracing.SpanContext(span_id='some-random-value')
        self.assertEqual(context.span_id, 'some-random-value')

    def test_that_context_is_valid_when_span_and_trace_are_set(self):
        self.assertFalse(bool(tracing.SpanContext(trace_id='t')))
        self.assertFalse(bool(tracing.SpanContext(span_id='s')))
        self.assertTrue(bool(tracing.SpanContext(trace_id='t', span_id='s')))

    def test_that_context_is_valid_when_it_has_parents(self):
        parent = tracing.SpanContext()
        self.assertTrue(bool(tracing.SpanContext(parents=[parent])))

    def test_that_context_defaults_to_not_sampled(self):
        self.assertFalse(tracing.SpanContext().sampled)

    def test_that_sampled_can_be_toggled(self):
        context = tracing.SpanContext()
        context.sampled = True
        self.assertTrue(context.sampled)

    def test_that_context_is_valid_when_sampling_is_enabled(self):
        context = tracing.SpanContext(sampled=True)
        self.assertTrue(bool(context))

    def test_that_sampled_propagates_to_children(self):
        parent = tracing.SpanContext(sampled=True)
        child = tracing.SpanContext(parents=[parent])
        self.assertTrue(child.sampled)

        grand_parent = tracing.SpanContext(sampled=True)
        parent = tracing.SpanContext(parents=[grand_parent])
        child = tracing.SpanContext(parents=[parent])
        self.assertTrue(child.sampled)

    def test_that_trace_id_is_fetched_from_first_parent(self):
        first_parent = tracing.SpanContext()
        other_parent = tracing.SpanContext()
        child = tracing.SpanContext(parents=[first_parent, other_parent])
        self.assertEqual(child.trace_id, first_parent.trace_id)

    def test_that_parents_are_immutable(self):
        parent = tracing.SpanContext(sampled=True)
        child = tracing.SpanContext(parents=[parent])
        del child.parents[:]
        self.assertEqual(child.parents, [parent])

    def test_that_parents_are_converted_to_span_contexts(self):
        context_parent = tracing.SpanContext()
        span_parent = tracing.Span('foo', tracing.SpanContext())
        str_parent = 'df4d1639094d4d1bbfc14b319f455e94'
        bytes_parent = b'fda52ed87bcc469791998ee6037bde41'
        child = tracing.SpanContext(parents=[context_parent, span_parent,
                                             str_parent, bytes_parent])
        for p in child.parents:
            self.assertIsInstance(p, tracing.SpanContext)

    def test_that_service_endpoint_is_inherited(self):
        grand_parent = tracing.SpanContext()
        grand_parent.service_endpoint = 'grandparent', 80
        parent = tracing.SpanContext(parents=[grand_parent])
        span = tracing.SpanContext(parents=[parent])

        self.assertEqual(span.service_endpoint, grand_parent.service_endpoint)

        parent.service_endpoint = 'parent', 80
        self.assertEqual(span.service_endpoint, parent.service_endpoint)

        span.service_endpoint = 'span', 80
        self.assertEqual(span.service_endpoint, ('span', 80))

    def test_that_service_name_is_inherited(self):
        grand_parent = tracing.SpanContext()
        grand_parent.service_name = 'grandparent'
        parent = tracing.SpanContext(parents=[grand_parent])
        span = tracing.SpanContext(parents=[parent])

        self.assertEqual(span.service_name, grand_parent.service_name)

        parent.service_name = 'parent'
        self.assertEqual(span.service_name, parent.service_name)

        span.service_name = 'span'
        self.assertEqual(span.service_name, 'span')

    def test_that_context_can_be_created_with_parent_span_id(self):
        context = tracing.SpanContext(parents=['12345', b'67890'])
        self.assertEqual(len(context.parents), 2)
        self.assertEqual(context.parents[0].span_id, '12345')
        self.assertEqual(context.parents[1].span_id, '67890')

    def test_that_creating_with_unacceptable_parent_type_fails(self):
        with self.assertRaises(ValueError):
            tracing.SpanContext(parents=[12345])

    def test_that_service_endpoint_is_none_when_unavailable(self):
        grand_parent = tracing.SpanContext()
        self.assertIsNone(grand_parent.service_endpoint)

        parent = tracing.SpanContext(parents=[grand_parent])
        self.assertIsNone(parent.service_endpoint)

        context = tracing.SpanContext(parents=[parent])
        self.assertIsNone(context.service_endpoint)

    def test_that_service_name_is_none_when_unavailable(self):
        grand_parent = tracing.SpanContext()
        self.assertIsNone(grand_parent.service_name)

        parent = tracing.SpanContext(parents=[grand_parent])
        self.assertIsNone(parent.service_name)

        context = tracing.SpanContext(parents=[parent])
        self.assertIsNone(context.service_name)


class SpanTests(tests.helpers.SprocketsTracingTestCase):

    def setUp(self):
        super(SpanTests, self).setUp()
        install(self.application, unittest.mock.Mock())

    def test_that_boolean_tags_are_preserved(self):
        with opentracing.tracer.start_span('operation') as span:
            span.set_tag('a bool', True)
            span.set_tag('another bool', False)

            self.assertIs(span.get_tag('a bool'), True)
            self.assertIs(span.get_tag('another bool'), False)

    def test_that_numeric_tags_are_preserved(self):
        with opentracing.tracer.start_span('operation') as span:
            span.set_tag('a float', 22.0 / 7.0)
            span.set_tag('an int', 42)

            self.assertAlmostEqual(span.get_tag('a float'), 22.0 / 7.0, 6)
            self.assertEqual(span.get_tag('an int'), 42)

    def test_that_string_tags_are_preserved(self):
        with opentracing.tracer.start_span('operation') as span:
            span.set_tag('s', 'tring')

            self.assertEqual(span.get_tag('s'), 'tring')

    def test_that_datetimes_are_isoformatted(self):
        now = maya.now()
        with opentracing.tracer.start_span('operation') as span:
            # first do a tzaware one
            span.set_tag('now', now.datetime())
            self.assertEqual(iso8601.parse_date(span.get_tag('now')),
                             now.datetime())

            # tz-naive values are assumed to be UTC
            span.set_tag('now', now.datetime(naive=True))
            self.assertEqual(
                span.get_tag('now'),
                now.datetime(naive=True).strftime(
                    '%Y-%m-%dT%H:%M:%S.%f+00:00'))

    def test_that_finished_spans_are_not_finished_twice(self):
        span = opentracing.tracer.start_span('operation')
        opentracing.tracer.complete_span = unittest.mock.Mock()

        span.finish()
        opentracing.tracer.complete_span.assert_called_once_with(span)
        span.finish()
        opentracing.tracer.complete_span.assert_called_once_with(span)

    def test_that_duration_is_not_set_until_finished(self):
        span = opentracing.tracer.start_span('operation')
        self.assertIsNone(span.duration)

        span.finish()
        self.assertIsNotNone(span.duration)

    def test_that_exception_is_logged_if_span_finishes_with_exception(self):
        exc = RuntimeError()
        span = opentracing.tracer.start_span('operation')
        span.log_kv = unittest.mock.Mock()
        try:
            with span:
                raise exc
        except RuntimeError:
            pass

        span.log_kv.assert_called_once_with({
            'python.exception.type': exc.__class__,
            'python.exception.val': exc,
            'python.exception.tb': unittest.mock.ANY,
        })


class TracerTests(tests.helpers.SprocketsTracingTestCase):

    def test_that_kwargs_are_passed_through_to_new_span(self):
        tracer = tracing.Tracer(unittest.mock.Mock())
        with unittest.mock.patch('sprocketstracing.tracing.Span') as SpanClass:
            span = tracer.start_span('operation_name', what='ever')
            SpanClass.assert_called_once_with(
                'operation_name', unittest.mock.ANY, what='ever')
            self.assertIs(span, SpanClass.return_value)

            SpanClass.reset_mock()
            span = tracer.start_span('operation_name',
                                     child_of=tracing.SpanContext(),
                                     what='ever')
            SpanClass.assert_called_once_with(
                'operation_name', unittest.mock.ANY, what='ever')
            self.assertIs(span, SpanClass.return_value)

    def test_that_stop_returns_none_when_called_second_time(self):
        span_queue = unittest.mock.Mock()
        tracer = tracing.Tracer(span_queue)
        future = tracer.stop()
        self.assertIs(future, span_queue.join.return_value)
        self.assertIsNone(tracer.stop())
        span_queue.join.assert_called_once_with()


class RequestHandler(tracing.RequestHandlerMixin, web.RequestHandler):

    @gen.coroutine
    def prepare(self):
        if self.get_query_argument('no-operation-name', None) is None:
            self.tracing_operation = 'running-test'
        yield super(RequestHandler, self).prepare()
        if self.get_query_argument('force-sample', None) is not None:
            self.request_is_traced = True

    def get(self):
        self.set_status(204)


class TracingMixinTests(testing.AsyncHTTPTestCase):

    @classmethod
    def setUpClass(cls):
        super(TracingMixinTests, cls).setUpClass()
        reporting.add_reporter('recorder',
                               sprocketstracing.testing.RecordingReporter)

    def setUp(self):
        self.application = None
        super(TracingMixinTests, self).setUp()
        ipv4_port, ipv6_port = None, None
        for sock in self.http_server._sockets.values():
            if sock.family == socket.AF_INET:
                _, ipv4_port = sock.getsockname()
            if sock.family == socket.AF_INET6:
                _, ipv6_port = sock.getsockname()

        if not ipv4_port and not ipv6_port:  # should never happen
            pass
        elif not ipv4_port:
            sock = netutil.bind_sockets(ipv6_port, '127.0.0.1',
                                        family=socket.AF_INET)[0]
            self.http_server.add_sockets([sock])
        elif not ipv6_port and socket.has_ipv6:
            sock = netutil.bind_sockets(ipv4_port, '::1',
                                        family=socket.AF_INET6)[0]
            self.http_server.add_sockets([sock])

    def tearDown(self):
        coro = shutdown(self.application)
        self.io_loop.add_future(coro, self.stop)
        self.wait()
        super(TracingMixinTests, self).tearDown()

    def get_app(self):
        settings = {'propagation_syntax': 'b3',
                    'report_format': 'recorder',
                    'service_name': 'test-service'}
        self.application = web.Application([web.url(r'/', RequestHandler)],
                                           opentracing=settings, debug=True)
        install(self.application, self.io_loop)
        return self.application

    @property
    def captured_spans(self):
        r = self.application.settings['opentracing']['state']['reporter']
        return r.captured_spans

    def test_that_span_recorded_when_tracing_headers_present(self):
        span = opentracing.tracer.start_span('outer-operation')
        self.fetch('/', headers={'X-B3-TraceId': span.context.trace_id,
                                 'X-B3-SpanId': span.context.span_id,
                                 'X-B3-Sampled': '1'})
        self.assertEqual(len(self.captured_spans), 1)
        self.assertEqual(self.captured_spans[0].context.trace_id,
                         span.context.trace_id)
        self.assertEqual(self.captured_spans[0].context.parents[0].span_id,
                         span.context.span_id)
        self.assertNotEqual(self.captured_spans[0].context.span_id,
                            span.context.span_id)

    def test_that_user_agent_included_in_span(self):
        span = opentracing.tracer.start_span('outer-operation')
        self.fetch('/', headers={'X-B3-TraceId': span.context.trace_id,
                                 'X-B3-SpanId': span.context.span_id,
                                 'X-B3-Sampled': '1',
                                 'User-Agent': 'tests'})
        self.assertEqual(len(self.captured_spans), 1)
        self.assertEqual(self.captured_spans[0].get_tag('http.user_agent'),
                         'tests')

    def test_that_span_not_recorded_without_operation_name(self):
        self.fetch('/?no-operation-name')
        self.assertEqual(self.captured_spans, [])

    def test_that_unknown_propagation_syntax_ignores_span(self):
        opentracing.tracer.propagation_syntax = 'nothing-valid'
        response = self.fetch('/')
        self.assertEqual(response.code, 204)
        self.assertEqual(len(self.captured_spans), 0)

    def test_that_ipv4_literals_are_reported(self):
        self.http_client.fetch(
            'http://127.0.0.1:{}/?force-sample'.format(self.get_http_port()),
            self.stop)
        response = self.wait()
        self.assertEqual(response.code, 204)
        self.assertEqual(len(self.captured_spans), 1)
        self.assertEqual(self.captured_spans[0].context.service_endpoint,
                         ('127.0.0.1', self.get_http_port()))

    @unittest.skipUnless(socket.has_ipv6, 'IPv6 is not supported')
    def test_that_ipv6_literals_are_reported(self):
        self.http_client.fetch(
            'http://[::1]:{}/?force-sample'.format(self.get_http_port()),
            self.stop)
        response = self.wait()
        self.assertEqual(response.code, 204)
        self.assertEqual(len(self.captured_spans), 1)
        self.assertEqual(self.captured_spans[0].context.service_endpoint,
                         ('::1', self.get_http_port()))

    def test_that_service_port_uses_scheme_when_not_set(self):
        connection = unittest.mock.Mock()
        connection.context.remote_ip = '127.0.0.1'

        def run_prepare(host):
            request = httputil.HTTPServerRequest(
                method='GET', uri='/', host=host, connection=connection)
            handler = tracing.RequestHandlerMixin(self.application, request)
            handler.tracing_operation = 'some-operation'
            maybe_future = handler.prepare()
            if concurrent.is_future(maybe_future):
                self.io_loop.add_future(maybe_future, self.stop)
                self.wait()
            return handler

        connection.context.protocol = 'http'
        handler = run_prepare('127.0.0.1')
        self.assertEqual(handler.span.context.service_endpoint[1], 80)

        connection.context.protocol = 'https'
        handler = run_prepare('127.0.0.1')
        self.assertEqual(handler.span.context.service_endpoint[1], 443)

        handler = run_prepare('[::1]')
        self.assertEqual(handler.span.context.service_endpoint[1], 443)

        connection.context.protocol = None  # should never happen
        handler = run_prepare('127.0.0.1')
        self.assertEqual(handler.span.context.service_endpoint[1], 80)
