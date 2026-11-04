#!/usr/bin/env python3
"""Detached restart worker: one control request, concurrent readiness verification."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updates import FileLock, read_state, write_state
from scripts.update_workbench import interpreter
from scripts.service import state_dir

RECOVERY_SECONDS = 120
CONTROL_SECONDS = 40
HEALTH_URL = 'http://127.0.0.1:8001/api/health'


def launch_restart(root, forced, log):
    args = [str(interpreter(root)), str(root / 'scripts/service.py'), 'restart', '--no-wait']
    if forced:
        args.append('--force')
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    return subprocess.Popen(args, cwd=str(root), stdin=subprocess.DEVNULL, stdout=log,
                            stderr=log, close_fds=True, **options)


def stop_command(process):
    """Only stop the control subprocess/group created here, never a port owner."""
    if process is None or process.poll() is not None:
        return
    def send(sig):
        try:
            if os.name != 'nt': os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM: process.terminate()
            else: process.kill()
        except ProcessLookupError:
            pass
    send(signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == 'nt': process.kill()
        else: send(signal.SIGKILL)
        process.wait(timeout=2)


def owned_pid(root):
    runtime = read_state(state_dir(root) / 'runtime.json')
    pid = runtime.get('pid')
    if runtime.get('project') == str(root) and isinstance(pid, int) and pid > 1:
        return pid
    return None


def pid_exited(pid):
    # Signal zero is not a harmless existence probe on Windows. This timestamp
    # is optional; new-instance health still determines restart success there.
    if pid is None or os.name == 'nt':
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def run(root, health_url=HEALTH_URL):
    root = Path(root)
    directory = root / 'workspace/system-restart'
    path = directory / 'job.json'
    lock = FileLock(directory / 'worker.lock')
    if not lock.acquire(): return
    job = read_state(path)
    process = None
    command_log = None
    try:
        if job.get('phase') != 'starting': return
        # One total budget covers command and recovery, rather than serial timeouts.
        remaining = min(RECOVERY_SECONDS, max(0, job.get('restartDeadline', time.time()+RECOVERY_SECONDS)-time.time()))
        deadline = time.monotonic() + remaining
        job.setdefault('restartDeadline', time.time()+remaining)
        job.setdefault('stageTimes', {})
        job.setdefault('diagnostics', {})

        def save():
            current = read_state(path)
            if current.get('id') != job.get('id'):
                raise RuntimeError('重启记录已变化，停止本次验证。')
            job['updatedAt'] = time.time()
            write_state(path, job)

        def mark(name):
            job['stageTimes'].setdefault(name, time.time())

        def stage(value, message):
            if job.get('stage') != value:
                job['stageStartedAt'] = time.time()
            job.update(stage=value, message=message)

        old_pid = owned_pid(root)
        if old_pid: job['oldPid'] = old_pid
        mark('stopRequestedAt')
        stage('stopping', '正在停止服务…')
        job['phase'] = 'restarting'
        save()
        # Flush the initiating response and the streams closed by RestartManager.
        time.sleep(.3)
        command_log = (directory / 'service-command.log').open('ab')
        command_log.write(('\nrestart job=' + str(job.get('id')) + '\n').encode())
        command_log.flush()
        mark('startRequestedAt')
        process = launch_restart(root, bool(job.get('forced')), command_log)
        control_deadline = min(deadline, time.monotonic() + CONTROL_SECONDS) if job.get('forced') else deadline
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if old_pid and 'oldProcessExitedAt' not in job['stageTimes'] and pid_exited(old_pid):
                mark('oldProcessExitedAt')
                stage('starting', '正在启动服务…')
            returncode = process.poll()
            if returncode is not None and 'commandFinishedAt' not in job['stageTimes']:
                mark('commandFinishedAt')
                job['diagnostics']['commandExitCode'] = returncode
                if returncode:
                    job['diagnostics']['commandError'] = '服务控制命令未成功完成，继续确认服务是否恢复；详情见 service-command.log。'
                if job.get('stage') == 'stopping' and (returncode == 0 or not old_pid):
                    stage('starting', '正在启动服务…')
            elif returncode is None and time.monotonic() >= control_deadline:
                job['diagnostics']['commandTimedOut'] = True
                stop_command(process)
            save()
            try:
                with opener.open(health_url, timeout=min(1, max(.1, deadline-time.monotonic()))) as response:
                    health = json.load(response)
            except (OSError, ValueError):
                health = {}
            if not isinstance(health, dict): health = {}
            instance = health.get('instanceId')
            if instance and instance != job['instanceId'] and health.get('status') == 'ok':
                mark('newInstanceReadyAt')
                if old_pid and pid_exited(old_pid): mark('oldProcessExitedAt')
                job.update(phase='verifying', newInstanceId=instance)
                stage('verifying_plugins', '正在确认插件…')
                save()
                plugins = health.get('plugins')
                if isinstance(plugins, dict) and plugins.get('ok') is False:
                    raise RuntimeError('新服务已启动，但插件加载失败，请查看插件管理及服务日志。')
                mark('pluginHealthConfirmedAt')
                # The page additionally verifies its account's exact target versions.
                job.update(phase='complete', error='', message='工作台已重启，正在确认目标插件版本…')
                mark('completedAt')
                save()
                return
            time.sleep(.5)
        raise RuntimeError('重启等待超时，未确认新服务就绪；请检查 service-command.log 和 service.log，或手动打开工作台后重新检查连接。')
    except Exception as exc:
        if read_state(path).get('id') == job.get('id'):
            job.update(phase='failed', error=str(exc)[:600], updatedAt=time.time())
            write_state(path, job)
    finally:
        try:
            stop_command(process)
        finally:
            if command_log: command_log.close()
            lock.release()


if __name__ == '__main__': run(Path(__file__).resolve().parents[1])
