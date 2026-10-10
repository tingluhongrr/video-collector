"""预览结果、画质选择、进度状态的界面回归检查（不联网）。"""
import io
import copy
from dataclasses import replace
from itertools import product
import tempfile
import tkinter as tk
from tkinter import font as tkfont, ttk
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from gui import App
from settings_ui import SiteSettings
from site_config import default_config
from site_config import load_config, save_config


def destroy_root(root):
    for callback in root.tk.call('after', 'info'):
        root.after_cancel(callback)
    root.destroy()


def make_test_app(root):
    # 布局验证不读取程序旁的私人 Cookie 或代理设置。
    with patch('gui.load_config', return_value=default_config()), patch('gui.DesktopNotifier'):
        return App(root)


def assert_fully_visible(test, widget):
    """固定操作控件应完整显示，包含每一级容器的裁切边界。"""
    label = widget.cget('text') if 'text' in widget.keys() else str(widget)
    test.assertTrue(widget.winfo_ismapped(), label)
    test.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight(), label)
    test.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), label)
    top = widget.winfo_toplevel()
    while widget is not top:
        parent = widget.master
        test.assertGreaterEqual(widget.winfo_rootx(), parent.winfo_rootx(), label)
        test.assertGreaterEqual(widget.winfo_rooty(), parent.winfo_rooty(), label)
        test.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                             parent.winfo_rootx() + parent.winfo_width(), label)
        test.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                             parent.winfo_rooty() + parent.winfo_height(), label)
        widget = parent


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = make_test_app(self.root)
        self.addCleanup(lambda: destroy_root(self.root))

    def test_preview_enables_selection_and_loads_cover(self):
        app = self.app
        app.items['0'] = {'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw'}
        app.tree.insert('', 'end', iid='0', values=('待解析', '等待'))
        app.tree.selection_set('0')
        data = {'title': '测试视频', 'uploader': '作者', 'duration': 19, 'platform': 'youtube',
                'description': '简介', 'url': app.items['0']['url'],
                'qualities': [{'label': '640 × 360', 'height': 360}, {'label': '1280 × 720', 'height': 720}]}
        stream = io.BytesIO()
        Image.new('RGB', (160, 90), 'blue').save(stream, format='PNG')
        app.events.put(('preview', ('0', data)))
        app.events.put(('cover', ('0', stream.getvalue())))
        app.events.put(('done', '预览完成'))
        app.poll()
        self.assertEqual(app.title_label.cget('text'), '测试视频')
        self.assertIn('00:19', app.author_label.cget('text'))
        self.assertEqual(str(app.download_button.cget('state')), 'normal')
        self.assertEqual(app.cover.cget('text'), '')
        app.quality.set('640 × 360')
        app.set_quality()
        self.assertEqual(app.items['0']['quality'], '360')

    def test_progress_and_merge_are_distinct(self):
        app = self.app
        app.show_progress({'stage': 'downloading', 'index': 1, 'count': 1, 'downloaded': 72, 'total': 100,
                           'speed': 1024, 'eta': 5})
        self.assertEqual(app.percent.get(), '72%')
        self.assertEqual(app.progress['value'], 72)
        app.show_progress({'stage': 'processing', 'index': 1, 'count': 1})
        self.assertEqual(str(app.progress['mode']), 'indeterminate')
        app.show_progress({'stage': 'downloaded', 'index': 1, 'count': 1})
        self.assertEqual(str(app.progress['mode']), 'determinate')
        self.assertEqual(app.percent.get(), '100%')
        app.show_progress({'stage': 'skipped_archive', 'index': 1, 'count': 1})
        self.assertEqual(app.percent.get(), '100%')
        self.assertIn('跳过', app.progress_title.get())
        self.assertIn('未重复下载', app.progress_detail.get())

    def test_output_folder_button_updates_download_path_and_cancel_preserves_it(self):
        app = self.app
        with tempfile.TemporaryDirectory() as temporary:
            chosen = Path(temporary) / '视频 下载目录'
            chosen.mkdir()
            with patch('gui.filedialog.askdirectory', side_effect=[str(chosen), '']) as chooser:
                # 使用按钮调用验证实际绑定，而不是只调用目录选择函数。
                app.output_button.invoke()
                self.assertEqual(app.output.get(), str(chosen))
                self.assertEqual(app.output_entry.get(), str(chosen))
                self.assertEqual(app.settings().output, chosen)
                app.output_button.invoke()
                self.assertEqual(app.output.get(), str(chosen))
                self.assertEqual(app.settings().output, chosen)
            self.assertEqual(chooser.call_count, 2)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'settings.json'
        self.config = default_config()
        self.config['theme'] = 'light'
        for site in self.config['sites']:
            self.config['sites'][site]['cookies'] = str(self.directory / f'{site}.cookies.txt')
            self.config['sites'][site]['proxy'] = 'http://127.0.0.1:7890'
        self.config['update_proxy'] = 'http://127.0.0.1:7891'
        save_config(self.path, self.config)
        for replacement in (patch('gui.ROOT', self.directory), patch('gui.load_config', side_effect=load_config)):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(lambda: destroy_root(self.root))
        self.app = App(self.root)

    def assert_theme_colors(self, app):
        palette = app.palette
        self.assertEqual(app.root.cget('background'), palette['bg'])
        self.assertEqual(app.links.cget('background'), palette['input'])
        self.assertEqual(app.links.cget('foreground'), palette['ink'])
        self.assertEqual(app.preview_canvas.cget('background'), palette['card'])
        style = ttk.Style(app.root)
        self.assertEqual(style.lookup('Page.TFrame', 'background'), palette['bg'])
        self.assertEqual(style.lookup('Card.TFrame', 'background'), palette['card'])
        self.assertEqual(style.lookup('Treeview', 'fieldbackground'), palette['card'])
        if hasattr(app, 'log_text'):
            self.assertEqual(app.log_text.cget('background'), palette['log_bg'])
            self.assertEqual(app.log_text.cget('foreground'), palette['log_fg'])
        if dialog := getattr(app, 'site_dialog', None):
            if not dialog._closed:
                self.assertEqual(dialog.dialog.cget('background'), palette['bg'])
                self.assertEqual(style.lookup('Settings.Page.TFrame', 'background'), palette['bg'])
                for canvas, content in dialog._scroll_views.values():
                    self.assertEqual(canvas.cget('background'), palette['bg'])
                    for card in content.winfo_children():
                        self.assertEqual(card.cget('background'), palette['card'])

    def test_theme_button_changes_colors_and_preserves_work(self):
        app = self.app
        app.output.set(str(self.directory / '视频 输出'))
        app.items['0'] = {'url': 'https://youtu.be/jNQXAC9IVRw'}
        app.tree.insert('', 'end', iid='0', values=('测试视频', '就绪'))
        app.tree.selection_set('0')
        preview = {'title': '完整的视频标题', 'uploader': '作者', 'duration': 19,
                   'platform': 'youtube', 'description': '视频简介', 'url': app.items['0']['url'],
                   'qualities': [{'label': '1280 × 720', 'height': 720}]}
        app.events.put(('preview', ('0', preview)))
        app.poll()
        app.show_progress({'stage': 'downloading', 'index': 1, 'count': 1,
                           'downloaded': 72, 'total': 100, 'speed': 1024, 'eta': 5})
        app.logs.append('测试日志：已读取信息，正在下载。')
        app.show_logs()
        app.log_window.withdraw()
        app.site_dialog = SiteSettings(app, self.directory)
        app.site_dialog.dialog.withdraw()
        # 下载过程中也能切换主题，不应打断进度或禁用主题按钮。
        app.begin('正在下载测试视频')
        self.assertEqual(str(app.theme_button.cget('state')), 'normal')

        def snapshot():
            return (app.output.get(), app.title_label.cget('text'), app.author_label.cget('text'),
                    app.quality.get(), app.mode.get(), app.percent.get(), app.progress['value'],
                    copy.deepcopy(app.items), tuple(app.tree.item('0', 'values')),
                    app.running, app.stop.is_set(), app.log_text.get('1.0', 'end-1c'))

        before = snapshot()
        self.assertEqual(app.theme_mode, 'light')
        self.assert_theme_colors(app)
        app.theme_button.invoke()
        self.assertEqual(app.theme_mode, 'dark')
        self.assert_theme_colors(app)
        self.assertEqual(snapshot(), before)
        app.theme_button.invoke()
        self.assertEqual(app.theme_mode, 'light')
        self.assert_theme_colors(app)
        self.assertEqual(snapshot(), before)
        app.site_dialog.close()

    def test_theme_is_remembered_and_settings_save_preserves_profiles(self):
        app = self.app
        app.theme_button.invoke()
        self.assertEqual(load_config(self.path)['theme'], 'dark')
        dialog = SiteSettings(app, self.directory)
        dialog.vars['youtube']['proxy'].set('http://127.0.0.1:9090')
        dialog.save_button.invoke()
        saved = load_config(self.path)
        self.assertEqual(saved['theme'], 'dark')
        self.assertEqual(saved['update_proxy'], self.config['update_proxy'])
        for site, profile in self.config['sites'].items():
            self.assertEqual(saved['sites'][site]['cookies'], profile['cookies'])
            self.assertEqual(saved['sites'][site]['proxy'],
                             'http://127.0.0.1:9090' if site == 'youtube' else profile['proxy'])
        destroy_root(self.root)
        self.root = tk.Tk()
        self.root.withdraw()
        reopened = App(self.root)
        self.assertEqual(reopened.theme_mode, 'dark')
        self.assert_theme_colors(reopened)
        self.assertEqual(reopened.config, saved)

    def test_failed_theme_save_still_applies_without_claiming_it_was_remembered(self):
        app = self.app
        with patch('gui.save_config', side_effect=OSError('测试写入失败')):
            app.theme_button.invoke()
        self.assertEqual(app.theme_mode, 'dark')
        self.assert_theme_colors(app)
        self.assertEqual(load_config(self.path)['theme'], 'light')
        self.assertIn('保存', app.status.get())
        for phrase in ('已记住', '已保存', '已记忆'):
            self.assertNotIn(phrase, app.status.get())


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'settings.json'
        self.config = default_config()
        self.config['theme'] = 'dark'
        self.config['sites']['douyin']['cookies'] = str(self.directory / 'fake.cookies.txt')
        self.config['sites']['youtube']['proxy'] = 'http://127.0.0.1:7890'
        self.config['update_proxy'] = 'http://127.0.0.1:7891'
        save_config(self.path, self.config)
        for replacement in (patch('gui.ROOT', self.directory), patch('gui.load_config', side_effect=load_config),
                            patch('gui.DesktopNotifier')):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(lambda: destroy_root(self.root))
        self.app = App(self.root)
        self.app.output.set(str(self.directory / 'downloads'))

    def jobs(self, count):
        jobs = []
        for index in range(count):
            key = str(index)
            item = {'preview': {'url': f'https://www.youtube.com/watch?v=test{index}'}, 'quality': 'best'}
            self.app.items[key] = item
            self.app.tree.insert('', 'end', iid=key, values=(f'测试视频 {index}', '就绪'))
            jobs.append((key, item))
        return jobs

    def drain_events(self):
        values = []
        while not self.app.events.empty():
            values.append(self.app.events.get_nowait())
        return values

    def test_worker_reports_one_batch_and_duplicate_delivery_notifies_once(self):
        app = self.app
        jobs = self.jobs(3)
        app.begin('测试下载')
        with patch('gui.collect', side_effect=[{'counts': {'downloaded': 1}},
                                               {'counts': {'skipped_archive': 1}}, OSError('测试下载失败')]):
            app.download_worker(jobs, replace(app.settings(), interval=0))
        events = self.drain_events()
        batches = [value for kind, value in events if kind == 'batch_done']
        self.assertEqual(len(batches), 1)
        batch = batches[0]
        self.assertEqual(batch['counts'], {'downloaded': 1, 'skipped_archive': 1, 'failed': 1})
        self.assertEqual(batch['total'], 3)
        self.assertEqual(batch['output'], app.output.get())
        self.assertFalse(batch['stopped'])
        self.assertIn('batch_id', batch)
        for event in events:
            app.events.put(event)
        app.events.put(('batch_done', batch))
        app.poll()
        app.notifier.show.assert_called_once()
        message = str(app.notifier.show.call_args)
        for word in ('下载', '跳过', '失败'):
            self.assertIn(word, message)
        self.assertFalse(app.running)

    def test_only_enabled_batch_completion_notifies(self):
        app = self.app
        for message in ('预览完成：3 个视频就绪。', '采集组件更新完成。'):
            app.events.put(('done', message))
        app.poll()
        app.notifier.show.assert_not_called()
        app.notifications_enabled.set(False)
        batch = {'batch_id': 1, 'counts': {'downloaded': 1}, 'total': 1,
                 'output': app.output.get(), 'stopped': False, 'mode': 'video'}
        app.events.put(('batch_done', batch))
        app.poll()
        app.notifier.show.assert_not_called()
        app.notifications_enabled.set(True)
        stopped = {'batch_id': 2, 'counts': {'downloaded': 1, 'cancelled': 2}, 'total': 3,
                   'output': app.output.get(), 'stopped': True, 'mode': 'video'}
        app.events.put(('batch_done', stopped))
        app.poll()
        app.notifier.show.assert_called_once()
        self.assertIn('停止', str(app.notifier.show.call_args))

    def test_unavailable_desktop_notification_uses_nonmodal_fallback(self):
        app = self.app
        app.notifier.show.side_effect = [False, OSError('测试系统通知不可用')]
        with patch.object(app, 'show_completion_fallback') as fallback:
            for batch_id in (1, 2):
                app.begin('测试下载')
                app.events.put(('batch_done', {'batch_id': batch_id, 'counts': {'downloaded': 1},
                                               'total': 1, 'output': app.output.get(),
                                               'stopped': False, 'mode': 'video'}))
                app.poll()
                self.assertFalse(app.running)
                fallback.assert_called_with(*app.notifier.show.call_args.args,
                                            **app.notifier.show.call_args.kwargs)
            self.assertEqual(fallback.call_count, 2)
            app.events.put(('done', '后续任务事件正常处理'))
            app.poll()
            self.assertEqual(app.status.get(), '后续任务事件正常处理')
            self.assertEqual(fallback.call_count, 2)

    def test_stopped_worker_reports_unexecuted_jobs_without_downloading(self):
        app = self.app
        jobs = self.jobs(2)
        app.stop.set()
        with patch('gui.collect') as download:
            app.download_worker(jobs, replace(app.settings(), interval=0))
        download.assert_not_called()
        batches = [value for kind, value in self.drain_events() if kind == 'batch_done']
        self.assertEqual(len(batches), 1)
        self.assertTrue(batches[0]['stopped'])
        self.assertEqual(batches[0]['total'], 2)
        self.assertEqual(batches[0]['counts'].get('cancelled'), 2)

    def test_notification_setting_is_remembered_and_preserved_by_site_save(self):
        app = self.app
        self.assertTrue(app.notifications_enabled.get())
        app.notify_toggle.invoke()
        self.assertFalse(app.notifications_enabled.get())
        self.assertIs(load_config(self.path)['completion_notifications'], False)
        dialog = SiteSettings(app, self.directory)
        dialog.save_button.invoke()
        saved = load_config(self.path)
        self.assertIs(saved['completion_notifications'], False)
        for name in ('theme', 'sites', 'update_proxy'):
            self.assertEqual(saved[name], self.config[name])
        destroy_root(self.root)
        self.root = tk.Tk()
        self.root.withdraw()
        reopened = App(self.root)
        self.assertFalse(reopened.notifications_enabled.get())
        with patch('gui.save_config', side_effect=OSError('测试写入失败')):
            reopened.notify_toggle.invoke()
        self.assertTrue(reopened.notifications_enabled.get())
        self.assertIs(load_config(self.path)['completion_notifications'], False)
        self.assertIn('保存失败', reopened.status.get())
        self.assertNotIn('已保存', reopened.status.get())


class LayoutTests(unittest.TestCase):
    def test_actions_remain_visible_in_short_windows_and_high_dpi(self):
        for scaling, theme in product((1.333333, 1.666667, 2.0), ('light', 'dark')):
            with self.subTest(scaling=scaling, theme=theme):
                root = tk.Tk()
                try:
                    root.attributes('-alpha', 0)
                    root.tk.call('tk', 'scaling', scaling)
                    app = make_test_app(root)
                    if app.theme_mode != theme:
                        with patch('gui.save_config'):
                            app.theme_button.invoke()
                    # 长错误和视频标题也不能把固定操作栏挤出可视区域。
                    app.status.set('更新 Cookie 后请重新获取视频预览。' * 4)
                    app.title_label.configure(text='这是用于检查长标题和缩放后布局的视频标题' * 3)
                    app.progress_title.set('正在处理第 12 / 20 个视频 · 合并完成后保存为 MP4')
                    app.progress_detail.set('当前文件下载进度 72% · 速度 12.5 MB/s · 剩余时间 00:19 · 视频和音频分别下载后自动合并。')
                    for geometry in ('960x600', '1180x700', '1440x760'):
                        with self.subTest(geometry=geometry):
                            root.geometry(geometry)
                            root.update()
                            for button in (app.log_button, app.stop_button, app.download_button, app.all_button,
                                           app.preview_button, app.import_button, app.update_button,
                                           app.settings_button, app.theme_button, app.open_button, app.quality_combo,
                                           app.output_entry, app.output_button, app.notify_toggle, *app.mode_buttons):
                                assert_fully_visible(self, button)
                            line_height = tkfont.Font(root=root, font=app.links.cget('font')).metrics('linespace')
                            self.assertGreaterEqual(app.links.winfo_height(), line_height + 2 * int(app.links.cget('pady')))
                            self.assertTrue(app.tree.winfo_ismapped())
                            row_height = int(ttk.Style(root).lookup('Treeview', 'rowheight'))
                            self.assertGreaterEqual(app.tree.winfo_height(), row_height * 2)
                            self.assertGreater(app.preview_canvas.winfo_height(), 30)
                            app.preview_canvas.yview_moveto(1)
                            root.update()
                            self.assertEqual(app.preview_canvas.yview()[1], 1.0)
                            # 详情文字横向不应被滚动面板裁切。
                            for widget in (app.title_label,):
                                canvas = app.preview_canvas
                                self.assertGreaterEqual(widget.winfo_rootx(), canvas.winfo_rootx())
                                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                                     canvas.winfo_rootx() + canvas.winfo_width())
                finally:
                    destroy_root(root)

    def test_settings_footer_and_scroll_are_usable_at_high_dpi(self):
        for scaling, theme in product((1.333333, 1.666667, 2.0), ('light', 'dark')):
            with self.subTest(scaling=scaling, theme=theme), tempfile.TemporaryDirectory() as temporary:
                root = tk.Tk()
                try:
                    root.attributes('-alpha', 0)
                    root.tk.call('tk', 'scaling', scaling)
                    app = make_test_app(root)
                    if app.theme_mode != theme:
                        with patch('gui.save_config'):
                            app.theme_button.invoke()
                    root.update()
                    settings = SiteSettings(app, Path(temporary))
                    settings.dialog.attributes('-alpha', 0)
                    settings.note.set('更新 Cookie 后，请重新获取视频预览；配置只应用于所选站点。' * 4)
                    for geometry in ('730x500', '850x700'):
                        with self.subTest(geometry=geometry):
                            settings.dialog.geometry(geometry)
                            root.update()
                            for tab in settings.tabs.tabs():
                                settings.tabs.select(tab)
                                root.update()
                                assert_fully_visible(self, settings.save_button)
                                assert_fully_visible(self, settings.cancel_button)
                                canvas, content = settings._scroll_views[tab]
                                self.assertGreater(canvas.winfo_height(), 30)
                                self.assertGreater(canvas.winfo_width(), 100)
                                canvas.yview_moveto(1)
                                root.update()
                                self.assertEqual(canvas.yview()[1], 1.0)
                    settings.close()
                    root.update()
                    self.assertTrue(settings._closed)
                    self.assertIsNone(settings._poll_job)
                    self.assertFalse((Path(temporary) / 'settings.json').exists())
                finally:
                    destroy_root(root)


if __name__ == '__main__':
    unittest.main()
