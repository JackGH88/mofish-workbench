"""Resource and state locations shared by source and the macOS distribution."""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = os.environ.get('MOFISH_DESKTOP') == '1' or (RESOURCE_ROOT / 'desktop-release.json').is_file()
DATA_ROOT = Path.home() / 'Library/Application Support/MofishWorkbench' if DESKTOP else RESOURCE_ROOT
LOG_ROOT = Path.home() / 'Library/Logs/MofishWorkbench' if DESKTOP else RESOURCE_ROOT / 'logs'
PLATFORM_ORIGIN = 'https://api.qqtoken.cc'
UPDATE_MESSAGE = '请退出墨鱼工作台后使用新版安装包替换应用，个人数据会保留。'


def release_info():
    try:
        value = json.loads((RESOURCE_ROOT / 'desktop-release.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        value = {'version': (RESOURCE_ROOT / 'VERSION').read_text().strip()}
    return {'version': value['version'], 'commit': value.get('commit'), 'development': False,
            'architecture': value.get('architecture', platform.machine()), 'distribution': 'desktop'}


def health_info():
    if not DESKTOP:
        return {}
    return {'distribution': 'desktop', 'architecture': platform.machine(),
            'desktopInstance': os.environ.get('MOFISH_INSTANCE', ''),
            'chromeAvailable': Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file()}


class DataVersionError(RuntimeError):
    def __init__(self, current, required):
        self.current_version = current
        self.required_version = required
        super().__init__(f'此数据由更新版本创建：当前应用 {current}，数据要求 {required} 或更新版本。请打开新版墨鱼工作台。')


def prepare_data_version(data_root, current):
    """Refuse downgrade; atomically publish markers and keep the last valid copy."""
    import uuid
    path = Path(data_root) / 'desktop-data-version.json'
    backup = path.with_suffix('.previous.json')
    def parse(raw):
        value = json.loads(raw)['version']
        parts = tuple(int(n) for n in value.split('.'))
        if len(parts) != 3:
            raise ValueError('invalid version')
        return parts
    if path.exists():
        try:
            raw = path.read_text()
            previous = parse(raw)
        except (OSError, ValueError, KeyError, TypeError):
            # Recover only from a valid prior marker; never assume damaged data is old.
            try:
                raw = backup.read_text()
                previous = parse(raw)
            except (OSError, ValueError, KeyError, TypeError):
                raise RuntimeError('数据版本记录损坏，已保留原数据。请从备份恢复版本记录后再启动。') from None
        if backup.exists():
            try:
                previous = max(previous, parse(backup.read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if previous > parse(json.dumps({'version':current})):
            raise DataVersionError(current, '.'.join(map(str, previous)))
        # Keep the most recent version in the recovery marker, including the new version.
    text = json.dumps({'version':current})
    for destination in (backup, path):
        temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('x') as handle:
                handle.write(text); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


CORE_DATA_SCHEMA = 2
CORE_DATA_MARKER = '.core-data-schema.json'


def require_core_data_schema(data_root):
    """Check before stores open; desktop startup or offline maintenance upgrades data."""
    roots = [Path(data_root) / name for name in ('workspace', 'downloads')]
    initialize = []
    for root in roots:
        marker = root / CORE_DATA_MARKER
        if root.is_symlink() or marker.is_symlink():
            raise RuntimeError('数据目录需要维护检查，请完成离线迁移后重启。')
        if marker.exists():
            try:
                version = json.loads(marker.read_text())['version']
            except (OSError, ValueError, KeyError, TypeError):
                raise RuntimeError('数据格式标记损坏，请完成离线迁移后重启。') from None
            if type(version) is not int or version != CORE_DATA_SCHEMA:
                raise RuntimeError('数据格式与当前版本不兼容，请完成离线迁移后重启。')
            continue
        existing = any(root.glob('*.json'))
        if root.name == 'workspace':
            existing = existing or any((root / 'scripts').glob('*.json'))
        else:
            existing = existing or any(root.glob('*/task.json')) or any(root.glob('*/video.json')) or any(root.glob('*/rewrite*.json'))
        if existing:
            raise RuntimeError('历史数据尚未完成迁移，请联系维护者先备份并迁移，再启动新版工作台。')
        initialize.append(root)
    # Validate every root first: a blocked upgrade never partially marks data new.
    for root in initialize:
        root.mkdir(parents=True, exist_ok=True)
        path = root / CORE_DATA_MARKER
        with path.open('x', encoding='utf-8') as handle:
            json.dump({'version': CORE_DATA_SCHEMA}, handle)
