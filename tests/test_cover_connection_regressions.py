"""Regression tests for v0.7.1 cover connections. Uses fake HTTP; no API keys or internet."""
from pathlib import Path
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cover_downloader as art


class FakeResponse:
    def __init__(self, body, url):
        self.data, self.url = body, url
        self.headers={'Content-Length': str(len(body))}
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, count): return self.data[:count]
    def geturl(self): return self.url


class FakeOpener:
    def __init__(self, response=None, exc=None):
        self.response, self.exc = response, exc
    def open(self, req, timeout=None):
        if self.exc: raise self.exc
        return self.response


class ConnectionTests(unittest.TestCase):
    def test_plain_and_pasted_key(self):
        for text in ('abcDEF0123','Bearer abcDEF0123', ' "abcDEF0123" ', '\ufeffabcDEF0123\n'):
            self.assertEqual(art.normalise_api_key(text),'abcDEF0123')
        for text in ('abc def','abc\rdef','a\u200db',''):
            with self.assertRaises(art.CoverError): art.normalise_api_key(text)

    def test_proxy_value_error_retries_direct_success(self):
        url='https://www.steamgriddb.com/api/v2/search/autocomplete/Mario'
        data=b'{"success":true,"data":[]}'
        fake=FakeOpener(FakeResponse(data,url))
        with patch.object(art,'urlopen',side_effect=ValueError('Malformed system proxy')),\
             patch.object(art,'build_opener',return_value=fake) as build:
            response=art._json(url, {'Authorization':'Bearer DEMO_ONLY'})
        self.assertTrue(response['success'])
        build.assert_called_once()

    def test_http_401_not_mislabeled_as_connection_failure(self):
        url='https://www.steamgriddb.com/api/v2/search/autocomplete/Mario'
        error=HTTPError(url,401,'Unauthorized',{},io.BytesIO())
        with patch.object(art,'urlopen',side_effect=error),\
             patch.object(art,'build_opener') as fallback:
            with self.assertRaisesRegex(art.CoverError,'HTTP 401') as caught:
                art._json(url, {'Authorization':'Bearer SUPERSECRET_TEST_TOKEN'})
        self.assertNotIn('SUPERSECRET_TEST_TOKEN',str(caught.exception))
        fallback.assert_not_called()

    def test_http_statuses(self):
        url='https://www.steamgriddb.com/api/v2/search/autocomplete/Mario'
        for code in (400,403,404,429,503):
            with self.subTest(code=code):
                with patch.object(art,'urlopen',side_effect=HTTPError(url,code,'fail',{},io.BytesIO())):
                    with self.assertRaisesRegex(art.CoverError, str(code)):
                        art._get(url)

    def test_double_proxy_failure_reports_proxy_not_key(self):
        url='https://www.steamgriddb.com/api/v2/search/autocomplete/Mario'
        with patch.object(art,'urlopen',side_effect=ValueError('Bad proxy')),\
             patch.object(art,'build_opener',return_value=FakeOpener(exc=ValueError('Bad proxy'))):
            with self.assertRaisesRegex(art.CoverError,'proxy') as ctx:
                art._get(url)
        self.assertNotIn('authorization rejected',str(ctx.exception))

    def test_direct_connection_failure_reports_network(self):
        url='https://www.steamgriddb.com/api/v2/search/autocomplete/Mario'
        with patch.object(art,'urlopen',side_effect=URLError('Name or service not known')):
            with self.assertRaisesRegex(art.CoverError,'network, DNS, or proxy'):
                art._get(url)

    def test_key_test_endpoint_and_token(self):
        with patch.object(art,'_json',return_value={'success':True,'data':[]}) as call:
            self.assertTrue(art.test_steamgriddb_key('Bearer sample_key'))
        args, kwargs = call.call_args
        self.assertTrue(args[0].endswith('/search/autocomplete/Mario'))
        self.assertEqual(args[1]['Authorization'],'Bearer sample_key')

    def test_api_secret_never_in_user_facing_error(self):
        with patch.object(art,'_get',side_effect=art.CoverError('provider returned HTTP 401')):
            with self.assertRaises(art.CoverError) as ctx:
                art.test_steamgriddb_key('my_private_test_secret')
        self.assertNotIn('my_private_test_secret',str(ctx.exception))


if __name__=='__main__':unittest.main()
