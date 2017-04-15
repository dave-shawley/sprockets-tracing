import binascii
import os
try:
    from unittest import mock
except ImportError:
    import mock

from tornado import httputil
import opentracing

import sprocketstracing
import tests.helpers


class B3PropagationTests(tests.helpers.SprocketsTracingTestCase):

    def setUp(self):
        super(B3PropagationTests, self).setUp()
        self.application.settings['opentracing'] = {'propagation_syntax': 'b3'}
        sprocketstracing.install(self.application, self.io_loop)

    def tearDown(self):
        sprocketstracing.shutdown(self.application)
        super(B3PropagationTests, self).tearDown()

    @staticmethod
    def get_random_bits(bit_count):
        return binascii.hexlify(os.urandom(bit_count // 8)).lower()

    def test_that_all_headers_are_extracted(self):
        headers = httputil.HTTPHeaders()
        headers['X-B3-TraceId'] = self.get_random_bits(128)
        headers['X-B3-SpanId'] = self.get_random_bits(64)
        headers['X-B3-ParentSpanId'] = self.get_random_bits(64)
        headers['X-B3-Sampled'] = '1'

        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertEqual(context.trace_id, headers['X-B3-TraceId'])
        self.assertEqual(context.span_id, headers['X-B3-SpanId'])
        self.assertEqual(context.sampled, bool(int(headers['X-B3-Sampled'])))
        self.assertEqual(context.parents[0].span_id,
                         headers['X-B3-ParentSpanId'])

    def test_that_all_headers_are_injected(self):
        headers = httputil.HTTPHeaders()
        outer_span = opentracing.tracer.start_span('do-something')
        outer_span.context.sampled = True
        inner_span = opentracing.start_child_span(
            outer_span, 'doing-something')
        opentracing.tracer.inject(inner_span.context,
                                  opentracing.Format.HTTP_HEADERS,
                                  headers)
        self.assertEqual(headers['X-B3-TraceId'], inner_span.context.trace_id)
        self.assertEqual(headers['X-B3-SpanId'], inner_span.context.span_id)
        self.assertEqual(headers['X-B3-ParentSpanId'],
                         outer_span.context.span_id)
        self.assertEqual(headers['X-B3-Sampled'], '1')

    def test_that_extraction_of_minimal_headers_is_correct(self):
        headers = httputil.HTTPHeaders()
        headers['X-B3-TraceId'] = self.get_random_bits(128)
        headers['X-B3-SpanId'] = self.get_random_bits(64)

        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertEqual(context.trace_id, headers['X-B3-TraceId'])
        self.assertEqual(context.span_id, headers['X-B3-SpanId'])
        self.assertFalse(context.sampled)
        self.assertEqual(context.parents, [])

    def test_that_injection_of_minimal_context_as_headers_is_correct(self):
        headers = {}
        with opentracing.tracer.start_span('do-something') as span:
            opentracing.tracer.inject(span.context,
                                      opentracing.Format.HTTP_HEADERS, headers)
        self.assertEqual(headers['X-B3-TraceId'], span.context.trace_id)
        self.assertEqual(headers['X-B3-SpanId'], span.context.span_id)
        self.assertEqual(headers['X-B3-Sampled'], '0')
        self.assertNotIn('X-B3-ParentSpanId', headers)

    def test_that_injection_of_unknown_format_fails(self):
        span = opentracing.tracer.start_span('do-something')
        with self.assertRaises(opentracing.UnsupportedFormatException):
            opentracing.tracer.inject(span.context, 'whatever', {})

    def test_that_extraction_of_unknown_format_fails(self):
        with self.assertRaises(opentracing.UnsupportedFormatException):
            opentracing.tracer.extract('whatever', {})

    def test_that_extraction_of_empty_headers_is_empty_context(self):
        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, {})
        self.assertFalse(context)

    def test_that_debug_flag_forces_sample(self):
        headers = {'X-B3-Flags': '1', 'X-B3-Sampled': '0',
                   'X-B3-SpanId': self.get_random_bits(64),
                   'X-B3-TraceId': self.get_random_bits(64)}
        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertTrue(context.sampled)

        new_headers = {}
        opentracing.tracer.inject(context,
                                  opentracing.Format.HTTP_HEADERS,
                                  new_headers)
        self.assertEqual(new_headers, headers)

    def test_that_debug_flag_enables_sample(self):
        headers = {'X-B3-Flags': '1',
                   'X-B3-SpanId': self.get_random_bits(64),
                   'X-B3-TraceId': self.get_random_bits(64)}
        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertTrue(context.sampled)

        new_headers = {}
        opentracing.tracer.inject(context,
                                  opentracing.Format.HTTP_HEADERS,
                                  new_headers)
        self.assertEqual(new_headers, headers)

    def test_that_sampled_flag_enables_sample(self):
        headers = {'X-B3-Flags': '2',
                   'X-B3-SpanId': self.get_random_bits(64),
                   'X-B3-TraceId': self.get_random_bits(64)}
        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertTrue(context.sampled)

        new_headers = {}
        opentracing.tracer.inject(context,
                                  opentracing.Format.HTTP_HEADERS,
                                  new_headers)
        self.assertEqual(new_headers, headers)

    def test_that_root_flag_removes_parent(self):
        headers = {'X-B3-Flags': '8', 'X-B3-Sampled': '1',
                   'X-B3-SpanId': self.get_random_bits(64),
                   'X-B3-TraceId': self.get_random_bits(64),
                   'X-B3-ParentSpanId': self.get_random_bits(64)}
        context = opentracing.tracer.extract(
            opentracing.Format.HTTP_HEADERS, headers)
        self.assertTrue(context.sampled)

        del headers['X-B3-ParentSpanId']  # should not be propagated
        new_headers = {}
        opentracing.tracer.inject(context,
                                  opentracing.Format.HTTP_HEADERS,
                                  new_headers)
        self.assertEqual(new_headers, headers)
