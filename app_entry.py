"""Windows 打包入口；默认打开 GUI，诊断模式不显示窗口。"""
import json
import subprocess
import sys
import traceback
from pathlib import Path

import collector


def self_test(output):
    result = {'frozen': collector.FROZEN, 'output_root': str(collector.ROOT)}
    try:
        import tkinter as tk
        from gui import App
        from media_downloader import EnsureMP4PP
        result['mp4_processor'] = EnsureMP4PP.__name__
        from yt_dlp import YoutubeDL
        import yt_dlp
        from updater import current_version
        result['yt_dlp_version'] = current_version()
        result['yt_dlp_path'] = yt_dlp.__file__
        result['default_download_directory'] = str(collector.DEFAULT_OUTPUT)
        from yt_dlp.extractor import gen_extractor_classes
        from yt_dlp_ejs.yt.solver import core, lib
        import requests
        result['requests'] = requests.__version__
        # yt-dlp-ejs exposes JS data via importlib.resources.
        result['ejs'] = bool(core() and lib())
        result['extractors'] = [ie.ie_key() for ie in gen_extractor_classes()
                                if ie.ie_key() in {'Youtube', 'BiliBili', 'Douyin'}]
        with YoutubeDL({'quiet': True}):
            pass
        for label, executable, flag in [('ffmpeg', collector.find_ffmpeg(), '-version'),
                                         ('node', collector.find_node(), '--version')]:
            if not executable:
                raise RuntimeError(f'{label} missing')
            completed = subprocess.run([executable, flag], capture_output=True, text=True,
                                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result[label] = {'path': executable, 'version': completed.stdout.splitlines()[0]}
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        result['window_icon'] = [app.app_icon.width(), app.app_icon.height()]
        result['icon_resource'] = (collector.RESOURCE_ROOT / 'assets' / 'video-collector.ico').is_file()
        result['themes'] = []
        for mode in ('light', 'dark'):
            app.theme_mode = mode
            app.style()
            app.show_cover(app._cover_bytes, app._cover_placeholder)
            if root.cget('background') != app.palette['bg'] or app.links.cget('background') != app.palette['input']:
                raise RuntimeError(f'{mode} theme failed')
            result['themes'].append(mode)
        root.update()
        root.destroy()
        result['gui'] = 'ok'
        result['ok'] = len(result['extractors']) == 3 and result['ejs']
    except Exception:
        result.update(ok=False, error=traceback.format_exc())
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def notification_test(output):
    """发送明确标注为测试的完成提醒，不下载视频。"""
    import tkinter as tk
    from gui import App
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.notifications_enabled.set(True)
    result = {'frozen': collector.FROZEN, 'ok': False, 'test_only': True}
    native_show = app.notifier.show

    def record_show(title, message):
        result['ok'] = native_show(title + '（测试）', message + '\n演示通知，没有下载视频。')
        return result['ok']

    app.notifier.show = record_show
    app.events.put(('batch_done', {'batch_id': 1, 'counts': {'downloaded': 5, 'failed': 1},
                                   'total': 6, 'output': str(collector.DEFAULT_OUTPUT),
                                   'stopped': False, 'mode': 'video'}))
    app.poll()
    # 给系统显示通知的时间，退出时销毁临时托盘图标。
    root.after(8000, root.destroy)
    root.mainloop()
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        raise SystemExit(self_test(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == '--notification-test':
        raise SystemExit(notification_test(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == '--cli':
        sys.argv.pop(1)
        with (collector.ROOT / 'cli.log').open('w', encoding='utf-8') as log:
            sys.stdout = sys.stderr = log
            raise SystemExit(collector.main())
    import tkinter as tk
    from gui import App
    window = tk.Tk()
    App(window)
    window.mainloop()
