# -*- coding: utf-8 -*-

"""
Copyright (C) 2018, Zato Source s.r.o. https://zato.io

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

"""
   Copyright 2006-2008 SpringSource (http://springsource.com), All Rights Reserved

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""

# stdlib
import logging
import sys
from json import loads
from logging import basicConfig, DEBUG, Formatter, getLogger, INFO, StreamHandler
from logging.handlers import RotatingFileHandler
from os import getpid, getppid, path
from thread import start_new_thread
from threading import RLock
from traceback import format_exc
from wsgiref.simple_server import make_server
import httplib

# Bunch
from bunch import Bunch, bunchify

# ThreadPool
from threadpool import ThreadPool, WorkRequest, NoResultsPending

# YAML
import yaml

# Zato
from zato.common.auth_util import parse_basic_auth
from zato.common.broker_message import code_to_name, DEFINITION
from zato.common.zato_keyutils import KeyUtils
from zato.server.connection.jms_wmq.jms import WebSphereMQJMSException, NoMessageAvailableException
from zato.server.connection.jms_wmq.jms.connection import WebSphereMQConnection
from zato.server.connection.jms_wmq.jms.core import TextMessage

# ################################################################################################################################

default_logging_config = {
    'loggers': {
        'zato_websphere_mq': {
            'qualname': 'zato_websphere_mq', 'level': 'INFO', 'propagate': False, 'handlers': ['websphere_mq']}
    },
    'handlers': {
        'websphere_mq': {
            'formatter': 'default', 'backupCount': 10, 'mode': 'a', 'maxBytes': 20000000, 'filename': './logs/websphere-mq.log'
        },
    },
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - %(process)d:%(threadName)s - %(name)s:%(lineno)d - %(message)s'}
    }
}

# ################################################################################################################################

_http_200 = b'{} {}'.format(httplib.OK, httplib.responses[httplib.OK])
_http_400 = b'{} {}'.format(httplib.BAD_REQUEST, httplib.responses[httplib.BAD_REQUEST])
_http_403 = b'{} {}'.format(httplib.FORBIDDEN, httplib.responses[httplib.FORBIDDEN])
_http_500 = b'{} {}'.format(httplib.INTERNAL_SERVER_ERROR, httplib.responses[httplib.INTERNAL_SERVER_ERROR])

# ################################################################################################################################

class WebSphereMQTask(object):
    """ A process to listen for messages and to send them to WebSphere MQ queue managers.
    """
    def __init__(self, conn, on_message_callback):
        self.conn = conn
        self.on_message_callback = on_message_callback
        self.handlers_pool = ThreadPool(5)
        self.keep_running = True
        self.has_debug = self.logger.isEnabledFor(DEBUG)

# ################################################################################################################################

    def _get_destination_info(self):
        return 'destination:`%s`, %s' % (self.destination, self.conn.get_connection_info())

# ################################################################################################################################

    def send(self, payload, queue_name):
        return self.conn.send(TextMessage(payload), queue_name)

# ################################################################################################################################

    def listen_for_messages(self, queue_name):
        """ Runs a background queue listener in its own  thread.
        """
        def _impl():
            while self.keep_running:
                try:
                    message = self.conn.receive(queue_name, 1000)
                    if self.has_debug:
                        self.logger.debug('Message received `%s`' % str(message).decode('utf-8'))

                    work_request = WorkRequest(self.on_message_callback, [message])
                    self.handlers_pool.putRequest(work_request)

                    try:
                        self.handlers_pool.poll()
                    except NoResultsPending, e:
                        pass

                except NoMessageAvailableException, e:
                    if self.has_debug:
                        self.logger.debug('Consumer did not receive a message. `%s`' % self._get_destination_info())

                except WebSphereMQJMSException, e:
                    self.logger.error('%s in run, completion_code:`%s`, reason_code:`%s`' % (
                        e.__class__.__name__, e.completion_code, e.reason_code))
                    raise

        # Start listener in a thread
        start_new_thread(_impl, ())

# ################################################################################################################################

class ConnectionContainer(object):
    def __init__(self):
        self.host = '127.0.0.1'
        self.port = None
        self.username = None
        self.password = None
        self.basic_auth_expected = None
        self.server_pid = None
        self.server_name = None
        self.cluster_name = None
        self.logger = None

        self.parent_pid = getppid()
        self.keyutils = KeyUtils('zato-wmq', self.parent_pid)
        self.lock = RLock()
        self.connections = {}
        self.set_config()

    def set_config(self):
        """ Sets self attributes, as configured in keyring by our parent process.
        """
        '''
        config = self.keyutils.user_get()
        config = loads(config)
        config = bunchify(config)
        '''

        self.port = 34567#config.port
        self.base_dir = '/home/dsuch/env/qs-ps2/server1'
        '''
        self.username = config.username
        self.password = config.password
        self.server_pid = config.server_pid
        self.server_name = config.server_name
        self.cluster_name = config.cluster_name
        self.base_dir = config.base_dir
        '''

        with open('/home/dsuch/env/qs-ps2/server1/config/repo/logging.conf') as f:#config.logging_conf_path) as f:
            logging_config = yaml.load(f)

        # WebSphere MQ logging configuration is new in Zato 3.0, so it's optional.
        if not 'zato_websphere_mq' in logging_config['loggers']:
            logging_config = default_logging_config

        self.set_up_logging(logging_config)

# ################################################################################################################################

    def set_up_logging(self, config):

        logger_conf = config['loggers']['zato_websphere_mq']
        wmq_handler_conf = config['handlers']['websphere_mq']
        del wmq_handler_conf['formatter']
        del wmq_handler_conf['class']
        formatter_conf = config['formatters']['default']['format']

        self.logger = getLogger(logger_conf['qualname'])
        self.logger.setLevel(getattr(logging, logger_conf['level']))

        formatter = Formatter(formatter_conf)

        wmq_handler_conf['filename'] = path.abspath(path.join(self.base_dir, wmq_handler_conf['filename']))
        wmq_handler = RotatingFileHandler(**wmq_handler_conf)
        wmq_handler.setFormatter(formatter)

        stdout_handler = StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)

        self.logger.addHandler(wmq_handler)
        self.logger.addHandler(stdout_handler)

# ################################################################################################################################

    def on_mq_message_received(self, msg):
        self.logger.info('MQ message received %s', msg)

# ################################################################################################################################

    def add_conn_def(self, config):
        with self.lock:
            conn = WebSphereMQConnection(**config)
            conn.connect()

            self.connections[config.name] = conn

# ################################################################################################################################

    def add_channel(self, config):
        with self.lock:

            task = WebSphereMQTask(conn, self.on_mq_message_received)
            task.listen_for_messages('DEV.QUEUE.1')

            import time
            time.sleep(1)

            for x in range(40):
                task.send('aaa', 'DEV.QUEUE.1')

            time.sleep(2)

            #print(conn.receive('DEV.QUEUE.1', 100))

# ################################################################################################################################

    def _on_DEFINITION_JMS_WMQ_CREATE(self, msg):
        pass

# ################################################################################################################################

    def _on_DEFINITION_JMS_WMQ_EDIT(self, msg):
        pass

# ################################################################################################################################

    def _on_DEFINITION_JMS_WMQ_DELETE(self, msg):
        pass

# ################################################################################################################################

    def handle_http_request(self, msg):
        """ Dispatches incoming HTTP requests - either reconfigures the connector or puts messages to queues.
        """
        self.logger.warn('MSG received %s', msg)
        msg = bunchify(loads(msg))
        action = msg.action

        self.logger.info(msg)
        return b'OK'

# ################################################################################################################################

    def check_credentials(self, auth):
        """ Checks incoming username/password and returns True only if they were valid and as expected.
        """
        return True
        username, password = parse_basic_auth(auth)

        if username != self.username:
            self.logger.warn('Invalid username or password')
            return

        elif password != self.password:
            self.logger.warn('Invalid username or password')
            return
        else:
            # All good, we let the request in
            return True

# ################################################################################################################################

    def on_wsgi_request(self, environ, start_response):
        try:
            content_length = environ['CONTENT_LENGTH']
            if not content_length:
                status = _http_400
                response = 'Missing content'
                content_type = 'text/plain'
            else:
                data = environ['wsgi.input'].read(int(content_length))
                if self.check_credentials(environ.get('HTTP_AUTHORIZATION')):
                    status = _http_200
                    response = self.handle_http_request(data)
                    content_type = 'text/json'
                else:
                    status = _http_403
                    response = 'You are not allowed to access this resource'
                    content_type = 'text/plain'

        except Exception as e:
            self.logger.warn(format_exc())
            content_type = 'text/plain'
            status = _http_500
            response = 'Internal server error'
        finally:
            headers = [('Content-type', content_type)]
            start_response(status, headers)

            return [response]

# ################################################################################################################################

    def run(self):
        server = make_server(self.host, self.port, self.on_wsgi_request)
        server.serve_forever()

# ################################################################################################################################

if __name__ == '__main__':

    container = ConnectionContainer()
    container.run()

# ################################################################################################################################