import binascii
import os

from tornado import web
import opentracing

import sprocketstracing.propagation


class RequestHandlerMixin(web.RequestHandler):

    """
    Mix-in to enable tracing of a request handler.

    .. attribute:: opentracing_options

       A :class:`dict` containing options that are passed to the
       :class:`~sprocketstracing.tracing.Span` instance created
       for each request.

    """

    def __init__(self, *args, **kwargs):
        super(RequestHandlerMixin, self).__init__(*args, **kwargs)
        if not hasattr(self, 'opentracing_options'):
            self.opentracing_options = {}


class SpanContext(object):

    """
    Identifies a specific span.

    :keyword str trace_id: optional trace identifier
    :keyword str span_id: optional span identifier
    :keyword bool sampled: should this span be sampled?
    :keyword list parents: optional list of parent spans.  List elements
        will be converted into :class:`.SpanContext` elements.

    Instances of this class contain the information to identify a
    :class:`.Span` in an immutable way.  They are used to form references
    to other spans whether you have access to the :class:`.Span` instance
    or not.  For example, a ``SpanContext`` instance can be extracted
    from the HTTP headers on a request without having a :class:`.Span`
    instance at all.

    The span context is also responsible for storing state that is
    propagated to all descendant spans.  Implementation-defined state
    is established using keyword parameters during construction.  The
    user-specified "baggage" is available by iterating over the context
    object itself (e.g., ``for name, value in context:``).

    This class implements the ``SpanContext`` concept described in
    the Open Tracing API [#]_ .

    .. [#]  https://github.com/opentracing/specification/blob/1.1/specification.md#spancontext

    """

    def __init__(self, **kwargs):
        super(SpanContext, self).__init__()
        self._trace_id = kwargs.get('trace_id')
        self._span_id = kwargs.get('span_id')
        self._sampled = kwargs.get('sampled')
        self._baggage = kwargs.get('baggage', {})
        self._parents = []
        for parent in kwargs.get('parents', []):
            if isinstance(parent, SpanContext):
                self._parents.append(parent)
            elif isinstance(parent, Span):
                self._parents.append(parent.context)
            elif isinstance(parent, (bytes, str)):
                self._parents.append(SpanContext(span_id=parent))

    @property
    def trace_id(self):
        """
        Unique identifier for this trace.

        The trace ID is a opaque value that identifies this trace
        across process boundaries.  If a trace ID is not explicitly
        set, then this implementation will generate a random 128-bit
        value and return it as a string of lower-cased hexadecimal
        digits.

        """
        if self._trace_id is None:
            if self.parents:
                self._trace_id = self.parents[0].trace_id
            else:
                self._trace_id = binascii.hexlify(os.urandom(16))
        return self._trace_id

    @property
    def span_id(self):
        """
        Unique identifier for this span.

        The span ID is a opaque value that uniquely identifies this
        span within the parent span.  If a span ID is not explicitly
        set, then this implementation will generate a random 64-bit
        value and return it as a string of lower-cased hexadecimal
        digits.

        """
        if self._span_id is None:
            self._span_id = binascii.hexlify(os.urandom(8))
        return self._span_id

    @property
    def parents(self):
        """
        Parents of this span.

        This :class:`list` contains the :class:`.SpanContext` instances
        that represent the parent spans.

        """
        return self._parents[:]

    @property
    def sampled(self):
        """Should this span be sampled?"""
        if self._sampled is None:
            for parent in self.parents:
                if parent.sampled:
                    return True
        return bool(self._sampled)

    @sampled.setter
    def sampled(self, on_or_off):
        self._sampled = on_or_off

    @property
    def baggage(self):
        return self._baggage.copy()

    def __bool__(self):
        """Is this context valid?"""
        return (self.sampled or len(self.parents) > 0 or
                (self._trace_id is not None and self._span_id is not None))

    def __iter__(self):
        """Iterate over the user-specified baggage items."""
        return iter(self._baggage.items())


class Span(object):

    """
    A node in the trace graph.

    A ``Span`` is a node in the directed, acyclic graph that represents
    a single trace.  It is a single unit of work in the trace and is
    connected to other spans via relationships recorded in the span's
    context.

    Spans are created by calling :meth:`.Tracer.start_span` and completed
    by a call to :meth:`.finish`.  You should use a span as a context
    manager if possible since it ensures that ``finish`` is always called.

    :param str span_name: the name to report this span as.  You can change
        the name of the span by calling :meth:`set_operation_name`.
    :param SpanContext context: the context associated with this span.
    :keyword float start_time: optional number of seconds since the Epoch
        that this span started at.  If omitted, the current time is used.

    """

    def __init__(self, span_name, context, **kwargs):
        super(Span, self).__init__()
        self.operation_name = span_name
        self._context = context

    @property
    def context(self):
        """
        Retrieve the immutable context associated with this span.

        :rtype: SpanContext

        """
        return self._context

    @property
    def tracer(self):
        """
        Returns the tracer that created this span.

        :rtype: .Tracer
        """
        return opentracing.tracer

    def set_operation_name(self, new_name):
        """
        Overwrite the operation name passed in during construction.

        :param str new_name: the name to report this span as.

        """

    def log_kv(self, log_values):
        pass

    def finish(self, end_time=None):
        """
        Mark this span as finished.

        :param float end_time: the number of seconds since the
            Epoch that this span completed at.  If not specified
            then the current time is used.

        Calls to this method are ignored after the first call.  Note
        that calling any method after ``finish`` has undefined results.

        """

    def set_tag(self, tag, value):
        """
        Set the value associated with `tag` on this span.

        :param str tag: name of the tag to set.
        :param value: value to store at `tag`.  The value is
            coerced to a :class:`str` before saving it.

        This implementation will retain the value from the *last*
        call to ``set_tag`` if it is called multiple times with the
        same `tag`.

        """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.log_kv({'python.exception.type': exc_type,
                         'python.exception.val': exc_val,
                         'python.exception.tb': exc_tb})
        self.finish()

    # Non-standard properties & methods
    @property
    def sampled(self):
        """Is sampling enabled for this span?"""
        return self.context.sampled

    @sampled.setter
    def sampled(self, on_or_off):
        """Manipulate the context's sampled property."""
        self.context.sampled = on_or_off


class Tracer(object):

    """
    Primary entrypoint into the opentracing API.

    A single instance of this class is created and installed by
    calling the :func:`~sprocketstracing.install` function.  Afterwards,
    it *SHOULD* be accessed as :data:`opentracing.tracer` as described
    in the Open Tracing API [#]_.  In a Tornado application, it *MAY*
    be accessed using the ``opentracing`` attribute of the application
    instance.

    :param tornado.queues.Queue span_queue:

    .. [#] https://github.com/opentracing/opentracing-python/blob/1.2.2/opentracing/__init__.py#L34-L37

    """

    def __init__(self, span_queue, **kwargs):
        self.propagation_syntax = kwargs['propagation_syntax']

    def start_span(self, operation_name, **kwargs):
        """
        Create a new span for an operation.

        :param str operation_name: the name to report the new span as.
            The span's name can be changed by calling the
            :meth:`~Span.set_operation_name` method on the new span.
        :keyword float start_time: optional number of seconds since the
            Epoch that this span started at.  If this parameter is omitted,
            then the current time is used.
        :keyword SpanContext child_of: explicitly name the parent span's
            context.
        :returns: a newly created :class:`.Span` that has already been
            started.
        :rtype: Span

        This is the preferred mechanism for creating new :class:`.Span`
        instances.

        """
        if kwargs.get('child_of'):
            context = SpanContext(parents=[kwargs.pop('child_of')])
        else:
            context = SpanContext()
        return Span(operation_name, context, **kwargs)

    def inject(self, span_context, format_, carrier):
        """
        Inject `span_context` into a context carrier using a format.

        :param SpanContext span_context: the context to inject
        :param str format_: format to inject the context identifiers
            into the carrier with.  This identifies the operations
            performed on the carrier as well.
        :param carrier: object to insert context identifiers into.

        The `format_` parameter determines what operations are used
        to insert span identifiers into the `carrier`.

        """
        propagator = sprocketstracing.propagation.get_syntax(
            self.propagation_syntax)
        propagator.inject(span_context, format_, carrier)

    def extract(self, format_, carrier):
        """
        Extract a span context from a carrier.

        :param str format_: format to extract the context identifiers
            from the carrier with.  This identifies the operations
            performed on the carrier as well.
        :param carrier: object to extract context identifiers from.
        :returns: a new :class:`.SpanContext` instance or :data:`None`
            if no information is found in *carrier*
        :rtype: SpanContext

        """
        propagator = sprocketstracing.propagation.get_syntax(
            self.propagation_syntax)
        kwargs = propagator.extract(format_, carrier)
        return SpanContext(**kwargs)

    def stop(self):
        """
        Terminate the tracer and reporting layer,

        This method disables future traces from being started, starts
        the reporting shutdown process which is asynchronous, and returns
        a :class:`~tornado.concurrent.Future` that will resolve when the
        reporter has finished processing the span queue.

        :returns: :class:`~tornado.concurrent.Future` that blocks until
            the span queue has been completely consumed.
        :rtype: tornado.concurrent.Future

        """
