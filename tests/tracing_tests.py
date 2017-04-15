from sprocketstracing import tracing
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
