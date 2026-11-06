"""Shared package versions, separate account runtimes and durable user data.

Only this coordinator publishes versions. Runtime managers never activate a
pending package independently. Legacy account packages are recovery evidence.
"""
from __future__ import annotations

import json
import asyncio
import re
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager, ExitStack
from pathlib import Path

from .packages import WorkspacePackageManager, PackageStateStore, PackageError, reject, validate_package, version_tuple
from .registry import PluginRegistry, PluginError
from .workspace_packages import LegacyPackageManager, OwnedRegistry, account_key
from .move_guard import lease, is_blocked
from .registration_backup import RegistrationBackup


class AccountRuntime(WorkspacePackageManager):
    def __init__(self, coordinator, account):
        super().__init__(coordinator.shared.root, OwnedRegistry(coordinator.registry, account))
        self.coordinator = coordinator

    @contextmanager
    def request_lease(self, pid):
        with self.coordinator._lock:
            if pid in self.coordinator._changing:
                reject('插件正在切换状态，请稍后重试。', 'plugin_busy', 409)
            self._requests[pid] = self._requests.get(pid, 0) + 1
        try:
            yield
        finally:
            with self.coordinator._lock:
                self._requests[pid] -= 1

    def activate(self):
        raise RuntimeError('Versions must be activated by the global coordinator')


class PackageManager(LegacyPackageManager):
    global_packages = True

    def __init__(self, root, registry):
        super().__init__(root, registry)
        storage_registry = PluginRegistry(registry._state, registry._credentials,
                                         account_exists=registry._account_exists)
        self.shared = WorkspacePackageManager(self.root / 'global', storage_registry)
        self.marker = self.root / 'global-format.json'
        self.migration_pending = False
        self.migration_errors = {}
        self._global = self.marker.exists() or not any((self.root / 'accounts').glob('*/installed.json'))
        self._activating = False
        self._changing = set()
        self._started = set()
        self._lifecycle_tasks = set()
        self._start_lock = None
        if self.marker.exists():
            try:
                if json.loads(self.marker.read_text()).get('format') != 3:
                    raise ValueError('unsupported format')
            except Exception:
                self.store_error = '全局插件格式记录损坏或版本不兼容，原数据已保留。'

    def _remember(self, account):
        folder = self.root / 'accounts' / account_key(account)
        folder.mkdir(parents=True, exist_ok=True)
        owner = folder / 'owner.json'
        if not owner.exists():
            self._atomic_json(owner, {'accountId': account})

    @staticmethod
    def _atomic_json(path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.global-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def _accounts(self):
        accounts = set(self._owners)
        for installed in (self.root / 'accounts').glob('*/installed.json'):
            if not (installed.parent / 'owner.json').is_file():
                reject('工作台插件缺少归属记录，原数据已保留。', 'migration_failed', 409)
        for path in (self.root / 'accounts').glob('*/owner.json'):
            account = json.loads(path.read_text())['accountId']
            if path.parent.name != account_key(account):
                reject('工作台插件归属记录损坏。', 'migration_failed', 409)
            if not self.registry._account_exists or self.registry._account_exists(account):
                accounts.add(account)
        return sorted(accounts)

    def _ensure_state(self, manager, pid):
        registry = manager.registry
        if registry.legacy_migration_owner() == registry.owner:
            registry.migrate_legacy(registry.owner)
        key = registry._state_key(pid)
        raw = registry._state.read(key)
        reset = self.shared.state.read(pid).get('disabledGeneration')
        if not raw.get('installed') or (reset and raw.get('packageGeneration') != reset):
            registry._state.update(key, dict(installed=True, enabled=False, packageGeneration=reset,
                installationId=raw.get('installationId') or uuid.uuid4().hex,
                installedAt=raw.get('installedAt') or registry._clock()))

    def for_account(self, account):
        with self.registry.account_scope(account): pass
        if not self._global:
            return super().for_account(account)
        with self._lock:
            if account not in self._owners:
                self._remember(account)
                manager = AccountRuntime(self, account)
                self._owners[account] = manager
                if not self._activating and not is_blocked(account):
                    for pid, record in self.shared.records().items():
                        if record.get('active') and not record.get('uninstalled') and pid not in self._changing:
                            try:
                                manager._load(record['active'])
                                self._ensure_state(manager, pid)
                            except Exception:
                                manager.registry.record_failure(pid, 'activation', '插件加载失败，数据已保留。')
            return self._owners[account]

    def inspect(self, raw, account):
        if not self._global:
            reject('插件正在迁移，请等待任务完成并重启后安装。', 'migration_pending', 409)
        if self.store_error: reject(self.store_error, 'package_state_invalid', 409)
        pid = validate_package(raw)[0]['id']
        with self._lock:
            if pid in self._changing: reject('插件正在卸载，请稍后重试。', 'plugin_busy', 409)
            self.for_account(account)
            return dict(self.shared.inspect(raw, account), scope='global')

    def confirm(self, token, account, *, trusted=False):
        if not self._global: reject('插件迁移尚未完成。', 'migration_pending', 409)
        with self._lock:
            if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
                reject('导入预览已失效。')
            try: pid = validate_package((self.shared.root/'staging'/(token+'.zip')).read_bytes())[0]['id']
            except OSError: reject('导入预览已失效。')
            if pid in self._changing: reject('插件正在卸载，请稍后重试。', 'plugin_busy', 409)
            self.for_account(account)
            result = self.shared.confirm(token, account, trusted=trusted, defer_activation=True)
            self._publish_format()
            return dict(result, scope='global')

    def metadata(self, pid):
        if not self._global:
            value = super().metadata(pid)
            value.update(restartRequired=True, migrationPending=True,
                         installError=self.migration_errors.get(pid) or self.migration_errors.get('migration') or value.get('installError'))
            return value
        return dict(self.shared.metadata(pid), scope='global')

    def views(self):
        result = super().views()
        for view in result:
            view.update(self.metadata(view['id']))
            if self._global:
                record = self.shared.state.read(view['id'])
                view['installed'] = bool(record.get('active')) and not record.get('uninstalled', False)
        return result

    def health_snapshot(self, account=None):
        value = super().health_snapshot(account)
        if self.migration_errors:
            value['ok'] = False
            value['failures'].extend(dict(source=pid, stage='migration', message=message)
                                     for pid, message in self.migration_errors.items())
        return value

    def resources(self, pid):
        result = super().resources(pid)
        if result and self._global:
            digest = self.shared.state.read(pid).get('active', {}).get('digest', '')
            for field in ('scripts', 'styles'):
                result[field] = [url + '&digest=' + digest for url in result[field]]
            if result['icon']: result['icon'] += '&digest=' + digest
        return result

    def uninstall(self, pid):
        reject('卸载将影响所有工作台，请在插件管理中确认全局卸载。', 'global_confirmation_required', 409)

    @contextmanager
    def _all_leases(self):
        with ExitStack() as stack:
            for account in self._accounts():
                stack.enter_context(lease(account))
            yield

    def _check_safe(self, pid, candidate=None):
        for account in self._accounts():
            if is_blocked(account): reject('工作台正在恢复脚本移动，请稍后重试。', 'script_move_busy', 409)
            manager = self.for_account(account)
            record = manager.state.read(pid)
            if record.get('active') and not record.get('uninstalled'):
                manager._safe_to_upgrade(pid, candidate)
            elif manager._requests.get(pid, 0):
                reject('插件仍有请求，请稍后重试。', 'plugin_busy', 409)

    async def uninstall_global(self, pid, *, confirmed=False):
        if not isinstance(pid, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{1,47}', pid):
            reject('插件标识不合法。')
        if not confirmed: reject('请确认卸载会影响所有工作台。', 'global_confirmation_required', 409)
        if not self._global: reject('插件迁移尚未完成。', 'migration_pending', 409)
        # A disconnected HTTP caller must not strand half-stopped runtimes.
        task = asyncio.create_task(self._uninstall_global(pid))
        self._lifecycle_tasks.add(task)
        def completed(done):
            self._lifecycle_tasks.discard(done)
            if not done.cancelled(): done.exception()
        task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def _uninstall_global(self, pid):
        # Never hold a synchronous mutex/file lock across an await. The reservation
        # rejects competing mutations while background stop hooks yield the loop.
        with self._all_leases():
            with self._lock, self.shared.transaction(pid):
                if pid in self._changing: reject('插件正在卸载，请稍后重试。', 'plugin_busy', 409)
                record = self.shared.state.read(pid)
                if not record or record.get('uninstalled'): reject('插件未安装。', 'plugin_not_found', 404)
                self._check_safe(pid)
                self._changing.add(pid)
            stopped = []
            committed = False
            try:
                for manager in list(self._owners.values()):
                    module = manager.modules.get(pid)
                    if module is None: continue
                    context = manager.registry._require_entry(pid).context
                    key = (manager.registry.owner, pid, id(module))
                    stopped.append((module, context, key))
                    self._started.discard(key)
                    stop = getattr(module, 'stop_runtime', None)
                    if callable(stop):
                        result = stop(context)
                        if hasattr(result, '__await__'): await result
                    cancel = getattr(module, 'cancel_runtime', None)
                    if callable(cancel): cancel(context)
                with self._lock, self.shared.transaction(pid):
                    record.update(previous=record.get('active') or record.get('previous'), active=None,
                                  pending=None, failed=None, uninstalled=True, installAccounts=[], installError=None,
                                  disabledGeneration=uuid.uuid4().hex)
                    self.shared.state.replace(pid, record)
                    committed = True
                    # Tombstone/generation are authoritative even if scoped cleanup
                    # is interrupted. A reinstall will still default to disabled.
                    for key, state in self.registry._state.read_all().items():
                        try: pair = json.loads(key)
                        except ValueError: continue
                        if isinstance(pair, list) and len(pair) == 2 and pair[1] == pid:
                            self.registry._state.update(key, {'installed': False, 'enabled': False})
            except BaseException:
                if not committed:
                    for module, context, key in stopped:
                        start = getattr(module, 'start_runtime', None)
                        try:
                            if callable(start):
                                result = start(context)
                                if hasattr(result, '__await__'): await result
                            self._started.add(key)
                        except Exception:
                            self.registry.record_failure(pid, 'start_runtime', '卸载失败后后台恢复失败，可重新打开工作台重试。')
                    raise
                self.registry.record_failure(pid, 'uninstall', '插件已卸载，工作台状态将在重装时自动核对。')
            finally:
                with self._lock:
                    if committed:
                        for manager in self._owners.values():
                            manager.registry._entries.pop(pid, None); manager.modules.pop(pid, None)
                    self._changing.discard(pid)
            return dict(installed=False, enabled=False, scope='global', dataRetained=True)

    async def ensure_account_runtimes(self, account):
        if is_blocked(account): return
        manager = self.for_account(account)
        if self._start_lock is None: self._start_lock = asyncio.Lock()
        async with self._start_lock:
            for pid, module in list(manager.modules.items()):
                key = (account, pid, id(module))
                if key in self._started or pid in self._changing: continue
                start = getattr(module, 'start_runtime', None)
                if callable(start):
                    with manager.request_lease(pid):
                        result = start(manager.registry._require_entry(pid).context)
                        if hasattr(result, '__await__'): await result
                self._started.add(key)

    async def start_runtimes(self):
        for account in self._accounts():
            try: await self.ensure_account_runtimes(account)
            except Exception: self.registry.record_failure(account, 'start_runtime', '插件后台任务恢复失败。')

    async def stop_runtimes(self):
        if self._lifecycle_tasks:
            await asyncio.gather(*list(self._lifecycle_tasks), return_exceptions=True)
        await super().stop_runtimes()
        self._started.clear()

    def restart_blockers(self):
        blockers = super().restart_blockers()
        blockers.extend(self.migration_errors.values())
        for account in self._accounts():
            if is_blocked(account): blockers.append('工作台正在恢复脚本移动')
        return blockers

    def mutation_allowed(self, pid, method, path):
        if method in ('GET', 'HEAD', 'OPTIONS'): return True
        if not self.migration_pending and not self.shared.state.read(pid).get('pending'): return True
        # Existing tasks must still be able to complete/return/reconcile during draining.
        return ('/tasks/' in path and path.endswith(('/return', '/download', '/adopt', '/cancel', '/reconcile'))) or path.endswith(('/close', '/release')) or ('/results/' in path and path.endswith('/adopt')) or method == 'DELETE'

    def _publish_format(self):
        self._atomic_json(self.marker, {'format': 3, 'minimumAppVersion': '0.1.22'})
        # Older desktop releases already refuse data requiring a newer app version.
        data_root = self.root.parent.parent
        version_file = data_root / 'desktop-data-version.json'
        if version_file.exists():
            from app.runtime import prepare_data_version
            existing = json.loads(version_file.read_text())['version']
            floor = max(existing, '0.1.22', key=version_tuple)
            prepare_data_version(data_root, floor)

    def migrate_existing(self, distribution):
        if self.marker.exists(): return
        # Reuse pre-package migration first; never reseed a previously removed plugin.
        super().migrate_existing(distribution)
        self._global = not any((self.root / 'accounts').glob('*/installed.json'))

    def _load_legacy(self):
        # Load only active versions. Pending versions are selected globally later.
        for account in self._accounts():
            manager = super().for_account(account)
            if is_blocked(account): continue
            for pid, record in manager.records().items():
                if record.get('active') and not record.get('uninstalled'):
                    try: manager._load(record['active'])
                    except Exception: manager.registry.record_failure(pid, 'activation', '原插件加载失败，数据已保留。')

    def _migration_candidates(self):
        choices, seen = {}, {}
        for account in self._accounts():
            manager = super().for_account(account)
            for pid, record in manager.state.read_all().items():
                if record.get('uninstalled'): continue
                result = choices.setdefault(pid, dict(history=[], installAccounts=[], migrationSources=[]))
                result['migrationSources'].append({'accountId': account, 'record': record})
                for slot in ('active', 'pending', 'previous', 'failed'):
                    item = record.get(slot)
                    if not item: continue
                    version = item['manifest']['version']
                    source = manager.root / 'versions' / pid / version
                    manifest, contents, digest = validate_package((source / 'package.zip').read_bytes())
                    if manifest != item['manifest'] or digest != item['digest']:
                        reject(f'{pid} 原插件包校验失败。', 'migration_failed', 409)
                    if any((source / name).is_symlink() or (source / name).read_bytes() != content for name, content in contents.items()):
                        reject(f'{pid} 原插件文件被修改。', 'migration_failed', 409)
                    key = (pid, version)
                    if key in seen and seen[key] != digest:
                        reject(f'{pid} 同版本包含不同内容，请先解决冲突。', 'version_conflict', 409)
                    seen[key] = digest
                    dest = self.shared.root / 'versions' / pid / version
                    if dest.exists():
                        if validate_package((dest / 'package.zip').read_bytes())[2] != digest:
                            reject(f'{pid} 全局版本目录存在内容冲突。', 'version_conflict', 409)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        temp = Path(tempfile.mkdtemp(prefix='.migration-', dir=dest.parent))
                        try:
                            shutil.copytree(source, temp, dirs_exist_ok=True)
                            os.replace(temp, dest)
                        finally:
                            if temp.exists(): shutil.rmtree(temp)
                    old = result.get(slot)
                    if not old or version_tuple(version) > version_tuple(old['manifest']['version']): result[slot] = item
        for record in choices.values():
            if record.get('active') and record.get('pending') and version_tuple(record['pending']['manifest']['version']) <= version_tuple(record['active']['manifest']['version']):
                record['pending'] = None
        return choices

    def _backup_migration(self):
        dest = self.root / 'global-migration-backup'
        if dest.exists(): return
        temp = Path(tempfile.mkdtemp(prefix='.backup-', dir=self.root))
        try:
            shutil.copytree(self.root / 'accounts', temp / 'accounts')
            state = self.registry._state.path
            if state.exists(): shutil.copy2(state, temp / 'plugins.json')
            self._atomic_json(temp / 'journal.json', {'phase': 'backed_up', 'createdAt': time.time()})
            os.replace(temp, dest)
        finally:
            if temp.exists(): shutil.rmtree(temp)

    def _migrate(self):
        self.migration_pending = True
        backup = None
        try:
            ids = set()
            for account in self._accounts():
                ids.update(super().for_account(account).state.read_all())
            self._backup_migration()
            backup = RegistrationBackup(self, ids)
            backup.__enter__()
            self._load_legacy()
            # Detect invalid scoped state instead of letting the lenient state store erase it.
            path = self.registry._state.path
            if path.exists():
                raw = json.loads(path.read_text())
                if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
                    reject('工作台插件状态损坏。', 'migration_failed', 409)
            candidates = self._migration_candidates()
            self._backup_migration()
            with self._all_leases():
                for pid in candidates: self._check_safe(pid)
                # Preflight every account with fresh module namespaces, before publishing.
                new_owners = {a: AccountRuntime(self, a) for a in self._accounts()}
                for manager in new_owners.values():
                    for record in candidates.values():
                        if record.get('active'): manager._load(record['active'])
                self._atomic_json(self.shared.state.path, candidates)
                self._publish_format()
                backup.commit()
                self._owners = new_owners
                self._global = True
                self.migration_pending = False
                self._atomic_json(self.root / 'global-migration-journal.json', {'phase': 'committed', 'at': time.time()})
        except Exception as exc:
            if backup and not backup.committed and backup.path.exists(): RegistrationBackup.recover(self)
            message = getattr(exc, 'message', None) or '插件迁移失败，原数据已保留。'
            if getattr(exc, 'code', None) not in ('plugin_busy', 'upgrade_unknown', 'script_move_busy'):
                self.migration_errors['migration'] = message
            self._atomic_json(self.root / 'global-migration-journal.json', {'phase': 'waiting', 'message': message, 'at': time.time()})

    def activate(self):
        if self.store_error: return
        with self._lock:
            RegistrationBackup.recover(self)
            self._global = self.marker.exists() or not any((self.root / 'accounts').glob('*/installed.json'))
            if not self._global:
                self._migrate()
                if not self._global: return
            self._activating = True
            try:
                for account in self._accounts(): self.for_account(account)
                with self.shared.transaction():
                    for pid, record in self.shared.records().items():
                        if record.get('uninstalled'): continue
                        active, pending = record.get('active'), record.get('pending')
                        backup = None
                        original = json.loads(json.dumps(record))
                        try:
                            if active:
                                for manager in self._owners.values():
                                    if is_blocked(manager.registry.owner): continue
                                    manager._load(active)
                            if pending:
                                with self._all_leases():
                                    if active: self._check_safe(pid, pending)
                                    backup = RegistrationBackup(self, [pid])
                                    backup.__enter__()
                                    for manager in self._owners.values(): manager._load(pending)
                                record.update(previous=active, active=pending, pending=None, failed=None, installError=None)
                            for manager in self._owners.values():
                                if pid in manager.modules: self._ensure_state(manager, pid)
                            self.shared.state.replace(pid, record)
                            if backup and backup.path.exists(): backup.commit()
                        except Exception as exc:
                            if backup and backup.path.exists(): RegistrationBackup.recover(self)
                            record = original
                            record['installError'] = getattr(exc, 'message', None) or '新版插件加载失败，已恢复旧版本，数据已保留。'
                            if pending and getattr(exc, 'code', None) not in ('plugin_busy', 'upgrade_unknown', 'script_move_busy'):
                                record.update(failed=pending, pending=None)
                            # Roll back ALL accounts, even those which loaded the candidate.
                            for manager in self._owners.values():
                                manager.registry._entries.pop(pid, None); manager.modules.pop(pid, None)
                                if active and not is_blocked(manager.registry.owner):
                                    try: manager._load(active)
                                    except Exception: manager.registry.record_failure(pid, 'activation', '旧版本恢复加载失败。')
                        self.shared.state.replace(pid, record)
                if not self.shared.store_error: self._publish_format()
                else: self.store_error = self.shared.store_error
            finally:
                self._activating = False
