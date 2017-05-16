from urllib import parse
import json
import os
import uuid

from tornado import gen, testing, web

from sprocketstracing import tracing
import sprocketstracing


class SleepingHandler(tracing.RequestHandlerMixin, web.RequestHandler):

    def initialize(self):
        super(SleepingHandler, self).initialize()
        self.tracing_operation = 'sleep'

    @gen.coroutine
    def get(self):
        self.span.sampled = True
        if self.get_query_argument('sleep', None):
            with self.application.opentracing.start_span('nap-time'):
                yield gen.sleep(float(self.get_query_argument('sleep')))
        self.set_status(int(self.get_query_argument('status', 200)))
        self.finish()


class ZipkinReporterTests(testing.AsyncHTTPTestCase):

    @classmethod
    def setUpClass(cls):
        super(ZipkinReporterTests, cls).setUpClass()
        cls.service_name = uuid.uuid4().hex

    @classmethod
    def tearDownClass(cls):
        super(ZipkinReporterTests, cls).tearDownClass()

    def setUp(self):
        self.application = None
        super(ZipkinReporterTests, self).setUp()

    def tearDown(self):
        if self.application:
            def shutdown():
                return sprocketstracing.shutdown(self.application)
            self.io_loop.run_sync(shutdown,
                                  timeout=testing.get_async_test_timeout())
        super(ZipkinReporterTests, self).tearDown()

    def get_app(self):
        settings = {'service_name': self.service_name,
                    'report_format': 'zipkin',
                    'report_target': os.environ['ZIPKIN_URL'],
                    'propagation_syntax': 'b3'}
        self.application = web.Application(
            [web.url('/sleep', SleepingHandler)],
            opentracing=settings, debug=True)
        sprocketstracing.install(self.application, self.io_loop)
        return self.application

    def retrieve_trace_by_id(self, trace_id, allow_404=False):
        zipkin_url = os.environ['ZIPKIN_URL']
        if not zipkin_url.endswith('/'):
            zipkin_url += '/'
        url = parse.urljoin(zipkin_url,
                            'trace/{}'.format(parse.quote(trace_id)))
        self.http_client.fetch(url, headers={'Accept': 'application/json'},
                               callback=self.stop)
        response = self.wait()
        for _ in range(0, 5):
            self.http_client.fetch(url, headers={'Accept': 'application/json'},
                                   callback=self.stop)
            response = self.wait()
            if response.code == 200:
                break

            if response.code == 404:
                self.io_loop.add_future(gen.sleep(0.1),
                                        lambda _: self.io_loop.stop())
                self.io_loop.start()
            else:
                self.fail('unexpected response {}'.format(response.code))

        if allow_404:
            self.assertIn(response.code, (200, 404))
        else:
            self.assertEqual(response.code, 200)

        if response.body:
            return json.loads(response.body.decode('utf-8'))

    def test_that_simple_trace_is_reported(self):
        result = self.fetch('/sleep')
        self.assertEqual(result.code, 200)
        self.assertIn('X-B3-TraceId', result.headers)

        spans = self.retrieve_trace_by_id(result.headers['X-B3-TraceId'])
        self.assertEqual(len(spans), 1)
        self.assertIsNone(spans[0].get('parentId'))
        for annotation in spans[0]['annotations']:
            if annotation['value'] in ('sr', 'ss'):
                self.assertEqual(annotation['endpoint']['serviceName'],
                                 self.service_name)
                if 'ipv4' in annotation['endpoint']:
                    self.assertEqual(annotation['endpoint']['ipv4'],
                                     '127.0.0.1')
                else:
                    self.assertEqual(annotation['endpoint']['ipv6'], '::1')
                self.assertEqual(annotation['endpoint']['port'],
                                 self.get_http_port())

    def test_that_http_client_details_are_reported(self):
        result = self.fetch('/sleep')
        self.assertEqual(result.code, 200)
        self.assertIn('X-B3-TraceId', result.headers)

        spans = self.retrieve_trace_by_id(result.headers['X-B3-TraceId'])
        self.assertIsNone(spans[0].get('parentId'))
        expected = {'peer.address': '127.0.0.1'}
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in expected:
                self.assertEqual(bin_annotation['value'],
                                 expected[bin_annotation['key']])
                self.assertIsNone(bin_annotation.get('endpoint'))

    def test_that_http_request_details_are_reported(self):
        result = self.fetch('/sleep')
        self.assertEqual(result.code, 200)
        self.assertIn('X-B3-TraceId', result.headers)

        spans = self.retrieve_trace_by_id(result.headers['X-B3-TraceId'])
        self.assertIsNone(spans[0].get('parentId'))
        expected = {'server.type': 'http',
                    'http.url': 'http://{}:{}/sleep'.format(
                        'localhost', self.get_http_port()),
                    'http.method': 'GET',
                    'http.version': 'HTTP/1.1',
                    'http.user_agent': ''}
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in expected:
                self.assertEqual(bin_annotation['value'],
                                 expected[bin_annotation['key']])
                self.assertIsNone(bin_annotation.get('endpoint'))
        
    def test_that_http_response_details_are_reported(self):
        result = self.fetch('/sleep')
        self.assertEqual(result.code, 200)
        self.assertIn('X-B3-TraceId', result.headers)

        spans = self.retrieve_trace_by_id(result.headers['X-B3-TraceId'])
        self.assertIsNone(spans[0].get('parentId'))
        expected = {'server.type': 'http',
                    'http.status_code': '200',
                    'http.reason': 'OK'}
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in expected:
                self.assertEqual(bin_annotation['value'],
                                 expected[bin_annotation['key']])
                self.assertIsNone(bin_annotation.get('endpoint'))

    def test_that_client_span_is_reported(self):
        with self.application.opentracing.start_span('client-test') as span:
            # provide the context that our request handler provides
            span.context.service_name = 'my-service'
            span.context.service_endpoint = 'localhost', self.get_http_port()
            span.sampled = True

            # set up the span as a client call
            span.set_tag('span.kind', 'client')
            span.set_tag('peer.service', 'other-service')
            span.set_tag('peer.ipv4', '127.0.0.1')
            span.set_tag('peer.port', 1234)

            # we need this to retrieve the reported span from zipkin
            trace_id = span.context.trace_id

        # let the reporter run
        self.io_loop.add_future(gen.moment, lambda _: self.io_loop.stop())
        self.io_loop.start()

        spans = self.retrieve_trace_by_id(trace_id)
        self.assertEqual(len(spans), 1)
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] == 'sa':
                self.assertEqual(bin_annotation['value'].lower(), 'true')
                self.assertEqual(bin_annotation['endpoint']['serviceName'],
                                 'other-service')
                self.assertEqual(bin_annotation['endpoint']['ipv4'],
                                 '127.0.0.1')
                self.assertEqual(bin_annotation['endpoint']['port'], 1234)

        annotation_names = [annotation['key']
                            for annotation in spans[0]['binaryAnnotations']]
        self.assertNotIn('peer.service', annotation_names)
        self.assertNotIn('peer.ipv4', annotation_names)
        self.assertNotIn('peer.port', annotation_names)

    def test_that_arbitrary_tags_are_reported(self):
        tags = {'my-tag': 'whatever', 'numeric-tag': 12345}
        with self.application.opentracing.start_span('server',
                                                     tags=tags) as span:
            # provide the context that our request handler provides
            span.context.service_name = 'my-service'
            span.context.service_endpoint = '::1', self.get_http_port()
            span.sampled = True
            
            # mark this as a server span
            span.set_tag('span.kind', 'server')

            # we need this to retrieve the reported span from zipkin
            trace_id = span.context.trace_id

        # let the reporter run
        self.io_loop.add_future(gen.moment, lambda _: self.io_loop.stop())
        self.io_loop.start()

        spans = self.retrieve_trace_by_id(trace_id)
        self.assertEqual(len(spans), 1)
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in tags:
                self.assertEqual(bin_annotation['value'],
                                 str(tags[bin_annotation['key']]))
                self.assertIsNone(bin_annotation.get('endpoint'))
        
        annotation_names = [annotation['key']
                            for annotation in spans[0]['binaryAnnotations']]
        self.assertNotIn('span.kind', annotation_names)

    def test_that_periodic_spans_are_reported_as_server_spans(self):
        with self.application.opentracing.start_span('periodic') as span:
            span.context.service_name = 'my-service'
            span.context.service_endpoint = '127.0.0.1', self.get_http_port()
            span.sampled = True
            span.set_tag('span.kind', 'periodic')
            
            trace_id = span.context.trace_id
        
        self.io_loop.add_future(gen.moment, lambda _: self.io_loop.stop())
        self.io_loop.start()
        
        spans = self.retrieve_trace_by_id(trace_id)
        self.assertEqual(len(spans), 1)
        keys = [annotation['value'] for annotation in spans[0]['annotations']]
        self.assertIn('sr', keys)
        self.assertIn('ss', keys)

    def test_that_producer_spans_are_reported_as_client_spans(self):
        with self.application.opentracing.start_span('producer') as span:
            span.context.service_name = 'my-service'
            span.context.service_endpoint = '127.0.0.1', 0
            span.sampled = True
            span.set_tag('span.kind', 'producer')
        
            trace_id = span.context.trace_id
    
        self.io_loop.add_future(gen.moment, lambda _: self.io_loop.stop())
        self.io_loop.start()
    
        spans = self.retrieve_trace_by_id(trace_id)
        self.assertEqual(len(spans), 1)
        keys = [annotation['value'] for annotation in spans[0]['annotations']]
        self.assertIn('cs', keys)
        self.assertIn('cr', keys)

    def test_that_unknown_span_types_are_not_reported(self):
        with self.application.opentracing.start_span('whatever') as span:
            span.sampled = True
            span.set_tag('span.kind', str(uuid.uuid4()))
            
            trace_id = span.context.trace_id
        
        spans = self.retrieve_trace_by_id(trace_id, allow_404=True)
        self.assertIsNone(spans)

    def test_that_malformed_ip_literals_are_not_reported(self):
        with self.application.opentracing.start_span('malformed') as span:
            span.context.service_endpoint = '256.256.256.256', 0
            span.sampled = True
            
            trace_id = span.context.trace_id
        
        spans = self.retrieve_trace_by_id(trace_id, allow_404=True)
        self.assertIsNone(spans)
