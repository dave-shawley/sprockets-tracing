import datetime
import json
import logging
import os
import signal

from sprocketstracing import tracing
from tornado import concurrent, gen, httpserver, ioloop, web
import opentracing
import sprocketstracing


class UTC(datetime.tzinfo):  # not necessary in modern python versions...
    _ZERO = datetime.timedelta(0)

    def utcoffset(self, _):
        return self._ZERO

    def tzname(self, _):
        return 'UTC'

    def dst(self, _):
        return self._ZERO


class TimeHandler(tracing.RequestHandlerMixin, web.RequestHandler):

    def initialize(self):
        super(TimeHandler, self).initialize()
        self.tracing_operation = 'fetch-time'

    @gen.coroutine
    def prepare(self):
        maybe_future = super(TimeHandler, self).prepare()
        if concurrent.is_future(maybe_future):
            yield maybe_future

        force_sample = self.get_query_argument('force-sample', 'false')
        if force_sample.lower() in ('true', 'yes', '1', 't'):
            self.request_is_traced = True

    @gen.coroutine
    def get(self):
        response = {'start_time': datetime.datetime.now(UTC()).isoformat()}
        before_time = self.get_query_argument('sleep-before', 0)
        if before_time:
            with opentracing.start_child_span(self.span, 'sleep-before'):
                yield gen.sleep(float(before_time))
        response['time'] = datetime.datetime.now(UTC()).isoformat()
        after_time = self.get_query_argument('sleep-after', 0)
        if after_time:
            with opentracing.start_child_span(self.span, 'sleep-after'):
                yield gen.sleep(float(after_time))
        response['end_time'] = datetime.datetime.now(UTC()).isoformat()
        self.set_status(200)
        self.set_header('Content-Type', 'application/json; charset="utf8"')
        self.write(json.dumps(response).encode('utf-8'))
        self.finish()


def make_app(**settings):
    settings['debug'] = True
    zipkin_url = os.environ.get('ZIPKIN_URL',
                                'http://127.0.0.1:9411/api/v1')
    iol = ioloop.IOLoop.instance()
    app = web.Application([web.url('/', TimeHandler)],
                          opentracing={'service_name': 'Father Time',
                                       'report_format': 'zipkin',
                                       'report_target': zipkin_url,
                                       'propagation_syntax': 'b3'},
                          **settings)
    sprocketstracing.install(app, iol)
    return app


def run():
    app = make_app()
    server = httpserver.HTTPServer(app)
    server.listen(int(os.environ.get('PORT', '8888')))

    def shutdown():
        iol = ioloop.IOLoop.instance()
        server.stop()
        maybe_future = sprocketstracing.shutdown(app)
        if concurrent.is_future(maybe_future):
            iol.add_future(maybe_future, lambda _: iol.stop())
        else:
            iol.stop()

    def on_signal(signo, frame):
        ioloop.IOLoop.instance().add_callback_from_signal(shutdown)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    ioloop.IOLoop.instance().start()


if __name__ == '__main__':
    logging.basicConfig(format='%(levelname)1.1s - %(name)s: %(message)s',
                        level=logging.DEBUG)
    run()
