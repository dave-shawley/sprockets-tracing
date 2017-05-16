import ipaddress
import json
import logging
import socket
import urllib.parse

from tornado import gen, httpclient


_reporter_factories = {}


@gen.coroutine
def report_spans(reporter, span_queue):
    """
    Report spans out-of-band.

    :param reporter: the reporter to use
    :param tornado.queues.Queue span_queue: queue to consume spans from.

    This co-routine consumes spans from the `span_queue` and reports them
    to the aggregation endpoint.

    """
    logger = logging.getLogger('sprocketstracing.report_spans')
    logger.info('reporting spans using %s', reporter)
    while True:
        try:
            span = yield span_queue.get()
        except Exception as exc:
            try:
                yield reporter.flush()
            except Exception:
                logger.exception('reporter %r failed to flush during shutdown',
                                 reporter)
            raise exc

        try:
            if span.start_time:
                yield reporter.process_span(span)
            else:
                logger.error('refusing to submit span without '
                             'start time - %r', span)
        finally:
            span_queue.task_done()


def get_reporter(*args, **kwargs):
    """
    Create a reporter instance.

    :param str report_format: name that the reporter type was registered
        with when calling :func:`.add_reporter`.
    :param args: positional parameters to pass to the reporter factory.
    :param kwargs: keyword parameterws to pass to the reporter factory.
    :return: a new reporter instance.
    :rtype: NullReporter

    """
    factory = _reporter_factories[kwargs.get('report_format', 'null')]
    return factory(*args, **kwargs)


def add_reporter(name, reporter_factory):
    """
    Add a new reporter.

    :param str name: name to register the reporter with
    :param reporter_factory: function to create a new reporter instance
        with.  This will be called by :func:`.get_reporter` with any
        additional parameters.

    """
    _reporter_factories[name] = reporter_factory


class NullReporter(object):

    """
    Reporter that doesn't report.

    This is the default reporter class installed as the *null* factory.
    It implements the reporting interface and does absolutely nothing
    with the reported spans.

    """

    def __init__(self, *args, **kwargs):
        super(NullReporter, self).__init__()

    @gen.coroutine
    def process_span(self, span):
        """
        Report `span` to the tracing aggregator.

        :param sprocketstracing.tracing.Span span: the span to report

        """

    @gen.coroutine
    def flush(self):
        """
        Flush any outstanding messages.

        This is called before termination and is the last chance the
        the reporter gets to take action before being shutdown.

        """


class ZipkinReporter(NullReporter):

    """
    Report spans to a `Zipkin <http://zipkin.io>`_ compatible backend.

    :keyword str service_name: the name of the service to report as
    :keyword str report_target: the root URL of the
        `Zipkin API <http://zipkin.io/zipkin-api/#/>`_ to submit traces to.
    :keyword dict client_options: additional keyword parameters to pass
        to the HTTP client when it is created.

    """

    def __init__(self, *args, **kwargs):
        super(ZipkinReporter, self).__init__()
        self.logger = logging.getLogger('sprocketstracing.ZipkinReporter')
        self.service_name = kwargs['service_name']
        report_target = kwargs.get('report_target',
                                   'http://127.0.0.1:9411/api/v1')
        if not report_target.endswith('/'):
            report_target += '/'
        self.report_url = urllib.parse.urljoin(report_target, 'spans')
        self.json_encoder = json.JSONEncoder(default=jsonify)
        self._client = None
        self._client_options = kwargs.get('client_options', {})
        self._client_options.setdefault('force_instance', True)

    @property
    def http_client(self):
        """
        Lazily created HTTP client.

        :rtype: tornado.httpclient.AsyncHTTPClient

        """
        if self._client is None:
            self._client = httpclient.AsyncHTTPClient(**self._client_options)
        return self._client

    @gen.coroutine
    def process_span(self, span):
        """
        Transform a span into a Zipkin-ready payload.

        :param sprocketstracing.tracer.Span span: the span to process.

        This method generates the Zipkin payload for the span and sends
        it to the Zipkin API endpoint.

        """
        payload = self._generate_zipkin_span(span)
        if payload:
            self.logger.debug('submitting span %r', span)
            request = httpclient.HTTPRequest(self.report_url, method='POST')
            request.headers['Content-Type'] = 'application/json; charset=UTF8'
            request.body = self.json_encoder.encode([payload]).encode('utf-8')
            self.logger.debug('submitting trace %r', request.body)
            response = yield self.http_client.fetch(request, raise_error=False)
            if response.code >= 400:
                self.logger.error('failed to submit span %r - %r',
                                  span, response)

    def _generate_zipkin_span(self, span):
        """
        Translate an :class:`opentracing.Span` into a zipkin span.

        :param sprocketstracing.tracing.Span span:
        :return: the zipkin representation of `span` as a :class:`dict`
            or :data:`None` if the span cannot be represented
        :rtype: dict

        """
        payload = ZipkinPayloadBuilder(span)
        start_micros = span.start_time * 1e6
        duration_micros = span.duration * 1e6
        sentinel = object()
        tags = dict(span.tags())

        def add_bin_if_tag_present(tag, annotation, add_endpoint=False):
            value = tags.pop(tag, sentinel)
            if value is not sentinel:
                payload.add_binary_annotation(annotation, value,
                                              add_endpoint=add_endpoint)

        kind = tags.pop('span.kind', 'client')
        if kind in ('server', 'periodic'):
            payload.add_annotation('sr', start_micros)
            payload.add_annotation('ss', start_micros + duration_micros)
            add_bin_if_tag_present('peer.address', 'ca', add_endpoint=True)

        elif kind in ('client', 'producer'):
            payload.add_annotation('cs', start_micros)
            payload.add_annotation('cr', start_micros + duration_micros)
            tags, endpoint = self.extract_endpoint(**tags)
            if endpoint:
                payload.add_binary_annotation('sa', endpoint=endpoint)

        else:
            self.logger.warning('skipping %r, unhandled span.kind %s',
                                span, kind)
            return None

        for name, value in tags.items():
            payload.add_binary_annotation(name, value)

        return payload.as_dict()

    @staticmethod
    def extract_endpoint(**tags):
        sentinel = object()
        tag_map = {'peer.service': 'serviceName',
                   'peer.ipv4': 'ipv4',
                   'peer.ipv6': 'ipv6',
                   'peer.port': 'port'}
        endpoint = {}
        for tracing_name, zipkin_name in tag_map.items():
            value = tags.pop(tracing_name, sentinel)
            if value is not sentinel:
                endpoint[zipkin_name] = value

        if 'ipv4' not in endpoint and 'ipv6' not in endpoint:
            name = tags.pop('peer.hostname', sentinel)
            if name is not sentinel:
                try:
                    addr = ipaddress.ip_address(name)
                    endpoint['ipv{}'.format(addr.version)] = str(addr)
                except ValueError as error:  # not an IP literal
                    family = (socket.AF_UNSPEC if socket.has_ipv6
                              else socket.AF_INET)
                    addrs = socket.getaddrinfo(name, 0, family=family,
                                               type=socket.SOCK_STREAM,
                                               proto=socket.IPPROTO_TCP,
                                               flags=socket.AI_PASSIVE)
                    if not addrs:
                        raise error

                    for family, socktype, proto, name, sa in addrs:
                        if family == socket.AF_INET:
                            endpoint['ipv4'] = sa[0]
                        elif family == socket.AF_INET6:
                            endpoint['ipv6'] = sa[0]

        if 'port' not in endpoint:
            endpoint['port'] = 0
        if 'ipv4' not in endpoint and 'ipv6' not in endpoint:
            endpoint = {}

        return tags, endpoint


class ZipkinPayloadBuilder(object):

    """
    Builds a Zipkin API payload.

    :param sprocketstracing.tracing.Span span: the span to generate
        a payload for.

    The most difficult part of this process is generating the endpoint
    structure.  It requires a formatted IPv4 or IPv6 literal for server
    side of the HTTP connection.  Tornado makes this difficult to get
    to easily.  The most reliable way to retrieve this is to parse the
    :attr:`tornado.httputil.HTTPServerRequest.host` attribute.  If the
    host is specified using a DNS name, then we need to call
    :func:`socket.getaddrinfo` to retrieve the appropriate IP address.

    """

    def __init__(self, span):
        self.span = span
        self.endpoint = {'serviceName': span.context.service_name}
        
        if span.context.service_endpoint:
            addr, port = span.context.service_endpoint
            _, endpoint = ZipkinReporter.extract_endpoint(
                **{'peer.hostname': addr, 'peer.port': port})
            self.endpoint.update(endpoint)

        self.payload = {'name': span.operation_name.lower(),
                        'id': span.context.span_id,
                        'traceId': span.context.trace_id,
                        'annotations': [],
                        'binaryAnnotations': []}

        if span.context.parents:
            self.payload['parentId'] = span.context.parents[0].span_id

    def as_dict(self):
        """
        Return the representation as a :class:`dict` instance.

        :rtype: dict

        """
        return self.payload

    def add_annotation(self, value, timestamp, **attributes):
        """
        Add a simple annotation.

        :param str value: the annotation's formatted value.
        :param float timestamp: seconds since the Epoch timestamp of
            when the annotation was recorded.
        :param attributes: additional attributes to append to the annotation.
        :return: the annotation after it is appended
        :rtype: dict

        The annotation structure is returned so that the caller can modify
        it if necessary.  It has already been appended to the internal
        payload but the reference is modifiable.

        """
        annotation = {'endpoint': self.endpoint,
                      'value': value, 'timestamp': int(timestamp)}
        annotation.update(attributes)
        self.payload['annotations'].append(annotation)
        return annotation

    def add_binary_annotation(self, key, value=True, endpoint=None,
                              add_endpoint=False, **attributes):
        """
        Add a binary annotation.

        :param str key: the annotation's name
        :param object value: value for the annotation.  If unspecified,
            the value :data:`True` is used by convention.
        :param dict endpoint: optional endpoint structure see the
            Zipkin API [#]_ for structure details.
        :param bool add_endpoint: optional flag that tells the reporter
            to insert the endpoint attribute if it is missing.
        :param attributes: additional attributes to append to the annotation.
        :return: the annotation after it is appended
        :rtype: dict

        The annotation structure is returned so that the caller can modify
        it if necessary.  It has already been appended to the internal
        payload but the reference is modifiable.

        """
        annotation = {'key': key, 'value': str(value)}
        if endpoint is not None:
            annotation['endpoint'] = endpoint
        elif add_endpoint:
            annotation['endpoint'] = self.endpoint
        annotation.update(attributes)
        self.payload['binaryAnnotations'].append(annotation)
        return annotation


add_reporter('null', NullReporter)
add_reporter('zipkin', ZipkinReporter)


def jsonify(obj):
    if isinstance(obj, bytes):
        return obj.decode('utf-8')
    raise TypeError(repr(obj) + ' is not JSON serializable')
