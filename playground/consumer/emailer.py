import email.message
import email.utils
import os
import smtplib
import time

from rejected import consumer
from sprocketstracing import reporting, tracing
from tornado import concurrent, gen, ioloop, queues
import opentracing


class AMQPTracer(consumer.Consumer):
    __tracing_state = {}

    def initialize(self):
        self.__span = None
        super(AMQPTracer, self).initialize()
        opentracing_settings = self.settings.get('opentracing', {})
        if opentracing_settings.get('enabled', False):
            try:
                self.install_tracing(opentracing_settings)
            except Exception as error:
                self.logger.warning('failed to install opentracing: %r',
                                    error)
                opentracing_settings['enabled'] = False

    @gen.coroutine
    def prepare(self):
        start_time = time.time()
        maybe_future = super(AMQPTracer, self).prepare()
        if concurrent.is_future(maybe_future):
            yield maybe_future

        if self.opentracing_enabled:
            try:
                if 'X-B3-Sampled' in self.headers:
                    self.logger.debug('found X-B3-Sampled: %r',
                                      self.headers['X-B3-Sampled'])
                else:
                    self.logger.debug('X-B3-Sampled is not in %r',
                                      self.headers)
                parent_context = opentracing.tracer.extract(
                    opentracing.Format.HTTP_HEADERS, self.headers)
                self.logger.debug('extracted %r from %r',
                                  parent_context, self.headers)
                if parent_context.sampled:
                    self._finish_broker_span(parent_context)

            except opentracing.UnsupportedFormatException:
                parent_context = None

            self.__span = opentracing.tracer.start_span(
                operation_name=self.name, start_time=start_time,
                child_of=parent_context,
                tags={'span.kind': 'server',
                      'amqp.exchange': self.exchange,
                      'amqp.routing_key': self.routing_key,
                      'correlation_id': self.correlation_id})
            self.__span.context.service_name = \
                self.settings['opentracing']['service_name']
            host, port = self._message.channel.connection.socket.getsockname()
            self.logger.debug('setting service endpoint to %r', (host, port))
            self.__span.context.service_endpoint = host, port

    def on_finish(self):
        super(AMQPTracer, self).on_finish()
        if self.opentracing_span is not None:
            self.opentracing_span.finish()

    def publish_message(self, exchange, routing_key, properties,
                        body, **kwargs):
        if self.opentracing_span is not None:
            headers = properties.get('headers', {})
            opentracing.tracer.inject(self.opentracing_span,
                                      opentracing.Format.HTTP_HEADERS,
                                      headers)
            properties['headers'] = headers
        return super(AMQPTracer, self).publish_message(
            exchange, routing_key, properties, body, **kwargs)

    def shutdown(self):
        super(AMQPTracer, self).shutdown()
        self.shutdown_tracing()

    @property
    def opentracing_enabled(self):
        settings = self.settings.get('opentracing', {})
        return settings.get('enabled', False)

    @property
    def opentracing_span(self):
        return self.__span

    def _finish_broker_span(self, context):
        self.logger.debug('finishing broker span %r', context)
        conn_params = self._message.channel.connection.params
        context.service_name = 'rabbitmq'
        context.service_endpoint = conn_params.host, conn_params.port
        span = tracing.Span('amqp.publish', context,
                            tags={'span.kind': 'consumer',
                                  'amqp.exchange': self.exchange,
                                  'amqp.routing_key': self.routing_key,
                                  'broker.service': 'rabbitmq',
                                  'broker.hostname': conn_params.host,
                                  'broker.port': conn_params.port})
        span.finish()

    @classmethod
    def install_tracing(cls, settings, io_loop=None):
        if not isinstance(opentracing.tracer, opentracing.Tracer):
            return

        io_loop = io_loop or ioloop.IOLoop.instance()
        span_queue = queues.Queue()
        tracer = tracing.Tracer(span_queue, **settings)
        reporter = reporting.get_reporter(**settings)
        opentracing.tracer = tracer
        io_loop.spawn_callback(reporting.report_spans, reporter, span_queue)

        cls.__tracing_state['io_loop'] = io_loop
        cls.__tracing_state['reporter'] = reporter
        cls.__tracing_state['tracer'] = tracer

    @classmethod
    def shutdown_tracing(cls):
        if isinstance(opentracing.tracer, opentracing.Tracer):
            return

        opentracing.tracer = opentracing.Tracer()
        try:
            io_loop = cls.__tracing_state['io_loop']
            reporter = cls.__tracing_state['reporter']
            tracer = cls.__tracing_state['tracer']
        except KeyError:
            return
        finally:
            cls.__tracing_state.clear()

        def reporter_flushed(f):
            pass

        def tracer_stopped(f):
            io_loop.add_future(reporter.flush(), reporter_flushed)

        io_loop.add_future(tracer.stop(), tracer_stopped)


class Emailer(AMQPTracer, consumer.SmartConsumer):

    def initialize(self):
        super(Emailer, self).initialize()
        smtp_settings = self.settings.get('smtp', {})
        self.smtp_user = smtp_settings.get(
            'user', os.environ.get('SMTP_USER'))
        self.smtp_password = smtp_settings.get(
            'password', os.environ.get('SMTP_PASSWORD'))
        self.smtp_host = smtp_settings.get(
            'host', os.environ.get('SMTP_HOST'))
        self.smtp_port = int(smtp_settings.get(
            'port', os.environ.get('SMTP_PORT', '25')))

    @gen.coroutine
    def process(self):
        try:
            smtp_sender = self.body['sender']['address']
            from_addr = (self.body['sender'].get('display'),
                         self.body['sender']['address'])
            smtp_recipient = self.body['recipient']['address']
            to_addrs = [(self.body['recipient'].get('display'),
                         self.body['recipient']['address'])]
            subject = self.body['subject']
            msg_body = self.body['body']
        except (AttributeError, KeyError) as error:
            raise consumer.MessageException(
                'bad message - {:r}'.format(error)) from error

        msg = email.message.EmailMessage()
        msg.add_header('From', email.utils.formataddr(from_addr))
        for addr_pair in to_addrs:
            msg.add_header('To', email.utils.formataddr(addr_pair))
        msg.add_header('Subject', subject)
        msg.add_header('X-Mailer', 'emailer/0.0.0')
        msg.add_header('Message-ID', email.utils.make_msgid())
        msg.add_header('Return-Path', '<LEysDGxMbLSs7GzsnMwsrLRGtMxsjIwcbMzs@smtp-coi-g20-058.aweber.com>')
        msg.add_header('X-Loop', 'awlist4250626@aweber.com')
        msg.add_header('X-AWMessage', 'f547a98d-302f-409e-b0a6-99d32e5bf7ec')
        msg.add_header('X_Id', '4250626:05-17-2017-16-11-44:daveshawley+bcast@gmail.com')
        msg.add_header('Require-Recipient-Valid-Since', 'daveshawley+bcast@gmail.com; Fri, 01 Apr 2016 12:40:09 +0000')
        msg.add_header('Sender', 'Dave Shawley <dvshawley=yahoo.com@send.aweber.com>')
        msg.set_type('text/plain')
        msg.set_charset('utf-8')
        msg.set_content(msg_body.encode('utf-8'), 'text', 'plain')

        self.opentracing_span.sampled = True
        with opentracing.start_child_span(self.opentracing_span,
                                          'send-email') as span:
            span.set_tag('span.kind', 'client')
            span.set_tag('peer.service', 'smtp')
            span.set_tag('peer.port', self.smtp_port)
            span.set_tag('smtp.server', self.smtp_host)
            span.set_tag('smtp.port', self.smtp_port)

            smtp = smtplib.SMTP(self.smtp_host, self.smtp_port)
            try:
                smtp.ehlo()
                if self.settings['smtp']['use_tls']:
                    smtp.starttls()
                    span.set_tag('smtp.tls', True)
                else:
                    span.set_tag('smtp.tls', False)

                body = msg.as_string()
                span.set_tag('smtp.payload_size', len(body))
                smtp.login(self.smtp_user, self.smtp_password)
                smtp.sendmail(smtp_sender,
                              [addr_pair[1] for addr_pair in to_addrs],
                              body)
                span.set_tag('peer.hostname', smtp.sock.getpeername()[0])
            except Exception as error:
                raise consumer.ProcessingException(
                    'smtp failure - {:r}'.format(error)) from error
            finally:
                smtp.close()
