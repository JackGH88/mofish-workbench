"""Owner-local native WorkBuddy handoff; never emulate keyboard input in Python."""
import hashlib
import json
import os
import plistlib
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import runtime

_LOCK = threading.RLock()


def guidance(code, desktop=False):
    name = '墨鱼工作台' if desktop else '工作台助手'
    return {
        'helper_missing': '自动发送需要工作台助手，请先下载安装。',
        'helper_unavailable': f'{name}暂不可用，请启动后重试。',
        'permission_required': f'系统尚未授予“{name}”辅助功能权限。',
        'permission_changed': f'应用已更新，系统尚未认可新版“{name}”的授权，请更新授权。',
        'verification_required': '权限已开启，请先验证自动发送。',
        'version_mismatch': f'发送组件版本不兼容，请更新{name}。',
        'unsupported': 'WorkBuddy 自动发送目前仅支持同机 macOS 部署。',
        'workbuddy_permission': '请先将 WorkBuddy 任务权限设为 fullAccess，再创建定时任务。',
        'session_inactive': '电脑已锁屏或当前用户会话不可用，未发送指令。',
        'target_changed': 'WorkBuddy 目标进程或输入控件发生变化，已停止发送，请在 WorkBuddy 中检查。',
        'composer_unavailable': '无法确认 WorkBuddy 输入框，已停止发送。',
        'accessibility_init_failed': 'WorkBuddy 控件访问初始化未完成，未提交指令，请检查应用状态后重新设置。',
        'assistant_unavailable': 'WorkBuddy 未能在限定时间内启动就绪，未提交指令。',
        'draft_mismatch': 'WorkBuddy 输入框与本次指令不一致，已停止发送。',
        'send_control_unavailable': '未找到唯一且可操作的 WorkBuddy 发送按钮，未执行提交。',
        'send_uncertain': '发送结果待确认，请在 WorkBuddy 中查看；不要重复提交。',
    }.get(code, '自动发送未完成，请检查助手状态。')


class NativeSendError(ValueError):
    def __init__(self, code, desktop=False):
        self.code = code
        super().__init__(guidance(code, desktop))


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise NativeSendError('helper_unavailable')
    return path


def read_json(path):
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_private(path, value):
    temporary = path.with_name(str(uuid.uuid4()) + '.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_receipt(receipt, request_id, task_id, digest):
    if any(receipt.get(k) != v for k, v in [('requestID', request_id), ('taskID', task_id), ('promptHash', digest)]):
        raise NativeSendError('send_uncertain')
    if receipt.get('protocolVersion') != 2 or receipt.get('state') != 'action_posted':
        raise NativeSendError(receipt.get('code', 'send_uncertain'))


def transcript_confirms(path, prompt, reply=None, accepted_only=False):
    """Require the exact final user instruction and subsequent model output, not draft text."""
    seen = False
    try:
        with path.open() as source:
            for line in source:
                row = json.loads(line)
                texts = [c.get('text', '') for c in row.get('content', []) if isinstance(c, dict)]
                if row.get('role') == 'user':
                    seen = any(text == prompt or (
                        text.startswith('<system-reminder') and
                        text.endswith('\n<user_query>' + prompt + '</user_query>')
                    ) for text in texts)
                    if seen and accepted_only:
                        return True
                if seen and row.get('role') == 'assistant':
                    if any(text.strip() for text in texts) and (reply is None or reply in texts):
                        return True
    except (OSError, ValueError, TypeError):
        pass
    return False


class NativeSendClient:
    def __init__(self, desktop=None):
        self.desktop = runtime.DESKTOP if desktop is None else desktop
        self.home = Path.home()
        self.root = self.home / 'Library/Application Support/MofishWorkbench/NativeSend' / ('desktop' if self.desktop else 'helper')

    def app_path(self):
        if self.desktop:
            return next((p for p in runtime.RESOURCE_ROOT.parents if p.suffix == '.app'), None)
        return next((p for p in (self.home / 'Applications/工作台助手.app', Path('/Applications/工作台助手.app')) if p.is_dir()), None)

    def fingerprint(self):
        app = self.app_path()
        if not app:
            return ''
        binary = app / ('Contents/MacOS/MofishWorkbench' if self.desktop else 'Contents/MacOS/WorkbenchAssistant')
        try:
            return hashlib.sha256(binary.read_bytes()).hexdigest()
        except OSError:
            return ''

    def prepare(self):
        private_directory(self.root)
        for folder in ('requests', 'receipts', 'claims', 'probes'):
            private_directory(self.root / folder)

    def launch(self, action, request_id=None):
        app = self.app_path()
        if not app:
            raise NativeSendError('helper_missing' if not self.desktop else 'helper_unavailable', self.desktop)
        # Launch the signed executable directly: LaunchServices refuses a second
        # instance when the desktop bundle has LSMultipleInstancesProhibited.
        if self.desktop:
            args = [str(app / 'Contents/MacOS/MofishWorkbench'), '--native-send']
        else:
            args = ['/usr/bin/open', '-g', '-n', str(app), '--args']
        args.append('--' + action)
        if request_id:
            args.append(request_id)
        subprocess.run(args, check=True, capture_output=True, timeout=90 if action in ('probe', 'submit') else 10)

    def _wait(self, name, since, timeout):
        end = time.monotonic() + timeout
        path = self.root / 'receipts' / (name + '.json')
        while time.monotonic() < end:
            try:
                if path.stat().st_mtime >= since:
                    result = read_json(path)
                    if result and result.get('state') != 'submit_attempted':
                        return result
            except OSError:
                pass
            time.sleep(0.15)
        raise NativeSendError('send_uncertain' if name != 'status' else 'helper_unavailable', self.desktop)

    def status(self):
        code = ''
        repair_available = False
        repaired = False
        try:
            if sys.platform != 'darwin':
                raise NativeSendError('unsupported')
            with _LOCK:
                self.prepare()
                since = time.time()
                self.launch('status')
                result = self._wait('status', since, 5)
            if result.get('protocolVersion') != 2:
                code = 'version_mismatch'
            else:
                fingerprint = self.fingerprint()
                previous = (read_json(self.root / 'permission.json') or read_json(self.root / 'verification.json')).get('fingerprint')
                repaired = bool(fingerprint and read_json(self.root / 'permission-repair.json').get('fingerprint') == fingerprint)
                if not result.get('accessibilityTrusted'):
                    code = 'permission_changed' if previous and fingerprint and previous != fingerprint and not repaired else 'permission_required'
                    repair_available = self.desktop and bool(fingerprint)
                else:
                    write_private(self.root / 'permission.json', {'fingerprint': fingerprint})
                    if read_json(self.root / 'verification.json').get('fingerprint') != fingerprint:
                        code = 'verification_required'
        except NativeSendError as exc:
            code = exc.code
        except (OSError, subprocess.SubprocessError):
            code = 'helper_unavailable'
        return {'ok': not code, 'code': code, 'deployment': 'desktop' if self.desktop else 'helper',
                'message': guidance(code, self.desktop) if code else '自动发送已就绪',
                'repairAvailable': repair_available, 'authorizationRefreshed': repaired,
                'action': {'permission_changed': 'repair_authorization', 'permission_required': 'authorize', 'verification_required': 'verify',
                           'helper_missing': 'install', 'helper_unavailable': 'start'}.get(code, '')}

    def action(self, action):
        if action not in ('authorize', 'reveal', 'start', 'verify', 'repair_authorization'):
            raise ValueError('不支持的操作。')
        with _LOCK:
            self.prepare()
            if action == 'repair_authorization':
                if not self.desktop:
                    raise ValueError('当前部署不支持此授权修复。')
                current = self.status()
                if current['ok'] or current['code'] == 'verification_required':
                    return {'ok': True, 'message': '权限已生效，无需修复。'}
                if current['code'] not in ('permission_required', 'permission_changed') or not current.get('repairAvailable'):
                    raise ValueError('无法确认当前权限状态，请重新检查。')
                # Only this application's Accessibility grant; never reset All or another app.
                try:
                    subprocess.run(['/usr/bin/tccutil', 'reset', 'Accessibility', 'cc.qqtoken.mofish.workbench'],
                                   check=True, capture_output=True, timeout=10)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise ValueError('系统未能更新授权记录，请稍后重试；没有修改其他应用权限。') from exc
                write_private(self.root / 'permission-repair.json', {'fingerprint': self.fingerprint()})
                self.launch('authorize')
                return {'ok': True, 'message': '旧授权记录已清理，请在系统设置中开启“墨鱼工作台”。'}
            if action == 'verify':
                since = time.time()
                self.launch('probe')
                latest = self._wait('last-probe', since, 35)
                return self.record_verification(latest.get('requestID', ''))
            self.launch('status' if action == 'start' else action)
        return {'ok': True}

    def sessions(self, cwd, since=0):
        db_path = self.home / '.workbuddy/workbuddy.db'
        try:
            with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                return db.execute('SELECT id, status FROM sessions WHERE cwd IN (?, ?) AND created_at >= ? AND deleted_at IS NULL ORDER BY created_at DESC',
                                  (str(cwd), str(Path(cwd).resolve()), since * 1000)).fetchall()
        except sqlite3.Error:
            raise NativeSendError('send_uncertain', self.desktop) from None

    def confirm(self, cwd, prompt, since=0, reply=None, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            matches = set()
            for sid, state in self.sessions(cwd, since):
                if not isinstance(sid, str) or not all(c in '0123456789abcdef-' for c in sid.lower()):
                    continue
                for file in (self.home / '.workbuddy/projects').glob('*/' + sid + '.jsonl'):
                    if transcript_confirms(file, prompt, reply, accepted_only=reply is None):
                        matches.add(sid)
            if len(matches) > 1:
                raise NativeSendError('send_uncertain', self.desktop)
            if matches:
                return matches.pop()
            time.sleep(0.5)
        raise NativeSendError('send_uncertain', self.desktop)

    def record_verification(self, request_id):
        request_id = str(uuid.UUID(request_id))
        request = read_json(self.root / 'requests' / (request_id + '.json'))
        receipt = read_json(self.root / 'receipts' / (request_id + '.json'))
        validate_receipt(receipt, request_id, request_id, request.get('promptHash'))
        expected = 'WB_NATIVE_SEND_OK_' + request_id
        sid = self.confirm(request['cwd'], request['prompt'], reply=expected, timeout=40)
        write_private(self.root / 'verification.json', {'fingerprint': self.fingerprint(), 'sessionId': sid,
                      'requestID': request_id, 'verifiedAt': time.time()})
        return {'ok': True, 'sessionId': sid, 'message': '自动发送验证通过'}

    def submit(self, task_id, prompt, cwd):
        status = self.status()
        if not status['ok']:
            raise NativeSendError(status['code'], self.desktop)
        task_id = str(uuid.UUID(task_id))
        request_id = str(uuid.uuid4())
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        since = time.time()
        request = {'taskID': task_id, 'issuedAt': since, 'prompt': prompt, 'promptHash': digest, 'cwd': str(Path(cwd).resolve())}
        try:
            with _LOCK:
                write_private(self.root / 'requests' / (request_id + '.json'), request)
                self.launch('submit', request_id)
                result = self._wait(request_id, since, 35)
                self.release_unsent_claim(result, request_id, task_id, digest)
            validate_receipt(result, request_id, task_id, digest)
        except NativeSendError as exc:
            if exc.code != 'send_uncertain':
                raise NativeSendError(exc.code, self.desktop) from None
            # Already claimed: reconcile only, never post Return again.
            since = 0
        except (OSError, subprocess.SubprocessError):
            # Launch may have succeeded even when its acknowledgement was lost.
            pass
        sid = self.confirm(request['cwd'], prompt, since=since)
        receipt = read_json(self.root / 'receipts' / (request_id + '.json'))
        receipt.update(requestID=request_id, taskID=task_id, promptHash=digest,
                       state='session_accepted', sessionId=sid)
        receipt['stages'] = receipt.get('stages', []) + [{'stage': 'session_accepted', 'timestamp': time.time()}]
        write_private(self.root / 'receipts' / (request_id + '.json'), receipt)
        return sid

    def release_unsent_claim(self, receipt, request_id, task_id, digest):
        """Only a final, matching pre-action receipt permits a later explicit retry.

        Never clear claims on a timeout, a failed AXPress, or an uncertain receipt.
        The native process has returned before this is called; no action is pending.
        """
        if (receipt.get('state') != 'blocked' or receipt.get('code') not in {
                'permission_required', 'session_inactive', 'assistant_unavailable',
                'target_changed', 'composer_unavailable', 'accessibility_init_failed',
                'draft_mismatch', 'send_control_unavailable',
            }):
            return
        if 'actionResult' in receipt or receipt.get('protocolVersion') != 2 or any(receipt.get(k) != v for k, v in (
                ('requestID', request_id), ('taskID', task_id), ('promptHash', digest))):
            raise NativeSendError('send_uncertain', self.desktop)
        claim = self.root / 'claims' / (task_id.lower() + '.claim')
        try:
            info = claim.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise NativeSendError('send_uncertain', self.desktop)
            # Permission/session checks also run BEFORE claim(). Only stages
            # emitted after this request won the claim prove ownership of it.
            stages = receipt.get('stages') or []
            if not any(isinstance(s, dict) and s.get('stage') in ('claim_acquired', 'application_launch', 'launch') for s in stages):
                raise NativeSendError('send_uncertain', self.desktop)
            claim.unlink()
        except FileNotFoundError:
            pass  # Authorization/session checks can fail before claiming.
