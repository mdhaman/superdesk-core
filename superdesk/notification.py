# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

"""Superdesk push notifications"""

import os
import logging
import asyncio
import websockets

from flask import current_app as app, json
from datetime import datetime
from superdesk.utils import json_serialize_datetime_objectId
from superdesk.websockets_broker import SocketMessageProducer


logger = logging.getLogger(__name__)


class ClosedSocket():
    """Mimic closed socket to simplify logic when connection
    can't be estabilished at first place.
    """
    def __init__(self):
        self.open = False

    def close(self):
        pass


def init_app(app):
    """Create websocket connection and put it on app object."""
    host = app.config['WS_HOST']
    port = app.config['WS_PORT']
    use_pub_sub = app.config.get('USE_PUB_SUB_FOR_WEBSOCKETS', False)
    try:
        if use_pub_sub:
            app.socket_message_producer = SocketMessageProducer(app.config['BROKER_URL'])
            logger.info('socket message producer started...')
        else:
            try:
                loop = asyncio.get_event_loop()
            except:
                loop = asyncio.new_event_loop()

            app.notification_client = loop.run_until_complete(websockets.connect('ws://%s:%s/server' % (host, port)))
            logger.info('websocket connected on=%s:%s' % app.notification_client.local_address)

    except (RuntimeError, OSError):
        # not working now, but we can try later when actually sending something
        if use_pub_sub:
            app.socket_message_producer = ClosedSocket()
        else:
            app.notification_client = ClosedSocket()


def _notify(message):

    @asyncio.coroutine
    def send_message():
        yield from app.notification_client.send(message)

    try:
        loop = asyncio.get_event_loop()
    except:
        loop = asyncio.new_event_loop()
    loop.run_until_complete(send_message())


def _create_socket_message(**kwargs):
    """Send out all kwargs as json string."""
    kwargs.setdefault('_created', datetime.utcnow().isoformat())
    kwargs.setdefault('_process', os.getpid())
    return json.dumps(kwargs, default=json_serialize_datetime_objectId)


def push_notification(name, **kwargs):
    """Push notification to websocket.

    In case socket is closed it will try to reconnect.

    :param name: event name
    """
    logger.info('pushing event {0} ({1})'.format(name, json.dumps(kwargs, default=json_serialize_datetime_objectId)))
    if app.config.get('USE_PUB_SUB_FOR_WEBSOCKETS', False):
        _push_notification_via_broker(name, **kwargs)
    else:
        _push_notification_via_sockets(name, **kwargs)


def _push_notification_via_broker(name, **kwargs):
    """
    Push the event via broker
    """
    if not app.socket_message_producer.open:
        app.socket_message_producer.close()
        init_app(app)

    if not app.socket_message_producer.open:
        logger.info('No connection to broker. Dropping event %s' % name)
        return

    try:
        message = _create_socket_message(event=name, extra=kwargs)
        logger.info('Sending the message to the broker...')
        app.socket_message_producer.send(message)
    except Exception as err:
        logger.exception(err)


def _push_notification_via_sockets(name, **kwargs):
    """
    Push the event via sockets
    """
    if not app.notification_client.open:
        app.notification_client.close()
        init_app(app)

    if not app.notification_client.open:
        logger.info('No connection to websocket server. Dropping event %s' % name)
        return
    try:
        message = _create_socket_message(event=name, extra=kwargs)
        logger.info('Sending the message to the socket...')
        _notify(message)
    except Exception as err:
        logger.exception(err)
