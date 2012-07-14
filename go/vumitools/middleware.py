# -*- test-case-name: go.vumitools.tests.test_middleware -*-
import sys
import base64
import redis
from urllib import urlencode

from twisted.internet.defer import inlineCallbacks, returnValue

from vumi.middleware import (TransportMiddleware, TaggingMiddleware,
                                BaseMiddleware)
from vumi.application import TagpoolManager
from vumi.utils import normalize_msisdn
from vumi.persist.txriak_manager import TxRiakManager
from vumi.persist.message_store import MessageStore
from vumi import log
from vumi.utils import load_class_by_string, http_request_full

from go.vumitools.credit import CreditManager
from go.vumitools.account import AccountStore
from go.vumitools.conversation import ConversationStore
from go.vumitools.opt_out import OptOutStore
from go.vumitools.contact import ContactStore

from vxpolls.manager import PollManager


class NormalizeMsisdnMiddleware(TransportMiddleware):

    def setup_middleware(self):
        self.country_code = self.config['country_code']
        self.strip_plus = self.config.get('strip_plus', False)

    def handle_inbound(self, message, endpoint):
        from_addr = normalize_msisdn(message.get('from_addr'),
                        country_code=self.country_code)
        message['from_addr'] = from_addr
        return message

    def handle_outbound(self, message, endpoint):
        if self.strip_plus:
            message['to_addr'] = message['to_addr'].lstrip('+')
        return message


class DebitAccountError(Exception):
    """Exception raised if a message can't be paid for."""


class NoUserError(DebitAccountError):
    """Account could not be debited because no user was found."""


class NoTagError(DebitAccountError):
    """Account could not be debited because no tag was found."""


class BadTagPool(DebitAccountError):
    """Account could not be debited because the tag pool doesn't
       specify a cost."""


class InsufficientCredit(DebitAccountError):
    """Account could not be debited because the user account has
       insufficient credit."""


class GoApplicationRouterMiddleware(BaseMiddleware):
    """
    Base class for middlewares used by dispatchers using the
    `GoApplicationRouter`. It configures the `account_store` and the
    `message_store`.

    :type message_store: dict
    :param message_store:
        Dictionary containing the following values:

        *store_prefix*: the store prefix, defaults to 'message_store'

    :type redis: dict
    :param redis:
        Dictionary containing the configuration parameters for connecting
        to Redis with. Passed along as **kwargs to the Redis client.

    """
    def setup_middleware(self):
        from go.vumitools.api import get_redis
        r_server = get_redis(self.config)

        mdb_config = self.config.get('message_store', {})
        self.mdb_prefix = mdb_config.get('store_prefix', 'message_store')
        r_server = get_redis(self.config)
        self.manager = TxRiakManager.from_config({
                'bucket_prefix': self.mdb_prefix})
        self.account_store = AccountStore(self.manager)
        self.message_store = MessageStore(self.manager, r_server,
                                            self.mdb_prefix)

    def add_metadata_to_message(self, message):
        """
        Subclasses should override this method to appropriately set values
        on a message's `helper_metadata`. If specific message types or
        directions require different behaviour they can be overridden
        separately.
        """
        raise NotImplementedError("add_metadata_to_message should be "
                                    "implemented by the subclass")

    @inlineCallbacks
    def handle_inbound(self, message, endpoint):
        yield self.add_metadata_to_message(message)
        returnValue(message)

    @inlineCallbacks
    def handle_event(self, event, endpoint):
        yield self.add_metadata_to_message(event)
        returnValue(event)

    @inlineCallbacks
    def handle_outbound(self, message, endpoint):
        yield self.add_metadata_to_message(message)
        returnValue(message)


class LookupAccountMiddleware(GoApplicationRouterMiddleware):
    """
    Look up the account_key for a given message by retrieving
    this from the message tag's info.

    *NOTE*  This requires the `TaggingMiddleware` to be configured and placed
            before this middleware for this to work as it expects certain
            values to be set in the `helper_metadata`
    """

    @inlineCallbacks
    def find_account_key_for_message(self, message):
        # NOTE: there is probably a better way of doing this when given a
        #       batch key but I'm not seeing it right now.
        tag = TaggingMiddleware.map_msg_to_tag(message)
        if tag:
            current_tag = yield self.message_store.get_tag_info(tag)
            if current_tag:
                batch = yield current_tag.current_batch.get()
                if batch:
                    returnValue(batch.metadata['user_account'])

    @inlineCallbacks
    def add_metadata_to_message(self, message):
        account_key = yield self.find_account_key_for_message(message)
        if account_key:
            helper_metadata = message.get('helper_metadata', {})
            go_metadata = helper_metadata.setdefault('go', {})
            go_metadata['user_account'] = account_key

    @staticmethod
    def map_message_to_account_key(message):
        go_metadata = message.get('helper_metadata', {}).setdefault('go', {})
        return go_metadata.get('user_account')


class LookupBatchMiddleware(GoApplicationRouterMiddleware):
    """
    Look up a `batch_key` by inspecting the tag for a given message.

    *NOTE*  This requires the `TaggingMiddleware` to be configured and placed
            before this middleware to ensure that the appropriate tagging
            values are set in the `helper_metadata`
    """

    @inlineCallbacks
    def find_batch_for_message(self, message):
        tag = TaggingMiddleware.map_msg_to_tag(message)
        if tag:
            current_tag = yield self.message_store.get_tag_info(tag)
            if current_tag:
                batch = yield current_tag.current_batch.get()
                returnValue(batch)

    @inlineCallbacks
    def add_metadata_to_message(self, message):
        batch = yield self.find_batch_for_message(message)
        if batch:
            helper_metadata = message.get('helper_metadata', {})
            go_metadata = helper_metadata.setdefault('go', {})
            go_metadata['batch_key'] = batch.key

    @staticmethod
    def map_message_to_batch_key(message):
        go_metadata = message.get('helper_metadata', {}).get('go', {})
        return go_metadata.get('batch_key')


class LookupConversationMiddleware(GoApplicationRouterMiddleware):
    """
    Look up a conversation based on the `account_key` and `batch_key` that
    have been stored in the `helper_metadata` by the `LookupAccountMiddleware`
    and the `LookupBatchMiddleware` middlewares.

    *NOTE*  This middleware depends on the `LookupAccountMiddleware`,
            `LookupBatchMiddleware` and the `TaggingMiddleware` being
            configured and placed before this middleware to ensure that the
            appropriate variables are set in the `helper_metadata`
    """

    @inlineCallbacks
    def find_conversation_for_message(self, message):
        account_key = LookupAccountMiddleware.map_message_to_account_key(
                                                                    message)
        batch_key = LookupBatchMiddleware.map_message_to_batch_key(message)
        if account_key and batch_key:
            conversation_store = ConversationStore(self.manager, account_key)
            account_submanager = conversation_store.manager
            batch = self.message_store.batches(batch_key)
            all_conversations = yield batch.backlinks.conversations(
                                                            account_submanager)
            conversations = [c for c in all_conversations if not
                                c.ended()]
            if conversations:
                if len(conversations) > 1:
                    conv_keys = [c.key for c in conversations]
                    log.warning('Multiple conversations found '
                        'going with most recent: %r' % (conv_keys,))
                conversation = sorted(conversations, reverse=True,
                    key=lambda c: c.start_timestamp)[0]
                returnValue(conversation)

    @inlineCallbacks
    def add_metadata_to_message(self, message):
        conversation = yield self.find_conversation_for_message(message)
        if conversation:
            helper_metadata = message.get('helper_metadata', {})
            conv_metadata = helper_metadata.setdefault('conversations', {})
            conv_metadata['conversation_key'] = conversation.key
            conv_metadata['conversation_type'] = conversation.conversation_type

    @staticmethod
    def map_message_to_conversation_info(message):
        helper_metadata = message.get('helper_metadata', {})
        conv_metadata = helper_metadata.get('conversations', {})
        if conv_metadata:
            return (
                conv_metadata['conversation_key'],
                conv_metadata['conversation_type']
            )


class OptOutMiddleware(BaseMiddleware):

    def setup_middleware(self):
        self.keyword_separator = self.config.get('keyword_separator', ' ')
        self.case_sensitive = self.config.get('case_sensitive', False)
        keywords = self.config.get('optout_keywords', [])
        self.optout_keywords = set([self.casing(word)
                                        for word in keywords])

    def casing(self, word):
        if not self.case_sensitive:
            return word.lower()
        return word

    def handle_inbound(self, message, endpoint):
        keyword = (message['content'] or '').strip()
        helper_metadata = message['helper_metadata']
        optout_metadata = helper_metadata.setdefault('optout', {})
        if self.casing(keyword) in self.optout_keywords:
            optout_metadata['optout'] = True
            optout_metadata['optout_keyword'] = self.casing(keyword)
        else:
            optout_metadata['optout'] = False
        return message

    @staticmethod
    def is_optout_message(message):
        return message['helper_metadata'].setdefault('optout').get('optout')


class DebitAccountMiddleware(TransportMiddleware):

    def setup_middleware(self):
        # TODO: There really needs to be a helper function to
        #       turn this config into managers.
        from go.vumitools.api import get_redis
        r_server = get_redis(self.config)
        tpm_config = self.config.get('tagpool_manager', {})
        tpm_prefix = tpm_config.get('tagpool_prefix', 'tagpool_store')
        self.tpm = TagpoolManager(r_server, tpm_prefix)
        cm_config = self.config.get('credit_manager', {})
        cm_prefix = cm_config.get('credit_prefix', 'credit_store')
        self.cm = CreditManager(r_server, cm_prefix)

    def _credits_per_message(self, pool):
        tagpool_metadata = self.tpm.get_metadata(pool)
        credits_per_message = tagpool_metadata.get('credits_per_message')
        try:
            credits_per_message = int(credits_per_message)
            assert credits_per_message >= 0
        except Exception:
            exc_tb = sys.exc_info()[2]
            raise (BadTagPool,
                   BadTagPool("Invalid credits_per_message for pool %r"
                              % (pool,)),
                   exc_tb)
        return credits_per_message

    @staticmethod
    def map_msg_to_user(msg):
        """Convenience method for retrieving a user that was added
        to a message.
        """
        user_account = msg['helper_metadata'].get('go', {}).get('user_account')
        return user_account

    @staticmethod
    def map_payload_to_user(payload):
        """Convenience method for retrieving a user from a payload."""
        go_metadata = payload.get('helper_metadata', {}).get('go', {})
        return go_metadata.get('user_account')

    @staticmethod
    def add_user_to_message(msg, user_account_key):
        """Convenience method for adding a user to a message."""
        go_metadata = msg['helper_metadata'].setdefault('go', {})
        go_metadata['user_account'] = user_account_key

    @staticmethod
    def add_user_to_payload(payload, user_account_key):
        """Convenience method for adding a user to a message payload."""
        helper_metadata = payload.setdefault('helper_metadata', {})
        go_metadata = helper_metadata.setdefault('go', {})
        go_metadata['user_account'] = user_account_key

    def handle_outbound(self, msg, endpoint):
        # TODO: what actually happens when we raise an exception from
        #       inside middleware?
        user_account_key = self.map_msg_to_user(msg)
        if user_account_key is None:
            raise NoUserError(msg)
        tag = TaggingMiddleware.map_msg_to_tag(msg)
        if tag is None:
            raise NoTagError(msg)
        credits_per_message = self._credits_per_message(tag[0])
        self._debit_account(user_account_key, credits_per_message)
        success = self.cm.debit(user_account_key, credits_per_message)
        if not success:
            raise InsufficientCredit("User %r has insufficient credit"
                                     " to debit %r." %
                                     (user_account_key, credits_per_message))
        return msg


class PerAccountLogicMiddleware(BaseMiddleware):

    def setup_middleware(self):
        super(PerAccountLogicMiddleware, self).setup_middleware()
        configured_accounts = self.config.get('accounts', {})
        self.accounts = {}
        for account_key, handlers in configured_accounts.items():
            for handler in handlers:
                [(name, handler_class_name)] = handler.items()
                self.accounts.setdefault(account_key, [])
                handler_config = self.config.get(name, {})
                handler_class = load_class_by_string(handler_class_name)
                handler = handler_class(**handler_config)
                self.accounts[account_key].append(handler)

    def teardown_middleware(self):
        for key, handlers in self.accounts.items():
            for handler in handlers:
                handler.teardown_handler()

    @inlineCallbacks
    def handle_outbound(self, message, endpoint):
        account_key = LookupAccountMiddleware.map_message_to_account_key(
                                                                    message)
        if account_key:
            handlers = self.accounts.get(account_key, [])
            for handler in handlers:
                yield handler.handle_message(message)
        returnValue(message)


class YoPaymentHandler(object):

    def __init__(self, username='', password='', url='', amount=0, reason='',
                    redis={}, poll_manager_prefix='vumigo.'):
        self.username = username
        self.password = password
        self.url = url
        self.amount = amount
        self.reason = reason
        self.pm_prefix = poll_manager_prefix
        self.pm = PollManager(self.get_redis(redis), self.pm_prefix)

    def get_redis(self, config):
        return redis.Redis(**config)

    def teardown_handler(self):
        self.pm.stop()

    def get_auth_headers(self, username, password):
        credentials = base64.b64encode('%s:%s' % (username, password))
        return {
            'Authorization': 'Basic %s' % (credentials.strip(),)
        }

    @inlineCallbacks
    def handle_message(self, message):
        if not self.url:
            log.error('No URL configured for YoPaymentHandler')
            return

        if not message.get('content'):
            return

        helper = LookupConversationMiddleware.map_message_to_conversation_info
        conv_info = helper(message)
        conv_key, conv_type = conv_info

        poll_id = 'poll-%s' % (conv_key,)
        poll_config = self.pm.get_config(poll_id)

        content = message.get('content')
        if not content:
            log.error('No content, skipping')
            return

        if content != poll_config.get('survey_completed_response'):
            log.error("Survey hasn't been completed, continuing")
            return

        request_params = {
            'msisdn': message['to_addr'],
            'amount': self.amount,
            'reason': self.reason,
        }
        response = yield http_request_full(self.url,
            data=urlencode(request_params),
            headers=self.get_auth_headers(self.username, self.password),
            method='GET')
        print response


class SNAUSSDOptOutHandler(object):

    def __init__(self, account_key=None, redis={},
                    poll_manager_prefix='vumigo.', riak={}):
        self.account_key = account_key
        self.pm_prefix = poll_manager_prefix
        self.pm = PollManager(self.get_redis(redis), self.pm_prefix)
        self.manager = TxRiakManager.from_config(riak)
        self.oo_store = OptOutStore(self.manager, self.account_key)
        self.contact_store = ContactStore(self.manager, self.account_key)

    def get_redis(self, config):
        return redis.Redis(**config)

    def teardown_handler(self):
        self.pm.stop()

    @inlineCallbacks
    def handle_message(self, message):
        addr = message['to_addr']
        contact = yield self.contact_store.contact_for_addr('ussd', addr)
        if contact:
            opted_out = contact.extra['opted_out']
            if opted_out is not None:
                if int(opted_out) > 1:
                    yield self.oo_store.new_opt_out('msisdn', addr,
                        message)
                else:
                    yield self.oo_store.delete_opt_out('msisdn', addr)
