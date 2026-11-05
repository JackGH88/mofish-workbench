"""Verified source-install runtime cache. Standard library only; Python >= 3.10.

prepare_runtime(root) -> runtime directory, or None only when no release exists.
install_wheels(root, python, runtime) -> None; raises on any verification/install error.
Layout: python/python.exe (Windows) or python/bin/python3 (macOS), tools/, wheelhouse/.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

MAX_DOWNLOAD = 2 * 1024**3
MAX_EXPANDED = 6 * 1024**3
MAX_FILES = 100000
DISK_MARGIN = 64 * 1024**2
CHUNK = 1024 * 1024
PLATFORMS = {'windows-x64', 'macos-arm64'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def platform_key():
    system, machine = platform.system(), platform.machine().lower()
    if system == 'Windows' and machine in ('amd64', 'x86_64'):
        return 'windows-x64'
    if system == 'Darwin' and machine in ('arm64', 'aarch64'):
        return 'macos-arm64'
    return None


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid SHA-256')
    return value


def _https(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('Runtime downloads require HTTPS without credentials or fragments')
    return url


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_entry(entry):
    _digest(entry['sha256'])
    _digest(entry['requirementsSha256'])
    if type(entry['bytes']) is not int or not 0 < entry['bytes'] <= MAX_DOWNLOAD:
        raise ValueError('Invalid bundle byte count')
    if not isinstance(entry['urls'], list) or not 1 <= len(entry['urls']) <= 4:
        raise ValueError('Expected 1–4 HTTPS mirrors')
    for url in entry['urls']:
        _https(url)


def _require_space(directory, remaining):
    required = remaining + DISK_MARGIN
    free = shutil.disk_usage(directory).free
    if free < required:
        raise OSError('Insufficient free disk space: need %d bytes (including %d margin), have %d at %s'
                      % (required, DISK_MARGIN, free, directory))


def download(entry, cache):
    """Bounded, resumable HTTPS download; caller holds the runtime cache lock.

    Persist partial bytes only with server validators; SHA-256 remains authoritative.
    All progress goes to stderr so caller stdout remains machine-readable.
    """
    validate_entry(entry)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (entry['sha256'] + '.bundle')
    part = cache / (entry['sha256'] + '.part')
    metadata = cache / (entry['sha256'] + '.part.json')
    if target.is_file() and not target.is_symlink():
        if target.stat().st_size == entry['bytes'] and sha256(target) == entry['sha256']:
            return target
    if target.exists() or target.is_symlink():
        target.unlink()
    opener = urllib.request.build_opener(_HTTPSRedirect())
    last = None
    deadline = time.monotonic() + 900
    def discard():
        part.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
    for attempt in range(3):
        for url in entry['urls']:
            if time.monotonic() >= deadline:
                raise TimeoutError('Runtime download exceeded global 900-second budget')
            offset, validator = 0, None
            try:
                if part.is_symlink() or metadata.is_symlink():
                    discard()
                if part.is_file():
                    saved = json.loads(metadata.read_text())
                    validator = saved.get('validator')
                    if (saved.get('url') == url and isinstance(validator, str)
                            and validator and '\r' not in validator and '\n' not in validator
                            and 0 < part.stat().st_size < entry['bytes']):
                        offset = part.stat().st_size
                    else:
                        discard()
            except (OSError, ValueError):
                discard()
            _require_space(cache, entry['bytes'] - offset)
            headers = {'Accept-Encoding': 'identity'}
            if offset:
                headers.update({'Range': 'bytes=' + str(offset) + '-', 'If-Range': validator})
            print('Runtime download: %d/%d bytes (attempt %d/3)' % (offset, entry['bytes'], attempt + 1), file=sys.stderr, flush=True)
            try:
                start = time.monotonic()
                request = urllib.request.Request(url, headers=headers)
                with opener.open(request, timeout=max(0.1, min(30, deadline - time.monotonic()))) as response:
                    _https(response.geturl())
                    status = response.status
                    if status == 206:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                        if not offset or not match or tuple(map(int, match.groups())) != (offset, entry['bytes'] - 1, entry['bytes']):
                            discard()
                            raise ValueError('Invalid resumed Content-Range')
                    elif status == 200:
                        offset = 0
                        _require_space(cache, entry['bytes'])
                    else:
                        discard()
                        raise ValueError('Unexpected download HTTP status')
                    if response.headers.get('Content-Encoding', 'identity') != 'identity':
                        discard()
                        raise ValueError('Encoded download response is unsupported')
                    etag = response.headers.get('ETag', '')
                    validator = etag if etag.startswith('"') and etag.endswith('"') else response.headers.get('Last-Modified')
                    if validator:
                        metadata.write_text(json.dumps({'url': url, 'validator': validator}))
                    else:
                        metadata.unlink(missing_ok=True)
                    count, last_report = offset, start
                    with part.open('ab' if offset else 'wb') as out:
                        while True:
                            data = response.read(min(CHUNK, entry['bytes'] - count + 1))
                            if not data:
                                break
                            count += len(data)
                            if count > entry['bytes'] or time.monotonic() - start > 600 or time.monotonic() > deadline:
                                raise ValueError('Download exceeds size/time bound')
                            out.write(data)
                            if time.monotonic() - last_report >= 1 or count == entry['bytes']:
                                print('Runtime download: %d/%d bytes' % (count, entry['bytes']), file=sys.stderr, flush=True)
                                last_report = time.monotonic()
                if count != entry['bytes']:
                    raise OSError('Incomplete runtime download; validated partial retained for retry')
                if sha256(part) != entry['sha256']:
                    discard()
                    raise ValueError('Bundle checksum mismatch')
                os.replace(part, target)
                metadata.unlink(missing_ok=True)
                return target
            except (OSError, ValueError, http.client.HTTPException) as exc:
                last = exc
                # On Windows an open file cannot be unlinked; discard after close too.
                if isinstance(exc, ValueError) or getattr(exc, 'code', None) == 416:
                    discard()
                if not metadata.exists():
                    part.unlink(missing_ok=True)
        if attempt < 2:
            time.sleep(attempt + 1)
    raise RuntimeError('Runtime download failed verification; retry to resume validated partial') from last


def safe_name(name):
    # Portable paths: reject Windows ADS, device names, aliasing and traversal too.
    if not name or '\\' in name or ':' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('Unsafe archive path: ' + repr(name))
    parts = name.rstrip('/').split('/')
    for part in parts:
        if part in ('', '.', '..') or part.endswith((' ', '.')) or re.fullmatch(
            r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part
        ):
            raise ValueError('Unsafe archive path: ' + repr(name))
    return PurePosixPath(*parts)


def safe_extract(archive, destination):
    """Extract regular files/directories only into a NEW directory, never links.

    ZIP and tar accepted. Reject duplicates (including case aliases), special files,
    sparse tar entries, traversal, oversized expansion and excessive entry counts.
    Failed extraction is removed. Standalone inputs must be link-free archives.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        is_zip = zipfile.is_zipfile(archive)
        with (zipfile.ZipFile(archive) if is_zip else tarfile.open(archive, 'r:*')) as source:
            seen, total, count = set(), 0, 0
            members = source.infolist() if is_zip else source
            if is_zip:
                unpacked = sum(member.file_size for member in members)
                if len(members) > MAX_FILES or unpacked > MAX_EXPANDED:
                    raise ValueError('Archive expansion/entries exceeds limit')
                _require_space(destination, unpacked)
            for member in members:
                count += 1
                if count > MAX_FILES:
                    raise ValueError('Too many archive entries')
                name = member.filename if is_zip else member.name
                path = safe_name(name)
                key = str(path).casefold()
                if key in seen:
                    raise ValueError('Duplicate archive path')
                seen.add(key)
                directory = member.is_dir() if is_zip else member.isdir()
                size = member.file_size if is_zip else member.size
                mode = (member.external_attr >> 16) if is_zip else member.mode
                if is_zip:
                    kind = stat.S_IFMT(mode)
                    if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
                        raise ValueError('Archive links/special files forbidden')
                elif not (member.isfile() or directory) or member.sparse:
                    raise ValueError('Archive links/special/sparse files forbidden')
                total += size
                if size < 0 or total > MAX_EXPANDED:
                    raise ValueError('Archive expansion exceeds limit')
                target = destination.joinpath(*path.parts)
                if directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                _require_space(destination, size)
                target.parent.mkdir(parents=True, exist_ok=True)
                with (source.open(member) if is_zip else source.extractfile(member)) as inp, target.open('xb') as out:
                    remaining = size
                    while remaining:
                        chunk = inp.read(min(CHUNK, remaining))
                        if not chunk:
                            raise ValueError('Truncated archive member')
                        out.write(chunk)
                        remaining -= len(chunk)
                target.chmod(0o755 if mode & 0o111 else 0o644)
    except BaseException:
        shutil.rmtree(destination)
        raise


def cache_root(root):
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif platform.system() == 'Darwin':
        base = Path.home() / 'Library/Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    cache = (base / 'Mofish/source-runtime').resolve()
    if cache.is_relative_to(Path(root).resolve()):
        raise ValueError('Runtime cache must be outside source repository')
    return cache


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Runtime must not contain links')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = {
                'sha256': sha256(path), 'bytes': path.stat().st_size,
                'executable': bool(path.stat().st_mode & 0o111) if os.name != 'nt' else False,
            }
    return result


def python_path(runtime, key=None):
    return Path(runtime) / ('python/python.exe' if (key or platform_key()) == 'windows-x64' else 'python/bin/python3')


def validate_layout(runtime, key):
    required = [python_path(runtime, key)] + [runtime / 'tools' / (name + ('.exe' if key == 'windows-x64' else '')) for name in ('ffmpeg', 'ffprobe')]
    if key == 'windows-x64':
        required.append(runtime / 'python/pythonw.exe')
    if not all(p.is_file() for p in required):
        raise ValueError('Bundle missing Python/pythonw (Windows)/ffmpeg/ffprobe')
    wheels = list((runtime / 'wheelhouse').glob('*'))
    if not wheels or any(not p.is_file() or p.suffix != '.whl' for p in wheels):
        raise ValueError('Wheelhouse must contain only wheels')
    if not any(p.name.lower().startswith('tzdata-') for p in wheels):
        raise ValueError('Wheelhouse missing tzdata')


@contextmanager
def _cache_lock(cache):
    """OS-managed lock: released on crashes; serialize cache repair across callers."""
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / '.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Runtime cache is busy; lock wait exceeded 30 seconds')
                    time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def validate_requirements(path):
    # No direct URL/local/editable requirements can bypass pip --no-index.
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not re.fullmatch(
            r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+', line
        ):
            raise ValueError('Runtime requirements must be plain exact package==version pins')


def prepare_runtime(root: Path) -> Path | None:
    # Locks live outside the source tree, including for installations with no release.
    with _cache_lock(cache_root(root)):
        return _prepare_runtime(root)


def _prepare_runtime(root: Path) -> Path | None:
    root = Path(root)
    manifest = json.loads((root / 'distribution/source-runtime.json').read_text(encoding='utf-8'))
    if manifest.get('schemaVersion') != 1 or not isinstance(manifest.get('platforms'), dict):
        raise ValueError('Unsupported source runtime manifest')
    key = platform_key()
    entry = manifest['platforms'].get(key)
    if not entry:
        return None
    validate_entry(entry)
    if sha256(root / 'requirements.txt') != entry['requirementsSha256']:
        raise ValueError('Runtime requirements fingerprint does not match source')
    cache = cache_root(root)
    archive = download(entry, cache / 'archives')
    target = cache / 'runtimes' / entry['sha256']
    # An external seal prevents mutable installed packages being mistaken for bundle files.
    seal = target.with_suffix('.json')
    if target.exists() or target.is_symlink():
        try:
            if target.is_dir() and not target.is_symlink() and json.loads(seal.read_text()) == inventory(target):
                validate_layout(target, key)
                return target
        except (OSError, ValueError):
            pass
        raise RuntimeError(
            'Existing runtime cache is invalid and has been preserved: ' + str(target)
            + '. Stop dependent applications and explicitly repair/recreate their venvs '
            'before removing this runtime and its seal; then retry.'
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=target.parent) as tmp:
        stage = Path(tmp) / 'runtime'
        safe_extract(archive, stage)
        validate_layout(stage, key)
        record = inventory(stage)
        stage.rename(target)
        seal_tmp = Path(tmp) / 'seal.json'
        seal_tmp.write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
        os.replace(seal_tmp, seal)
    return target


def install_wheels(root, python, runtime) -> None:
    """Install into caller-owned Python/venv, NEVER into the immutable runtime.

    Revalidate the selected release/cache first. pip is offline, binary-only, and
    resolves requirements.txt plus tzdata from the verified bundled wheelhouse.
    """
    root, runtime, python = Path(root), Path(runtime).resolve(), Path(python).absolute()
    python = python.parent.resolve() / python.name
    validate_requirements(root / 'requirements.txt')
    verified = prepare_runtime(root)
    if verified is None or verified.resolve() != runtime:
        raise ValueError('Runtime is not the verified release for this source')
    if python.is_relative_to(runtime):
        raise ValueError('Create a separate venv before installing wheels')
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(('PIP_', 'PYTHON')):
            env.pop(name)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    subprocess.run([str(python), '-I', '-B', '-m', 'pip', '--isolated', 'install',
                    '--no-index', '--only-binary=:all:', '--no-compile',
                    '--disable-pip-version-check', '--find-links', str(runtime / 'wheelhouse'),
                    '-r', str(root / 'requirements.txt'), 'tzdata==2025.2'], env=env, check=True, timeout=900)
