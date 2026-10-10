"""指定链接的视频采集器；默认只采集信息，--download 才下载。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

RESOURCE_ROOT = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
DEFAULT_OUTPUT = Path('D:/opencc')
if not FROZEN:
    sys.path.insert(0, str(ROOT / '.deps'))

from updater import bootstrap
UPDATE_NOTICE = bootstrap(ROOT / 'updates')


def dependency_help() -> str:
    return '请使用重新打包的最新版 EXE。' if FROZEN else '请运行 install.bat 安装或更新依赖。'

HOSTS = {
    'bilibili.com': 'bilibili', 'www.bilibili.com': 'bilibili',
    'm.bilibili.com': 'bilibili', 'b23.tv': 'bilibili',
    'youtube.com': 'youtube', 'www.youtube.com': 'youtube',
    'm.youtube.com': 'youtube', 'youtu.be': 'youtube',
    'douyin.com': 'douyin', 'www.douyin.com': 'douyin',
    'v.douyin.com': 'douyin', 'www.iesdouyin.com': 'douyin',
    'iesdouyin.com': 'douyin',
}
SHORT_HOSTS = {'b23.tv', 'v.douyin.com'}


def validate_host(url: str) -> str:
    p = urlsplit(url)
    if (p.scheme not in ('http', 'https') or p.hostname not in HOSTS
            or p.username or p.password or p.port not in (None, 80, 443)):
        raise ValueError('仅支持哔哩哔哩、YouTube、抖音的视频链接。')
    return HOSTS[p.hostname]


def normalize_url(url: str) -> str:
    validate_host(url)
    p = urlsplit(url)
    host, path, q = p.hostname, p.path, parse_qs(p.query)
    if host in SHORT_HOSTS:
        if not re.fullmatch(r'/[A-Za-z0-9_-]+/?', path):
            raise ValueError('无效的分享短链接。')
        return f'https://{host}{path}'
    if HOSTS[host] == 'bilibili':
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10}|av\d+)/?', path)
        if match:
            part = q.get('p', ['1'])[0]
            if not part.isdigit() or int(part) < 1:
                raise ValueError('B 站分 P 必须为正整数。')
            return f'https://www.bilibili.com/video/{match[1]}?p={int(part)}'
    elif HOSTS[host] == 'youtube':
        vid = q.get('v', [''])[0] if path == '/watch' else ''
        match = re.fullmatch(r'/(?:shorts/|embed/)?([A-Za-z0-9_-]{11})/?', path)
        if match and (host == 'youtu.be' or path.startswith(('/shorts/', '/embed/'))):
            vid = match[1]
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            return 'https://www.youtube.com/watch?' + urlencode({'v': vid})
    else:
        match = re.fullmatch(r'/(?:video|share/video)/(\d+)/?', path)
        vid = match[1] if match else q.get('modal_id', [''])[0]
        if vid.isdigit():
            return f'https://www.douyin.com/video/{vid}'
    raise ValueError('请提供具体视频链接，不支持主页、搜索页或播放列表。')


def parse_inputs(text: str) -> tuple[list[str], list[dict]]:
    """接受每行链接或手机分享文案；保留错误行，避免静默遗漏。"""
    urls, errors, seen = [], [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        candidates = re.findall(r'https?://[^\s<>"\u3000\u4e00-\u9fff]+', line)
        if not candidates and re.fullmatch(r'BV[A-Za-z0-9]{10}', line):
            candidates = ['https://www.bilibili.com/video/' + line]
        if not candidates:
            errors.append({'input': line, 'status': 'failed', 'error': '未找到视频链接。'})
        for candidate in candidates:
            candidate = candidate.rstrip('.,;!?)]}，。；！）】')
            try:
                url = normalize_url(candidate)
                if url not in seen:
                    urls.append(url)
                    seen.add(url)
            except ValueError as exc:
                errors.append({'input': candidate, 'status': 'failed', 'error': str(exc)})
    return urls, errors


def resolve_short(url: str, proxy: str | None = None) -> str:
    if urlsplit(url).hostname not in SHORT_HOSTS:
        return normalize_url(url)
    import requests
    # 每一跳先检查平台域名，避免将任意地址交给通用提取器。
    with requests.Session() as session:
        if proxy:
            session.proxies.update({'http': proxy, 'https': proxy})
        for _ in range(6):
            validate_host(url)
            with session.get(url, allow_redirects=False, timeout=20, stream=True,
                             headers={'User-Agent': 'Mozilla/5.0'}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    continue
                response.raise_for_status()
                if urlsplit(url).hostname in SHORT_HOSTS:
                    raise ValueError('短链接未返回视频地址，请在浏览器打开后复制完整视频链接。')
                return normalize_url(url)
    raise ValueError('短链接跳转次数过多，请使用完整视频链接。')


@dataclass
class Settings:
    output: Path = DEFAULT_OUTPUT
    download: bool = False
    quality: str = '1080'
    cookies: str | None = None
    proxy: str | None = None
    interval: float = 2.0
    ffmpeg: str | None = None
    node: str | None = None
    site_profiles: dict = field(default_factory=dict)


def settings_for_url(settings: Settings, url: str) -> Settings:
    platform = validate_host(url)
    if platform not in settings.site_profiles:
        return settings
    profile = settings.site_profiles[platform]
    return replace(settings, cookies=profile.get('cookies') or None, proxy=profile.get('proxy') or None)


def find_ffmpeg(explicit: str | None = None) -> str | None:
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            p = p / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg')
        if not p.is_file():
            raise ValueError('FFmpeg 路径不存在。')
        return str(p.resolve())
    if executable := shutil.which('ffmpeg'):
        return executable
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def find_node(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    packaged = RESOURCE_ROOT / 'runtime' / 'node.exe'
    if packaged.is_file():
        return str(packaged)
    if executable := shutil.which('node'):
        return executable
    bundled = (Path.home() / '.cache/codex-runtimes/codex-primary-runtime'
               / 'dependencies/node/bin/node.exe')
    return str(bundled) if bundled.is_file() else None


class Logger:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, message):
        if not message.startswith('[debug] '):
            self.emit(message)

    def warning(self, message):
        self.emit('提示：' + message)

    def error(self, message):
        self.emit('错误：' + message)


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def local_download_date():
    """按每条任务开始时的电脑本地日期归类，跨午夜的队列可落入不同日期。"""
    return datetime.now().strftime('%Y-%m-%d')


def filename_title(value):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', str(value or '')).strip().rstrip('. ')
    title = title or '未命名视频'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', title, re.I):
        title = '_' + title
    return title


def utf16_length(value):
    return len(str(value).encode('utf-16-le')) // 2


def truncate_filename(value, limit):
    return value.encode('utf-16-le')[:limit * 2].decode('utf-16-le', errors='ignore').rstrip('. ') or '_'


def video_output_paths(output, platform, info, day):
    """日期/标题 [平台_ID]/标题；为音画分轨、合并和 .part 后缀预留路径空间。"""
    video_id = str(info['id'])
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', video_id)
    if safe_id != video_id or len(safe_id) > 64 or not safe_id:
        safe_id = safe_id[:40] + '-' + hashlib.sha256(video_id.encode()).hexdigest()[:12]
    title = filename_title(info.get('title'))
    directory = output / day / f'{truncate_filename(title, 40)} [{platform}_{safe_id}]'
    budget = min(180, 240 - utf16_length(directory) - 1 - 32)
    if budget < 1:
        raise ValueError('保存目录路径过长，请选择更短的保存位置后重试。')
    stem = truncate_filename(title, budget)
    # 用字段值传递每个路径组件，避免标题和保存目录中的 %PATH% / $PATH 被展开。
    target = directory / stem
    info['_collector_path_parts'] = list(target.parts[1:])
    template = target.anchor + '/'.join(
        f'%(_collector_path_parts.{i})s' for i in range(len(info['_collector_path_parts']))) + '.%(ext)s'
    return directory, template


def error_hint(message: str) -> str:
    lower = message.lower()
    if 'cookie' in lower or 'sign in' in lower or 'login' in lower:
        return '请到“站点设置 / Cookie 管理”尝试更新 Cookie：从浏览器读取或导入新的 cookies.txt，并确认视频可以播放。'
    if '412' in lower or '429' in lower:
        return '平台限制了请求。请到“站点设置 / Cookie 管理”尝试更新 Cookie，并降低频率、稍后再试。'
    if '403' in lower:
        return '平台拒绝访问。请到“站点设置 / Cookie 管理”尝试更新 Cookie，并确认该账号能播放视频。'
    if 'unavailable' in lower or 'not available' in lower:
        return '请在浏览器确认视频未删除、当前账号和地区可以访问。'
    if 'timed out' in lower or 'connection' in lower:
        return '请检查网络；YouTube 需要本机能够访问，必要时填写已有代理地址。'
    if 'requested format' in lower:
        return '该视频没有符合高度限制的可用格式，可将最大高度改为 best 后重试。'
    return '请检查链接和日志；平台接口变化时，' + dependency_help()


def validate_settings(settings):
    if settings.quality != 'best' and not (settings.quality.isdigit() and 0 < int(settings.quality) <= 32768):
        raise ValueError('清晰度必须是 best 或有效的视频高度。')
    if not 0 <= settings.interval <= 3600:
        raise ValueError('任务间隔必须在 0 到 3600 秒之间。')
    if settings.cookies and not Path(settings.cookies).is_file():
        raise ValueError('Cookie 文件不存在。')
    if settings.node and not Path(settings.node).is_file():
        raise ValueError('Node.js 路径不存在。')


def extraction_options(settings, emit):
    runtimes = {'deno': {}}
    if node := find_node(settings.node):
        runtimes['node'] = {'path': node}
    options = {'noplaylist': True, 'playlistend': 1, 'ignoreerrors': False,
               'quiet': True, 'noprogress': True, 'socket_timeout': 20,
               'logger': Logger(emit), 'js_runtimes': runtimes, 'cachedir': False}
    if settings.cookies:
        options['cookiefile'] = settings.cookies
    if settings.proxy:
        options['proxy'] = settings.proxy
    return options


def check_video(info):
    if not info or info.get('_type', 'video') != 'video':
        raise ValueError('地址未解析为单个视频，请使用完整视频页面链接。')
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
        raise ValueError('当前仅支持已发布的视频，不采集正在直播或未开始的直播。')


def preview_video(source: str, settings: Settings, emit=lambda _: None) -> dict:
    """只读取视频信息；不会创建下载目录或启动下载。"""
    from yt_dlp import YoutubeDL
    settings = settings_for_url(settings, source)
    validate_settings(settings)
    url = resolve_short(source, settings.proxy)
    with YoutubeDL(extraction_options(settings, emit)) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        check_video(info)
        resolutions = {}
        for fmt in info.get('formats') or []:
            height = fmt.get('height')
            if fmt.get('vcodec') == 'none' or not height or fmt.get('has_drm'):
                continue
            height = int(height)
            resolutions[height] = {'height': height, 'width': fmt.get('width'),
                                   'label': f"{fmt.get('width') or '?'} × {height}"}
        fields = ('id', 'title', 'uploader', 'duration', 'thumbnail', 'description')
        result = {key: info.get(key) for key in fields}
        result.update(url=url, platform=validate_host(url),
                      qualities=[resolutions[key] for key in sorted(resolutions, reverse=True)])
        return result


def thumbnail_bytes(url, proxy=None):
    """限制封面下载体积与超时；失败不影响视频下载。"""
    if not url or urlsplit(url).scheme not in ('http', 'https'):
        return None
    import requests
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    with requests.get(url, timeout=(5, 10), stream=True, proxies=proxies,
                      headers={'User-Agent': 'Mozilla/5.0'}) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > 5 * 1024 * 1024:
                raise ValueError('封面超过 5 MB，已跳过。')
        return bytes(data)


def collect(text: str, settings: Settings, emit=print, stop=None, progress_emit=None) -> dict:
    from media_downloader import VideoDownloader, EnsureMP4PP

    validate_settings(settings)
    urls, rows = parse_inputs(text)
    if not urls and not rows:
        raise ValueError('请先粘贴至少一个视频链接。')
    output = settings.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'reports' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.json')
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'download' if settings.download else 'metadata', 'items': rows,
              'report_path': str(report_path)}
    ffmpeg = find_ffmpeg(settings.ffmpeg) if settings.download else None
    if settings.download and not ffmpeg:
        raise ValueError('输出 MP4 需要 FFmpeg。' + dependency_help())
    cap = '' if settings.quality == 'best' else f'[height<={settings.quality}]'
    runtimes = {'deno': {}}
    node = find_node(settings.node)
    if node:
        runtimes['node'] = {'path': node}
    resolved_seen = set()
    atomic_json(report_path, report)
    for index, source in enumerate(urls):
        if stop and stop.is_set():
            rows.extend({'input': pending, 'status': 'cancelled'} for pending in urls[index:])
            break
        if index:
            if stop:
                stop.wait(settings.interval)
            else:
                time.sleep(settings.interval)
            if stop and stop.is_set():
                rows.extend({'input': pending, 'status': 'cancelled'} for pending in urls[index:])
                break
        row = {'input': source, 'status': 'failed'}
        download_date = local_download_date()
        if progress_emit:
            progress_emit({'stage': 'extracting', 'index': index + 1, 'count': len(urls), 'url': source})
        emit(f'[{index + 1}/{len(urls)}] {source}')
        try:
            request_settings = settings_for_url(settings, source)
            validate_settings(request_settings)
            url = resolve_short(source, request_settings.proxy)
            if url in resolved_seen:
                row.update(status='duplicate', url=url)
                rows.append(row)
                atomic_json(report_path, report)
                continue
            resolved_seen.add(url)
            platform = validate_host(url)
            completed_files = []
            last_progress = [0.0]

            def progress(data):
                now = time.monotonic()
                if now - last_progress[0] >= 0.15 or data['status'] == 'finished':
                    last_progress[0] = now
                    total = data.get('total_bytes') or data.get('total_bytes_estimate')
                    done = data.get('downloaded_bytes', 0)
                    if progress_emit:
                        progress_emit({'stage': 'downloading', 'downloaded': done, 'total': total,
                                       'speed': data.get('speed'), 'eta': data.get('eta'),
                                       'filename': Path(data.get('filename') or '').name,
                                       'index': index + 1, 'count': len(urls)})
                    else:
                        emit(f'下载进度：{done / total:.0%}' if total else f'已接收 {done / 1048576:.1f} MB')

            def postprocess(data):
                if progress_emit:
                    progress_emit({'stage': 'processing', 'processor': data.get('postprocessor'),
                                   'index': index + 1, 'count': len(urls)})

            options = {
                'noplaylist': True, 'playlistend': 1, 'ignoreerrors': False,
                'skip_unavailable_fragments': False, 'continuedl': True,
                'overwrites': False, 'retries': 3, 'fragment_retries': 3,
                'socket_timeout': 20, 'concurrent_fragment_downloads': 1,
                'format': f'bv{cap}+ba/b{cap}' if ffmpeg else f'b{cap}',
                'format_sort': ['res', 'ext:mp4:m4a'],
                'merge_output_format': 'mp4/mkv', 'final_ext': 'mp4',
                'windowsfilenames': True, 'quiet': True, 'noprogress': True,
                'logger': Logger(emit), 'progress_hooks': [progress], 'postprocessor_hooks': [postprocess],
                'post_hooks': [completed_files.append], 'js_runtimes': runtimes,
                'cachedir': str(output / '.cache'),
            }
            if request_settings.cookies:
                options['cookiefile'] = request_settings.cookies
            if request_settings.proxy:
                options['proxy'] = request_settings.proxy
            if ffmpeg:
                options['ffmpeg_location'] = ffmpeg
            if settings.download:
                options['download_archive'] = str(output / 'archive.txt')
            with VideoDownloader(options) as ydl:
                if settings.download:
                    ydl.add_post_processor(EnsureMP4PP(ydl))
                # process=False 避免在校验返回类型前枚举播放列表或下载文件。
                info = ydl.extract_info(url, download=False, process=False)
                # yt-dlp 可在真正提取信息之前命中归档并返回 None。
                # 只把已确认的归档命中视为跳过，普通空结果仍应报错。
                if info is None and ydl.archived_info:
                    info = ydl.archived_info
                check_video(info)
                video_id = str(info['id'])
                row.update(url=url, title=info.get('title'))
                if settings.download and ydl.in_download_archive(info):
                    row['status'] = 'skipped_archive'
                    emit('已在下载记录中，跳过。')
                else:
                    directory, template = video_output_paths(output, platform, info, download_date)
                    ydl.params['outtmpl']['default'] = template
                    metadata_path = directory / 'metadata.json'
                    fields = ('id', 'title', 'description', 'uploader', 'uploader_id',
                              'duration', 'upload_date', 'timestamp', 'view_count',
                              'like_count', 'comment_count', 'tags', 'thumbnail')
                    metadata = {key: info.get(key) for key in fields}
                    metadata.update(platform=platform, webpage_url=url, download_date=download_date,
                                    collected_at=datetime.now(timezone.utc).isoformat())
                    atomic_json(metadata_path, metadata)
                    row.update(metadata=str(metadata_path), directory=str(directory), download_date=download_date)
                    if not settings.download:
                        row['status'] = 'metadata_saved'
                    else:
                        ydl.process_ie_result(info, download=True)
                        if not completed_files or not all(Path(p).is_file() and Path(p).suffix.lower() == '.mp4'
                                                          for p in completed_files):
                            raise RuntimeError('下载未产生完整文件，请检查平台限制或格式提示。')
                        row.update(status='downloaded', files=completed_files)
                emit(f"{row['status']}：{info.get('title', video_id)}")
        except Exception as exc:
            row['error'] = str(exc)
            row['hint'] = error_hint(str(exc))
            emit(f'失败：{exc}')
            emit(row['hint'])
        rows.append(row)
        if progress_emit:
            progress_emit({'stage': row['status'], 'index': index + 1, 'count': len(urls),
                           'url': source, 'error': row.get('hint')})
        atomic_json(report_path, report)
    report['counts'] = {status: sum(r['status'] == status for r in rows)
                        for status in sorted({r['status'] for r in rows})}
    atomic_json(report_path, report)
    emit('任务报告：' + str(report_path))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urls', nargs='*', help='视频链接或 B 站 BV 号')
    parser.add_argument('--file', type=Path, help='UTF-8 链接清单')
    parser.add_argument('--download', action='store_true', help='下载视频；默认仅保存信息')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--quality', default='1080', help='最大视频高度，例如 360、720、1080，或 best')
    parser.add_argument('--cookies', help='Netscape 格式 Cookie 文件')
    parser.add_argument('--proxy', help='例如 http://127.0.0.1:7890')
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--ffmpeg', help='FFmpeg 可执行文件或目录')
    parser.add_argument('--node', help='Node.js 可执行文件')
    args = parser.parse_args()
    try:
        text = '\n'.join(args.urls)
        if args.file:
            text += '\n' + args.file.read_text(encoding='utf-8-sig')
        settings = Settings(**{k: v for k, v in vars(args).items() if k not in ('urls', 'file')})
        report = collect(text, settings)
        return 1 if report['counts'].get('failed') else 0
    except (ValueError, OSError, ImportError) as exc:
        print(f'无法启动：{exc}。首次使用请运行 install.bat。', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('已中断；已完成任务的报告已保存。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
