import base64

from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.web.http_headers import Headers
from twisted.web import http

from vumi.utils import http_request_full
from vumi.middleware.tagger import TaggingMiddleware
from vumi.message import TransportUserMessage, TransportEvent

from go.vumitools.tests.utils import AppWorkerTestCase
from go.vumitools.api import VumiApi
from go.apps.http_api.vumi_app import StreamingHTTPWorker
from go.apps.http_api.client import StreamingClient, VumiMessageReceiver


class TestMessageReceiver(VumiMessageReceiver):
    message_class = TransportUserMessage

    def __init__(self, *args, **kwargs):
        VumiMessageReceiver.__init__(self, *args, **kwargs)
        self.inbox = DeferredQueue()
        self.errors = DeferredQueue()

    def onMessage(self, message):
        self.inbox.put(message)

    def onError(self, failure):
        self.errors.put(failure)


class TestEventReceiver(TestMessageReceiver):
    message_class = TransportEvent


class StreamingHTTPWorkerTestCase(AppWorkerTestCase):

    use_riak = True
    application_class = StreamingHTTPWorker

    @inlineCallbacks
    def setUp(self):
        yield super(StreamingHTTPWorkerTestCase, self).setUp()
        config = self.mk_config({
            'worker_name': 'foo',
            'web_path': '/foo',
            'web_port': 0,
            'metrics_prefix': 'foo',
            })
        self.app = yield self.get_application(config)
        self.addr = self.app.webserver.getHost()
        self.url = 'http://%s:%s%s' % (self.addr.host, self.addr.port,
                                        config['web_path'])

        # get the router to test
        self.vumi_api = yield VumiApi.from_config_async(config)
        self.account = yield self.mk_user(self.vumi_api, u'user')
        self.user_api = self.vumi_api.get_user_api(self.account.key)

        self.tag = ("pool", "tag")
        self.batch_id = yield self.vumi_api.mdb.batch_start([self.tag],
                                    user_account=unicode(self.account.key))
        self.conversation = yield self.create_conversation()
        self.conversation.batches.add_key(self.batch_id)
        self.conversation.set_metadata({
            'http_api': {
                'api_tokens': [
                    'token-1',
                    'token-2',
                    'token-3',
                ]
            }
        })
        yield self.conversation.save()

        self.auth_headers = {
            'Authorization': ['Basic ' + base64.b64encode('%s:%s' % (
                self.account.key, 'token-1'))],
            }

        self.client = StreamingClient()

    def dispatch_with_tag(self, msg, tag=None):
        if tag:
            TaggingMiddleware.add_tag_to_msg(msg, tag)
        return self.dispatch(msg)

    @inlineCallbacks
    def test_messages_stream(self):
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)

        messages = DeferredQueue()
        errors = DeferredQueue()

        receiver = self.client.stream(TransportUserMessage, messages.put,
                                            errors.put, url,
                                            Headers(self.auth_headers))
        msg1 = self.mkmsg_in(content='in 1', message_id='1')
        yield self.dispatch_with_tag(msg1, self.tag)

        msg2 = self.mkmsg_in(content='in 2', message_id='2')
        yield self.dispatch_with_tag(msg2, self.tag)

        rm1 = yield messages.get()
        rm2 = yield messages.get()

        receiver.disconnect()

        self.assertEqual(msg1['message_id'], rm1['message_id'])
        self.assertEqual(msg2['message_id'], rm2['message_id'])
        self.assertEqual(errors.size, None)

    @inlineCallbacks
    def test_events_stream(self):
        url = '%s/%s/events.json' % (self.url, self.conversation.key)

        events = DeferredQueue()
        errors = DeferredQueue()
        receiver = yield self.client.stream(TransportEvent, events.put,
                                            events.put, url,
                                            Headers(self.auth_headers))

        msg1 = self.mkmsg_in(content='in 1', message_id='1')
        yield self.vumi_api.mdb.add_outbound_message(msg1,
                                                        batch_id=self.batch_id)
        ack1 = self.mkmsg_ack(user_message_id=msg1['message_id'])
        yield self.dispatch_event(ack1)

        msg2 = self.mkmsg_in(content='in 1', message_id='2')
        yield self.vumi_api.mdb.add_outbound_message(msg2,
                                                        batch_id=self.batch_id)
        ack2 = self.mkmsg_ack(user_message_id=msg2['message_id'])
        yield self.dispatch_event(ack2)

        ra1 = yield events.get()
        ra2 = yield events.get()

        receiver.disconnect()

        self.assertEqual(ack1['event_id'], ra1['event_id'])
        self.assertEqual(ack2['event_id'], ra2['event_id'])
        self.assertEqual(errors.size, None)

    @inlineCallbacks
    def test_missing_auth(self):
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)

        queue = DeferredQueue()
        receiver = self.client.stream(TransportUserMessage, queue.put,
                                                queue.put, url)
        response = yield receiver.get_response()
        self.assertEqual(response.code, http.UNAUTHORIZED)
        self.assertEqual(response.headers.getRawHeaders('www-authenticate'), [
            'basic realm="Conversation Stream"'])

    @inlineCallbacks
    def test_invalid_auth(self):
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)

        queue = DeferredQueue()

        headers = Headers({
            'Authorization': ['Basic %s' % (base64.b64encode('foo:bar'),)],
            })

        receiver = self.client.stream(TransportUserMessage, queue.put,
                                                queue.put, url,
                                                Headers(headers))
        response = yield receiver.get_response()
        self.assertEqual(response.code, http.UNAUTHORIZED)
        self.assertEqual(response.headers.getRawHeaders('www-authenticate'), [
            'basic realm="Conversation Stream"'])

    @inlineCallbacks
    def test_send_to(self):
        msg = self.mkmsg_out()
        TaggingMiddleware.add_tag_to_msg(msg, self.tag)
        url = '%s/%s/messages.json' % (self.url, self.conversation.key)
        response = yield http_request_full(url, msg.to_json(),
                                            self.auth_headers, method='PUT')
        print response
        print response.delivered_body
        [msg] = self.get_dispatched_messages()
        print msg
