# -*- coding: utf-8 -*-

"""
Copyright (C) 2013 Dariusz Suchojad <dsuch at zato.io>

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
import ssl
from logging import getLogger
from tempfile import NamedTemporaryFile
from time import sleep
from traceback import format_exc
from unittest import TestCase

# bunch
from bunch import Bunch

# nose
from nose.tools import eq_

# requests
import requests

# Zato
from zato.common import URL_TYPE, ZATO_NONE
from zato.common.test import rand_float, rand_int, rand_string
from zato.common.test.tls import TLS_PORT, TLSServer
from zato.common.test.tls_material import ca_cert, ca_cert_invalid, client1_cert, client1_key
from zato.server.connection.http_soap.outgoing import HTTPSOAPWrapper

logger = getLogger(__name__)

class _FakeSession(object):
    def __init__(self, *ignored, **kwargs):
        self.pool_size = kwargs.get('pool_maxsize', 'missing')
        self.request_args = None
        self.request_kwargs = None

    def request(self, *args, **kwargs):
        self.request_args = args
        self.request_kwargs = kwargs

        return Bunch({'status_code':rand_string(), 'text':rand_string()})

class _FakeRequestsModule(object):
    def __init__(self):
        self.session_obj = None

    def session(self, *args, **kwargs):
        self.session_obj = _FakeSession(*args, **kwargs)
        return self.session_obj

class Base(object):

    def _get_config(self):
        return {'is_active':True, 'sec_type':rand_string(), 'address_host':rand_string(), 
            'address_url_path':rand_string(), 'ping_method':rand_string(), 'soap_version':'1.1',
            'pool_size':rand_int(), 'serialization_type':'string', 'timeout':rand_int(),
            'tls_verify':ZATO_NONE}

class HTTPSOAPWrapperTestCase(TestCase, Base):
    
    def test_ping_method(self):
        """ https://github.com/zatosource/zato/issues/44 (outconn HTTP/SOAP ping method)
        """
        config = self._get_config()
        expected_ping_method = 'ping-{}'.format(rand_string())
        config['ping_method'] = expected_ping_method
        requests_module = _FakeRequestsModule()

        wrapper = HTTPSOAPWrapper(config, requests_module)
        wrapper.ping(rand_string())

        ping_method = requests_module.session_obj.request_args[0]
        eq_(expected_ping_method, ping_method)

    def test_pool_size(self):
        """ https://github.com/zatosource/zato/issues/77 (outconn HTTP/SOAP pool size)
        """
        config = self._get_config()
        expected_pool_size = rand_int()
        config['pool_size'] = expected_pool_size
        requests_module = _FakeRequestsModule()

        wrapper = HTTPSOAPWrapper(config, requests_module)
        wrapper.ping(rand_string())

        eq_(expected_pool_size, requests_module.session_obj.pool_size)

    def test_timeout(self):
        """ https://github.com/zatosource/zato/issues/112 (HTTP timeouts)
        """
        for name in 'ping', 'get', 'delete', 'options', 'post', 'send', 'put', 'patch':
            for transport in URL_TYPE:
                config = self._get_config()
                config['transport'] = transport
                expected_timeout = rand_float()
                config['timeout'] = expected_timeout
                requests_module = _FakeRequestsModule()

                wrapper = HTTPSOAPWrapper(config, requests_module)
                func = getattr(wrapper, name)
                func(rand_string())

                self.assertIn('timeout', requests_module.session_obj.request_kwargs)
                eq_(expected_timeout, requests_module.session_obj.request_kwargs['timeout'])

    def test_set_address(self):
        address_host = rand_string()
        config = self._get_config()
        config['address_host'] = address_host
        requests_module = _FakeRequestsModule()

        for address_url_path in('/zzz', '/cust/{customer}/order/{order}/pid{process}/',):
            config['address_url_path'] = address_url_path
            wrapper = HTTPSOAPWrapper(config, requests_module)

            eq_(wrapper.address, '{}{}'.format(address_host, address_url_path))

            if address_url_path == '/zzz':
                eq_(wrapper.path_params, [])
            else:
                eq_(wrapper.path_params, ['customer', 'order', 'process'])

    def test_format_address(self):
        cid = rand_string()
        address_host = rand_string()
        address_url_path = '/a/{a}/b{b}/c-{c}/{d}d/'

        config = self._get_config()
        config['address_host'] = address_host
        config['address_url_path'] = address_url_path

        requests_module = _FakeRequestsModule()
        wrapper = HTTPSOAPWrapper(config, requests_module)

        try:
            wrapper.format_address(cid, None)
        except ValueError, e:
            eq_(e.message, 'CID:[{}] No parameters given for URL path'.format(cid))
        else:
            self.fail('Expected ValueError (params is None)')

        a = rand_string()
        b = rand_string()
        c = rand_string()
        d = rand_string()
        e = rand_string()
        f = rand_string()

        params = {'a':a, 'b':b, 'c':c, 'd':d, 'e':e, 'f':f}
        address, non_path_params = wrapper.format_address(cid, params)
        eq_(address, '{}/a/{}/b{}/c-{}/{}d/'.format(address_host, a, b, c, d))
        eq_(non_path_params, {'e':e, 'f':f})

        params = {'a':a, 'b':b}

        try:
            address, non_path_params = wrapper.format_address(cid, params)
        except ValueError, e:
            eq_(e.message, 'CID:[{}] Could not build URL path'.format(cid))
        else:
            self.fail('Expected ValueError (not enough keys in params)')

    def test_http_methods(self):
        address_host = rand_string()

        config = self._get_config()
        config['is_active'] = True
        config['soap_version'] = '1.2'
        config['address_host'] = address_host

        requests_module = _FakeRequestsModule()
        wrapper = HTTPSOAPWrapper(config, requests_module)

        for address_url_path in('/zzz', '/a/{a}/b/{b}'):
            for transport in('soap', rand_string()):
                for name in('get', 'delete', 'options', 'post', 'put', 'patch'):
                    config['transport'] = transport

                    _cid = rand_string()
                    _data = rand_string()

                    expected_http_request_value = rand_string()
                    expected_http_request_value = rand_string()

                    expected_params = rand_string()

                    expected_args1 = rand_string()
                    expected_args2 = rand_string()

                    expected_kwargs1 = rand_string()
                    expected_kwargs2 = rand_string()

                    def http_request(method, cid, data='', params=None, *args, **kwargs):

                        eq_(method, name.upper())
                        eq_(cid, _cid)

                        if name in('get', 'delete', 'options'):
                            eq_(data, '')
                        else:
                            eq_(data, _data)

                        eq_(params, expected_params)
                        eq_(args, (expected_args1, expected_args2))
                        eq_(sorted(kwargs.items()), [('bar', expected_kwargs2), ('foo', expected_kwargs1)])

                        return expected_http_request_value

                    def format_address(cid, params):
                        return expected_http_request_value

                    wrapper.http_request = http_request
                    wrapper.format_address = format_address

                    func = getattr(wrapper, name)

                    if name in('get', 'delete', 'options'):
                        http_request_value = func(
                            _cid, expected_params, expected_args1, expected_args2,
                            foo=expected_kwargs1, bar=expected_kwargs2)
                    else:
                        http_request_value = func(
                            _cid, _data, expected_params, expected_args1, expected_args2,
                            foo=expected_kwargs1, bar=expected_kwargs2)

                    eq_(http_request_value, expected_http_request_value)

class TLSTestCase(TestCase, Base):

    def test_ping_unknown_ca_verify_false(self):
        server = TLSServer()
        server.start()

        sleep(0.3)

        port = server.get_port()

        config = self._get_config()
        config['address_host'] = 'https://localhost:{}/'.format(port)
        config['address_url_path'] = ''
        config['ping_method'] = 'GET'
        config['tls_verify'] = ZATO_NONE

        requests_module = _FakeRequestsModule()
        wrapper = HTTPSOAPWrapper(config, requests)

        self.assertIn('Code: 200', wrapper.ping(rand_string()))

    def test_ping_unknown_ca_verify_invalid_ca_cert(self):

        with NamedTemporaryFile(prefix='zato-tls', delete=False) as ca_cert_tf:

            ca_cert_tf.write(ca_cert_invalid)
            ca_cert_tf.flush()

            server = TLSServer()
            server.start()

            sleep(0.3)

            port = server.get_port()

            config = self._get_config()
            config['address_host'] = 'https://localhost:{}/'.format(port)
            config['address_url_path'] = ''
            config['ping_method'] = 'GET'
            config['tls_verify'] = ca_cert_tf.name

            requests_module = _FakeRequestsModule()
            wrapper = HTTPSOAPWrapper(config, requests)

            try:
                wrapper.ping(rand_string())
            except Exception, e:
                self.assertIn('SSL3_GET_SERVER_CERTIFICATE:certificate verify failed', e.message[0][1])
            else:
                self.fail('Excepted a TLS error here because the CA is invalid')

    def test_ping_client_cert_required_no_client_cert(self):

        with NamedTemporaryFile(prefix='zato-tls', delete=False) as ca_cert_tf:

            ca_cert_tf.write(ca_cert)
            ca_cert_tf.flush()

            server = TLSServer(cert_reqs=ssl.CERT_REQUIRED)
            server.start()

            sleep(0.3)

            port = server.get_port()

            config = self._get_config()
            config['address_host'] = 'https://localhost:{}/'.format(port)
            config['address_url_path'] = ''
            config['ping_method'] = 'GET'
            config['tls_verify'] = ca_cert_tf.name

            requests_module = _FakeRequestsModule()
            wrapper = HTTPSOAPWrapper(config, requests)

            try:
                wrapper.ping(rand_string())
            except Exception, e:
                self.assertIn('SSL3_READ_BYTES:sslv3 alert handshake failure', e.message[0][1])
            else:
                self.fail('Excepted a TLS error here because no TLS cert has been provided by client')

    def test_ping_client_cert_required_has_client_cert(self):

        with NamedTemporaryFile(prefix='zato-tls', delete=False) as ca_cert_tf:

            ca_cert_tf.write(ca_cert)
            ca_cert_tf.flush()

            with NamedTemporaryFile(prefix='zato-tls', delete=False) as client_cert_tf:

                client_cert_tf.write(client1_cert)
                client_cert_tf.write('\n')
                client_cert_tf.write(client1_key)

                server = TLSServer(cert_reqs=ssl.CERT_REQUIRED)
                server.start()
    
                sleep(0.3)

                port = server.get_port()

                config = self._get_config()
                config['address_host'] = 'https://localhost:{}/'.format(port)
                config['address_url_path'] = ''
                config['ping_method'] = 'GET'
                config['tls_verify'] = ca_cert_tf.name
                SEC

                requests_module = _FakeRequestsModule()
                wrapper = HTTPSOAPWrapper(config, requests)

                wrapper.ping(rand_string())
