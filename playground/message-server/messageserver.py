import logging
import os

from sprockets.mixins import amqp
from sprockets.mixins.mediatype import content, transcoders
from sprocketstracing import tracing
from tornado import concurrent, gen, ioloop, web
import opentracing
import sprockets.http.mixins
import sprocketstracing


class EmailHandler(
        amqp.PublishingMixin,
        content.ContentMixin,
        tracing.RequestHandlerMixin,
        sprockets.http.mixins.ErrorLogger,
        sprockets.http.mixins.ErrorWriter,
        web.RequestHandler):

    def initialize(self):
        super(EmailHandler, self).initialize()
        self.tracing_operation = 'schedule-email'

    @gen.coroutine
    def post(self):
        self.request_is_traced = True
        settings = content.ContentSettings.from_application(self.application)
        json = settings.get('application/json')
        body = self.get_request_body()

        content_type, payload = json.to_bytes(body)
        yield self.amqp_publish('rpc', 'send.email', payload,
                                {'content_type': 'application/json'})

    def amqp_publish(self, exchange, routing_key, payload, properties=None):
        addr, port = self.application.amqp.connection.socket.getpeername()
        tags = {'span.kind': 'producer',
                'amqp.exchange': exchange, 'amqp.routing_key': routing_key,
                'broker.service': 'rabbitmq', 'broker.address': addr,
                'broker.port': port}
        span = opentracing.tracer.start_span(operation_name='amqp-publish',
                                             child_of=self.span, tags=tags)
        self.logger.debug('starting AMQP span with tags %r', tags)

        def on_published(f):
            span.finish()

        if properties is None:
            properties = {}
        headers = properties.pop('headers', {})
        opentracing.tracer.inject(span.context,
                                  opentracing.Format.HTTP_HEADERS,
                                  headers)
        properties['headers'] = headers

        future = super(EmailHandler, self).amqp_publish(
            exchange, routing_key, payload, properties)
        future.add_done_callback(on_published)

        return future


class Application(web.Application):

    def __init__(self, *args, **kwargs):
        handlers = [web.url(r'/email', EmailHandler)]
        kwargs['opentracing'] = {'propagation_syntax': 'b3',
                                 'report_format': 'zipkin',
                                 'report_target': os.environ['ZIPKIN_URL'],
                                 'service_name': 'message-server'}
        super(Application, self).__init__(handlers, *args, **kwargs)
        amqp.install(self, default_app_id='messageserver/0.0.0',
                     enable_confirmations=False)
        content.set_default_content_type(self, 'application/json', 'utf-8')
        content.add_transcoder(self, transcoders.JSONTranscoder())
        sprocketstracing.install(self, ioloop.IOLoop.instance())

        logging.getLogger('pika').setLevel(logging.INFO)


if __name__ == '__main__':
    os.environ.setdefault('DEBUG', '1')
    os.environ.setdefault('AMQP_URL', 'amqp://127.0.0.1:5672/%2f')
    sprockets.http.run(Application)
