import opentracing


_propagation_syntaxes = {}


def get_syntax(name):
    """
    Retrieve a syntax by name.

    :param str name: name of the syntax to retrieve
    :rtype: PropagationSyntax

    """
    return _propagation_syntaxes.get(name, PropagationSyntax)()


def add_syntax(name, syntax_factory):
    """
    Add a new propagation syntax class.

    :param str name: name of the syntax to register
    :param syntax_factory: function to call to create syntax handler

    """
    _propagation_syntaxes[name] = syntax_factory


class PropagationSyntax(object):

    """
    Logic to get spans into and out of a `carrier`.

    Sub-class this class to implement a new way to pass contextual
    information between traced processes.  Then register it with
    :func:`~sprocketstracing.propagation.add_syntax` so that it is
    available to the application.  When a new request comes in, a
    propagation syntax handler is created and used to extract a new
    :class:`~sprocketstracing.tracing.SpanContext` instance from
    the carrier.  Similarly, spans are propagated in out-going
    requests using the :meth:`.inject` method instead.

    The key to injecting and extracting from a generic *carrier*
    object is the use of a format specifier.  The implementation
    is explicitly told how to interact with the carrier using the
    specifier.  The following specifiers are defined by the
    `opentracing standard <http://opentracing.io>`_:

    - :data:`opentracing.Format.BINARY`
    - :data:`opentracing.Format.TEXT_MAP`
    - :data:`opentracing.Format.HTTP_HEADERS`

    If you try to manipulate a *carrier* using an unsupported value,
    then the method will raise :exc:`opentracing.UnsupportedFormatException`.

    """

    def inject(self, span_context, format_, carrier):
        """
        Inject identifying characteristics of a context into a carrier.

        :param sprocketstracing.tracing.SpanContext span_context:
            the context to inject into `carrier`
        :param str format_: the format of the carrier.  This controls
            which operations are available for interacting with `carrier`.
        :param carrier: the object to inject the context's identifiers into.

        :raises: opentracing.UnsupportedFormatException

        The `format_` value is required to be a value from
        :class:`opentracing.Format` namespace.

        """
        raise opentracing.UnsupportedFormatException(
            '{} does not support {}'.format(self.__class__.__name__,
                                            format_))

    def extract(self, format_, carrier):
        """
        Extract a context from a carrier.

        :param str format_: the format of the carrier.  This controls which
            operations are called on the carrier.
        :param carrier: the object to extract the context's identifiers from.

        :raises: opentracing.UnsupportedFormatException

        The `format_` value is required to be a value from
        :class:`opentracing.Format` namespace.

        """
        raise opentracing.UnsupportedFormatException(
            '{} does not support {}'.format(self.__class__.__name__,
                                            format_))


class B3PropagationSyntax(PropagationSyntax):

    """
    Implements span propagation for `Zipkin <http://zipkin.io>`_.

    Currently only HTTP header propagation is supported.

    """

    def inject(self, span_context, format_, carrier):
        """
        Inject span details using Zipkin's mechanisms.

        :param sprocketstracing.tracing.SpanContext span_context:
            the context to inject into the carrier
        :param str format_: controls how the span is injected into
            the carrier.  More specifically, this tells us how to
            inject values into the carrier (e.g., using ``__setitem__``).
        :param carrier:  carrier instance to inject the span details into.

        See `HTTP Propagation <https://tinyurl.com/mfxqypm>`_ in the
        openzipkin documentation on how HTTP propagation is designed
        to work.

        """
        if format_ == opentracing.Format.HTTP_HEADERS:
            carrier['X-B3-TraceId'] = span_context.trace_id
            carrier['X-B3-SpanId'] = span_context.span_id
            if span_context.parents:
                carrier['X-B3-ParentSpanId'] = span_context.parents[0].span_id

            if span_context.baggage.get('sample-requested') is None:
                if span_context.baggage.get('flags') is None:
                    carrier['X-B3-Sampled'] = ('1' if span_context.sampled
                                               else '0')
            elif span_context.baggage['sample-requested']:
                carrier['X-B3-Sampled'] = '1'
            else:
                carrier['X-B3-Sampled'] = '0'

            if span_context.baggage.get('flags') is not None:
                carrier['X-B3-Flags'] = str(span_context.baggage['flags'])

        else:
            super(B3PropagationSyntax, self).inject(span_context, format_,
                                                    carrier)

    def extract(self, format_, carrier):
        """
        Extract Zipkin span details from a carrier.

        :param str format_: controls how to extract span details from
            the carrier.  More specifically, this tells us how to
            extract values into the carrier (e.g., using ``__getitem__``).
        :param carrier:  carrier instance to extract the span details from.
        :return: the span detail as a :class:`dict`.
        :rtype: dict

        See `HTTP Propagation <https://tinyurl.com/mfxqypm>`_ in the
        openzipkin documentation on how HTTP propagation is designed
        to work.

        """
        if format_ == opentracing.Format.HTTP_HEADERS:
            details = {}
            try:
                details['trace_id'] = carrier['X-B3-TraceId']
                details['span_id'] = carrier['X-B3-SpanId']
            except KeyError:
                return details

            details['baggage'] = {'sample-requested': None,
                                  'flags': None}
            if 'X-B3-ParentSpanId' in carrier:
                details['parents'] = [carrier['X-B3-ParentSpanId']]

            if 'X-B3-Sampled' in carrier:
                details['sampled'] = bool(int(carrier['X-B3-Sampled']))
                details['baggage']['sample-requested'] = details['sampled']

            if 'X-B3-Flags' in carrier:
                flags = int(carrier['X-B3-Flags'])
                details['baggage']['flags'] = flags
                if flags & (1 << 0):  # debug!
                    details['sampled'] = True
                if flags & (1 << 1):  # other way to spell X-B3-Sampled: 1
                    details['sampled'] = True
                if flags & (1 << 3):  # root span, ignore parent
                    details['parents'] = []

            return details
        else:
            super(B3PropagationSyntax, self).extract(format_, carrier)


add_syntax('b3', B3PropagationSyntax)
add_syntax('zipkin', B3PropagationSyntax)
