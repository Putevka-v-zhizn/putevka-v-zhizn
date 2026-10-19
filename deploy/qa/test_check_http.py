import unittest
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from deploy.qa.check_http import check, main


def response(content_type, body=b'x'):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status = 200
    result.headers = Message()
    result.headers['Content-Type'] = content_type
    result.read.return_value = body
    return result


class QaHttpCheckTests(unittest.TestCase):
    @patch('deploy.qa.check_http.urlopen')
    def test_checks_login_css_and_javascript(self, urlopen):
        urlopen.side_effect = [response('text/html'), response('text/css; charset=utf-8'), response('text/javascript')]
        check('https://qa.example.test/')
        self.assertEqual([call.args[0] for call in urlopen.call_args_list], [
            'https://qa.example.test/admin/login/',
            'https://qa.example.test/static/admin/css/base.css',
            'https://qa.example.test/static/admin/js/core.js',
        ])

    @patch('deploy.qa.check_http.urlopen')
    def test_rejects_html_instead_of_styles(self, urlopen):
        urlopen.side_effect = [response('text/html'), response('text/html')]
        with self.assertRaisesRegex(ValueError, 'Content-Type text/html'):
            check('https://qa.example.test')

    @patch('deploy.qa.check_http.urlopen')
    def test_rejects_empty_styles(self, urlopen):
        urlopen.side_effect = [response('text/html'), response('text/css', b'')]
        with self.assertRaisesRegex(ValueError, 'empty response'):
            check('https://qa.example.test')

    @patch('sys.argv', ['check_http.py', 'https://qa.example.test', '--attempts', '2'])
    @patch('deploy.qa.check_http.time.sleep')
    @patch('deploy.qa.check_http.check')
    def test_retries_and_fails_the_deploy(self, check_request, sleep):
        check_request.side_effect = HTTPError('https://qa.example.test/static/admin/css/base.css', 404, 'Not Found', {}, None)
        with self.assertRaisesRegex(SystemExit, 'QA HTTP check failed'):
            main()
        self.assertEqual(check_request.call_count, 2)
        sleep.assert_called_once_with(2)


if __name__ == '__main__':
    unittest.main()
