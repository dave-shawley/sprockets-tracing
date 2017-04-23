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
        self.opentracing_options['operation_name'] = 'sleep'

    @gen.coroutine
    def get(self):
        self.span.sampled = True
        if self.get_query_argument('sleep', None):
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
            if response.code != 404:
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
        expected = {'server-type': 'http',
                    'url': 'http://{}:{}/sleep'.format('localhost',
                                                       self.get_http_port()),
                    'method': 'GET'}
        for bin_annotation in spans[0]['binaryAnnotations']:
            if bin_annotation['key'] in expected:
                self.assertEqual(bin_annotation['value'],
                                 expected[bin_annotation['key']])
                del expected[bin_annotation['key']]
        self.assertEqual(len(expected), 0)
