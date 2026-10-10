import copy
import functools
import http.server
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import collector as c
from yt_dlp import YoutubeDL

YT = 'https://www.youtube.com/watch?v=BaW_jenozKc'
BILI = 'https://www.bilibili.com/video/BV13x41117TL?p=2'


class InputTests(unittest.TestCase):
    def test_youtube_removes_playlist(self):
        self.assertEqual(c.normalize_url(YT + '&list=PL123&index=4'), YT)

    def test_short_and_mobile(self):
        for url in ['https://youtu.be/BaW_jenozKc?t=10',
                    'https://m.youtube.com/shorts/BaW_jenozKc']:
            self.assertEqual(c.normalize_url(url), YT)

    def test_bili_parts_are_distinct(self):
        urls, errors = c.parse_inputs(BILI + '\n' + BILI.replace('p=2', 'p=1'))
        self.assertEqual(len(urls), 2)
        self.assertFalse(errors)

    def test_bv_and_dedupe(self):
        urls, _ = c.parse_inputs('BV13x41117TL\nhttps://www.bilibili.com/video/BV13x41117TL')
        self.assertEqual(urls, [BILI.replace('p=2', 'p=1')])

    def test_share_text(self):
        urls, errors = c.parse_inputs('7.82 分享一个视频 https://v.douyin.com/AbC123/ 复制打开抖音')
        self.assertEqual(urls, ['https://v.douyin.com/AbC123/'])
        self.assertFalse(errors)

    def test_douyin_modal_and_mobile(self):
        for url in ['https://www.douyin.com/?modal_id=123456',
                    'https://www.iesdouyin.com/share/video/123456/']:
            self.assertEqual(c.normalize_url(url), 'https://www.douyin.com/video/123456')

    def test_rejects_non_video_and_wrong_hosts(self):
        for url in ['https://www.youtube.com/@someone', 'https://www.douyin.com/user/123',
                    'https://www.youtube.com/playlist?list=abc',
                    'https://www.youtube.com.evil.test/watch?v=BaW_jenozKc',
                    'https://user:password@www.youtube.com/watch?v=BaW_jenozKc',
                    'file:///video.mp4', BILI.replace('p=2', 'p=0')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                c.normalize_url(url)

    def test_invalid_rows_reported(self):
        urls, errors = c.parse_inputs('# comment\nnot a link\n' + YT)
        self.assertEqual(len(urls), 1)
        self.assertEqual(len(errors), 1)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.info = {'id': 'test', 'title': '中文标题', 'extractor_key': 'Youtube',
                     'extractor': 'youtube', 'formats': [], 'http_headers': {'Cookie': 'secret'}}

    def run_collect(self, result=None, **kwargs):
        with patch.object(YoutubeDL, 'extract_info', return_value=copy.deepcopy(result or self.info)):
            return c.collect(YT, c.Settings(output=self.output, interval=0, **kwargs), emit=lambda _: None)

    def test_metadata_does_not_download_or_leak_headers(self):
        with patch.object(YoutubeDL, 'process_ie_result') as download:
            report = self.run_collect()
        download.assert_not_called()
        meta = Path(report['items'][0]['metadata']).read_text(encoding='utf-8')
        self.assertIn('中文标题', meta)
        self.assertNotIn('secret', meta)
        self.assertFalse((self.output / 'archive.txt').exists())

    def test_playlist_rejected(self):
        report = self.run_collect({'_type': 'playlist', 'entries': []})
        self.assertEqual(report['counts'], {'failed': 1})

    def test_live_rejected(self):
        report = self.run_collect(dict(self.info, is_live=True))
        self.assertEqual(report['counts'], {'failed': 1})

    def test_preview_lists_actual_qualities_without_download(self):
        info = dict(self.info, duration=19, formats=[
            {'height': 360, 'width': 640, 'vcodec': 'avc1'},
            {'height': 720, 'width': 1280, 'vcodec': 'avc1'},
            {'height': 720, 'width': 1280, 'vcodec': 'vp9'},
            {'height': 1080, 'width': 1920, 'has_drm': True},
            {'height': None, 'vcodec': 'none'},
        ])
        with patch.object(YoutubeDL, 'extract_info', return_value=info), patch.object(YoutubeDL, 'process_ie_result') as download:
            result = c.preview_video(YT, c.Settings(output=self.output / 'not-created'))
        self.assertEqual([q['height'] for q in result['qualities']], [720, 360])
        self.assertEqual(result['duration'], 19)
        download.assert_not_called()
        self.assertFalse((self.output / 'not-created').exists())

    def test_default_directory_and_small_resolution(self):
        self.assertEqual(c.Settings().output, Path('D:/opencc'))
        report = self.run_collect(quality='360')
        self.assertEqual(report['counts'], {'metadata_saved': 1})

    def test_failed_item_does_not_abort_next(self):
        with patch.object(YoutubeDL, 'extract_info', side_effect=[RuntimeError('network'), self.info]):
            report = c.collect(YT + '\n' + BILI, c.Settings(output=self.output, interval=0), emit=lambda _: None)
        self.assertEqual(report['counts'], {'failed': 1, 'metadata_saved': 1})
        self.assertEqual(json.loads(Path(report['report_path']).read_text(encoding='utf-8'))['counts'], report['counts'])

    def test_archive_skip(self):
        (self.output / 'archive.txt').write_text('youtube test\n', encoding='utf-8')
        report = self.run_collect(download=True)
        self.assertEqual(report['counts'], {'skipped_archive': 1})
        self.assertNotIn('metadata', report['items'][0])
        self.assertFalse(list(self.output.glob('????-??-??')))

    def test_real_extractor_archive_short_circuit_is_successful_skip(self):
        from yt_dlp.extractor.youtube import YoutubeIE
        (self.output / 'archive.txt').write_text('youtube BaW_jenozKc\n', encoding='utf-8')
        events = []
        with patch.object(YoutubeIE, '_real_extract', side_effect=AssertionError('不得重复联网提取')) as extract:
            report = c.collect(YT, c.Settings(output=self.output, download=True),
                               emit=lambda _: None, progress_emit=events.append)
        extract.assert_not_called()
        self.assertEqual(report['counts'], {'skipped_archive': 1}, report)
        self.assertEqual(events[-1]['stage'], 'skipped_archive')
        self.assertNotIn('error', report['items'][0])
        self.assertFalse(list(self.output.glob('????-??-??')))

    def test_empty_extraction_without_archive_still_fails(self):
        with patch.object(YoutubeDL, 'extract_info', return_value=None):
            report = c.collect(YT, c.Settings(output=self.output, download=True), emit=lambda _: None)
        self.assertEqual(report['counts'], {'failed': 1})

    def test_missing_ffmpeg_cannot_claim_mp4_success(self):
        with patch.object(c, 'find_ffmpeg', return_value=None), self.assertRaisesRegex(ValueError, 'FFmpeg'):
            self.run_collect(download=True)

    def test_group_by_local_date_and_separate_same_title_videos(self):
        sources = YT + '\nhttps://youtu.be/jNQXAC9IVRw\n' + BILI
        results = [dict(self.info, id='first'), dict(self.info, id='second'), dict(self.info, id='first')]
        with patch.object(YoutubeDL, 'extract_info', side_effect=results), \
                patch.object(c, 'local_download_date', side_effect=['2026-09-22', '2026-09-22', '2026-09-23']):
            report = c.collect(sources, c.Settings(output=self.output, interval=0), emit=lambda _: None)
        self.assertEqual(report['counts'], {'metadata_saved': 3})
        directories = [Path(row['directory']) for row in report['items']]
        self.assertEqual(directories[0].parent, self.output / '2026-09-22')
        self.assertEqual(directories[1].parent, directories[0].parent)
        self.assertEqual(directories[2].parent, self.output / '2026-09-23')
        self.assertNotEqual(directories[0], directories[1])
        self.assertIn('bilibili_first', directories[2].name)

    def test_safe_titles_and_template_literals(self):
        titles = ['中文 / 日语: テスト? "标题" <test>|*\\结尾. ', 'CON', 'NUL.txt',
                  '', ' . ', '😀' * 200, '100% %(id)s %PATH% $PATH ${HOME}', '片名\n第二行']
        for title in titles:
            with self.subTest(title=title), YoutubeDL({'quiet': True, 'windowsfilenames': True}) as ydl:
                info = dict(self.info, title=title, ext='mp4')
                directory, template = c.video_output_paths(self.output, 'youtube', info, '2026-09-23')
                ydl.params['outtmpl']['default'] = template
                video = Path(ydl.prepare_filename(info))
                self.assertEqual(video.parent, directory)
                self.assertTrue(video.stem)
                self.assertLessEqual(c.utf16_length(video), 240)
                self.assertNotRegex(video.name, r'[<>:"/\\|?*\x00-\x1f]')
                if '%' in title:
                    self.assertEqual(video.stem, title)
                if title in ('CON', 'NUL.txt'):
                    self.assertTrue(video.stem.startswith('_'))

    def test_platforms_and_sanitized_ids_do_not_collide(self):
        paths = [c.video_output_paths(self.output, platform, dict(self.info, id=vid), '2026-09-23')[0]
                 for platform, vid in [('youtube', 'same'), ('bilibili', 'same'),
                                        ('youtube', 'a/b'), ('youtube', 'a_b')]]
        self.assertEqual(len(set(paths)), 4)

    def test_stop_before_start(self):
        stop = threading.Event()
        stop.set()
        report = c.collect(YT, c.Settings(output=self.output), stop=stop, emit=lambda _: None)
        self.assertEqual(report['counts'], {'cancelled': 1})

    def test_real_downloader_merges_audio_video(self):
        ffmpeg = c.find_ffmpeg()
        self.assertIsNotNone(ffmpeg, '运行 install.bat 安装 FFmpeg')
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'color=c=blue:s=160x90:d=0.5', '-c:v', 'libx264', str(self.output / 'video.mp4')], check=True)
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.5', '-c:a', 'aac', str(self.output / 'audio.m4a')], check=True)

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(self.output)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}/'
            info = dict(self.info, title='中文 日语テスト 100% %(id)s $PATH / 标题', formats=[
                {'format_id': 'v', 'url': base + 'video.mp4', 'ext': 'mp4', 'height': 90,
                 'vcodec': 'avc1', 'acodec': 'none'},
                {'format_id': 'a', 'url': base + 'audio.m4a', 'ext': 'm4a',
                 'vcodec': 'none', 'acodec': 'mp4a'},
            ])
            events = []
            with patch.object(YoutubeDL, 'extract_info', return_value=copy.deepcopy(info)):
                report = c.collect(YT, c.Settings(output=self.output, interval=0, download=True),
                                   emit=lambda _: None, progress_emit=events.append)
            self.assertEqual(report['counts'], {'downloaded': 1}, report)
            self.assertTrue(any(e['stage'] == 'downloading' and e.get('downloaded', 0) > 0 for e in events))
            self.assertTrue(any(e['stage'] == 'processing' for e in events))
            self.assertEqual(events[-1]['stage'], 'downloaded')
            video = report['items'][0]['files'][0]
            self.assertEqual(Path(video).suffix, '.mp4')
            self.assertEqual(Path(video).stem, c.filename_title(info['title']))
            self.assertEqual(Path(video).parent, Path(report['items'][0]['metadata']).parent)
            self.assertEqual(Path(video).parent.parent.name, report['items'][0]['download_date'])
            self.assertEqual(Path(video).parent.parent.parent, self.output)
            for stream in ['0:v:0', '0:a:0']:
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', video,
                                '-map', stream, '-f', 'null', '-'], check=True)
            self.assertIn('youtube test', (self.output / 'archive.txt').read_text())
            self.assertEqual(self.run_collect(info, download=True)['counts'], {'skipped_archive': 1})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_real_webm_remux_and_transcode_to_mp4(self):
        ffmpeg = c.find_ffmpeg()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(self.output))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for video_id, encoder, codec in [('remux', 'libvpx-vp9', 'vp9'), ('transcode', 'libvpx', 'vp8')]:
                with self.subTest(codec=codec):
                    source = self.output / f'{video_id}.webm'
                    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                    'color=c=blue:s=160x90:d=0.5', '-f', 'lavfi', '-i',
                                    'sine=frequency=440:duration=0.5', '-c:v', encoder, '-c:a', 'libopus',
                                    '-shortest', str(source)], check=True)
                    info = dict(self.info, id=video_id, formats=[{
                        'format_id': 'webm', 'url': f'http://127.0.0.1:{server.server_port}/{source.name}',
                        'ext': 'webm', 'height': 90, 'vcodec': codec, 'acodec': 'opus'}])
                    logs = []
                    with patch.object(YoutubeDL, 'extract_info', return_value=copy.deepcopy(info)):
                        report = c.collect(YT, c.Settings(output=self.output, download=True), emit=logs.append)
                    self.assertEqual(report['counts'], {'downloaded': 1}, report)
                    video = Path(report['items'][0]['files'][0])
                    self.assertEqual(video.suffix, '.mp4')
                    self.assertEqual(video.read_bytes()[4:8], b'ftyp')
                    self.assertFalse(list(video.parent.glob('*.webm')))
                    if codec == 'vp8':
                        self.assertTrue(any('正在转码' in log for log in logs), logs)
                    for stream in ['0:v:0', '0:a:0']:
                        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(video),
                                        '-map', stream, '-f', 'null', '-'], check=True)
                    self.assertIn(f'youtube {video_id}', (self.output / 'archive.txt').read_text())
            from media_downloader import EnsureMP4PP
            from yt_dlp.utils import PostProcessingError
            failed_info = dict(info, id='failed-conversion')
            with patch.object(YoutubeDL, 'extract_info', return_value=failed_info), \
                    patch.object(EnsureMP4PP, 'run', side_effect=PostProcessingError('conversion failed')):
                report = c.collect(YT, c.Settings(output=self.output, download=True), emit=lambda _: None)
            self.assertEqual(report['counts'], {'failed': 1})
            self.assertNotIn('failed-conversion', (self.output / 'archive.txt').read_text())
            self.assertTrue(list(Path(report['items'][0]['directory']).glob('*.webm')))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
