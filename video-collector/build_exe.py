"""用工作区 Miniconda 构建独立 EXE，依赖来自本项目 .deps。"""
import os
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.deps'))
from collector import find_node


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='VideoCollector', help='生成的 EXE 文件名（不含扩展名）')
    name = parser.parse_args().name
    if not name or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in name):
        raise SystemExit('EXE 名称只能包含英文字母、数字、连字符和下划线。')
    node = find_node()
    if not node:
        raise SystemExit('构建需要 Node.js，请安装并添加到 PATH。')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / '.deps')
    env['PYINSTALLER_CONFIG_DIR'] = str(build / 'pyinstaller-cache')
    conda_bin = Path(sys.prefix) / 'Library' / 'bin'
    env['PATH'] = str(conda_bin) + os.pathsep + env.get('PATH', '')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
               '--name', name, '--distpath', str(ROOT / 'dist'),
               '--workpath', str(build / 'work'), '--specpath', str(build),
               '--paths', str(ROOT / '.deps'), '--add-binary', f'{node};runtime',
               '--icon', str(ROOT / 'assets' / 'video-collector.ico'),
               '--add-data', f'{ROOT / "assets" / "video-collector.ico"};assets',
               '--add-data', f'{ROOT / "assets" / "video-collector-window.png"};assets',
               '--collect-all', 'yt_dlp', '--collect-all', 'yt_dlp_ejs',
               '--collect-all', 'imageio_ffmpeg', '--collect-all', 'Cryptodome',
               '--collect-all', 'certifi', '--collect-all', 'websockets',
               '--hidden-import', 'brotli', '--noupx',
               '--exclude-module', 'IPython', '--exclude-module', 'matplotlib',
               '--exclude-module', 'numpy', '--exclude-module', 'pandas',
               '--exclude-module', 'pytest', str(ROOT / 'app_entry.py')]
    for dll in ('tcl86t.dll', 'tk86t.dll'):
        if (conda_bin / dll).is_file():
            command[3:3] = ['--add-binary', f'{conda_bin / dll};.']
    subprocess.run(command, env=env, cwd=ROOT, check=True)
    print(ROOT / 'dist' / f'{name}.exe')


if __name__ == '__main__':
    main()
