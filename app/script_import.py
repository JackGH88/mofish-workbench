"""Local script import with durable receipts and crash-safe retries."""
from __future__ import annotations

import hashlib
import copy
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path


class ImportFailure(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def normalize_content(content):
    return content.replace('\r\n', '\n').replace('\r', '\n').strip()


def content_revision(script):
    text = (script.get('writingState') or {}).get('content', '') if script.get('source') == 'link' else script.get('content', '')
    return hashlib.sha256(json.dumps([text, script.get('updatedAt', '')], ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class ScriptImporter:
    def __init__(self, store):
        self.store = store
        self.root = store._workspace_dir / 'script-imports'

    @contextmanager
    def locked(self):
        with self.store._lock, file_lock(self.root / 'import.lock'):
            self.store._ensure_migrated()
            self.store._invalidate_script_cache()
            yield

    def _identity(self):
        path = self.root / 'identity.json'
        if not path.exists():
            atomic_json(path, {'workbenchId': str(uuid.uuid4())})
        return json.loads(path.read_text(encoding='utf-8'))['workbenchId']

    def identity(self):
        with self.locked():
            return self._identity()

    def _finish(self, path, receipt):
        if receipt['state'] == 'pending':
            script = receipt['script']
            destination = self.store._script_path(script['id'])
            if receipt.get('operation') == 'update':
                current = self._existing(script['id'], script['accountId'])
                if current.get('_externalImportSubmission') != receipt['submissionKey']:
                    if content_revision(current) != receipt['expectedRevision']:
                        raise ImportFailure('content_conflict', '原脚本已在其他地方修改，请核查后再回传。')
                    self.store._set_script_content(current, receipt['content'])
                    current['updatedAt'] = receipt['updatedAt']
                    current['_externalImportSubmission'] = receipt['submissionKey']
                    atomic_json(destination, current)
            elif not destination.exists():
                # An account removed before recovery must not acquire orphan scripts.
                self.store._require_account(script['accountId'])
                atomic_json(destination, script)
            receipt['state'] = 'done'
            atomic_json(path, receipt)
            self.store._invalidate_script_cache()

    def notifications(self):
        with self.locked():
            accounts = {a['id']: a for a in self.store.list_accounts()}
            scripts = self.store._load_scripts()
            items = []
            for path in sorted((self.root / 'receipts').glob('*.json')):
                receipt = json.loads(path.read_text(encoding='utf-8'))
                notice = receipt.get('notice')
                if receipt['state'] != 'done' or not notice:
                    continue
                script = scripts.get(notice['scriptId'])
                if (not script or script.get('retiredAsBreakdown')
                        or script['accountId'] != notice['accountId']
                        or notice['accountId'] not in accounts):
                    continue
                items.append({**notice, 'accountName': accounts[notice['accountId']]['name']})
            items.sort(key=lambda item: (item['createdAt'], item['id']))
            return {'workbenchId': self._identity(), 'items': items}

    def save(self, body):
        content = normalize_content(body['content'])
        if not content or len(body['content']) > 100000:
            raise ImportFailure('invalid_content', '正文不能为空或超过100000字符。', 422)
        title = body['title'].strip()
        if not title or len(title) > 160:
            raise ImportFailure('invalid_title', '标题必须为1至160字符。', 422)
        payload = {**body, 'content': content, 'title': title}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = hashlib.sha256(body['submissionId'].encode()).hexdigest()
        with self.locked():
            if body['workbenchId'] != self._identity():
                raise ImportFailure('workbench_changed', '工作台身份已变化，请重新选择。')
            account = body['accountId']
            try:
                self.store._require_account(account)
            except ValueError as exc:
                raise ImportFailure('account_missing', '目标账号不存在，请重新选择。', 404) from exc
            path = self.root / 'receipts' / (key + '.json')
            if path.exists():
                receipt = json.loads(path.read_text(encoding='utf-8'))
                if receipt['digest'] != digest:
                    raise ImportFailure('submission_conflict', '同一提交标识不能用于不同内容。')
                self._finish(path, receipt)
            else:
                # Reconcile interrupted writes before content deduplication.
                for old in sorted((self.root / 'receipts').glob('*.json')):
                    pending = json.loads(old.read_text(encoding='utf-8'))
                    if pending['state'] == 'pending':
                        try:
                            self._finish(old, pending)
                        except (KeyError, ValueError):
                            continue
                script = None
                if not body.get('forceNew', False):
                    for candidate in self.store.list_scripts(account):
                        candidate = self.store.get_script(candidate['id'])
                        text = (candidate.get('writingState') or {}).get('content', '') if candidate.get('source') == 'link' else candidate.get('content', '')
                        if normalize_content(text or '') == content:
                            script = candidate
                            break
                reused = script is not None
                if script is None:
                    now = self.store._now()
                    script = {'id': str(uuid.uuid4()), 'accountId': account, 'title': title,
                              'content': content, 'source': 'blank', 'stage': 'edit',
                              'processingStatus': 'ready', 'workflowStatus': 'pending',
                              'createdAt': now, 'updatedAt': now}
                receipt = {'digest': digest, 'state': 'done' if reused else 'pending',
                           'script': script, 'result': 'reused' if reused else 'created',
                           'notice': {'id': key, 'accountId': account, 'scriptId': script['id'],
                                      'title': script['title'], 'result': 'reused' if reused else 'created',
                                      'createdAt': self.store._now()}}
                atomic_json(path, receipt)
                self._finish(path, receipt)
            try:
                actual = self.store.get_script(receipt['script']['id'])
            except (KeyError, ValueError):
                raise ImportFailure('script_deleted', '此次提交的脚本已删除；不会自动重建。', 410)
            if actual['accountId'] != account:
                raise ImportFailure('script_moved', '此次提交的脚本已移动到其他账号。')
            return {'workbenchId': body['workbenchId'], 'accountId': account,
                    'submissionId': body['submissionId'], 'scriptId': actual['id'],
                    'title': actual['title'], 'result': receipt['result'],
                    'contentRevision': content_revision(actual)}

    def _existing(self, script_id, account):
        try:
            self.store._require_account(account)
        except ValueError as exc:
            raise ImportFailure('account_missing', '绑定内容账号不存在，请核查。', 404) from exc
        try:
            script = self.store.get_script(script_id)
        except ValueError as exc:
            raise ImportFailure('script_deleted', '绑定脚本不存在，不会自动新建。', 410) from exc
        if script['accountId'] != account or script.get('retiredAsBreakdown'):
            raise ImportFailure('script_moved', '绑定脚本的归属已变化，请核查。')
        return script

    def update(self, body):
        content = normalize_content(body['content'])
        if not content or len(body['content']) > 100000:
            raise ImportFailure('invalid_content', '正文不能为空或超过100000字符。', 422)
        key = hashlib.sha256(body['submissionId'].encode()).hexdigest()
        digest = hashlib.sha256(json.dumps({**body, 'content': content, 'operation': 'update'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.locked():
            if body['workbenchId'] != self._identity():
                raise ImportFailure('workbench_changed', '工作台身份已变化，请重新选择。')
            path = self.root / 'receipts' / (key + '.json')
            if path.exists():
                receipt = json.loads(path.read_text(encoding='utf-8'))
                if receipt['digest'] != digest:
                    raise ImportFailure('submission_conflict', '同一提交标识不能用于不同内容。')
            else:
                # Finish older interrupted operations before testing the caller's revision.
                for old in sorted((self.root / 'receipts').glob('*.json')):
                    pending = json.loads(old.read_text(encoding='utf-8'))
                    if pending['state'] == 'pending':
                        try:
                            self._finish(old, pending)
                        except (KeyError, ValueError):
                            continue
                script = self._existing(body['scriptId'], body['accountId'])
                if content_revision(script) != body['expectedRevision']:
                    raise ImportFailure('content_conflict', '原脚本已在其他地方修改，请核查后再回传。')
                now = self.store._now()
                receipt = {'operation': 'update', 'digest': digest, 'state': 'pending',
                           'script': copy.deepcopy(script), 'result': 'updated', 'submissionKey': key,
                           'expectedRevision': body['expectedRevision'], 'content': content, 'updatedAt': now,
                           'notice': {'id': key, 'accountId': body['accountId'], 'scriptId': script['id'],
                                      'title': script['title'], 'result': 'updated', 'createdAt': now}}
                atomic_json(path, receipt)
            self._finish(path, receipt)
            actual = self._existing(body['scriptId'], body['accountId'])
            return {'workbenchId': body['workbenchId'], 'accountId': body['accountId'],
                    'submissionId': body['submissionId'], 'scriptId': actual['id'],
                    'title': actual['title'], 'result': 'updated', 'contentRevision': content_revision(actual)}
