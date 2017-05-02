import binascii
import logging
import os
import time

from tornado import concurrent, gen, httputil, web
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
        # NB - these needs to be set BEFORE calling super.__init__ since
        # super.__init__ will call set_default_headers() amnd initialize()
        self.span = None
        self.opentracing_options = {}
        self.__operation_name = None
        super(RequestHandlerMixin, self).__init__(*args, **kwargs)

    @gen.coroutine
    def prepare(self):
        maybe_future = super(RequestHandlerMixin, self).prepare()
        if concurrent.is_future(maybe_future):
            yield maybe_future

        logger = logging.getLogger('sprocketstracing.RequestHandlerMixin')
        if self.__operation_name is None:
            logger.warning('no operation name, tracing disabled. '
                           'Did you forget to set tracing_operation?')
            self.span = None
            raise gen.Return()

        try:
            parent_context = opentracing.tracer.extract(
                opentracing.Format.HTTP_HEADERS, self.request.headers)

        except opentracing.UnsupportedFormatException as exc:
            logger.warning('failed to extract context - %r', exc)

        else:
            opts = self.opentracing_options.copy()
            opts['operation_name'] = self.__operation_name
            opts['start_time'] = time.time()
            if parent_context:
                opts['child_of'] = parent_context
            opts.setdefault('tags', {})
            opts['tags'].update({
                'span.kind': 'server',
                'http.method': self.request.method,
                'http.url': '{}://{}{}'.format(self.request.protocol,
                                               self.request.host,
                                               self.request.uri),
                'http.version': self.request.version,
                'peer.address': self.request.remote_ip,
            })
            self.span = opentracing.tracer.start_span(**opts)
            self.span.context.service_name = \
                self.application.settings['opentracing']['service_name']

            port = None
            if self.request.host.startswith('['):  # IPv6 literal
                idx = self.request.host.find(']')
                addr = self.request.host[1:idx]
                if self.request.host[idx + 1:].startswith(':'):
                    port = self.request.host[idx + 2:]
            else:
                addr, _, port = self.request.host.rpartition(':')

            if port:
                port = int(port)
            elif self.request.protocol == 'http':
                port = 80
            elif self.request.protocol == 'https':
                port = 443
            self.span.context.service_endpoint = addr, port

            self.__set_tracing_headers()

    @property
    def tracing_operation(self):
        """
        Retrieve the name of this operation in the tracing system.

        :rtype: str

        """
        return self.__operation_name

    @tracing_operation.setter
    def tracing_operation(self, operation_name):
        """
        Set the name for this operation.

        :param str operation_name: the name of the operation to report
            to the tracing system.

        This method MUST be called BEFORE calling ``super.prepare`` in
        your implementation of :meth:`tornado.web.RequestHandler.prepare`.

        """
        self.__operation_name = operation_name

    def on_finish(self):
        if self.span:
            self.span.set_tag('http.status_code', self.get_status())
            self.span.finish(end_time=time.time())
        super(RequestHandlerMixin, self).on_finish()

    def set_default_headers(self):  # called during __init__ and on error
        super(RequestHandlerMixin, self).set_default_headers()
        self.__set_tracing_headers()

    def __set_tracing_headers(self):
        if self.span:
            headers = httputil.HTTPHeaders()
            opentracing.tracer.inject(self.span.context,
                                      opentracing.Format.HTTP_HEADERS,
                                      headers)
            for name, value in headers.items():
                self.set_header(name, value)


class SpanContext(object):

    """
    Identifies a specific span.

    :keyword str trace_id: optional trace identifier
    :keyword str span_id: optional span identifier
    :keyword bool sampled: should this span be sampled?
    :keyword list parents: optional list of parent spans.  List elements
        will be converted into :class:`.SpanContext` elements.
    :keyword str service_name: optional name of the service that
        this span will be reported as.
    :keyword tuple service_endpoint: host and port number that this
        span was started by.

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

    The two attributes that break the "immutability" aspect of a context
    are the :attr:`.service_name` and :attr:`.service_endpoint`.  Both
    are settable as keyword parameters however the
    :meth:`opentracing.Tracer.start_span` method used to start the root
    span does not allow for arbitrary keywords to be passed on to the
    context.  Thus, the only option is to start the span and then set
    the service name and endpoint after the fact.

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
        self._service_name = kwargs.get('service_name')
        self._service_endpoint = kwargs.get('service_endpoint')
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

    # Non-standard methods

    def __repr__(self):
        return '<%s trace_id=%r span_id=%r sampled=%r>' % (
            self.__class__.__name__, self.trace_id, self.span_id,
            self.sampled)

    def __bool__(self):
        """Is this context valid?"""
        return (self.sampled or len(self.parents) > 0 or
                (self._trace_id is not None and self._span_id is not None))

    @property
    def service_endpoint(self):
        """
        The endpoint associated with this span.

        :return: the endpoint as a :class:`tuple` of address and port
            number.
        :rtype: tuple

        The address portion of the endpoint can be a host name or
        anything that is understood by the :mod:`ipaddress` module.
        The service endpoint is inherited by child spans and *SHOULD
        NOT* be modified on anything other than the root span since
        all spans share the same endpoint.

        """
        if self._service_endpoint:
            return self._service_endpoint
        for parent in self.parents:
            if parent._service_endpoint:
                return parent._service_endpoint
        for parent in self.parents:
            endpoint = parent.service_endpoint
            if endpoint:
                return endpoint

    @service_endpoint.setter
    def service_endpoint(self, new_value):
        self._service_endpoint = tuple(new_value)

    @property
    def service_name(self):
        """
        The name of the service associated with this span.

        :return: the name of the service
        :rtype: str

        Similar to :attr:`service_endpoint`, this attribute is
        inherited by child spans.  It *SHOULD NOT* be modified on a
        child span since that would break the immutability aspect of
        a span and the identity of a service does not change over
        the course of request processing.

        """
        if self._service_name:
            return self._service_name
        for parent in self.parents:
            if parent._service_name:
                return parent._service_name
        for parent in self.parents:
            name = parent.service_name
            if name:
                return name

    @service_name.setter
    def service_name(self, new_value):
        self._service_name = new_value


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
        self._start_time = kwargs.get('start_time') or time.time()
        self._end_time = None
        self._tags = kwargs.get('tags', {})

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
        if self._end_time is None:
            self._end_time = end_time or time.time()
            self.tracer.complete_span(self)

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
        self._tags[tag] = value

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

    @property
    def start_time(self):
        """Return the second since the Epoch at which this span started."""
        return self._start_time

    @property
    def duration(self):
        """Return the duration of this span from start to finish."""
        if self._end_time:
            return self._end_time - self._start_time
        return None

    def get_tag(self, key, default=None):
        """
        Retrieve the value for the specified tag.

        :param str key: key of the tag to retrieve
        :param default: value to return if tag is not set
        :return: the tag's value

        """
        return self._tags.get(key, default)

    def tags(self):
        """
        Return an iterator over tag items.

        :return: iterator that yields tag key + value pairs

        """
        return iter(self._tags.items())

    def __repr__(self):
        return '<%s %s trace_id=%r span_id=%r start_time=%r sampled=%r>' % (
            self.__class__.__name__, self.operation_name,
            self.context.trace_id, self.context.span_id,
            self.start_time, self.context.sampled)


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
        self.logger = logging.getLogger('sprocketstracing.Tracer')
        self.propagation_syntax = kwargs.get('propagation_syntax', 'none')
        self.span_queue = span_queue

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

    # Non-standard methods

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
        if self.span_queue is not None:
            self.logger.info('joining span queue')
            span_queue, self.span_queue = self.span_queue, None
            return span_queue.join()
        self.logger.warning('span queue is None, is a shutdown already '
                            'in progress?')

    def complete_span(self, span):
        """
        Called when a span is finished.

        :param .Span span: the span that has completed

        This is where we pass the completed span off to the running
        reporter so that it can be reported upstream.

        """
        if self.span_queue is not None:
            self.span_queue.put_nowait(span)
