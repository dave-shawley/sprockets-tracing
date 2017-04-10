from tornado import web


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
        self._baggage = {}

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
        pass

    @property
    def context(self):
        """
        Retrieve the immutable context associated with this span.

        :rtype: SpanContext

        """
        return None

    def set_operation_name(self, new_name):
        """
        Overwrite the operation name passed in during construction.

        :param str new_name: the name to report this span as.

        """

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

    def __init__(self, span_queue):
        pass

    def start_span(self, operation_name, start_time=None, child_of=None):
        """
        Create a new span for an operation.

        :param str operation_name: the name to report the new span as.
            The span's name can be changed by calling the
            :meth:`~Span.set_operation_name` method on the new span.
        :param float start_time: optional number of seconds since the
            Epoch that this span started at.  If this parameter is omitted,
            then the current time is used.
        :param SpanContext child_of: explicitly name the parent span's
            context.
        :returns: a newly created :class:`.Span` that has already been
            started.
        :rtype: Span

        This is the preferred mechanism for creating new :class:`.Span`
        instances.

        """

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
        pass

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
        pass
