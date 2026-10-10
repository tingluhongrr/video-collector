import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import collector
import updater as u


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def release(self):
        return {'info': {'version': '2099.1.1', 'requires_python': '>=3.10', 'requires_dist': []},
                'urls': [{'filename': 'yt_dlp-2099.1.1-py3-none-any.whl', 'url': 'https://files.pythonhosted.org/test.whl',
                          'digests': {'sha256': 'unused'}}]}

    def test_rejects_foreign_wheel_source(self):
        release = self.release()
        release['urls'][0]['url'] = 'https://untrusted.test/test.whl'
        with self.assertRaises(ValueError):
            u.wheel_for(release)

    def test_digest_mismatch(self):
        session = MagicMock()
        response = session.get.return_value.__enter__.return_value
        response.iter_content.return_value = [b'corrupted']
        with self.assertRaises(ValueError):
            u.download_wheel(session, {'url': 'https://files.pythonhosted.org/test',
                                      'digests': {'sha256': hashlib.sha256(b'expected').hexdigest()}}, self.root / 'test.whl')

    def test_rejects_zip_traversal(self):
        path = self.root / 'bad.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('../outside.py', 'oops')
        with self.assertRaises(ValueError):
            u.extract_wheel(path, self.root / 'output', 'yt_dlp')
        self.assertFalse((self.root / 'outside.py').exists())

    def test_failed_update_keeps_manifest(self):
        active = self.root / 'active.json'
        active.write_text('{"version":"old"}')
        with patch.object(u, 'metadata', return_value=self.release()), patch.object(u, 'download_wheel', side_effect=ValueError('bad checksum')):
            with self.assertRaises(ValueError):
                u.update_latest(self.root, force=True)
        self.assertEqual(json.loads(active.read_text())['version'], 'old')

    def test_complete_update_atomically_sets_manifest(self):
        def download(session, item, path):
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('yt_dlp/__init__.py', '')
                archive.writestr('yt_dlp/version.py', "__version__ = '2099.01.01'")
                archive.writestr('yt_dlp-2099.1.1.data/scripts/yt-dlp', 'unused launcher')
        with patch.object(u, 'metadata', return_value=self.release()), patch.object(u, 'download_wheel', side_effect=download):
            result = u.update_latest(self.root, force=True)
        manifest = json.loads((self.root / 'active.json').read_text())
        self.assertEqual(result['status'], 'installed')
        self.assertTrue((self.root / 'releases' / manifest['release'] / 'yt_dlp/version.py').is_file())


if __name__ == '__main__':
    unittest.main()
