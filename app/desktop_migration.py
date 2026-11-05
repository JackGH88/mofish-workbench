"""Offline desktop schema-2 upgrade with durable backups and crash recovery.

Called before importing stores/schedulers, while the desktop owns its process lock.
Only known application JSON records are converted; media/plugins/user prose stay put.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

from . import legacy_data as rules


class MigrationError(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def sync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data, mode=0o600):
    rules.safe(path)
    fd, name = tempfile.mkstemp(prefix='.mofish-migration-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read(path):
    rules.safe(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_nlink != 1:
        raise MigrationError('数据文件类型异常，已停止升级。')
    return path.read_bytes()


def version_guard(root, current):
    from .runtime import DataVersionError
    def parse(value):
        parts = value.split('.')
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError('invalid version')
        return tuple(map(int, parts))
    for name in ('desktop-data-version.json', 'desktop-data-version.previous.json'):
        raw = read(root / name)
        if raw is not None:
            try:
                required = rules.decode(raw)['version']
                newer = parse(required) > parse(current)
            except (ValueError, KeyError, TypeError, AttributeError):
                raise MigrationError('数据版本记录损坏，已保留原数据，请从备份恢复。') from None
            if newer:
                raise DataVersionError(current, required)


def plan(root):
    changes = []
    markers = []
    for name in ('workspace', 'downloads'):
        directory = rules.safe(root / name)
        marker = directory / rules.SCHEMA_MARKER
        raw = read(marker)
        if raw is not None:
            try:
                value = rules.decode(raw)
                if value != {'version': 2} or type(value.get('version')) is not int:
                    raise ValueError('unsupported schema')
            except (ValueError, AttributeError):
                raise MigrationError('数据格式标记损坏或来自更新版本，已保留原数据，不能自动迁移。') from None
            continue
        if directory.exists():
            for folder, dirs, files in os.walk(directory, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d.lower() not in rules.PRUNE_DIRS)
                for child in dirs:
                    rules.safe(Path(folder) / child)
                for filename in sorted(files):
                    path = Path(folder) / filename
                    if not rules.selected_file(directory, path):
                        continue
                    original = read(path)
                    parsed = rules.decode(original)
                    converted = rules.transform_file(parsed, path)
                    target = path.with_name(rules.RENAMES.get(path.name, path.name))
                    if target != path and read(target) is not None:
                        raise MigrationError('旧数据与新版文件重名，已保留原数据，请检查后重试。')
                    if converted != parsed or target != path:
                        changes.append((path, target, original, rules.encoded(converted) if converted != parsed else original,
                                        stat.S_IMODE(path.stat().st_mode)))
        markers.append((marker, marker, None, rules.encoded({'version': 2}), 0o600))
    return changes, markers


def entry_paths(root, entry):
    paths = []
    for key in ('source', 'target'):
        relative = Path(entry[key])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] not in ('workspace', 'downloads'):
            raise MigrationError('迁移记录路径异常，已停止恢复。')
        path = rules.safe(root / relative)
        directory = root / relative.parts[0]
        if not (path == directory / rules.SCHEMA_MARKER or rules.selected_file(directory, path)):
            raise MigrationError('迁移记录包含非业务数据，已停止恢复。')
        paths.append(path)
    source, target = paths
    if target != source.with_name(rules.RENAMES.get(source.name, source.name)):
        raise MigrationError('迁移记录重命名异常。')
    return source, target


def rollback(root, run, journal):
    restore = []
    seen = set()
    for entry in reversed(journal['entries']):
        source, target = entry_paths(root, entry)
        if source in seen or target in seen:
            raise MigrationError('迁移记录重复，已停止恢复。')
        seen.update((source, target))
        backup = entry['backup']
        if backup is None:
            if source.name != rules.SCHEMA_MARKER or entry['before'] is not None:
                raise MigrationError('原始数据备份缺失。')
            original = None
        else:
            if not isinstance(backup, str) or Path(backup).name != backup or not backup.endswith('.bin'):
                raise MigrationError('备份路径异常。')
            original = read(run / backup)
            if original is None or digest(original) != entry['before']:
                raise MigrationError('备份校验失败，已保留数据，请检查备份。')
        src, dst = digest(read(source)), digest(read(target))
        before, after = entry['before'], entry['after']
        if (source == target and src not in (before, after) or
                source != target and (src, dst) not in ((before, None), (None, after), (before, after))):
            raise MigrationError('迁移期间数据被其他程序修改，已保留现场，请检查备份。')
        restore.append((source, target, original, entry['mode'], src, dst))
    # Validate ALL backups first; withdraw schema markers before legacy restores.
    for source, target, original, mode, src, dst in restore:
        if digest(read(source)) != src or digest(read(target)) != dst:
            raise MigrationError('恢复期间数据发生变化，已停止。')
        if original is None:
            if source.exists():
                source.unlink()
                sync(source.parent)
        elif src != digest(original):
            atomic(source, original, mode)
        if target != source and target.exists():
            target.unlink()
            sync(target.parent)
    journal['state'] = 'rolled-back'
    atomic(run / 'journal.json', rules.encoded(journal))


def prepare(root, current, progress=lambda message: None):
    """Prepare fresh/legacy data. Failure leaves a durable recoverable journal."""
    import fcntl
    root = rules.safe(Path(root))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = rules.safe(root / '.desktop-migration.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MigrationError('另一个进程正在升级本地数据，请稍后重启。') from None
        return _prepare(root, current, progress)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MigrationError('本地数据升级未完成，原始备份已保留；请查看日志后重试。') from exc
    finally:
        os.close(fd)


def _prepare(root, current, progress):
    version_guard(root, current)
    progress('正在检查本地数据；旧数据将自动备份并升级…')
    backups = rules.safe(root / 'migration-backups')
    active = backups / 'active.json'
    raw = read(active)
    if raw is not None:
        run_id = rules.decode(raw)['run']
        if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
            raise MigrationError('迁移记录无效，已保留现场。')
        run = rules.safe(backups / run_id)
        journal = rules.decode(read(run / 'journal.json'))
        if journal.get('version') != 1 or journal.get('root') != str(root):
            raise MigrationError('迁移记录与当前数据目录不匹配。')
        if journal['state'] == 'prepared':
            progress('正在恢复上次未完成的数据升级…')
            rollback(root, run, journal)
        elif journal['state'] not in ('applied', 'rolled-back'):
            raise MigrationError('迁移记录状态异常，已停止。')
        active.unlink()
        sync(backups)
    changes, markers = plan(root)
    if not markers:
        return
    # Even unchanged legacy records require a journal for the readiness markers.
    old_records = any(any((root / name).glob('*.json')) or any((root / name).glob('*/*.json'))
                      for name in ('workspace', 'downloads'))
    if not changes and not old_records:
        from .runtime import require_core_data_schema
        require_core_data_schema(root)
        return
    progress('正在备份并升级本地数据，请勿退出…')
    for name in ('workspace', 'downloads'):
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.mkdir(mode=0o700, exist_ok=True)
    sync(root)
    run = backups / uuid.uuid4().hex
    run.mkdir(mode=0o700)
    sync(backups)
    entries = []
    for index, (source, target, original, updated, mode) in enumerate(changes + markers):
        backup = f'{index:06d}.bin' if original is not None else None
        if backup:
            atomic(run / backup, original)
        entries.append(dict(source=str(source.relative_to(root)), target=str(target.relative_to(root)),
                            backup=backup, before=digest(original), after=digest(updated), mode=mode))
    journal = dict(version=1, root=str(root), state='prepared', entries=entries)
    atomic(run / 'journal.json', rules.encoded(journal))
    atomic(active, rules.encoded({'run': run.name}))
    try:
        for source, target, original, updated, mode in changes + markers:
            if digest(read(source)) != digest(original) or target != source and read(target) is not None:
                raise MigrationError('备份期间数据发生变化，已停止升级。')
            atomic(target, updated, mode)
            if source != target:
                source.unlink()
                sync(source.parent)
        from .runtime import require_core_data_schema
        require_core_data_schema(root)
        journal['state'] = 'applied'
        atomic(run / 'journal.json', rules.encoded(journal))
    except Exception as exc:
        try:
            rollback(root, run, journal)
        except Exception as recovery:
            raise MigrationError(f'升级中断，备份保存在 {run}；自动恢复尚未完成，请检查后重启。') from recovery
        raise MigrationError(f'升级未完成，已恢复原数据；备份保存在 {run}。请重启重试。') from exc
    active.unlink()
    sync(backups)
    progress('本地数据升级完成，正在启动…')
