"""Offline, stdlib-only dependency diagnostics.

collect(root=None) is safe for an endpoint: it never launches browser automation
or generates media. CLI verification is explicit and uses disposable local data.
Versions are allowlisted tokens; child stderr and exception messages stay private.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .ffmpeg import _binary_path
from .runtime import DESKTOP
from .tool_paths import resolve_tool

CHROME_URL = 'https://www.google.com/chrome/'
TIMEOUT = 5
ACTIONS = {
    'git': '安装 Git 后重新运行项目安装入口。https://git-scm.com/downloads',
    'python': '源码安装支持 Python 3.11/3.12 64 位（Windows x64、macOS Apple Silicon）。请保留现有 .venv 和数据，先制定迁移方案，再通过项目安装入口修复；不要直接删除或重建环境。',
    'tzdata': '在项目虚拟环境运行 python -m pip install tzdata，然后重试。',
    'ffmpeg': '重新运行项目安装入口以安装 FFmpeg，或配置有效的本地 ffmpeg 可执行文件。',
    'ffprobe': '重新运行项目安装入口以安装 FFmpeg，或配置有效的本地 ffprobe 可执行文件。',
    'chrome': '从 ' + CHROME_URL + ' 安装 Google Chrome 后重试；不会自动下载浏览器。',
}


def _entry(status='ready', version=None, error=None, next_action=None):
    return {'ok': status == 'ready', 'status': status, 'version': version, 'errors': [error] if error else [],
            'nextAction': next_action}


def _run(args, timeout=TIMEOUT):
    # Do not retain arbitrary output in memory, or expose it to endpoint/CLI users.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.DEVNULL, timeout=timeout)
        output.seek(0)
        return result.returncode, output.read(8192).decode('utf-8', errors='replace')


def _version(name, executable):
    if not executable:
        return _entry('missing', error='executable_not_found', next_action=ACTIONS[name])
    try:
        code, output = _run([executable, '-version' if name in ('ffmpeg', 'ffprobe') else '--version'])
    except subprocess.TimeoutExpired:
        return _entry('error', error='version_timeout', next_action=ACTIONS[name])
    except OSError:
        return _entry('error', error='executable_unavailable', next_action=ACTIONS[name])
    patterns = {
        'git': r'^git version (\d+(?:\.\d+){1,3})\b',
        'ffmpeg': r'^ffmpeg version (?:n)?(\d+(?:\.\d+){1,3})\b',
        'ffprobe': r'^ffprobe version (?:n)?(\d+(?:\.\d+){1,3})\b',
        'chrome': r'^(?:Google Chrome(?: for Testing)?|Chromium) (\d+(?:\.\d+){1,3})\b',
    }
    match = re.search(patterns[name], output)
    if code or not match:
        return _entry('error', error='version_check_failed', next_action=ACTIONS[name])
    return _entry(version=match.group(1))


def _chrome_path(root=None):
    recorded = resolve_tool('chrome', root=root)
    if recorded:
        return recorded
    candidates = []
    system = platform.system()
    if system == 'Darwin':
        candidates = [base / 'Google Chrome.app/Contents/MacOS/Google Chrome'
                      for base in (Path('/Applications'), Path.home() / 'Applications')]
    elif system == 'Windows':
        candidates = [Path(os.environ[key]) / 'Google/Chrome/Application/chrome.exe'
                      for key in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)')
                      if os.environ.get(key)]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    for name in ('google-chrome', 'google-chrome-stable', 'chrome.exe'):
        candidate = resolve_tool(name, root=root)
        if candidate:
            return candidate
    return None


def _chrome_version(executable):
    # Windows Chrome is a GUI binary: --version does not reliably write stdout.
    if platform.system() == 'Windows' and executable:
        try:
            import ctypes
            from ctypes import wintypes
            class Info(ctypes.Structure):
                _fields_ = [(name, wintypes.DWORD) for name in (
                    'signature', 'structure', 'fileMS', 'fileLS', 'productMS',
                    'productLS', 'flagsMask', 'flags', 'os', 'type', 'subtype', 'dateMS', 'dateLS')]
            dll = ctypes.WinDLL('version', use_last_error=True)
            dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
            dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
            dll.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                         ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
            size = dll.GetFileVersionInfoSizeW(executable, None)
            if not 0 < size <= 1024 * 1024:
                raise ValueError
            buffer = ctypes.create_string_buffer(size)
            pointer, length = ctypes.c_void_p(), wintypes.UINT()
            if not dll.GetFileVersionInfoW(executable, 0, size, buffer) or not dll.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)):
                raise ValueError
            if length.value < ctypes.sizeof(Info):
                raise ValueError
            info = ctypes.cast(pointer, ctypes.POINTER(Info)).contents
            if info.signature != 0xFEEF04BD:
                raise ValueError
            return _entry(version='.'.join(str(n) for n in (
                info.productMS >> 16, info.productMS & 65535, info.productLS >> 16, info.productLS & 65535)))
        except (OSError, ValueError, AttributeError):
            return _entry('error', error='version_check_failed', next_action=ACTIONS['chrome'])
    return _version('chrome', executable)



def _chrome_guidance(executable):
    guidance = "检查项目虚拟环境中的 Playwright，并运行 --verify-browser 验证发布器使用的 channel='chrome'。"
    if executable:
        guidance += '已发现 Chrome，但自定义安装路径不保证该通道可用。'
        if platform.system() == 'Darwin' and executable != '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':
            guidance += '请将 Google Chrome 安装到 /Applications；仅放在 ~/Applications 或安装记录中的自定义路径不会改变发布器的通道查找位置。'
        else:
            guidance += '请使用 Chrome 官方安装器的标准安装位置。'
    return guidance + ACTIONS['chrome']


def _mp3_encoder(executable):
    action = '需要包含 libmp3lame 编码器的 FFmpeg。' + ACTIONS['ffmpeg']
    try:
        code, output = _run([executable, '-hide_banner', '-h', 'encoder=libmp3lame'])
        if code or not re.search(r'^Encoder libmp3lame \[', output, re.MULTILINE):
            return _entry('error', error='libmp3lame_unavailable', next_action=action)
        return _entry()
    except subprocess.TimeoutExpired:
        return _entry('error', error='encoder_check_timeout', next_action=action)
    except OSError:
        return _entry('error', error='encoder_check_failed', next_action=action)


def _overall(report):
    report['overall'] = 'ready' if all(item['status'] == 'ready' for item in report['dependencies'].values()) else 'degraded'
    report['status'] = report['overall']
    report['ok'] = report['overall'] == 'ready'
    return report


def collect(root=None) -> dict:
    """Return schemaVersion/overall/dependencies; root selects the install record."""
    dependencies = {'git': _version('git', resolve_tool('git', root=root))}
    supported = (sys.version_info >= (3, 9) if DESKTOP else
                 sys.version_info[:2] in ((3, 11), (3, 12)) and sys.maxsize > 2**32)
    dependencies['python'] = _entry('ready' if supported else 'error', platform.python_version(),
                                    None if supported else 'unsupported_python',
                                    None if supported else ('桌面运行时不可用，请重新安装墨鱼工作台并保留个人数据。' if DESKTOP else ACTIONS['python']))
    try:
        # Check an actual IANA zone, not just importability or UTC.
        ZoneInfo('Asia/Shanghai')
        try:
            version = importlib.metadata.version('tzdata')
            version = version if re.fullmatch(r'\d+(?:\.\d+){1,3}', version) else None
        except importlib.metadata.PackageNotFoundError:
            version = None  # OS zone database has no portable version interface.
        dependencies['tzdata'] = _entry(version=version)
    except (ZoneInfoNotFoundError, OSError, ValueError):
        dependencies['tzdata'] = _entry('missing', error='iana_timezone_unavailable', next_action=ACTIONS['tzdata'])
    for name in ('ffmpeg', 'ffprobe'):
        try:
            dependencies[name] = _version(name, _binary_path(name, root=root))
        except OSError:
            dependencies[name] = _entry('missing', error='executable_not_found', next_action=ACTIONS[name])
    if dependencies['ffmpeg']['ok']:
        encoder = _mp3_encoder(_binary_path('ffmpeg', root=root))
        dependencies['ffmpeg']['encoders'] = {'libmp3lame': encoder}
        if not encoder['ok']:
            dependencies['ffmpeg'].update(ok=False, status='error', errors=encoder['errors'], nextAction=encoder['nextAction'])
    chrome = _chrome_path(root)
    dependencies['chrome'] = _chrome_version(chrome)
    if (chrome and dependencies['chrome']['ok'] and platform.system() == 'Darwin'
            and chrome != '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'):
        dependencies['chrome']['nextAction'] = _chrome_guidance(chrome)
    return _overall({'schemaVersion': 1, 'dependencies': dependencies})


_BROWSER_SCRIPT = '''
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True,
        timeout=15000, args=['--disable-background-networking', '--no-first-run'])
    try:
        context = browser.new_context(service_workers='block')
        context.route('**/*', lambda route: route.continue_() if route.request.url == sys.argv[1] else route.abort())
        page = context.new_page()
        page.goto(sys.argv[1], wait_until='load', timeout=10000)
        assert page.title() == 'Mofish dependency check'
        assert page.evaluate('document.querySelector("#result").textContent') == 'local-ready'
        context.close()
    finally:
        browser.close()
'''


def _verify_browser(root=None):
    executable = _chrome_path(root)
    if not executable:
        return _entry('missing', error='executable_not_found', next_action=ACTIONS['chrome'])
    try:
        with tempfile.TemporaryDirectory(prefix='mofish-browser-check-') as directory:
            page = Path(directory) / 'check.html'
            page.write_text('<title>Mofish dependency check</title><div id="result"></div>'
                            '<script>document.querySelector("#result").textContent="local-ready"</script>', encoding='utf-8')
            code, _ = _run([sys.executable, '-c', _BROWSER_SCRIPT, page.as_uri()], timeout=35)
        if code:
            raise ValueError
        return _entry()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return _entry('error', error='browser_verification_failed', next_action=
                      _chrome_guidance(executable))


def _verify_media(root=None):
    try:
        with tempfile.TemporaryDirectory(prefix='mofish-media-check-') as directory:
            target = str(Path(directory) / 'check.mp3')
            code, _ = _run([_binary_path('ffmpeg', root=root), '-nostdin', '-v', 'error', '-f', 'lavfi',
                            '-i', 'sine=frequency=440:duration=0.1', '-c:a', 'libmp3lame', '-y', target], timeout=15)
            if code:
                raise ValueError
            code, output = _run([_binary_path('ffprobe', root=root), '-v', 'error', '-show_entries',
                                 'stream=codec_name,sample_rate:format=duration', '-of', 'json', target], timeout=10)
            data = json.loads(output)
            if code or not data.get('streams') or data['streams'][0]['codec_name'] != 'mp3' or not 0 < float(data['format']['duration']) < 1:
                raise ValueError
        return _entry()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return _entry('error', error='media_verification_failed', next_action='需要包含 libmp3lame 编码器的 FFmpeg。' + ACTIONS['ffmpeg'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='项目根目录（包含 workspace/install/state.json）')
    parser.add_argument('--verify-browser', action='store_true')
    parser.add_argument('--verify-media', action='store_true')
    args = parser.parse_args(argv)
    report = collect(args.root)
    verification_failed = False
    for enabled, name, verify in ((args.verify_browser, 'chrome', _verify_browser),
                                  (args.verify_media, 'ffmpeg', _verify_media)):
        if enabled:
            result = verify(args.root)
            report['dependencies'][name]['verification'] = result
            if result['ok'] and report['dependencies'][name]['ok']:
                report['dependencies'][name]['nextAction'] = None
            if result['status'] != 'ready':
                verification_failed = True
                report['dependencies'][name].update(ok=False, status='error', errors=result['errors'], nextAction=result['nextAction'])
    _overall(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if verification_failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
