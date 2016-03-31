#!/usr/bin/env python
# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014, 2015 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

import logging
import asyncio

from kombu import Queue, Exchange, Connection
from kombu.mixins import ConsumerMixin
from kombu.pools import producers
from superdesk.utils import get_random_string

logger = logging.getLogger(__name__)
exchange_name = 'socket_notification'


class SocketTransport:
    """
    Base class for message using broker (redis or rabbitmq)

    """
    def __init__(self, url):
        self.url = url
        self.connection = self.connect()
        self.channel = self.connection.channel()
        self.socket_exchange = Exchange(exchange_name, type='fanout', channel=self.channel)
        self.socket_exchange.declare()

    def open(self):
        return self.connection and self.connection.connected

    def connect(self):
        logger.info('Connecting to broker {}'.format(self.url))
        conn = Connection(self.url)
        conn.connect()
        logger.info('Connected to broker {}'.format(self.url))
        return conn

    def close(self):
        if hasattr(self, 'connection') and self.connection:
            logger.info('Closing connecting to broker {}'.format(self.url))
            self.connection.release()
            self.connection = None
            logger.info('Connection closed to broker {}'.format(self.url))


class SocketMessageProducer(SocketTransport):
    """
    Publishes messages to a exchange (fanout).
    """
    def __init__(self, url):
        super().__init__(url)

    def send(self, message):
        """
        Publishes the message to an exchange
        :param str message: message to be publishes
        """
        with producers[self.connection].acquire(block=True) as producer:
            producer.publish(message, exchange=self.socket_exchange)
            logger.debug('message:{} published to broker:{}.'.format(message, self.url))


class SocketMessageConsumer(SocketTransport, ConsumerMixin):
    """
    Consumer of the message.
    """
    def __init__(self, url, callback):
        """
        :param string url:
        :param callback: On receiving the message by the consumer following should be called
        """
        super().__init__(url)
        self.callback = callback
        self.queue_name = 'socket_consumer_{}'.format(get_random_string())
        self.queue = Queue(self.queue_name, exchange=self.socket_exchange, channel=self.channel)

    def get_consumers(self, Consumer, channel):
        return [Consumer(queues=[self.queue], callbacks=[self.on_message])]

    def on_message(self, body, message):
        """
        Event fired when message is received by the queue
        :param str body:
        :param kombu.Message message: Message object
        """
        try:
            try:
                loop = asyncio.get_event_loop()
            except:
                loop = asyncio.new_event_loop()

            logger.debug('Queue: {}. Broadcasting message {}'.format(self.queue_name, body))
            loop.run_until_complete(self.callback(body))
        except:
            logger.exception('Dropping event. Failed to send message {}.'.format(body))
        try:
            message.ack()
        except:
            logger.exception('Failed to ack message {} on queue {}.'.format(body, self.queue_name))

    def close(self):
        """
        Closing the consumer.
        :return:
        """
        logger.info('closing consumer')
        self.should_stop = True
        try:
            self.queue.delete()
        except:
            logger.exception('Failed to delete queue {}.'.format(self.queue_name))
        logger.info('queue: {} deleted'.format(self.queue_name))
        super().close()
        logger.info('consumer terminated successfully')
