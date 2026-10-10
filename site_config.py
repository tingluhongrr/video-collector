"""站点配置与按域名隔离的本地 Cookie 存储。"""
import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

SITES = {'bilibili': '哔哩哔哩', 'youtube': 'YouTube', 'douyin': '抖音'}
DOMAINS = {'bilibili': ('bilibili.com', 'b23.tv'),
           'youtube': ('youtube.com', 'youtu.be', 'google.com'),
           'douyin': ('douyin.com', 'iesdouyin.com')}


def default_config():
    return {'sites': {name: {'cookies': '', 'proxy': ''} for name in SITES}, 'update_proxy': '',
            'theme': 'light', 'completion_notifications': True}


def load_config(path):
    config = default_config()
    try:
        saved = json.loads(Path(path).read_text(encoding='utf-8'))
        for name in SITES:
            profile = saved.get('sites', {}).get(name, {})
            config['sites'][name] = {key: str(profile.get(key) or '') for key in ('cookies', 'proxy')}
        config['update_proxy'] = str(saved.get('update_proxy') or '')
        if saved.get('theme') in ('light', 'dark'):
            config['theme'] = saved['theme']
        if isinstance(saved.get('completion_notifications'), bool):
            config['completion_notifications'] = saved['completion_notifications']
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return config


def save_config(path, config):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def belongs_to_site(domain, site):
    host = domain.lstrip('.').lower()
    return any(host == suffix or host.endswith('.' + suffix) for suffix in DOMAINS[site])


def store_cookies(jar, directory, site, source):
    from yt_dlp.cookies import YoutubeDLCookieJar
    if site not in SITES:
        raise ValueError('不支持的站点。')
    selected = YoutubeDLCookieJar()
    for cookie in jar:
        if belongs_to_site(cookie.domain, site) and not cookie.is_expired():
            selected.set_cookie(copy.copy(cookie))
    if not len(selected):
        raise ValueError(f'没有找到 {SITES[site]} 的有效 Cookie。请先在所选浏览器打开该站点并登录，或重新导出 cookies.txt。')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{site}.cookies.txt'
    temp = directory / f'{site}-{uuid.uuid4().hex}.tmp'
    selected.save(str(temp), ignore_discard=True, ignore_expires=False)
    temp.replace(path)
    info = {'count': len(selected), 'source': source, 'updated_at': datetime.now(timezone.utc).isoformat()}
    save_config(directory / f'{site}.status.json', info)
    return {'path': str(path.resolve()), **info}


def import_cookies(path, directory, site):
    from yt_dlp.cookies import YoutubeDLCookieJar
    jar = YoutubeDLCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return store_cookies(jar, directory, site, 'cookies.txt')


def read_browser_cookies(browser, directory, site, profile=None):
    from yt_dlp.cookies import extract_cookies_from_browser
    if browser not in ('chrome', 'edge', 'firefox'):
        raise ValueError('不支持的浏览器。')
    # 不把浏览器 Cookie、密钥或个人路径输出到日志；只返回目标站点条数。
    class QuietLogger:
        def debug(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
        def warning(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
        def progress_bar(self, *args, **kwargs):
            return None
    try:
        jar = extract_cookies_from_browser(browser, profile=profile or None, logger=QuietLogger())
        return store_cookies(jar, directory, site, browser)
    except Exception as exc:
        raise RuntimeError(f'{browser} 读取未成功。请确认浏览器已安装、选对配置目录并先关闭浏览器后重试。若仍受系统加密限制，请导入 cookies.txt，或尝试 Firefox。') from exc
