"""Workspace-owned package coordination. No global plugin/version selection."""
from __future__ import annotations

import asyncio
import time
import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

from .registry import PluginRegistry, PluginError
from .packages import WorkspacePackageManager, validate_package, reject
from .runtime_data import prepare_runtime


def account_key(account):
    return hashlib.sha256(account.encode('utf-8')).hexdigest()


class OwnedRegistry(PluginRegistry):
    def __init__(self, parent, account):
        super().__init__(parent._state, parent._credentials, script_snapshot=parent._script_snapshot,
                         media_root=parent._media_root, clock=parent._clock,
                         account_exists=lambda value: value == account and
                         (not parent._account_exists or parent._account_exists(value)))
        self.services = parent.services
        self.owner = account
        self._account.set(account)

    @property
    def account_id(self):
        return self.owner

    def plugin_media_dir(self, plugin_id):
        if self._media_root is None:
            return super().plugin_media_dir(plugin_id)
        return prepare_runtime(self._media_root, self.owner, plugin_id)


class LegacyPackageManager:
    workspace_scoped = True

    def __init__(self, root, registry):
        self.root, self.registry = Path(root), registry
        self.root.mkdir(parents=True, exist_ok=True)
        self._owners = {}
        self._lock = threading.RLock()
        self.store_error = None
        registry.packages = self

    def for_account(self, account):
        # Validate before deriving a filesystem path or creating any directory.
        with self.registry.account_scope(account):
            pass
        with self._lock:
            if account not in self._owners:
                root = self.root / 'accounts' / account_key(account)
                manager = WorkspacePackageManager(root, OwnedRegistry(self.registry, account))
                owner = root / 'owner.json'
                if not owner.exists():
                    tmp = root / 'owner.tmp'
                    tmp.write_text(json.dumps({'accountId': account}), encoding='utf-8')
                    os.replace(tmp, owner)
                self._owners[account] = manager
            return self._owners[account]

    def _current(self):
        if self.store_error:
            reject(self.store_error, 'package_state_invalid', 409)
        return self.for_account(self.registry.account_id)

    def inspect(self, raw, account):
        if self.store_error: reject(self.store_error, 'package_state_invalid', 409)
        return self.for_account(account).inspect(raw, account)

    def confirm(self, token, account, *, trusted=False):
        if self.store_error: reject(self.store_error, 'package_state_invalid', 409)
        return self.for_account(account).confirm(token, account, trusted=trusted)

    def metadata(self, pid):
        return self._current().metadata(pid)

    def views(self):
        if self.store_error: return []
        manager = self._current()
        views = manager.views()
        for view in views:
            if view.get('resources'):
                view['resources'] = self.resources(view['id'])
                view['resourceRevision'] = manager.state.read(view['id'])['active']['digest']
        return views

    def resources(self, pid):
        resources = self._current().resources(pid)
        if not resources: return None
        account = quote(self.registry.account_id, safe='')
        def scoped(url):
            return url.replace('/api/plugin-assets/', '/api/plugin-assets/' + account + '/', 1) + '?accountId=' + account
        return dict(scripts=[scoped(x) for x in resources['scripts']],
                    styles=[scoped(x) for x in resources['styles']],
                    icon=scoped(resources['icon']) if resources['icon'] else None)

    def asset(self, account, pid, version, name):
        if account != self.registry.account_id:
            reject('插件资源不属于当前工作台。', 'asset_not_found', 404)
        return self._current().asset(pid, version, name)

    def uninstall(self, pid):
        manager = self._current()
        with manager.transaction(pid):
            record = manager.state.read(pid)
            if not record or record.get('uninstalled'):
                reject('当前工作台未安装此插件。', 'plugin_not_found', 404)
            if record.get('active') and pid in manager.modules:
                manager._safe_to_upgrade(pid)
            elif manager._requests.get(pid, 0):
                reject('插件仍有本地操作，请稍后重试。', 'plugin_busy', 409)
            cancel = getattr(manager.modules.get(pid), 'cancel_runtime', None)
            if callable(cancel):
                cancel(manager.registry._require_entry(pid).context)
            # Persist cancellation first: crashes must never resurrect an install.
            record['previous'] = record.get('active') or record.get('previous')
            record.update(active=None, pending=None, failed=None, installAccounts=[], installError=None, uninstalled=True)
            manager.state.replace(pid, record)
            manager.registry._state.replace(manager.registry._state_key(pid), {})
            manager.registry._credentials.delete(manager.registry._cred_ref(pid))
            manager.registry._entries.pop(pid, None)
            manager.modules.pop(pid, None)
            return manager.registry.state_view(pid)

    def request_lease(self, pid):
        return self._current().request_lease(pid)

    def _safe_to_upgrade(self, pid):
        return self._current()._safe_to_upgrade(pid)

    async def start_runtimes(self):
        await self._runtime_hooks('start_runtime')

    async def stop_runtimes(self):
        await self._runtime_hooks('stop_runtime')

    async def _runtime_hooks(self, name):
        """Run optional async hooks only after package registration has completed."""
        from .move_guard import is_blocked
        for manager in list(self._owners.values()):
            if name == 'start_runtime' and is_blocked(manager.registry.owner):
                continue
            for pid, module in list(manager.modules.items()):
                hook = getattr(module, name, None)
                if not callable(hook):continue
                try:
                    await hook(manager.registry._require_entry(pid).context)
                except Exception:
                    manager.registry.record_failure(pid, name, '插件后台任务恢复或停止失败。')

    async def refresh_restart_tasks(self):
        """Optional plugin hook queries existing jobs; legacy packages stay supported."""
        from .restart_tasks import refresh_legacy_tasks
        now = time.monotonic()
        if now - getattr(self, '_restart_poll_at', float('-inf')) < 10: return
        self._restart_poll_at = now
        with self._lock:
            managers = list(self._owners.values())
        for manager in managers:
            for pid, module in list(manager.modules.items()):
                try:
                    context = manager.registry._require_entry(pid).context
                    hook = getattr(module, 'refresh_restart_tasks', None)
                    with manager.request_lease(pid):
                        await asyncio.wait_for(hook(context) if callable(hook)
                                               else refresh_legacy_tasks(pid, context), timeout=15)
                except Exception:
                    # upgrade_safe remains authoritative, including unknown data.
                    pass

    def restart_blockers(self):
        """All owners participate; unknown/damaged plugin state fails closed."""
        if self.store_error: return [self.store_error]
        with self._lock:
            managers = list(self._owners.values())
        blockers = []
        for manager in managers:
            if manager.store_error:
                blockers.append('插件数据状态无法确认')
                continue
            for pid, record in manager.state.read_all().items():
                if not record.get('active') or record.get('uninstalled'): continue
                try:
                    with manager.transaction(pid):
                        manager._safe_to_upgrade(pid)
                except Exception:
                    blockers.append(f'{pid} 仍有进行中或结果未知的任务，正在等待确认')
        return blockers

    def activate(self):
        if self.store_error: return
        from .move_guard import is_blocked
        for owner_file in sorted((self.root / 'accounts').glob('*/owner.json')):
            try:
                account = json.loads(owner_file.read_text())['accountId']
                if owner_file.parent.name != account_key(account): raise ValueError('owner mismatch')
                if is_blocked(account):
                    continue
                manager = self.for_account(account)
                manager.activate()
            except PluginError as exc:
                if exc.code != 'account_not_found':
                    self.registry.record_failure(owner_file.parent.name, 'activation', exc.message)
            except Exception:
                self.registry.record_failure(owner_file.parent.name, 'activation', '插件加载失败，数据已保留。')

    def health_snapshot(self, account=None):
        managers = [self.for_account(account)] if account else list(self._owners.values())
        loaded, failures = [], list(self.registry._failures)
        for manager in managers:
            snapshot = manager.registry.health_snapshot()
            loaded.extend(dict(x, accountId=manager.registry.owner) for x in snapshot['loaded'])
            failures.extend(snapshot['failures'])
        if self.store_error: failures.append(dict(source='packages', stage='migration', message=self.store_error))
        return dict(ok=not failures and all(not x['loadError'] for x in loaded), loaded=loaded, failures=failures)

    def migrate_existing(self, distribution):
        """Copy old shared records once. Tombstones make retries non-resurrecting."""
        marker = self.root / 'workspace-migration.json'
        if marker.exists(): return
        try:
            # Preserve support for installations preceding ZIP packages.
            parent = self.registry
            legacy_registry = PluginRegistry(parent._state, parent._credentials, media_root=parent._media_root)
            legacy = WorkspacePackageManager(self.root, legacy_registry)
            legacy.migrate_existing(distribution)
            if legacy.store_error: reject(legacy.store_error, 'package_state_invalid', 409)
            if legacy_registry._failures:
                reject('旧插件迁移包缺失或损坏，请恢复插件包后重启重试。', 'migration_failed', 409)
            records = legacy.state.read_all()
            states = parent._state.read_all()
            if parent._state.path.exists():
                original = json.loads(parent._state.path.read_text(encoding='utf-8'))
                if not isinstance(original, dict) or any(not isinstance(v, dict) for v in original.values()):
                    reject('原工作台插件安装状态损坏。', 'migration_failed', 409)
            installed = {}
            for key, state in states.items():
                try:
                    pair = json.loads(key)
                    if isinstance(pair, list) and len(pair) == 2 and state.get('installed'):
                        installed.setdefault(pair[1], set()).add(pair[0])
                except ValueError:
                    if state.get('installed') and parent.legacy_migration_owner():
                        installed.setdefault(key, set()).add(parent.legacy_migration_owner())
            for pid, record in records.items():
                owners = installed.get(pid, set()) | set(record.get('installAccounts', []))
                for account in sorted(owners):
                    if parent._account_exists and not parent._account_exists(account): continue
                    target = self.for_account(account)
                    with target.transaction(pid):
                        if target.state.read(pid): continue
                        clone = json.loads(json.dumps(record))
                        clone['installAccounts'] = [account] if account in record.get('installAccounts', []) else []
                        if account not in installed.get(pid, set()) and account not in record.get('installAccounts', []):
                            clone['pending'] = None
                        for slot in ('active', 'pending', 'previous', 'failed'):
                            item = clone.get(slot)
                            if not item: continue
                            version = item['manifest']['version']
                            source = self.root / 'versions' / pid / version
                            manifest, contents, digest = validate_package((source / 'package.zip').read_bytes())
                            if digest != item['digest'] or manifest != item['manifest']: reject('原插件包完整性校验失败。')
                            if any((source / n).is_symlink() or (source / n).read_bytes() != b for n,b in contents.items()):
                                reject('原插件文件已修改。')
                            dest = target.root / 'versions' / pid / version
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            if not dest.exists():
                                tmp = Path(tempfile.mkdtemp(prefix='.copy-', dir=dest.parent))
                                try:
                                    shutil.copytree(source, tmp, dirs_exist_ok=True)
                                    os.replace(tmp, dest)
                                finally:
                                    if tmp.exists(): shutil.rmtree(tmp)
                        # Prepare legacy data before publishing this account's record.
                        target.registry.plugin_media_dir(pid)
                        clone['workspaceMigrated'] = True
                        target.state.replace(pid, clone)
            # Keep installed.json and versions as an immutable recovery backup.
            tmp = marker.with_suffix('.tmp')
            tmp.write_text(json.dumps({'format': 2}), encoding='utf-8')
            os.replace(tmp, marker)
        except Exception:
            self.store_error = '插件工作台隔离迁移失败，原数据已保留；修复后重启可重试。'


# Global packages retain the legacy coordinator solely for safe migration.
from .global_packages import PackageManager  # noqa: E402
