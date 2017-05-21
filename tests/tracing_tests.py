from unittest import mock

import iso8601
import maya
import opentracing

from sprocketstracing import install, tracing
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


class SpanTests(tests.helpers.SprocketsTracingTestCase):

    def setUp(self):
        super(SpanTests, self).setUp()
        install(self.application, mock.Mock())

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
        opentracing.tracer.complete_span = mock.Mock()

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
        span.log_kv = mock.Mock()
        try:
            with span:
                raise exc
        except RuntimeError:
            pass

        span.log_kv.assert_called_once_with({
            'python.exception.type': exc.__class__,
            'python.exception.val': exc,
            'python.exception.tb': mock.ANY,
        })
