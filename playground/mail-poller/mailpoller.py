import email
import json
import logging
import os
import urllib.parse

from motor import motor_tornado
from tornado import concurrent, gen, httpclient, ioloop, web
import opentracing
import sprockets.http.mixins
import sprocketstracing


class MailTrap(object):

    def __init__(self, message_store, **settings):
        self.logger = logging.getLogger('mailtrap')
        self.message_store = message_store
        self.settings = settings
        self.http_client = None

    async def poll_for_email(self):
        if self.http_client is None:
            self.http_client = httpclient.AsyncHTTPClient()

        tags = {'span.kind': 'periodic'}
        with opentracing.tracer.start_span('poll-email', tags=tags) as span:
            span.context.service_name = 'mail-poller'
            span.context.service_endpoint = ('127.0.0.1', 0)
            span.sampled = True

            msg_url = '/api/v1/inboxes/{box_id}/messages'.format(
                **self.settings)
            response = await self.call_api('fetch-inbox', 'GET', msg_url, span)
            if response.code == 200:
                span.set_tag('message_count', len(response.json))
                if len(response.json) < 1:
                    span.sampled = False
                for message_info in response.json:
                    self.logger.debug('looking at %s', message_info['id'])
                    response = await self.call_api(
                        'fetch-message', 'GET',
                        message_info['download_path'], span)
                    if response.code == 200:
                        await self.message_store.store_message(
                            response.rfc822, span)
                        url = message_info['download_path']
                        url = url[:url.rfind('/')]
                        response = await self.call_api('delete-message', 'DELETE',
                                                       url, span)
                        if response.code != 200:
                            self.logger.warning(
                                'failed to delete message %s - %r',
                                message_info['id'], response)
                    else:
                        self.logger.warning(
                            'failed to retrieve message %s - %r',
                            message_info['id'], response)
            else:
                self.logger.warning('failed to retrieve inbox - %r', response)

    async def call_api(self, operation_name, method, path, parent_span):
        headers = {
            'Authorization': 'Token token={}'.format(self.settings['token']),
        }
        url = urllib.parse.urljoin(self.settings['base_url'], path)

        span_tags = {'span.kind': 'client', 'peer.service': 'mailtrap',
                     'peer.hostname': 'mailtrap.io', 'peer.port': 443,
                     'http.url': url, 'http.method': method}
        with opentracing.start_child_span(parent_span, operation_name,
                                          tags=span_tags) as span:
            response = await self.http_client.fetch(
                url, method=method, headers=headers, raise_error=False)
            span.set_tag('http.status', str(response.code))
            if response.body and response.body == b'[]':
                span.sampled = False

        if response.code == 200:
            content_type = response.headers.get(
                'Content-Type', 'application/json')
            if content_type.startswith('application/json'):
                body = json.loads(response.body.decode('utf-8'))
                setattr(response, 'json', body)
            elif content_type.startswith('message/rfc822'):
                setattr(response, 'rfc822',
                        email.message_from_bytes(response.body))
        return response


class MessageStore(object):

    def __init__(self, mongodb_url, **settings):
        self.logger = logging.getLogger('MessageStore')
        self.mongo_client = None
        parsed = urllib.parse.urlsplit(mongodb_url)
        client_settings = dict(urllib.parse.parse_qsl(parsed.query))
        client_settings.setdefault('connect', True)
        client_settings.setdefault('tz_aware', True)
        self.mongo_url = '{0.scheme}://{0.netloc}/'.format(parsed)
        self.mongo_settings = client_settings
        if parsed.path == '/':
            self.mongo_database = 'test'
        else:
            self.mongo_database = parsed.path[1:]

    def extract_content(self, part):
        if part.is_multipart():
            return {'content': [extract_content(p)
                                for p in part.iter_parts()]}
        else:
            return part.get_payload()

    async def store_message(self, email_message, parent_span):
        if self.mongo_client is None:
            self.mongo_client = motor_tornado.MotorClient(
                self.mongo_url, **self.mongo_settings)

        self.logger.debug('storing %r', email_message)
        message_info = {'headers': dict(email_message.items()),
                        'body': self.extract_content(email_message)}

        collection = self.mongo_client[self.mongo_database]['raw']
        span_tags = {'span.kind': 'client',
                     'db.type': 'mongodb',
                     'db.instance': collection.full_name,
                     'peer.service': 'mongodb',
                     'peer.address': self.mongo_client.address[0],
                     'peer.port': self.mongo_client.address[1]}
        with opentracing.start_child_span(parent_span, 'store-message',
                                          tags=span_tags) as span:
            self.logger.debug('inserting %r', message_info)
            result = await collection.insert_one(message_info)
            if result is not None:
                span.set_tag('db.object_id', result.inserted_id)
                return result.inserted_id


class Application(web.Application):

    def __init__(self, *args, **kwargs):
        handlers = []
        kwargs['opentracing'] = {'propagation_syntax': 'b3',
                                 'report_format': 'zipkin',
                                 'report_target': os.environ['ZIPKIN_URL'],
                                 'service_name': 'mail-poller'}
        super(Application, self).__init__(handlers, *args, **kwargs)

        self.message_store = MessageStore(
            mongodb_url=os.environ['MONGODB_URL'],
            connect=True, tz_aware=True)
        self.mailtrap = MailTrap(
            self.message_store,
            base_url=os.environ.get('MAILTRAP_URL', 'https://mailtrap.io'),
            token=os.environ['MAILTRAP_TOKEN'],
            box_id=os.environ['MAILTRAP_BOXID'])
        self.poller = None
        self.runner_callbacks = {'before_run': [sprocketstracing.install,
                                                self.on_start],
                                 'on_stop': [self.on_stop,
                                             sprocketstracing.shutdown]}

    def on_start(self, _, io_loop):
        self.poller = ioloop.PeriodicCallback(self.mailtrap.poll_for_email,
                                              30 * 1000)
        self.poller.start()

    def on_stop(self, _, io_loop):
        if self.poller is not None:
            self.poller.stop()
            self.mailtrap.flush()

if __name__ == '__main__':
    os.environ.setdefault('DEBUG', '1')
    sprockets.http.run(Application)
