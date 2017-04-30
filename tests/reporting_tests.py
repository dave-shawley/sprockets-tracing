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

    def retrieve_trace_by_id(self, trace_id):
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
                self.wait()
            else:
                self.fail('unexpected response {}'.format(response.code))

        self.assertEqual(response.code, 200)

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
        expected = {'server.type': 'http',
                    'http.url': 'http://{}:{}/sleep'.format(
                        'localhost', self.get_http_port()),
                    'http.method': 'GET'}
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in expected:
                self.assertEqual(bin_annotation['value'],
                                 expected[bin_annotation['key']])
                del expected[bin_annotation['key']]
        self.assertEqual(len(expected), 0)

    def test_that_client_span_is_reported(self):
        with self.application.opentracing.start_span('client-test') as span:
            # provide the context that our request handler provides
            span.context.service_name = 'my-service'
            span.context.service_endpoint = 'localhost', self.get_http_port()

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
            
            # mark this as a server span
            span.set_tag('span.kind', 'server')

            # we need this to retrieve the reported span from zipkin
            trace_id = span.context.trace_id

        # let the reporter run
        self.io_loop.add_future(gen.moment, lambda _: self.io_loop.stop())
        self.io_loop.start()

        expected_endpoint = {'serviceName': 'my-service',
                             'port': self.get_http_port(),
                             'ipv6': '::1'}
        spans = self.retrieve_trace_by_id(trace_id)
        self.assertEqual(len(spans), 1)
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in tags:
                self.assertEqual(bin_annotation['value'],
                                 str(tags[bin_annotation['key']]))
                self.assertEqual(bin_annotation['endpoint'], expected_endpoint)
        
        annotation_names = [annotation['key']
                            for annotation in spans[0]['binaryAnnotations']]
        self.assertNotIn('span.kind', annotation_names)
