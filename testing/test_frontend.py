"""Integration checks for the single Flask frontend and removed legacy interfaces."""
import re
import unittest
from unittest.mock import patch
from soundwaves.web.app import app


class FrontendRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_current_pages_and_their_assets_load(self):
        assets = set()
        for url in ('/', '/live', '/check', '/upload', '/easy', '/convert', '/test'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('class="site-head"', html)
                self.assertIn('/site.css', html)
                assets.update(re.findall(r'(?:src|href)="(/static/[^"]+)"', html))
        for url in assets:
            with self.subTest(asset=url), self.client.get(url) as response:
                self.assertEqual(response.status_code, 200)

    def test_old_pages_redirect_to_current_workflows(self):
        for old, current in (('/practice', '/live'), ('/record', '/check')):
            response = self.client.get(old)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, current)

    def test_removed_demo_and_independent_ipad_are_not_app_assets(self):
        for url in ('/ipad-keys.html', '/static/ipad-keys.html',
                    '/practice-assets/practice.js', '/practice-assets/practice-demo.js'):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_oversized_upload_shows_current_check_page(self):
        with patch.dict(app.config, MAX_CONTENT_LENGTH=1):
            response = self.client.post('/check', data={'bpm': '120'})
        self.assertEqual(response.status_code, 413)
        self.assertIn('Upload too large', response.get_data(as_text=True))
