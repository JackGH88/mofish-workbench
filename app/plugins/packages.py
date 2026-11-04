"""Trusted local plugin packages. Validation never imports code; activation is restart-only.

Package code is trusted Python, not a sandbox. Persistent data and credentials are
owned by the host and never copied into version directories.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import types
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .manifest import build_manifest
from .registry import PluginError
from .state import PluginStateStore

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 96 * 1024 * 1024
MAX_FILES = 512
TOKEN_TTL = 3600


class PackageError(PluginError):
    pass


def reject(message, code='invalid_package', status=400):
    raise PackageError(code, message, status)


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        reject('插件版本必须采用主版本.次版本.修订号。')
    return tuple(map(int, value.split('.')))


def safe_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))):
        reject('插件包含非法文件路径。')
    for part in name.split('/'):
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part.endswith('.')
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}):
            reject('插件文件路径不兼容目标系统。')
    return name


def validate_package(raw):
    if len(raw) > MAX_ARCHIVE:
        reject('插件包超过 32 MB 限制。')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_EXPANDED:
                reject('插件解压大小或文件数超过限制。')
            names = set()
            contents = {}
            for info in infos:
                name = safe_name(info.filename)
                folded = name.casefold()
                mode = info.external_attr >> 16
                if folded in names or info.is_dir() or info.flag_bits & 1 or stat.S_ISLNK(mode):
                    reject('插件包含重复、加密或不支持的文件。')
                names.add(folded)
                # Whitelist excludes runtime data, secrets and arbitrary root files.
                allowed = name == 'manifest.json' or (
                    name.startswith('backend/') and name.endswith('.py')) or (
                    name.startswith('frontend/') and Path(name).suffix in {'.js', '.css', '.png', '.jpg', '.webp', '.svg', '.woff2'}) or (
                    name.startswith('skills/') and Path(name).suffix.lower() in {'.md', '.json', '.yaml', '.yml', '.py', '.js', '.css', '.html', '.svg', '.png', '.jpg', '.webp', '.txt'})
                if not allowed or any(p.startswith('.') or p == '__pycache__' for p in name.split('/')):
                    reject('插件包含清单白名单以外的文件。')
                contents[name] = archive.read(info)
        if len(contents.get('manifest.json', b'')) > 128 * 1024:
            reject('插件清单过大。')
        manifest = json.loads(contents.pop('manifest.json'))
        build_manifest(manifest)
        version_tuple(manifest.get('version'))
        if manifest['id'] == 'packages': reject('插件标识与宿主保留路径冲突。')
        if manifest.get('packageFormat') != 1 or manifest.get('dataVersion') != 1:
            reject('不支持此插件包或数据格式。')
        if (type(manifest.get('hostApiMin')) is not int or type(manifest.get('hostApiMax')) is not int
                or not manifest['hostApiMin'] <= 1 <= manifest['hostApiMax']):
            reject('当前工作台不兼容此插件，请先更新工作台。', 'incompatible_host')
        if manifest.get('backend') != 'backend/plugin.py':
            reject('插件后端入口必须是 backend/plugin.py。')
        for field, suffix in (('scripts', '.js'), ('styles', '.css')):
            values = manifest.get(field)
            if not isinstance(values, list) or len(values) != len(set(values)):
                reject('前端资源清单不合法。')
            if any(not safe_name(v).startswith('frontend/') or not v.endswith(suffix) for v in values):
                reject('前端资源类型不合法。')
        required = [manifest['backend'], *manifest['scripts'], *manifest['styles']]
        if manifest.get('icon'):
            required.append(safe_name(manifest['icon']))
        if any(name not in contents for name in required):
            reject('插件缺少入口或前端资源。')
        checksums = manifest.get('files')
        if not isinstance(checksums, dict) or set(checksums) != set(contents):
            reject('插件文件与完整性清单不一致。')
        if any(hashlib.sha256(content).hexdigest() != checksums[name] for name, content in contents.items()):
            reject('插件文件完整性校验失败。')
        if not isinstance(manifest.get('releaseNotes'), str) or len(manifest['releaseNotes']) > 20000:
            reject('插件更新说明不合法。')
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
        return manifest, contents, digest
    except PackageError:
        raise
    except Exception as exc:
        raise PackageError('invalid_package', '插件包损坏或清单格式不正确。', 400) from exc


class PackageStateStore(PluginStateStore):
    def _read(self):
        try:
            raw = json.loads(self._path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
                raise ValueError('invalid records')
            for pid, record in raw.items():
                for slot in ('active', 'pending', 'previous', 'failed'):
                    item = record.get(slot)
                    if item:
                        if item['manifest']['id'] != pid or not isinstance(item['digest'], str):
                            raise ValueError('invalid identity')
                        build_manifest(item['manifest'])
                        version_tuple(item['manifest']['version'])
            return raw
        except FileNotFoundError:
            return {}
        except Exception as exc:
            raise PackageError('package_state_invalid', '插件安装记录损坏或不可读，已停止安装操作并保留原文件。', 409) from exc


class WorkspacePackageManager:
    def __init__(self, root, registry):
        self.root = Path(root)
        self.registry = registry
        self.state = PackageStateStore(self.root / 'installed.json')
        self.store_error = None
        self._lock = threading.RLock()
        self._requests = {}
        self._operation_locks = {}
        self.modules = {}
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'staging').mkdir(exist_ok=True)
        registry.packages = self

    def records(self):
        try:
            return self.state.read_all()
        except PackageError as exc:
            if not self.store_error:
                self.registry.record_failure('packages', 'state', exc.message)
            self.store_error = exc.message
            return {}

    def operation_lock(self, plugin_id):
        with self._lock:
            return self._operation_locks.setdefault(plugin_id, threading.RLock())

    @contextmanager
    def transaction(self, plugin_id=None):
        # Same workspace/plugin is serialized; unrelated plugins remain independent.
        with self.operation_lock(plugin_id):
            lock_name = 'install-' + plugin_id + '.lock' if plugin_id else 'install.lock'
            with (self.root / lock_name).open('a+b') as handle:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == 'nt':
                        handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def request_lease(self, plugin_id):
        with self.operation_lock(plugin_id):
            self._requests[plugin_id] = self._requests.get(plugin_id, 0) + 1
        try:
            yield
        finally:
            with self.operation_lock(plugin_id):
                self._requests[plugin_id] -= 1

    def _comparison(self, manifest, digest, record):
        unchanged = False
        for slot in ('active', 'pending', 'failed', 'previous'):
            old = record.get(slot)
            if not old:
                continue
            cmp = (version_tuple(manifest['version']), version_tuple(old['manifest']['version']))
            if slot == 'failed' and cmp[0] != cmp[1]: continue
            if cmp[0] < cmp[1]:
                reject('不能通过普通导入降级插件。', 'downgrade', 409)
            if cmp[0] == cmp[1]:
                if digest != old['digest']:
                    reject('相同版本包含不同内容，请发布新的版本号。', 'version_conflict', 409)
                if slot not in ('failed', 'previous'): unchanged = True
        if unchanged: return 'unchanged'
        return 'upgrade' if record.get('active') else 'install'

    def inspect(self, raw, account):
        manifest, _, digest = validate_package(raw)
        with self.transaction(manifest['id']):
            action = self._comparison(manifest, digest, self.state.read(manifest['id']))
            # Expire abandoned uploads, never installed code.
            for old in (self.root / 'staging').glob('*'):
                if old.stat().st_mtime < time.time() - TOKEN_TTL:
                    old.unlink(missing_ok=True)
            token = uuid.uuid4().hex
            staging = self.root / 'staging' / token
            staging.with_suffix('.zip').write_bytes(raw)
            staging.with_suffix('.json').write_text(json.dumps(dict(account=account, digest=digest, created=time.time())))
            os.chmod(staging.with_suffix('.zip'), 0o600)
            return dict(token=token, manifest=manifest, action=action, compatible=True,
                        activeVersion=self.metadata(manifest['id'])['activeVersion'],
                        pendingVersion=self.metadata(manifest['id'])['pendingVersion'])

    def _safe_to_upgrade(self, plugin_id):
        if self._requests.get(plugin_id, 0):
            reject('插件仍有请求或本地写入操作，请稍后重试。', 'plugin_busy', 409)
        module = self.modules.get(plugin_id)
        if module is None:
            reject('无法确认当前插件任务状态，暂不能升级。', 'upgrade_unknown', 409)
        hook = getattr(module, 'upgrade_safe', None)
        try:
            safe = callable(hook) and hook(self.registry._require_entry(plugin_id).context) is True
        except Exception:
            safe = False
        if not safe:
            reject('仍有进行中、结果未知的任务，或无法确认数据状态，暂不能升级。', 'plugin_busy', 409)

    def confirm(self, token, account, *, trusted=False, defer_activation=False):
        if not trusted:
            reject('请确认插件包来自可信来源；插件代码将在本机运行。', 'trust_required')
        if not re.fullmatch('[a-f0-9]{32}', token):
            reject('导入预览已失效，请重新选择插件包。')
        staging = self.root / 'staging' / token
        try:
            lock_pid = validate_package(staging.with_suffix('.zip').read_bytes())[0]['id']
        except OSError:
            reject('导入预览已失效，请重新选择插件包。')
        with self.transaction(lock_pid):
            staging = self.root / 'staging' / token
            try:
                preview = json.loads(staging.with_suffix('.json').read_text())
                raw = staging.with_suffix('.zip').read_bytes()
            except (OSError, ValueError):
                reject('导入预览已失效，请重新选择插件包。')
            if preview['account'] != account or time.time() - preview['created'] > TOKEN_TTL:
                reject('导入预览不属于当前工作台或已过期。')
            manifest, contents, digest = validate_package(raw)
            if preview['digest'] != digest or manifest['id'] != lock_pid:
                reject('暂存插件包已变化，请重新导入。')
            pid = manifest['id']
            record = self.state.read(pid)
            record['uninstalled'] = False
            action = self._comparison(manifest, digest, record)
            if action != 'unchanged':
                if record.get('active') and not defer_activation:
                    self._safe_to_upgrade(pid)
                target = self.root / 'versions' / pid / manifest['version']
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # A previous failed activation can be retried only with identical bytes.
                    if validate_package((target / 'package.zip').read_bytes())[2] != digest:
                        reject('该版本目录已存在不同内容，请使用新版本号。', 'version_conflict', 409)
                else:
                    tmp = Path(tempfile.mkdtemp(prefix='.unpack-', dir=target.parent))
                    try:
                        for name, content in contents.items():
                            out = tmp / name
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(content)
                        (tmp / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
                        (tmp / 'package.zip').write_bytes(raw)
                        os.replace(tmp, target)
                    finally:
                        if tmp.exists(): shutil.rmtree(tmp)
                record['pending'] = dict(manifest=manifest, digest=digest)
                record['installError'] = None
                record['failed'] = None
                record['history'] = (record.get('history', []) + [dict(version=manifest['version'], event='staged', at=time.time())])[-50:]
            accounts = record.setdefault('installAccounts', [])
            with self.registry.account_scope(account):
                if not self.registry.state_view(pid)['installed'] and account not in accounts:
                    accounts.append(account)
            self.state.replace(pid, record)
            if action == 'unchanged' and record.get('active') and not record.get('pending'):
                self._install_accounts(pid, record)
            staging.with_suffix('.zip').unlink(missing_ok=True)
            staging.with_suffix('.json').unlink(missing_ok=True)
            return self.metadata(pid)

    def cancel_account_install(self, pid, account):
        with self.transaction(pid):
            record = self.state.read(pid)
            if record:
                record.update(active=None, pending=None, failed=None, installAccounts=[], installError=None, uninstalled=True)
                self.state.replace(pid, record)

    def _install_accounts(self, pid, record):
        retry = []
        for account in record.get('installAccounts', []):
            try:
                with self.registry.account_scope(account):
                    if not self.registry.state_view(pid)['installed']:
                        self.registry.install(pid)
            except PluginError as exc:
                if exc.code != 'account_not_found':
                    retry.append(account)
                    record['installError'] = '插件已加载，但工作台安装状态写入失败，请重启重试。'
            except Exception:
                retry.append(account)
                record['installError'] = '插件已加载，但工作台安装状态写入失败，请重启重试。'
        record['installAccounts'] = retry
        self.state.replace(pid, record)

    def _load(self, item):
        manifest = item['manifest']; pid = manifest['id']
        folder = self.root / 'versions' / pid / manifest['version']
        verified, contents, digest = validate_package((folder / 'package.zip').read_bytes())
        if digest != item['digest'] or verified != manifest:
            reject('已安装插件包完整性校验失败。')
        for name, content in contents.items():
            if (folder / name).is_symlink() or (folder / name).read_bytes() != content:
                reject('已安装插件文件被修改。')
        # Unique package namespace keeps relative imports local to this version.
        name = '_workbench_plugin_' + pid.replace('-', '_') + '_' + uuid.uuid4().hex
        namespace = types.ModuleType(name)
        namespace.__path__ = [str(folder / 'backend')]
        sys.modules[name] = namespace
        spec = importlib.util.spec_from_file_location(name + '.plugin', folder / manifest['backend'])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            module.PLUGIN = manifest
            self.registry._entries.pop(pid, None)
            self.registry.register_module(module)
            if self.registry._require_entry(pid).load_error:
                raise RuntimeError('register_failed')
            if not callable(getattr(module, 'upgrade_safe', None)):
                raise RuntimeError('missing_upgrade_contract')
            self.modules[pid] = module
        except Exception:
            self.registry._entries.pop(pid, None)
            self.modules.pop(pid, None)
            for key in list(sys.modules):
                if key == name or key.startswith(name + '.'): sys.modules.pop(key, None)
            raise

    def activate(self):
        with self.transaction():
            for pid, record in self.records().items():
                if record.get('uninstalled'): continue
                active, pending = record.get('active'), record.get('pending')
                if active:
                    try:
                        self._load(active)
                    except Exception:
                        record['installError'] = '当前插件加载失败，原有数据已保留。'
                        self.state.replace(pid, record)
                        continue
                if pending:
                    try:
                        if active: self._safe_to_upgrade(pid)
                        self._load(pending)
                    except PackageError as exc:
                        record['installError'] = exc.message
                        # Busy tasks may finish later; keep the candidate for next restart.
                        if exc.code not in ('plugin_busy', 'upgrade_unknown'):
                            record['failed'] = pending
                            record['pending'] = None
                    except Exception:
                        record['installError'] = '新版插件加载失败，已保留旧版本和数据。'
                        record['failed'] = pending
                        record['pending'] = None
                    else:
                        record['failed'] = None
                        record['previous'] = active
                        record['active'] = pending
                        record['pending'] = None
                        record['installError'] = None
                        record['history'] = (record.get('history', []) + [dict(version=pending['manifest']['version'], event='activated', at=time.time())])[-50:]
                    if pid not in self.modules and active:
                        try: self._load(active)
                        except Exception: record['installError'] = '插件恢复加载失败，原有数据已保留。'
                self.state.replace(pid, record)
                if pid in self.modules and not record.get('pending'):
                    self._install_accounts(pid, record)

    def migrate_existing(self, distribution):
        """Only seed packages for existing installations; never install on a fresh host.

        Distribution ZIPs are release artifacts shipped alongside this upgrade.
        Their ID/version remain unchanged; no account or credential migration here.
        """
        self.records()
        if self.store_error: return
        existing = self.registry._state.read_all()
        ids = set()
        for key, value in existing.items():
            if not value.get('installed'):
                continue
            try:
                scoped = json.loads(key)
                if isinstance(scoped, list) and len(scoped) == 2: ids.add(scoped[1])
            except ValueError:
                ids.add(key)  # Older unscoped records keep their existing migration path.
        with self.transaction():
            for archive in sorted(Path(distribution).glob('*.zip')):
                try:
                    raw = archive.read_bytes()
                    manifest, contents, digest = validate_package(raw)
                    pid = manifest['id']
                    if pid not in ids or self.state.read(pid): continue
                    target = self.root / 'versions' / pid / manifest['version']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        tmp = Path(tempfile.mkdtemp(prefix='.migration-', dir=target.parent))
                        try:
                            for name, content in contents.items():
                                out = tmp / name
                                out.parent.mkdir(parents=True, exist_ok=True)
                                out.write_bytes(content)
                            (tmp / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                            (tmp / 'package.zip').write_bytes(raw)
                            os.replace(tmp, target)
                        finally:
                            if tmp.exists(): shutil.rmtree(tmp)
                    self.state.replace(pid, dict(active=dict(manifest=manifest, digest=digest),
                                                 history=[dict(event='migrated', version=manifest['version'], at=time.time())]))
                except Exception:
                    self.registry.record_failure(archive.name, 'migration', '插件包迁移失败，原数据已保留。')
            for pid in ids:
                if not self.state.read(pid):
                    self.registry.record_failure(pid, 'migration', '未找到原插件迁移包，请导入对应插件包。')

    def metadata(self, pid):
        record = self.state.read(pid)
        active = record.get('active'); pending = record.get('pending')
        return dict(activeVersion=active['manifest']['version'] if active else None,
                    pendingVersion=pending['manifest']['version'] if pending else None,
                    restartRequired=bool(pending), installError=record.get('installError'))

    def views(self):
        views = {v['id']: v for v in self.registry.list_views() if v['installed']}
        for pid, record in self.records().items():
            if record.get('uninstalled'): continue
            item = record.get('active') or record.get('pending') or record.get('failed')
            if not item: continue
            view = views.setdefault(pid, dict(build_manifest(item['manifest']).as_dict(), **self.registry.state_view(pid)))
            view.update(self.metadata(pid))
            view['releaseNotes'] = item['manifest']['releaseNotes']
            view['resources'] = self.resources(pid) if pid in self.modules else None
            if pid not in self.modules: view['loadError'] = 'not_loaded'
        return list(views.values())

    def resources(self, pid):
        active = self.state.read(pid).get('active')
        if not active: return None
        m = active['manifest']
        base = '/api/plugin-assets/' + pid + '/' + m['version'] + '/'
        return dict(scripts=[base + p for p in m['scripts']], styles=[base + p for p in m['styles']],
                    icon=base + m['icon'] if m.get('icon') else None)

    def asset(self, pid, version, name):
        record = self.state.read(pid)
        active = record.get('active')
        if not active or pid not in self.modules or active['manifest']['version'] != version:
            reject('插件资源版本未生效，请刷新页面。', 'asset_not_found', 404)
        name = safe_name(name)
        if not name.startswith('frontend/') or name not in active['manifest']['files']:
            reject('插件资源不存在。', 'asset_not_found', 404)
        path = self.root / 'versions' / pid / version / name
        if not path.is_file() or path.is_symlink(): reject('插件资源不存在。', 'asset_not_found', 404)
        return path


# Public coordinator; the single-owner manager above retains package validation.
from .workspace_packages import PackageManager  # noqa: E402
