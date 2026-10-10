import http.cookiejar
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import collector as c
import site_config as sc


def cookie(domain, name='session', expired=False):
    return http.cookiejar.Cookie(0, name, 'test-value', None, False, domain, True, domain.startswith('.'),
                                 '/', True, False, 1 if expired else None, not expired, None, None, {}, False)


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_domain_boundary_and_expiry(self):
        jar = [cookie('.bilibili.com'), cookie('.youtube.com'), cookie('.bilibili.com.evil.test'),
               cookie('.bilibili.com', 'old', expired=True)]
        result = sc.store_cookies(jar, self.root, 'bilibili', 'test')
        self.assertEqual(result['count'], 1)
        text = Path(result['path']).read_text()
        self.assertNotIn('youtube', text)
        self.assertNotIn('evil', text)
        self.assertNotIn('\told\t', text)

    def test_file_import_filters_other_sites(self):
        jar = http.cookiejar.MozillaCookieJar(str(self.root / 'input.txt'))
        jar.set_cookie(cookie('.douyin.com'))
        jar.set_cookie(cookie('.youtube.com'))
        jar.save(ignore_discard=True)
        result = sc.import_cookies(self.root / 'input.txt', self.root / 'managed', 'douyin')
        self.assertEqual(result['count'], 1)
        self.assertNotIn('youtube', Path(result['path']).read_text())

    def test_browser_button_delegates_and_filters(self):
        for browser in ('chrome', 'edge', 'firefox'):
            with patch('yt_dlp.cookies.extract_cookies_from_browser', return_value=[cookie('.douyin.com')]) as read:
                result = sc.read_browser_cookies(browser, self.root, 'douyin')
            self.assertEqual(read.call_args.args[0], browser)
            self.assertEqual(result['count'], 1)

    def test_missing_cookies_preserves_existing_file(self):
        sc.store_cookies([cookie('.douyin.com')], self.root, 'douyin', 'test')
        before = (self.root / 'douyin.cookies.txt').read_bytes()
        with self.assertRaises(ValueError):
            sc.store_cookies([cookie('.youtube.com')], self.root, 'douyin', 'test')
        self.assertEqual((self.root / 'douyin.cookies.txt').read_bytes(), before)

    def test_profiles_do_not_inherit_other_sites(self):
        settings = c.Settings(cookies='global.txt', proxy='http://global', site_profiles={
            'bilibili': {'cookies': 'bili.txt', 'proxy': ''},
            'youtube': {'cookies': '', 'proxy': 'http://youtube'},
            'douyin': {'cookies': 'douyin.txt', 'proxy': ''}})
        bili = c.settings_for_url(settings, 'https://b23.tv/abc')
        youtube = c.settings_for_url(settings, 'https://youtu.be/jNQXAC9IVRw')
        douyin = c.settings_for_url(settings, 'https://v.douyin.com/abc')
        self.assertEqual(bili.cookies, 'bili.txt')
        self.assertIsNone(bili.proxy)
        self.assertIsNone(youtube.cookies)
        self.assertEqual(youtube.proxy, 'http://youtube')
        self.assertEqual(douyin.cookies, 'douyin.txt')
        self.assertIsNone(douyin.proxy)

    def test_config_persists_separate_profiles(self):
        cfg = sc.default_config()
        cfg['sites']['youtube']['proxy'] = 'http://localhost:7890'
        sc.save_config(self.root / 'config.json', cfg)
        actual = sc.load_config(self.root / 'config.json')
        self.assertEqual(actual['sites']['youtube']['proxy'], 'http://localhost:7890')
        self.assertEqual(actual['sites']['douyin']['proxy'], '')

    def test_theme_is_saved_and_legacy_or_invalid_preferences_use_light(self):
        path = self.root / 'config.json'
        config = sc.default_config()
        config['theme'] = 'dark'
        config['sites']['youtube']['proxy'] = 'http://127.0.0.1:7890'
        sc.save_config(path, config)
        self.assertEqual(sc.load_config(path)['theme'], 'dark')
        self.assertEqual(sc.load_config(path)['sites']['youtube']['proxy'], config['sites']['youtube']['proxy'])
        for theme in (None, 'unknown-theme'):
            legacy = {'sites': config['sites'], 'update_proxy': 'http://127.0.0.1:7891'}
            if theme is not None:
                legacy['theme'] = theme
            path.write_text(json.dumps(legacy), encoding='utf-8')
            loaded = sc.load_config(path)
            self.assertEqual(loaded['theme'], 'light')
            self.assertEqual(loaded['sites'], config['sites'])
            self.assertEqual(loaded['update_proxy'], legacy['update_proxy'])

    def test_completion_notification_preference_is_boolean_and_defaults_on(self):
        path = self.root / 'config.json'
        self.assertIs(sc.default_config()['completion_notifications'], True)
        legacy = {'sites': sc.default_config()['sites'], 'update_proxy': ''}
        path.write_text(json.dumps(legacy), encoding='utf-8')
        self.assertIs(sc.load_config(path)['completion_notifications'], True)
        config = sc.default_config()
        config['completion_notifications'] = False
        sc.save_config(path, config)
        self.assertIs(sc.load_config(path)['completion_notifications'], False)

    def test_cookie_errors_suggest_manager(self):
        for message in ('HTTP Error 403', 'HTTP Error 412', 'Fresh cookies needed'):
            self.assertIn('尝试更新 Cookie', c.error_hint(message))


if __name__ == '__main__':
    unittest.main()
