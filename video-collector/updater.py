"""从 PyPI 更新纯 Python 提取器；独立 EXE 无需 pip，重启后生效。"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit


def bootstrap(directory: Path) -> str | None:
    """仅在进程启动时调用。损坏的更新自动回退到随程序附带的版本。"""
    manifest = directory / 'active.json'
    if not manifest.is_file():
        return None
    path = None
    try:
        record = json.loads(manifest.read_text(encoding='utf-8'))
        path = (directory / 'releases' / record['release']).resolve()
        if not path.is_relative_to((directory / 'releases').resolve()):
            raise ValueError('更新目录无效')
        if not (path / 'yt_dlp/version.py').is_file():
            raise ValueError('更新文件不完整')
        sys.path.insert(0, str(path))
        importlib.invalidate_caches()
        import yt_dlp
        import yt_dlp.version
        if not Path(yt_dlp.__file__).resolve().is_relative_to(path):
            raise RuntimeError('更新模块没有正确加载')
        if yt_dlp.version.__version__ != record['version']:
            raise RuntimeError('更新版本不匹配')
        return None
    except Exception as exc:
        if path and str(path) in sys.path:
            sys.path.remove(str(path))
        for name in list(sys.modules):
            if name == 'yt_dlp' or name.startswith('yt_dlp.') or name == 'yt_dlp_ejs' or name.startswith('yt_dlp_ejs.'):
                sys.modules.pop(name, None)
        importlib.invalidate_caches()
        return f'外部更新未能加载，已回退到内置版本：{exc}'


def current_version():
    from yt_dlp.version import __version__
    return __version__


def metadata(session, package, version=None):
    suffix = f'/{quote(version, safe="")}' if version else ''
    response = session.get(f'https://pypi.org/pypi/{package}{suffix}/json', timeout=(10, 30))
    response.raise_for_status()
    return response.json()


def wheel_for(data):
    from packaging.specifiers import SpecifierSet
    running_python = '.'.join(map(str, sys.version_info[:3]))
    requirement = data['info'].get('requires_python')
    if requirement and not SpecifierSet(requirement).contains(running_python):
        raise RuntimeError('新版要求更高的 Python 版本，需要升级整个 EXE。')
    for item in data.get('urls', []):
        if item['filename'].endswith('-py3-none-any.whl') and not item.get('yanked'):
            url = urlsplit(item['url'])
            if url.scheme != 'https' or url.hostname != 'files.pythonhosted.org':
                raise ValueError('更新文件来源不是 PyPI 官方文件域名。')
            return item
    raise RuntimeError('没有兼容的纯 Python 更新包，请升级整个 EXE。')


def download_wheel(session, item, path):
    digest, size = hashlib.sha256(), 0
    with session.get(item['url'], stream=True, timeout=(10, 30)) as response:
        response.raise_for_status()
        with path.open('wb') as stream:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 32 * 1024 * 1024:
                    raise ValueError('更新包超过大小限制。')
                digest.update(chunk)
                stream.write(chunk)
    if digest.hexdigest() != item['digests']['sha256']:
        raise ValueError('更新包 SHA-256 校验失败，旧版本保持不变。')


def extract_wheel(wheel, destination, package):
    with zipfile.ZipFile(wheel) as archive:
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('更新包解压体积异常。')
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename:
                raise ValueError('更新包包含非法路径。')
            first = name.parts[0] if name.parts else ''
            if first.startswith(package + '-') and first.endswith('.data'):
                # wheel 的命令行启动脚本及文档由 pip 使用；EXE 只加载包模块。
                continue
            if first != package and not (first.startswith(package + '-') and first.endswith('.dist-info')):
                raise ValueError('更新包包含非预期模块。')
            target = destination.joinpath(*name.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('更新文件越界。')
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))


def update_latest(directory: Path, proxy=None, emit=lambda _: None, force=False):
    """先校验并完整安装，再原子切换版本指针；不改动正在运行的模块。"""
    import requests
    from packaging.requirements import Requirement
    from packaging.version import Version
    directory = Path(directory).resolve()
    current = current_version()
    with requests.Session() as session:
        if proxy:
            session.proxies.update({'http': proxy, 'https': proxy})
        emit('正在检查 PyPI 官方最新版本…')
        release = metadata(session, 'yt-dlp')
        latest = release['info']['version']
        if not force and Version(latest) <= Version(current):
            return {'status': 'current', 'version': current}
        packages = [('yt_dlp', wheel_for(release))]
        for dependency in release['info'].get('requires_dist') or []:
            req = Requirement(dependency)
            if req.name.replace('_', '-').lower() != 'yt-dlp-ejs':
                continue
            if req.marker and not req.marker.evaluate({'extra': 'default'}):
                continue
            exact = next((s.version for s in req.specifier if s.operator == '=='), None)
            ejs = metadata(session, 'yt-dlp-ejs', exact)
            if ejs['info']['version'] not in req.specifier:
                raise RuntimeError('未找到匹配的 YouTube JS 组件，旧版本保持不变。')
            packages.append(('yt_dlp_ejs', wheel_for(ejs)))
            break
        directory.mkdir(parents=True, exist_ok=True)
        release_name = uuid.uuid4().hex
        target = directory / 'releases' / release_name
        target.mkdir(parents=True)
        try:
            for package, item in packages:
                emit(f'正在下载并校验 {package}…')
                wheel = target / f'{package}.whl'
                download_wheel(session, item, wheel)
                extract_wheel(wheel, target, package)
                wheel.unlink()
            version_file = target / 'yt_dlp/version.py'
            import ast
            tree = ast.parse(version_file.read_text(encoding='utf-8'))
            installed = next(ast.literal_eval(node.value) for node in tree.body
                             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets))
            if Version(installed) != Version(latest):
                raise ValueError('更新包内部版本与官方元数据不符。')
            record = {'version': installed, 'release': release_name}
            manifest_temp = directory / f'active-{release_name}.tmp'
            manifest_temp.write_text(json.dumps(record), encoding='utf-8')
            manifest_temp.replace(directory / 'active.json')
            return {'status': 'installed', 'version': installed}
        except Exception:
            # target 为本函数刚创建的独立 UUID 目录，且明确限制在更新目录下。
            if target.resolve().is_relative_to((directory / 'releases').resolve()):
                shutil.rmtree(target)
            raise
