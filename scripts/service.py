#!/usr/bin/env python3
"""Current-user desktop service management. Uses only stdlib until `run`."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import plistlib
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'com.local.douyin-workbench'
PORT = 8001
COMMAND_TIMEOUT = 10
BOOTOUT_TIMEOUT = 40


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def state_dir(root=ROOT):
    base = (Path(os.environ['LOCALAPPDATA']) if sys.platform == 'win32'
            else Path.home() / 'Library/Application Support')
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return base / 'VideoWorkbench' / key


class InstanceLock:
    """OS-owned lock: a crash releases it, without trusting stale PID files."""
    def __init__(self, path):
        self.path = path
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        try:
            if sys.platform == 'win32':
                import msvcrt
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.file = handle
        return True

    def release(self):
        if self.file is not None:
            if sys.platform == 'win32':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None


def check_owner(owner, root, relocate=False):
    if owner and Path(owner).resolve() != root.resolve():
        if relocate and not Path(owner).exists():
            return
        raise RuntimeError('后台服务属于其他目录：' + owner + '。请先在原项目停用并卸载注册；搬迁后原目录不存在时可使用 --relocate。')


def port_owner_hint(port):
    """Best-effort ownership hint; never stops or changes another process."""
    try:
        if sys.platform == 'win32':
            script = (f'$pids=Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction Stop | '
                      'Select-Object -ExpandProperty OwningProcess -Unique; '
                      'Get-Process -Id $pids | Select-Object Id,Path | ConvertTo-Json -Compress')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, text=True, timeout=5, encoding='utf-8', errors='replace')
        else:
            result = subprocess.run(['lsof', '-nP', f'-iTCP:{int(port)}', '-sTCP:LISTEN'],
                                    capture_output=True, text=True, timeout=5, encoding='utf-8', errors='replace')
        if result.returncode == 0 and result.stdout.strip():
            return ' 占用进程：' + result.stdout.strip()[:1500]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ' 可用 lsof（macOS）或 Get-NetTCPConnection（Windows）查询占用进程。'


def check_port(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # POSIX TIME_WAIT must not block a legitimate restart. Windows uses
            # exclusive binding to avoid masking another listener with REUSEADDR.
            if sys.platform == 'win32':
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    except OSError as exc:
        raise RuntimeError(f'端口 {port} 已被占用，未停止占用它的程序。' + port_owner_hint(port)) from exc


def page_accessible(port):
    try:
        # Loopback must not be sent to a configured system proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/', timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def runtime_status(state, port):
    lock = InstanceLock(state / 'instance.lock')
    acquired = lock.acquire()
    lock.release()
    return {'running': not acquired, 'pageAccessible': page_accessible(port)}


def login_session():
    """Windows authentication LUID changes at logon, survives sleep/reboot checks."""
    from ctypes import wintypes
    class LUID(ctypes.Structure):
        _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]
    class TOKEN_STATISTICS(ctypes.Structure):
        _fields_ = [('TokenId', LUID), ('AuthenticationId', LUID),
                    ('ExpirationTime', ctypes.c_longlong), ('TokenType', wintypes.DWORD),
                    ('ImpersonationLevel', wintypes.DWORD), ('DynamicCharged', wintypes.DWORD),
                    ('DynamicAvailable', wintypes.DWORD), ('GroupCount', wintypes.DWORD),
                    ('PrivilegeCount', wintypes.DWORD), ('ModifiedId', LUID)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    handle = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(handle)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        stats, needed = TOKEN_STATISTICS(), wintypes.DWORD()
        if not advapi.GetTokenInformation(handle, 10, ctypes.byref(stats), ctypes.sizeof(stats), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        boot = command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        '(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().Ticks']).stdout.strip()
        if not boot:
            raise RuntimeError('无法识别本次 Windows 登录，未启动服务。')
        return f'{boot}:{stats.AuthenticationId.HighPart}:{stats.AuthenticationId.LowPart}'
    finally:
        kernel.CloseHandle(handle)


def is_paused(path, session):
    return read_json(path).get('session') == session


def mac_plist(root, logs, label=LABEL):
    return plistlib.dumps({
        'Label': label,
        'ProgramArguments': [str(root / '.venv/bin/python'), str(root / 'scripts/service.py'), 'run'],
        'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True,
        'ThrottleInterval': 15, 'ExitTimeOut': 30,
        # Runtime directs stdout/stderr to rotating logs. No unbounded launchd log.
        'EnvironmentVariables': {'PYTHONUNBUFFERED': '1', 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
    })


def windows_xml(root, sid):
    ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    ET.register_namespace('', ns)
    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, '{' + ns + '}' + tag, attrs)
        if text is not None:
            node.text = text
        return node
    task = ET.Element('{' + ns + '}Task', {'version': '1.2'})
    info = add(task, 'RegistrationInfo')
    add(info, 'Description', json.dumps({'project': str(root)}, ensure_ascii=False))
    triggers = add(task, 'Triggers')
    logon = add(triggers, 'LogonTrigger')
    add(logon, 'Enabled', 'true')
    add(logon, 'UserId', sid)
    timer = add(triggers, 'TimeTrigger')
    repetition = add(timer, 'Repetition')
    add(repetition, 'Interval', 'PT1M')
    add(repetition, 'StopAtDurationEnd', 'false')
    add(timer, 'StartBoundary', '2020-01-01T00:00:00')
    add(timer, 'Enabled', 'true')
    principals = add(task, 'Principals')
    principal = add(principals, 'Principal', id='CurrentUser')
    add(principal, 'UserId', sid)
    add(principal, 'LogonType', 'InteractiveToken')
    add(principal, 'RunLevel', 'LeastPrivilege')
    settings = add(task, 'Settings')
    for name, value in {
        'MultipleInstancesPolicy': 'IgnoreNew', 'DisallowStartIfOnBatteries': 'false',
        'StopIfGoingOnBatteries': 'false', 'StartWhenAvailable': 'true',
        'RunOnlyIfNetworkAvailable': 'false', 'AllowStartOnDemand': 'true',
        'Enabled': 'true', 'WakeToRun': 'false', 'ExecutionTimeLimit': 'PT0S',
    }.items():
        add(settings, name, value)
    actions = add(task, 'Actions', Context='CurrentUser')
    action = add(actions, 'Exec')
    add(action, 'Command', str(root / '.venv/Scripts/pythonw.exe'))
    add(action, 'Arguments', subprocess.list2cmdline(['-B', '-X', 'utf8', str(root / 'scripts/service.py'), 'run']))
    add(action, 'WorkingDirectory', str(root))
    return ET.tostring(task, encoding='unicode')


def command(args, allow_failure=False, *, timeout=COMMAND_TIMEOUT):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout, **options)
    except subprocess.TimeoutExpired as exc:
        # Even allow_failure probes must abort: a timeout is not proof of absence.
        raise RuntimeError(f'命令 {shlex.join(args)} 超时（{timeout} 秒）；'
                           '系统操作可能仍在完成，请检查 status 后重试。') from exc
    if result.returncode and not allow_failure:
        raise RuntimeError((result.stderr or result.stdout).strip() or f'命令失败：{args[0]}')
    return result


class MacService:
    def __init__(self, root):
        self.root = root
        self.path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
        self.domain = f'gui/{os.getuid()}'
        self.target = self.domain + '/' + LABEL

    def config(self):
        return plistlib.loads(self.path.read_bytes()) if self.path.exists() else None

    def owner(self):
        config = self.config()
        if config is None:
            return None
        if not config.get('WorkingDirectory'):
            raise RuntimeError('已有后台服务缺少项目归属信息，未更改它。')
        return config['WorkingDirectory']

    def loaded(self):
        return command(['launchctl', 'print', self.target], True).returncode == 0

    def registered(self):
        return self.path.exists()

    def enabled(self):
        result = command(['launchctl', 'print-disabled', self.domain])
        return not any(f'"{LABEL}" => {value}' in result.stdout for value in ('true', 'disabled'))

    def install(self):
        self.stop()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(mac_plist(self.root, state_dir(self.root) / 'logs'))
        temporary.replace(self.path)
        self.enable()

    def enable(self):
        command(['launchctl', 'enable', self.target])
        if not self.loaded():
            self.stop_legacy_listener()
            command(['launchctl', 'bootstrap', self.domain, str(self.path)])

    def start(self):
        if not self.enabled():
            raise RuntimeError('自启动已停用，请先执行 enable。')
        self.enable()
        command(['launchctl', 'kickstart', self.target])

    def restart_forced(self):
        """Restart only the verified loaded source runtime; never re-register it.

        Disk registration alone cannot authorize a signal: launchd may still
        have another project's old job loaded under the same global label.
        Fail closed on unknown print formats, legacy jobs and startup races.
        """
        owner = self.owner()
        if not owner or not self.registered():
            raise RuntimeError('尚未注册后台服务，无法强制重启。')
        check_owner(owner, self.root)
        if not self.enabled():
            raise RuntimeError('自启动已停用，请先执行 enable。')
        expected = [str(self.root / '.venv/bin/python'),
                    str(self.root / 'scripts/service.py'), 'run']
        config = self.config()
        if config.get('Label') != LABEL or config.get('ProgramArguments') != expected or config.get('Program'):
            raise RuntimeError('注册不是受支持的现代 run 入口，请使用普通重启或重新安装注册。')
        loaded = command(['launchctl', 'print', self.target], True)
        if loaded.returncode:
            raise RuntimeError('后台服务未加载或无法查询，未强制重启：' + (loaded.stderr or loaded.stdout).strip())
        def field(name):
            matches = re.findall(r'^\s*' + re.escape(name) + r' = (.+)$', loaded.stdout, re.M)
            return matches[0].strip() if len(matches) == 1 else None
        arguments = re.findall(r'^\s*arguments = \{\n(.*?)^\s*\}', loaded.stdout, re.M | re.S)
        if (field('path') != str(self.path) or field('program') != expected[0]
                or field('working directory') != str(self.root) or len(arguments) != 1
                or [line.strip() for line in arguments[0].splitlines() if line.strip()] != expected):
            raise RuntimeError('已加载服务的项目或 run 入口不匹配，未强制重启。')
        pid_text = field('pid')
        if not pid_text or not pid_text.isdigit() or int(pid_text) <= 1:
            raise RuntimeError('无法确认已加载服务的 PID，未强制重启；请稍后重试或使用普通重启。')
        pid = int(pid_text)
        cwd = command(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'])
        directories = [line[1:] for line in cwd.stdout.splitlines() if line.startswith('n')]
        info = command(['ps', '-p', str(pid), '-o', 'command=']).stdout.strip()
        # launchd's verified program/arguments above establish the executable.
        # macOS framework Python may exec Python.app, so ps need not retain the
        # registered venv symlink. Validate the exact script + run suffix and a
        # single absolute Python executable prefix (paths may contain spaces).
        # Do not resolve the venv symlink: that also need not name Python.app.
        suffix = ' ' + ' '.join(expected[1:])
        executable = info[:-len(suffix)] if info.endswith(suffix) else ''
        python_entry = (Path(executable).is_absolute()
                        and re.fullmatch(r'(?:Python|python(?:\d+(?:\.\d+)*)?)', Path(executable).name))
        if directories != [str(self.root)] or not (python_entry or info == shlex.join(expected)):
            raise RuntimeError('运行 PID 的项目或命令归属无法确认，未强制重启。')
        state = state_dir(self.root)
        runtime = read_json(state / 'runtime.json')
        if (runtime.get('pid') != pid or runtime.get('project') != str(self.root)
                or not runtime_locked(state)):
            raise RuntimeError('运行记录或实例锁与已加载服务不一致，未强制重启。')
        listeners = command(['lsof', '-t', f'-iTCP:{PORT}', '-sTCP:LISTEN'], True)
        if listeners.returncode not in (0, 1) or (listeners.returncode == 1 and listeners.stdout.strip()):
            raise RuntimeError('无法确认端口归属，未强制重启。')
        pids = set(listeners.stdout.split())
        if pids and pids != {str(pid)}:
            raise RuntimeError(f'端口 {PORT} 被其他或无法确认归属的程序使用，未停止它。')
        if not pids:
            check_port(PORT)
        # launchd replaces this job, while run() retains both OS-owned locks.
        # Never fall back after an ambiguous/failed kickstart: it may have run.
        command(['launchctl', 'kickstart', '-k', self.target])

    def stop(self):
        if self.loaded():
            # Allow the runtime's 25s graceful shutdown / launchd's 30s exit
            # window to complete, while still bounding a stalled bootout.
            command(['launchctl', 'bootout', self.target], timeout=BOOTOUT_TIMEOUT)
        else:
            self.stop_legacy_listener()
        deadline = time.monotonic() + 35
        while runtime_locked(state_dir(self.root)) and time.monotonic() < deadline:
            time.sleep(.2)
        if runtime_locked(state_dir(self.root)):
            raise RuntimeError('后台服务尚未停止，未启动竞争实例。')

    def stop_legacy_listener(self):
        # Migration from the previous foreground restart.sh: only a uvicorn
        # listener whose OS-reported working directory is this project belongs
        # to us. A command-name match alone is insufficient.
        result = command(['lsof', '-t', f'-iTCP:{PORT}', '-sTCP:LISTEN'], True)
        pids = sorted(set(result.stdout.split()))
        verified = []
        for text in pids:
            pid = int(text)
            cwd = command(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], True).stdout
            directories = [line[1:] for line in cwd.splitlines() if line.startswith('n')]
            if len(directories) != 1 or Path(directories[0]).resolve() != self.root.resolve():
                raise RuntimeError(f'端口 {PORT} 正被其他目录或无法确认归属的程序使用，未停止它。')
            info = command(['ps', '-p', str(pid), '-o', 'command='], True).stdout
            words = shlex.split(info)
            if not any(words[i:i+3] == ['-m', 'uvicorn', 'app.main:app'] for i in range(len(words))):
                raise RuntimeError(f'端口 {PORT} 上的程序不是可接管的旧版工作台，未停止它。')
            verified.append(pid)
        for pid in verified:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if verified:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if not command(['lsof', '-t', f'-iTCP:{PORT}', '-sTCP:LISTEN'], True).stdout.strip():
                    return
                time.sleep(.2)
            raise RuntimeError('旧版服务未及时释放端口，未强制终止它。')

    def disable(self):
        command(['launchctl', 'disable', self.target])
        self.stop()

    def uninstall(self):
        self.stop()
        self.path.unlink(missing_ok=True)


class WindowsService:
    def __init__(self, root):
        self.root = root
        self.state = state_dir(root)

    def invoke(self, action, xml=None):
        args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(ROOT / 'scripts/windows-service.ps1'), '-Action', action]
        if xml:
            args.extend(['-XmlPath', str(xml)])
        result = command(args, allow_failure=True)
        if result.returncode:
            try:
                error = json.loads(result.stdout.lstrip('\ufeff').strip())
            except ValueError:
                error = {}
            code = str(error.get('errorCode', '')).upper()
            hint = {
                '0X800706BE': 'RPC 调用被中断；可能是安全软件拦截计划任务创建，请检查拦截记录和任务计划程序状态。',
                '0X80070005': '访问被拒绝；请检查当前用户权限、系统策略及安全软件记录，不要直接关闭防护。',
            }.get(code, '请检查任务计划程序和安全软件记录。')
            if action == 'install':
                raise RuntimeError(f'后台任务注册失败（{code or "未知错误码"}）。{hint} '
                                   '已保留依赖和数据；修复后运行 install.ps1 -RegisterOnly，无需重新安装依赖。')
            raise RuntimeError(f'后台任务操作 {action} 失败（{code or "未知错误码"}）；请检查任务计划程序状态。')
        return json.loads(result.stdout.lstrip('\ufeff').strip() or '{}')

    def owner(self):
        info = self.invoke('query')
        if not info.get('registered'):
            return None
        try:
            return json.loads(info['description'])['project']
        except (ValueError, KeyError):
            raise RuntimeError('已有计划任务缺少项目归属信息，未更改它。')

    def registered(self):
        return self.invoke('query').get('registered', False)

    def enabled(self):
        return self.invoke('query').get('enabled', False)

    def install(self):
        if self.registered():
            self.stop()
        self.state.mkdir(parents=True, exist_ok=True)
        path = self.state / 'task.xml'
        path.write_text(windows_xml(self.root, self.invoke('identity')['sid']), encoding='utf-8')
        self.invoke('install', path)
        self.start()

    def enable(self):
        self.invoke('enable')
        self.start()

    def start(self):
        if not self.enabled():
            raise RuntimeError('自启动已停用，请先执行 enable。')
        (self.state / 'pause.json').unlink(missing_ok=True)
        self.invoke('start')

    def stop(self):
        write_json(self.state / 'pause.json', {'session': login_session()})
        # Allow the runtime to flush data and gracefully close browser sessions.
        deadline = time.monotonic() + 35
        while runtime_locked(self.state) and time.monotonic() < deadline:
            time.sleep(.2)
        if runtime_locked(self.state):
            raise RuntimeError('服务尚未完成停止；已暂停本次登录的自动拉起，请查看日志。')

    def disable(self):
        self.invoke('disable')
        self.stop()

    def uninstall(self):
        self.disable()
        self.invoke('uninstall')


def runtime_locked(state):
    lock = InstanceLock(state / 'instance.lock')
    acquired = lock.acquire()
    lock.release()
    return not acquired


class LogStream:
    def __init__(self, logger):
        self.logger = logger
    def write(self, text):
        if text.strip():
            self.logger.info(text.rstrip())
        return len(text)
    def flush(self):
        pass
    def isatty(self):
        return False


def run(root=ROOT, port=PORT):
    state = state_dir(root)
    session = login_session() if sys.platform == 'win32' else None
    if session and is_paused(state / 'pause.json', session):
        return 0
    lock = InstanceLock(state / 'instance.lock')
    if not lock.acquire():
        return 0
    if session and is_paused(state / 'pause.json', session):
        lock.release()
        return 0
    port_lock = InstanceLock(state.parent / f'port-{port}.lock')
    if not port_lock.acquire():
        lock.release()
        return 1
    log_dir = state / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'service.log', maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    previous_streams = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = LogStream(logging.getLogger('console'))
    ended = threading.Event()
    try:
        check_port(port)
        os.chdir(root)
        sys.path.insert(0, str(root))
        import uvicorn
        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
            child = logging.getLogger(name)
            child.handlers.clear()
            child.propagate = True
        server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=port,
                                               log_config=None, timeout_graceful_shutdown=25))
        if session:
            def watch_stop():
                while not ended.wait(.5):
                    if is_paused(state / 'pause.json', session):
                        server.should_exit = True
                        return
            threading.Thread(target=watch_stop, daemon=True).start()
        write_json(state / 'runtime.json', {'pid': os.getpid(), 'project': str(root)})
        server.run()
        code = 0 if server.started else 1
        if code:
            write_json(state / 'last-exit.json', {'time': time.time(), 'code': code})
        return code
    except Exception:
        logger.exception('工作台启动或运行失败')
        write_json(state / 'last-exit.json', {'time': time.time(), 'code': 1})
        return 1
    finally:
        ended.set()
        (state / 'runtime.json').unlink(missing_ok=True)
        sys.stdout, sys.stderr = previous_streams
        logger.removeHandler(handler)
        handler.close()
        port_lock.release()
        lock.release()


def wait_ready(state, port=PORT):
    started = time.time()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if runtime_locked(state) and page_accessible(port):
            return
        failure = read_json(state / 'last-exit.json')
        if failure.get('code') and failure.get('time', 0) >= started - 2:
            raise RuntimeError(f'后台进程启动后已退出，请查看 {state / "logs/service.log"}；修复原因后重试服务启动，无需重新安装依赖。')
        time.sleep(.5)
    raise RuntimeError(f'服务未在 45 秒内就绪。请查看 {state / "logs/service.log"}；若日志不存在，请检查系统启动记录、解释器和项目磁盘访问权限。')


def main():
    parser = argparse.ArgumentParser(description='工作台后台服务管理（当前电脑用户）')
    parser.add_argument('action', choices=['install', 'run', 'start', 'stop', 'restart', 'status', 'enable', 'disable', 'uninstall'])
    parser.add_argument('--relocate', action='store_true', help='仅安装时接替原目录已经不存在的注册')
    parser.add_argument('--force', action='store_true', help='仅 restart：强制重启已验证的 macOS 服务')
    parser.add_argument('--no-wait', action='store_true', help='仅 restart：提交重启后不等待页面就绪')
    args = parser.parse_args()
    if args.action != 'restart' and (args.force or args.no_wait):
        parser.error('--force 和 --no-wait 仅可用于 restart')
    if args.action == 'run':
        return run()
    management_lock = InstanceLock(state_dir().parent / 'management.lock')
    if not management_lock.acquire():
        raise RuntimeError('另一个服务管理操作正在执行，请稍后重试。')
    try:
        return manage(args)
    finally:
        management_lock.release()


def manage(args):
    if sys.platform not in ('darwin', 'win32'):
        raise RuntimeError('自动后台服务目前支持 macOS 和 Windows。')
    adapter = MacService(ROOT) if sys.platform == 'darwin' else WindowsService(ROOT)
    owner = adapter.owner()
    check_owner(owner, ROOT, relocate=args.action == 'install' and args.relocate)
    state = state_dir()
    if args.action == 'status':
        result = runtime_status(state, PORT)
        result.update(registered=adapter.registered(), enabled=adapter.enabled() if owner else False,
                      project=str(ROOT), logs=str(state / 'logs'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.action == 'install':
        interpreter = ROOT / ('.venv/Scripts/pythonw.exe' if sys.platform == 'win32' else '.venv/bin/python')
        if not interpreter.exists():
            raise RuntimeError('项目虚拟环境不存在，请先执行安装入口。')
        if not owner:
            check_port(PORT)
        adapter.install()
    else:
        if not owner:
            raise RuntimeError('尚未注册后台服务，请先执行安装入口。')
        if args.action == 'restart':
            if not adapter.enabled():
                raise RuntimeError('自启动已停用，请先执行 enable。')
            if sys.platform == 'darwin' and getattr(args, 'force', False):
                adapter.restart_forced()
            # Legacy launchd jobs have no managed lock, but belong to this root.
            elif sys.platform == 'darwin' and 'run' not in adapter.config().get('ProgramArguments', []):
                adapter.stop()
                adapter.start()
                if not getattr(args, 'no_wait', False) and not page_accessible(PORT):
                    for _ in range(90):
                        time.sleep(.5)
                        if page_accessible(PORT):
                            break
                    else:
                        raise RuntimeError('旧版服务未就绪，请查看原服务日志。')
                print(f'重启已提交：http://127.0.0.1:{PORT}' if getattr(args, 'no_wait', False)
                      else f'服务已重启：http://127.0.0.1:{PORT}')
                return 0
            else:
                adapter.stop()
                adapter.start()
        else:
            getattr(adapter, args.action)()
    if args.action in ('install', 'start', 'restart', 'enable'):
        if args.action == 'restart' and getattr(args, 'no_wait', False):
            print(f'重启已提交：http://127.0.0.1:{PORT}')
            return 0
        wait_ready(state)
        print(f'工作台已在后台运行：http://127.0.0.1:{PORT}')
    else:
        print({'stop': '工作台已停止；下次登录电脑后自动恢复。',
               'disable': '已停止工作台并停用自启动。',
               'uninstall': '后台注册已卸载，项目配置和业务数据已保留。'}[args.action])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f'操作失败：{exc}', file=sys.stderr)
        sys.exit(1)
