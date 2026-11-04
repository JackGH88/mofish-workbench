#!/usr/bin/env python3
"""Dependency-free local Mofish client shared by Codex and WorkBuddy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager


class ClientError(Exception):
    pass


def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def endpoint(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'}):
        raise ClientError('仅支持本机 HTTP 工作台地址，例如 http://127.0.0.1:8001')
    try:
        parsed.port
    except ValueError as exc:
        raise ClientError('端口无效') from exc
    return value.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(base, path, body=None):
    req = urllib.request.Request(endpoint(base) + path,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json'}, method='GET' if body is None else 'POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get('detail', {})
        except (ValueError, AttributeError):
            detail = {}
        message = detail.get('message') if isinstance(detail, dict) else None
        raise ClientError(message or f'接口返回 HTTP {exc.code}；请确认工作台已更新并支持脚本导入。') from exc
    except (OSError, ValueError) as exc:
        raise ClientError('无法连接或解析本机工作台响应，请检查服务是否运行。') from exc


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default=None):
    if not path.exists() and default is not None:
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ClientError(f'无法读取 JSON 文件：{path}') from exc


@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'client.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b'0'); handle.flush()
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def info(base):
    result = request(base, '/api/script-import/info')
    if (not isinstance(result, dict) or result.get('importVersion') != 1
            or not result.get('workbenchId') or not isinstance(result.get('accounts'), list)):
        raise ClientError('此工作台尚不支持当前脚本导入协议，请更新。')
    return result


def check_target(base, expected, account):
    current = info(base)
    if current['workbenchId'] != expected:
        raise ClientError('地址对应的工作台已变化，请重新选择；未提交。')
    found = next((a for a in current['accounts'] if a['id'] == account), None)
    if not found:
        raise ClientError('目标内容账号不存在，请重新选择；未提交。')
    return current, found


def revision(script):
    text = (script.get('writingState') or {}).get('content', '') if script.get('source') == 'link' else script.get('content', '')
    return hashlib.sha256(json.dumps([text, script.get('updatedAt', '')], ensure_ascii=False).encode()).hexdigest()


def binding_path(root, conversation):
    if not isinstance(conversation, str) or not conversation.strip() or len(conversation) > 200:
        raise ClientError('conversation-id 必须是本对话的稳定唯一标识。')
    return root / 'conversations' / (hashlib.sha256(conversation.encode()).hexdigest() + '.json')


def remember_binding(root, package, receipt, actual):
    conversation = package.get('conversationId')
    if not conversation or not package.get('bindResult', True):
        return
    path = binding_path(root, conversation)
    old = read_json(path, {})
    sid = package['body']['submissionId']
    # A historical retry may verify an old receipt, but must never move this chat backwards.
    if old.get('lastSubmissionId') not in (None, package.get('bindingParent'), sid) and old.get('pending') != sid:
        return
    write_json(path, {'conversationId': conversation, 'url': package['url'],
                     'workbenchId': receipt['workbenchId'], 'accountId': receipt['accountId'],
                     'scriptId': receipt['scriptId'], 'contentRevision': revision(actual),
                     'lastSubmissionId': sid, 'pending': None})


def deliver(path, package):
    body, base = package['body'], package['url']
    current, account = check_target(base, body['workbenchId'], body['accountId'])
    updating = package.get('operation') == 'update'
    if updating and 'update-script-v1' not in current.get('capabilities', []):
        raise ClientError('当前工作台不支持原稿更新，请更新工作台；不会退回新建脚本。')
    receipt = request(base, '/api/script-import/update' if updating else '/api/script-import', body)
    for key in ('workbenchId', 'accountId', 'submissionId'):
        if receipt.get(key) != body[key]:
            raise ClientError('回执身份不匹配；保留待提交记录供核查。')
    if updating and receipt.get('scriptId') != body['scriptId']:
        raise ClientError('更新回执的脚本身份不匹配。')
    sid = urllib.parse.quote(receipt['scriptId'], safe='')
    actual = request(base, '/api/scripts/' + sid + '/workspace')['script']
    text = (actual.get('writingState') or {}).get('content', '') if actual.get('source') == 'link' else actual.get('content', '')
    if actual.get('accountId') != body['accountId'] or normalize(text) != normalize(body['content']):
        raise ClientError('保存回执已收到，但读回内容或归属已变化；请核查，不会自动另建。')
    package.update(state='verified', receipt=receipt)
    write_json(path, package)
    remember_binding(path.parent.parent, package, receipt, actual)
    return {**receipt, 'conversationId': package.get('conversationId'), 'verified': True, 'url': base, 'kind': current['kind'],
            'accountName': account['name'], 'outbox': str(path)}


def run(args):
    root = Path(args.state_dir).expanduser()
    with lock(root):
        config_path = root / 'config.json'
        config = read_json(config_path, {'targets': [], 'selected': None})
        if args.command == 'new-conversation':
            return {'conversationId': str(uuid.uuid4()), 'instruction': '在本对话后续回传中始终复用这个标识。'}
        if args.command == 'binding':
            return read_json(binding_path(root, args.conversation_id), {})
        if args.command == 'bind':
            target = binding_path(root, args.conversation_id)
            if target.exists():
                raise ClientError('本对话已有绑定，请勿重新绑定来绕过冲突检查。')
            source = Path(args.outbox).expanduser().resolve()
            if source.parent != (root / 'outbox').resolve():
                raise ClientError('必须使用本对话原回执对应的共享 outbox。')
            package = read_json(source)
            if package.get('state') != 'verified':
                raise ClientError('请先重试并确认原提交成功，再绑定本对话。')
            result = deliver(source, package)
            script = request(package['url'], '/api/scripts/' + urllib.parse.quote(result['scriptId'], safe='') + '/workspace')['script']
            text = (script.get('writingState') or {}).get('content', '') if script.get('source') == 'link' else script.get('content', '')
            if normalize(text) != normalize(package['body']['content']) or script['accountId'] != result['accountId']:
                raise ClientError('原脚本已变化，不能自动绑定。')
            remember_binding(root, {**package, 'conversationId': args.conversation_id, 'bindResult': True}, result, script)
            return read_json(target)
        if args.command == 'list':
            urls = list(dict.fromkeys([t['url'] for t in config['targets']] + ['http://127.0.0.1:8001'] + args.url))
            items = []
            for url in urls:
                try:
                    items.append({'url': endpoint(url), **info(url)})
                except ClientError as exc:
                    items.append({'url': url, 'error': str(exc)})
            return {'workbenches': items, 'selected': config['selected']}
        if args.command == 'select':
            base = endpoint(args.url)
            target = info(base)
            accounts = target['accounts']
            aid = args.account
            if not aid and len(accounts) == 1:
                aid = accounts[0]['id']
            if not any(a['id'] == aid for a in accounts):
                raise ClientError('请从 list 返回的内容账号中选择，并传入 --account ID。')
            selected = {'url': base, 'workbenchId': target['workbenchId'], 'accountId': aid}
            config['targets'] = [t for t in config['targets'] if t['workbenchId'] != target['workbenchId']] + [selected]
            config['selected'] = selected
            write_json(config_path, config)
            return {'selected': selected, 'accounts': accounts}
        if args.command == 'retry':
            path = Path(args.outbox).expanduser().resolve()
            if path.parent != (root / 'outbox').resolve():
                raise ClientError('仅可重试共享 outbox 中的记录。')
            return deliver(path, read_json(path))
        conversation = getattr(args, 'conversation_id', None)
        binding = read_json(binding_path(root, conversation), {}) if conversation else {}
        selected = binding if binding.get('url') else config.get('selected')
        if not selected:
            raise ClientError('尚未选择工作台和内容账号，请先执行 list 和 select。')
        check_target(selected['url'], selected['workbenchId'], selected['accountId'])
        payload = read_json(Path(args.payload).expanduser())
        title, content = payload.get('title'), payload.get('content')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise ClientError('标题必须为1至160字符。')
        if not isinstance(content, str) or not normalize(content) or len(content) > 100000:
            raise ClientError('正文必须非空且不超过100000字符；未提交。')
        if binding.get('pending') and not args.new_copy:
            pending_path = root / 'outbox' / (hashlib.sha256(binding['pending'].encode()).hexdigest() + '.json')
            pending = read_json(pending_path)
            if normalize(content) != pending['body']['content']:
                raise ClientError(f'本对话还有未完成的回传，请先核查或重试：{pending_path}')
            return deliver(pending_path, pending)
        updating = bool(binding.get('scriptId')) and not args.new_copy
        body = {'workbenchId': selected['workbenchId'], 'accountId': selected['accountId'],
                'title': title.strip(), 'content': normalize(content), 'forceNew': args.new_copy}
        if args.new_copy and not args.submission_id:
            raise ClientError('另存一份需提供唯一 --submission-id；失败重试必须复用该标识。')
        if updating:
            body = {'workbenchId': binding['workbenchId'], 'accountId': binding['accountId'],
                    'scriptId': binding['scriptId'], 'expectedRevision': binding['contentRevision'],
                    'content': normalize(content)}
        # Share unfinished requests across both assistants; successful new save intentions get a new ID.
        fingerprint = hashlib.sha256(json.dumps({'body':body, 'conversationId':conversation}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = None
        for candidate in sorted((root / 'outbox').glob('*.json')):
            old = read_json(candidate)
            if args.submission_id:
                if old['body']['submissionId'] == args.submission_id:
                    expected = {**body, 'submissionId': args.submission_id}
                    if old['body'] != expected or old.get('conversationId') != conversation:
                        raise ClientError('同一提交标识不能用于不同内容或目标。')
                    path = candidate; package = old; break
            elif old.get('fingerprint') == fingerprint and old.get('state') != 'verified':
                path = candidate; package = old; break
        if path is None:
            body['submissionId'] = args.submission_id or str(uuid.uuid4())
            key = hashlib.sha256(body['submissionId'].encode()).hexdigest()
            path = root / 'outbox' / (key + '.json')
            package = {'url': selected['url'], 'body': body, 'state': 'pending', 'fingerprint': fingerprint,
                       'operation': 'update' if updating else 'create', 'conversationId': conversation,
                       'bindResult': not (args.new_copy and binding.get('scriptId')),
                       'bindingParent': binding.get('lastSubmissionId')}
            write_json(path, package)
        if conversation and package.get('bindResult', True):
            write_json(binding_path(root, conversation), {**selected, **binding, 'conversationId': conversation,
                       'pending': package['body']['submissionId']})
        try:
            return deliver(path, package)
        except ClientError as exc:
            raise ClientError(f'{exc} 待提交记录：{path}；使用 retry --outbox 重试。') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', default=str(Path.home() / '.mofish' / 'script-import'))
    sub = parser.add_subparsers(dest='command', required=True)
    ls = sub.add_parser('list'); ls.add_argument('--url', action='append', default=[])
    select = sub.add_parser('select'); select.add_argument('--url', required=True); select.add_argument('--account')
    save = sub.add_parser('save'); save.add_argument('--payload', required=True)
    save.add_argument('--conversation-id'); save.add_argument('--submission-id'); save.add_argument('--new-copy', action='store_true')
    sub.add_parser('new-conversation')
    binding = sub.add_parser('binding'); binding.add_argument('--conversation-id', required=True)
    bind = sub.add_parser('bind'); bind.add_argument('--conversation-id', required=True); bind.add_argument('--outbox', required=True)
    retry = sub.add_parser('retry'); retry.add_argument('--outbox', required=True)
    try:
        print(json.dumps(run(parser.parse_args()), ensure_ascii=False, indent=2))
    except (ClientError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
