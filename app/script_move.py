"""Recoverable script-scoped transfer of account-owned AI video records.

Media is copied and verified before ownership changes. Journals contain before/after
images of *selected records*, not whole databases: recovery never rewinds another
script. Source media is retained because published references can be shared.
"""
from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import uuid

from .plugins.move_guard import move_guard

_LOCK = threading.RLock()
SECTIONS = ('drafts', 'sources', 'tasks', 'results', 'skills', 'attachments')
FINAL_GENERATION = {'completed', 'saved', 'failed', 'cancelled', 'adopt_failed', 'edit_failed'}
FINAL_EDIT = {'completed', 'saved', 'cancelled', 'superseded', 'abandoned'}
FINAL_SCHEDULE = {'completed', 'failed', 'missed', 'cancelled', 'stopped'}


class ScriptMoveError(Exception):
    def __init__(self, code, message, status_code=409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def fail(code, message):
    raise ScriptMoveError('script_move_' + code, message)


def read_json(path, default):
    if not path.exists():
        return deepcopy(default)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, type(default)):
            raise ValueError()
        return value
    except (ValueError, OSError):
        fail('conflict', '制作记录损坏，请先恢复备份。')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with tmp.open('w', encoding='utf-8') as f:
            os.chmod(tmp, 0o600)
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_name(value):
    if not isinstance(value, str) or not value or Path(value).name != value or value in ('.', '..') or '\\' in value:
        fail('conflict', '素材引用包含无效路径。')
    return value


class ScriptMoveService:
    def __init__(self, store, packages=None):
        self.store, self.packages = store, packages
        self.root = Path(store._workspace_dir).resolve()
        self.media = self.root / 'plugins'
        self.journals = self.root / 'script-moves'

    @contextmanager
    def _disk_lock(self):
        self.journals.mkdir(parents=True, exist_ok=True)
        with (self.journals / '.lock').open('a+b') as handle:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if handle.tell() == 0:
                        handle.write(b'0'); handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fail('busy', '另一个进程正在迁移或恢复脚本，请稍后再试。')
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def runtime(self, account, plugin='heygen'):
        return self.media / 'accounts' / hashlib.sha256(account.encode()).hexdigest() / plugin

    def _contexts(self, accounts, stack):
        contexts = {}
        if self.packages is None:
            fail('plugin_incompatible', '请通过工作台服务执行迁移。')
        if hasattr(self.packages, 'assert_move_compatible'):
            try:
                self.packages.assert_move_compatible(*accounts, ['heygen'])
            except Exception as exc:
                fail('plugin_incompatible', str(exc))
            return contexts
        for account in sorted(set(accounts)):
            manager = self.packages.for_account(account)
            try:
                view = manager.registry.state_view('heygen')
                if not view.get('installed') or not view.get('enabled'):
                    raise ValueError()
                if manager.metadata('heygen').get('restartRequired'):
                    raise ValueError()
                entry = manager.registry._require_entry('heygen')
                ctx = entry.context
                if entry.load_error or not all(hasattr(ctx, key) for key in ('studio', 'editing', 'heygen_tasks', 'schedules')):
                    raise ValueError()
            except Exception:
                fail('plugin_incompatible', '来源和目标工作台需启用兼容的 AI 视频工作流插件，并完成待生效升级。')
            contexts[account] = ctx
            # The scheduler acquires its lock before calling the editing service.
            for lock in (ctx.schedules.lock, ctx.editing.lock, ctx.heygen_tasks._lock):
                stack.enter_context(lock)
        return contexts

    def _has_data(self, account, sid):
        for pid in ('heygen', 'ai-edit'):
            root = self.runtime(account, pid)
            for name in ('editing.json', 'tasks.json', 'schedules/schedules.json'):
                p = root / name
                if p.exists() and self._contains(read_json(p, [] if name == 'tasks.json' else {}), sid):
                    return True
            for name in ('studio/workflow.sqlite3', 'spoken-drafts.sqlite3', 'audio-refs.sqlite3'):
                p = root / name
                if p.exists():
                    with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)) as db:
                        for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
                            if 'script' in columns and db.execute(f'SELECT 1 FROM "{table}" WHERE script=? LIMIT 1', (sid,)).fetchone():
                                return True
        return False

    def _has_artifacts(self, account, sid):
        for pid in ('heygen', 'ai-edit'):
            root = self.runtime(account, pid)
            editing = read_json(root / 'editing.json', {})
            if any(v.get('scriptId') == sid for k in ('sources', 'tasks', 'results', 'attachments') for v in editing.get(k, {}).values()):
                return True
            if any(v.get('scriptId') == sid for v in read_json(root / 'tasks.json', [])):
                return True
            p = root / 'studio/workflow.sqlite3'
            if p.exists():
                with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)) as db:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone() and db.execute('SELECT 1 FROM tasks WHERE script=? LIMIT 1', (sid,)).fetchone():
                        return True
        return False

    @staticmethod
    def _contains(data, sid):
        if isinstance(data, list):
            return any(isinstance(v, dict) and v.get('scriptId') == sid for v in data)
        return any(isinstance(bucket, dict) and (sid in bucket or any(isinstance(v, dict) and v.get('scriptId') == sid for v in bucket.values())) for bucket in data.values())

    def _plan(self, sid, source, target, contexts, preserve_target_drafts=False):
        """Build a deterministic manifest without modifying runtime data."""
        src, dst = self.runtime(source), self.runtime(target)
        plan = {'scriptId': sid, 'source': source, 'target': target, 'json': [], 'sql': [], 'files': []}
        planned_files = {}
        json_updates = {}

        def update(path, before, after):
            if before == after:
                return
            key = str(path)
            if key in json_updates:
                json_updates[key]['after'] = after
            else:
                json_updates[key] = {'path': key, 'before': before, 'after': after}

        def file(source_path, target_path, required=True, content=None):
            if not source_path.is_file():
                if required:
                    fail('asset_missing', '素材文件缺失：' + source_path.name)
                return
            if source_path.is_symlink() or not source_path.resolve().is_relative_to(self.media):
                fail('conflict', '素材路径不在工作台媒体目录内。')
            if not target_path.resolve().is_relative_to(self.media):
                fail('conflict', '目标素材目录无效。')
            checksum = digest(source_path) if content is None else hashlib.sha256(content.encode('utf-8')).hexdigest()
            if target_path.exists():
                if not target_path.is_file() or digest(target_path) != checksum:
                    fail('conflict', '目标存在不同内容的素材：' + target_path.name)
                return
            key = str(target_path)
            if key in planned_files and planned_files[key]['sha256'] != checksum:
                fail('conflict', '多个来源的素材内容冲突。')
            planned_files[key] = {'source': str(source_path), 'path': key, 'sha256': checksum}
            if content is not None:
                planned_files[key]['content'] = content

        def directory(source_path, target_path, rewrite_context=False):
            if not source_path.is_dir():
                fail('asset_missing', '任务或 Skill 目录缺失：' + source_path.name)
            for p in sorted(source_path.rglob('*')):
                if p.is_symlink():
                    fail('conflict', '任务目录包含符号链接，请先处理。')
                if p.is_file():
                    content = None
                    if rewrite_context and p == source_path / 'context.md':
                        content = self._rewrite(p.read_text(encoding='utf-8'), source, target, src, dst, {})
                        content = self._rewrite(content, source, target, self.runtime(source, 'ai-edit'), dst, {})
                    file(p, target_path / p.relative_to(source_path), content=content)

        def find(root, relative):
            candidates = [root / relative, src / relative, self.runtime(source, 'ai-edit') / relative]
            return next((p for p in candidates if p.is_file() or p.is_dir()), candidates[0])

        def merge(bucket, key, value, allow_draft=False):
            old = bucket.get(key)
            if old is not None and old != value:
                if not (allow_draft and self._empty_draft(old)):
                    fail('conflict', '目标工作台已有不同的同 ID 制作记录。')
            bucket[key] = value

        # Merge retired editing records into HeyGen. Legacy copies may coexist.
        empty = {k: {} for k in SECTIONS}
        target_before = read_json(dst / 'editing.json', empty)
        target_edit = deepcopy(target_before)
        for section in SECTIONS:
            target_edit.setdefault(section, {})
        skill_map = {}
        authoritative = {k: set() for k in SECTIONS}
        for root in (src, self.runtime(source, 'ai-edit')):
            p = root / 'editing.json'
            before = read_json(p, empty)
            after = deepcopy(before)
            selected = {k: {i: deepcopy(v) for i, v in before.get(k, {}).items() if (i == sid if k == 'drafts' else v.get('scriptId') == sid)} for k in SECTIONS if k != 'skills'}
            if root != src:
                for section, rows in selected.items():
                    for key in set(rows) & authoritative[section]:
                        rows.pop(key)
                        after[section].pop(key, None)
            else:
                for section, rows in selected.items():
                    authoritative[section].update(rows)
            for t in selected['tasks'].values():
                if t.get('status') not in FINAL_EDIT:
                    fail('task_active', '剪辑任务尚未结束，请完成或取消后再移动。')
            skills = {v.get('skillId') for group in selected.values() for v in group.values() if v.get('skillId') not in (None, '', 'preset')}
            workflow_path = src / 'studio/workflow.sqlite3'
            if root == src and workflow_path.exists():
                with closing(sqlite3.connect(workflow_path.as_uri() + '?mode=ro', uri=True)) as db:
                    for table in ('drafts', 'tasks'):
                        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                            for raw, in db.execute(f'SELECT data FROM {table} WHERE script=? AND owner=?', (sid, source)):
                                record = json.loads(raw)
                                skill_id = (record.get('draft') or record).get('skillId')
                                if skill_id not in (None, '', 'preset'):
                                    skills.add(skill_id)
            for skill_id in sorted(skills):
                safe_name(skill_id)
                skill = before.get('skills', {}).get(skill_id)
                if not skill:
                    # Deleted skills may still be frozen in historical task folders.
                    frozen = next((find(root, Path('tasks') / t['id'] / 'skills' / skill_id) for t in selected['tasks'].values() if t.get('skillId') == skill_id), None)
                    if not frozen or not frozen.is_dir():
                        fail('asset_missing', '脚本引用的自定义 Skill 已缺失。')
                    skill = {'id': skill_id, 'name': skill_id, 'preset': False}
                    folder = frozen
                else:
                    folder = find(root, Path('skills') / skill_id)
                if not folder.is_dir():
                    fail('asset_missing', '脚本引用的自定义 Skill 文件已缺失。')
                signature = self._directory_digest(folder)
                new_id = skill_map.get(skill_id, skill_id)
                existing = target_edit['skills'].get(new_id)
                target_folder = dst / 'skills' / new_id
                different_files = target_folder.exists() and self._directory_digest(target_folder) != signature
                if (existing and existing != skill) or different_files:
                    suffix = hashlib.sha256((json.dumps(skill, sort_keys=True) + signature).encode()).hexdigest()[:12]
                    new_id = skill_id + '-moved-' + suffix
                skill_map[skill_id] = new_id
                migrated = dict(skill, id=new_id)
                merge(target_edit['skills'], new_id, migrated)
                directory(folder, dst / 'skills' / new_id)
            for section, rows in selected.items():
                for key, value in rows.items():
                    safe_name(key)
                    value = self._rewrite(value, source, target, src, dst, skill_map)
                    if section == 'attachments':
                        if value.get('id') != key:
                            fail('conflict', '补充素材 ID 与记录不一致。')
                        name = safe_name(value.get('name'))
                        relative = Path('attachments') / key / name
                        folder = find(root, relative)
                        if folder.resolve() != folder.absolute():
                            fail('conflict', '补充素材目录包含符号链接。')
                        for item in value.get('files', []):
                            path = item.get('path')
                            if not isinstance(path, str) or '\\' in path or any(part in ('', '.', '..') for part in path.split('/')) or Path(path).is_absolute():
                                fail('conflict', '补充素材引用包含无效路径。')
                            asset = folder / path
                            if not asset.is_file() or asset.stat().st_size != item.get('size'):
                                fail('asset_missing', '补充素材文件缺失或大小已改变。')
                        directory(folder, dst / relative)
                    if section in ('sources', 'results'):
                        name = safe_name(value.get('file'))
                        file(find(root, Path('media') / name), dst / 'media' / name)
                        if 'media' in value:
                            value['media'] = 'heygen/media/' + name
                    if section == 'tasks':
                        # Invalidate every old return capability, including after A→B→A.
                        # Keep the historical status/ID and create new tasks for future edits.
                        existing = target_edit['tasks'].get(key)
                        if existing and existing.get('movedHistory'):
                            value = existing if self._same_history(existing, value) else value
                        else:
                            value.update(token=secrets.token_urlsafe(32), installationId='moved-history', movedHistory=True)
                        directory(find(root, Path('tasks') / key), dst / 'tasks' / key,
                                  rewrite_context=bool(value.get('attachmentId')))
                    if not (section == 'drafts' and preserve_target_drafts and key in target_edit[section]):
                        merge(target_edit[section], key, value, section == 'drafts')
                    after[section].pop(key, None)
            update(p, before, after)
        update(dst / 'editing.json', target_before, target_edit)

        # Legacy avatar index, retained in memory by TaskManager.
        p, q = src / 'tasks.json', dst / 'tasks.json'
        before, target_before = read_json(p, []), read_json(q, [])
        rows = [r for r in before if r.get('scriptId') == sid]
        target_rows = {r['id']: r for r in target_before}
        for row in rows:
            if row.get('status') not in FINAL_GENERATION:
                fail('task_active', '数字人生成任务尚未结束，请完成或取消后再移动。')
            value = self._rewrite(row, source, target, src, dst, skill_map)
            if row.get('localFile'):
                name = safe_name(row['localFile'])
                file(src / 'media' / name, dst / 'media' / name)
            if row.get('audioRef'):
                name = safe_name(row['audioRef'])
                file(src / 'recordings' / name, dst / 'recordings' / name)
            merge(target_rows, row['id'], value)
        update(p, before, [r for r in before if r.get('scriptId') != sid])
        update(q, target_before, list(target_rows.values()))

        # SQLite moves are selected by script and owner; unrelated preferences remain.
        for relative, tables in (
            ('studio/workflow.sqlite3', ('drafts', 'tasks')),
            ('spoken-drafts.sqlite3', ('drafts',)),
            ('audio-refs.sqlite3', ('audio_refs', 'audio_drafts')),
        ):
            p, q = src / relative, dst / relative
            if not p.exists():
                continue
            with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)) as db:
                for table in tables:
                    schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                    if not schema:
                        continue
                    columns = [r[1] for r in db.execute(f'PRAGMA table_info({table})')]
                    owner = json.dumps(source) if relative == 'spoken-drafts.sqlite3' else source
                    target_owner = json.dumps(target) if relative == 'spoken-drafts.sqlite3' else target
                    selected_rows = db.execute(f'SELECT * FROM {table} WHERE script=? AND owner=?', (sid, owner)).fetchall()
                    if not selected_rows:
                        continue
                    target_old = self._sql_rows(q, table, columns, sid, target_owner)
                    migrated = []
                    for row in selected_rows:
                        value = dict(zip(columns, row))
                        value['owner'] = target_owner
                        if 'data' in value:
                            record = json.loads(value['data'])
                            if table == 'tasks' and record.get('status') not in FINAL_GENERATION:
                                fail('task_active', '数字人生成任务尚未结束或提交结果未知，请先处理。')
                            record = self._rewrite(record, source, target, src, dst, skill_map)
                            if relative.startswith('studio/'):
                                if table == 'drafts':
                                    record.pop('voiceSpeeds', None)
                                for name in (record.get('localFile'), record.get('audioFile'), record.get('audioRef'), (record.get('draft') or {}).get('audioRef')):
                                    if name:
                                        file(src / 'studio' / safe_name(name), dst / 'studio' / name)
                                ref = record.get('mediaRef', '')
                                if ref.startswith('heygen/media/'):
                                    name = safe_name(ref[len('heygen/media/'):])
                                    file(src / 'media' / name, dst / 'media' / name)
                            if table == 'audio_refs':
                                file(src / 'recordings' / safe_name(value['ref']), dst / 'recordings' / value['ref'])
                            value['data'] = json.dumps(record, ensure_ascii=False)
                        migrated.append([value[c] for c in columns])
                    if target_old and table in ('drafts', 'audio_drafts') and preserve_target_drafts:
                        migrated = target_old
                    if target_old and target_old != migrated:
                        harmless = table == 'drafts' and 'data' in columns and all(self._empty_draft(json.loads(r[columns.index('data')])) or self._placeholder_studio_draft(json.loads(r[columns.index('data')]), json.loads(migrated[0][columns.index('data')])) for r in target_old)
                        if not harmless:
                            fail('conflict', '目标工作台已有不同的制作草稿或任务。')
                    for path, own, old, new in ((p, owner, selected_rows, []), (q, target_owner, target_old, migrated)):
                        plan['sql'].append({'path': str(path), 'table': table, 'columns': columns, 'schema': schema[0], 'script': sid, 'owner': own, 'before': [list(r) for r in old], 'after': new})

        # Old uploads bind remote asset IDs to the old credential fingerprint.
        # Preserve history, but use the local recording for future studio generation
        # so the destination uploads it with its own provider credentials.
        audio_ops = [op for op in plan['sql'] if op['path'] == str(dst / 'audio-refs.sqlite3')]
        refs = {dict(zip(op['columns'], row))['ref']: dict(zip(op['columns'], row))
                for op in audio_ops if op['table'] == 'audio_refs' for row in op['after']}
        chosen = {dict(zip(op['columns'], row))['ref'] for op in audio_ops if op['table'] == 'audio_drafts' for row in op['after']}
        studio_path = dst / 'studio/workflow.sqlite3'
        studio_draft = next((op for op in plan['sql'] if op['path'] == str(studio_path) and op['table'] == 'drafts'), None)
        target_draft = self._sql_rows(studio_path, 'drafts', ['owner', 'script', 'data'], sid, target)
        if chosen and studio_draft is None and not target_draft:
            if len(chosen) != 1:
                fail('conflict', '旧版脚本存在多个录音草稿，请先明确当前录音。')
            ref = next(iter(chosen))
            if ref not in refs:
                fail('asset_missing', '旧版录音草稿缺少录音记录。')
            meta = json.loads(refs[ref]['data'])
            name = ref + ('.wav' if meta.get('mime') == 'audio/wav' else '.mp3')
            file(src / 'recordings' / safe_name(ref), dst / 'studio' / name)
            draft = {'videoType': 'avatar', 'mode': 'audio', 'audioRef': name, 'audioName': meta.get('name', name)}
            plan['sql'].append({'path': str(studio_path), 'table': 'drafts', 'columns': ['owner', 'script', 'data'],
                               'schema': 'CREATE TABLE drafts(owner TEXT,script TEXT,data TEXT,PRIMARY KEY(owner,script))',
                               'script': sid, 'owner': target, 'before': [],
                               'after': [[target, sid, json.dumps(draft, ensure_ascii=False)]]})

        p, q = src / 'schedules/schedules.json', dst / 'schedules/schedules.json'
        before, target_before = read_json(p, {'schedules': {}}), read_json(q, {'schedules': {}})
        after, target_after = deepcopy(before), deepcopy(target_before)
        for key, row in before.get('schedules', {}).items():
            if row.get('scriptId') != sid:
                continue
            if row.get('status') not in FINAL_SCHEDULE:
                fail('task_active', '脚本存在待执行或未结束的定时任务，请先取消或完成。')
            value = self._rewrite(row, source, target, src, dst, skill_map)
            merge(target_after.setdefault('schedules', {}), key, value)
            after['schedules'].pop(key)
        moved_ids = set(target_after.get('schedules', {})) - set(target_before.get('schedules', {}))
        moved_ids.update(authoritative['tasks'])
        for key, value in before.get('hiddenCards', {}).items():
            if key.partition(':')[2] in moved_ids:
                merge(target_after.setdefault('hiddenCards', {}), key, value)
                after.get('hiddenCards', {}).pop(key, None)
        update(p, before, after)
        update(q, target_before, target_after)
        plan['json'] = list(json_updates.values())
        plan['files'] = list(planned_files.values())
        return plan

    @staticmethod
    def _directory_digest(folder):
        h = hashlib.sha256()
        for p in sorted(folder.rglob('*')):
            if p.is_symlink():
                fail('conflict', 'Skill 目录包含符号链接。')
            if p.is_file():
                h.update(str(p.relative_to(folder)).encode())
                h.update(digest(p).encode())
        return h.hexdigest()

    @staticmethod
    def _same_history(a, b):
        ignored = {'token', 'installationId', 'movedHistory'}
        return {k: v for k, v in a.items() if k not in ignored} == {k: v for k, v in b.items() if k not in ignored}

    @staticmethod
    def _empty_draft(value):
        # Loading an empty destination creates this editing draft automatically.
        return all(k in ('agentId', 'skillId', 'requirements') for k in value) and value.get('skillId', 'preset') in ('', 'preset') and not value.get('requirements')

    @staticmethod
    def _placeholder_studio_draft(value, incoming):
        # Opening the avatar tab persists defaults before any resources are selected.
        defaults = {'mode': 'text', 'voicePlatform': 'heygen', 'avatarPlatform': 'heygen',
                    'voice': None, 'avatar': None, 'ratio': 'auto', 'quality': '1080p',
                    'skillId': '', 'agentId': 'codex', 'requirements': '', 'voiceSpeeds': {}}
        return value.get('text', '') == incoming.get('text', '') and all(
            k in ('text', 'videoType') or (k in defaults and v == defaults[k]) for k, v in value.items())

    @staticmethod
    def _rewrite(value, source, target, src, dst, skills):
        if isinstance(value, dict):
            return {k: (target if k == 'accountId' and v == source else skills.get(v, v) if k == 'skillId' and isinstance(v, str) else ScriptMoveService._rewrite(v, source, target, src, dst, skills)) for k, v in value.items()}
        if isinstance(value, list):
            return [ScriptMoveService._rewrite(v, source, target, src, dst, skills) for v in value]
        if isinstance(value, str):
            return value.replace(str(src), str(dst)).replace('accountId=' + source, 'accountId=' + target)
        return value

    @staticmethod
    def _sql_rows(path, table, columns, sid, owner):
        if not path.exists():
            return []
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return []
            return [list(r) for r in db.execute(f'SELECT {",".join(columns)} FROM {table} WHERE script=? AND owner=?', (sid, owner))]

    def move(self, script_id, target_account_id, source_account_id=None, preserve_target_drafts=False):
        if preserve_target_drafts and not source_account_id:
            fail('conflict', '保留目标草稿仅用于明确指定来源的历史恢复。')
        with _LOCK, self._disk_lock():
            script = self.store.get_script(script_id)
            self.store._require_account(target_account_id)
            source = source_account_id or script['accountId']
            if source == target_account_id:
                # Preserve validation for an ordinary same-account request.
                for p in self.journals.glob('*/journal.json'):
                    previous = read_json(p, {})
                    if previous.get('scriptId') == script_id and previous.get('target') == target_account_id and previous.get('status') == 'committed':
                        return script
                raise ValueError('脚本已归属该账号。')
            self.store._require_account(source)
            if source_account_id and script['accountId'] != target_account_id:
                fail('conflict', '修复目标必须是脚本当前所属工作台。')
            accounts = [source, target_account_id]
            with move_guard.exclusive(accounts), ExitStack() as stack:
                self._check_pending(accounts)
                contexts = self._contexts(accounts, stack) if self._has_data(source, script_id) else {}
                stack.enter_context(self.store._lock)
                if self.store.get_script(script_id) != script:
                    fail('conflict', '脚本在迁移前已变化，请重试。')
                plan = self._plan(script_id, source, target_account_id, contexts, preserve_target_drafts)
                for ctx in contexts.values():
                    for op in plan['sql']:
                        if op['table'] == 'tasks':
                            for row in op['before']:
                                tid = row[op['columns'].index('id')]
                                worker = getattr(ctx.studio, 'workers', {}).get(tid)
                                if worker is not None and not worker.done():
                                    fail('task_active', '数字人任务仍在收尾，请稍后再移动。')
                    for tid, job in getattr(ctx.schedules, 'jobs', {}).items():
                        record = ctx.schedules.read().get('schedules', {}).get(tid, {})
                        if record.get('scriptId') == script_id and not job.done():
                            fail('task_active', '定时任务仍在收尾，请稍后再移动。')
                plan['scriptBefore'] = script
                plan['scriptAfter'] = dict(script, accountId=target_account_id, updatedAt=self.store._now())
                plan['id'] = uuid.uuid4().hex
                plan['status'] = 'prepared'
                journal = self.journals / plan['id'] / 'journal.json'
                atomic_json(journal, plan)
                try:
                    stage = journal.parent / 'files'
                    for i, item in enumerate(plan['files']):
                        path = stage / str(i)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item['source'], path)
                        if 'content' in item:
                            path.write_text(item['content'], encoding='utf-8')
                        with path.open('rb') as copied:
                            os.fsync(copied.fileno())
                        if digest(path) != item['sha256']:
                            fail('asset_missing', '素材复制校验失败。')
                    plan['status'] = 'applying'
                    atomic_json(journal, plan)
                    for i, item in enumerate(plan['files']):
                        path = Path(item['path'])
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if path.exists():
                            if digest(path) != item['sha256']:
                                fail('conflict', '迁移期间目标文件发生变化。')
                        else:
                            os.replace(stage / str(i), path)
                    self._apply(plan, forward=True)
                    atomic_json(self.store._script_path(script_id), plan['scriptAfter'])
                    # Durable writes bypass WorkspaceStore._write_json; invalidate its indexes too.
                    self.store._invalidate_script_cache()
                    plan['status'] = 'committed'
                    atomic_json(journal, plan)
                except Exception as exc:
                    try:
                        self._rollback(plan)
                        plan['status'] = 'rolled_back'
                        atomic_json(journal, plan)
                    except Exception:
                        move_guard.set_blocked(accounts, True)
                        fail('recovery_required', '迁移中断且恢复尚未完成，相关工作台暂不可写，请重启后检查恢复记录。')
                    if isinstance(exc, ScriptMoveError):
                        raise
                    raise ScriptMoveError('script_move_failed', '迁移失败，脚本及制作记录已恢复到移动前。', 500) from exc
                finally:
                    for ctx in contexts.values():
                        manager = ctx.heygen_tasks
                        manager._tasks = [r for r in manager._tasks if r.get('scriptId') != script_id] + [r for r in manager._load() if r.get('scriptId') == script_id]
                # Topic unlink is an idempotent post-commit cleanup, recover() repeats it.
                self._finish(plan)
                plan['finalized'] = True
                atomic_json(journal, plan)
                return self.store.get_script(script_id)

    def _finish(self, plan):
        self.store._unlink_topics_for_script(plan['scriptId'], account_id=plan['source'], status=str(plan['scriptBefore'].get('workflowStatus') or ''))

    def _check_pending(self, accounts):
        for p in self.journals.glob('*/journal.json'):
            j = read_json(p, {})
            if j.get('status') not in ('committed', 'rolled_back') and set(accounts) & {j.get('source'), j.get('target')}:
                fail('recovery_required', '上次迁移尚未恢复，请先重启工作台完成恢复。')

    @staticmethod
    def _patch(current, before, after):
        """Apply only changed entries; keep records written by other scripts."""
        if before == after:
            return current
        if isinstance(before, dict) and isinstance(after, dict) and isinstance(current, dict):
            result = deepcopy(current)
            for key in before.keys() | after.keys():
                if key in before and key in after and before[key] == after[key]:
                    continue
                if key not in after:
                    if result.get(key) == before[key]:
                        result.pop(key, None)
                elif key not in before:
                    if key in result and result[key] != after[key]:
                        fail('conflict', '恢复时发现不同内容的记录，已停止以保留数据。')
                    result[key] = after[key]
                else:
                    result[key] = ScriptMoveService._patch(result.get(key), before[key], after[key])
            return result
        if isinstance(before, list) and isinstance(after, list) and all(isinstance(v, dict) and 'id' in v for v in before + after):
            result = ScriptMoveService._patch({v['id']: v for v in current}, {v['id']: v for v in before}, {v['id']: v for v in after})
            return list(result.values())
        if current not in (before, after):
            fail('conflict', '恢复时发现制作记录已变化，请人工核对备份。')
        return deepcopy(after)

    def _apply(self, plan, forward):
        start, end = ('before', 'after') if forward else ('after', 'before')
        for op in plan['json']:
            p = Path(op['path'])
            current = read_json(p, op['before'])
            atomic_json(p, self._patch(current, op[start], op[end]))
        for op in plan['sql']:
            p = Path(op['path'])
            p.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(p, timeout=30)) as db, db:
                db.execute(op['schema'] if 'IF NOT EXISTS' in op['schema'].upper() else op['schema'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
                table, columns = op['table'], op['columns']
                current = [list(r) for r in db.execute(f'SELECT {",".join(columns)} FROM {table} WHERE script=? AND owner=?', (op['script'], op['owner']))]
                if current not in (op[start], op[end]):
                    fail('conflict', '迁移记录已发生变化，请核对恢复日志。')
                db.execute(f'DELETE FROM {table} WHERE script=? AND owner=?', (op['script'], op['owner']))
                for row in op[end]:
                    db.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', row)

    def _rollback(self, plan):
        self._apply(plan, forward=False)
        p = self.store._script_path(plan['scriptId'])
        current = read_json(p, {})
        if current == plan['scriptAfter']:
            atomic_json(p, plan['scriptBefore'])
            self.store._invalidate_script_cache()
        elif current != plan['scriptBefore']:
            fail('conflict', '脚本归属已变化，无法自动回滚。')
        # Keep copied files as recovery assets. They have no effective ownership index.

    def recover(self):
        reports = []
        touched, blocked = set(), set()
        with _LOCK, self._disk_lock(), self.store._lock:
            for p in sorted(self.journals.glob('*/journal.json')):
                plan = read_json(p, {})
                accounts = [plan['source'], plan['target']]
                touched.update(accounts)
                if plan['status'] == 'rolled_back':
                    continue
                try:
                    if plan['status'] == 'committed':
                        if not plan.get('finalized'):
                            self._finish(plan)
                            plan['finalized'] = True
                            atomic_json(p, plan)
                    else:
                        self._rollback(plan)
                        plan['status'] = 'rolled_back'
                        atomic_json(p, plan)
                    reports.append({'id': plan['id'], 'status': plan['status']})
                except Exception:
                    blocked.update(accounts)
                    reports.append({'id': plan['id'], 'status': 'recovery_required'})
            move_guard.set_blocked(touched - blocked, False)
            move_guard.set_blocked(blocked, True)
        return reports

    def scan(self):
        """Read-only: do not activate plugins or create destination stores."""
        accounts = read_json(self.root / 'accounts.json', [])
        reports = []
        for p in sorted((self.root / 'scripts').glob('*.json')):
            script = read_json(p, {})
            sid, target = script.get('id'), script.get('accountId')
            if not sid or not target:
                continue
            sources = [a['id'] for a in accounts if a['id'] != target and self._has_artifacts(a['id'], sid)]
            if not sources:
                continue
            report = {'scriptId': sid, 'targetAccountId': target, 'sourceAccountIds': sources, 'status': 'conflict' if len(sources) != 1 else 'recoverable'}
            if len(sources) == 1:
                try:
                    plan = self._plan(sid, sources[0], target, {})
                    report['files'] = len(plan['files'])
                except ScriptMoveError as exc:
                    report.update(status=exc.code, message=exc.message)
            reports.append(report)
        return reports
