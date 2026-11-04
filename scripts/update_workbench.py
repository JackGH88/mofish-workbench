#!/usr/bin/env python3
"""Detached update worker. Target and previous revision come from local state only."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updates import FileLock, read_state, write_state
from app.versioning import Repository, VersionError


def interpreter(root):
    return root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')


def command(args, root, timeout):
    try:
        result = subprocess.run([str(arg) for arg in args], cwd=str(root), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        if result.returncode:
            raise VersionError('执行失败，请检查项目依赖、网络或后台服务日志。')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VersionError('执行失败或超时，请检查项目依赖、网络或后台服务日志。') from exc


def install_dependencies(root):
    python = interpreter(root)
    if not python.is_file():
        raise VersionError('项目虚拟环境不存在，不能安装依赖。')
    command([python, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-r', root / 'requirements.txt'], root, 600)


def restart(root):
    command([interpreter(root), root / 'scripts/service.py', 'restart'], root, 120)


def verify_health(root, commit, version=None):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urlopen('http://127.0.0.1:8001/api/health', timeout=2) as response:
                status = json.load(response)
            running = status.get('runningVersion', {})
            if status.get('status') == 'ok' and running.get('commit') == commit and (version is None or running.get('version') == version):
                # 目标版本报告插件加载失败时，不能判定为更新成功；旧版本无此字段按健康处理。
                plugins = status.get('plugins')
                if isinstance(plugins, dict) and plugins.get('ok') is False:
                    raise VersionError('目标版本的插件加载失败，未判定为更新成功：' + _plugin_failure_summary(plugins))
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise VersionError('重启后未能验证目标版本，旧进程或其他服务的响应不能算更新成功。')


def _plugin_failure_summary(plugins):
    names = [str(item.get('source') or '?') for item in (plugins.get('failures') or [])]
    names += [str(item.get('id')) for item in (plugins.get('loaded') or []) if item.get('loadError')]
    return '、'.join(names[:5]) if names else '未知插件'


def run(root):
    root = Path(root).resolve()
    directory = root / 'workspace/system-update'
    path = directory / 'job.json'
    lock = FileLock(directory / 'worker.lock')
    if not lock.acquire():
        return
    job = read_state(path)
    if job.get('phase') != 'starting':
        lock.release()
        return
    repo = Repository(root)
    installed = False
    deps_changed = False

    def phase(value, message):
        job.update(phase=value, message=message, updatedAt=time.time())
        write_state(path, job)

    try:
        target = job['target']
        actual = repo.remote_tags().get(target['tag'], {})
        if actual.get('commit', actual.get('object')) != target['commit']:
            raise VersionError('远程版本已变化或移除，请重新检查更新。')
        if repo.preflight(target['commit']) != job['previous']:
            raise VersionError('本地代码在等待期间发生变化，请重新检查更新。')
        phase('installing', '正在安装目标版本…')
        changed = repo.git('diff', '--name-only', job['previous'], target['commit'])
        deps_changed = 'requirements.txt' in changed.splitlines()
        repo.install(target['commit'])
        installed = True
        if deps_changed:
            phase('dependencies', '正在安装版本所需依赖…')
            install_dependencies(root)
        phase('restarting', '正在重启工作台…')
        restart(root)
        phase('verifying', '正在验证新版本是否正常运行…')
        verify_health(root, target['commit'], target['version'])
        phase('succeeded', '更新成功，工作台已运行新版本。')
    except Exception as exc:
        job['error'] = str(exc) if isinstance(exc, VersionError) else '更新发生异常，请查看本地更新记录。'
        job['failedPhase'] = job.get('phase')
        job['recovered'] = False
        if installed:
            phase('recovering', '更新失败，正在尝试恢复更新前代码…')
            try:
                repo.rollback(job['target']['commit'], job['previous'])
                if deps_changed:
                    install_dependencies(root)
                restart(root)
                verify_health(root, job['previous'])
                job['recovered'] = True
            except Exception as recovery:
                job['recoveryError'] = str(recovery) if isinstance(recovery, VersionError) else '自动恢复失败，请人工检查后台服务。'
        phase('failed', '更新失败；' + ('已恢复更新前代码。' if job['recovered'] else '请按错误说明处理后重试，本地资料已保留。'))
    finally:
        lock.release()


if __name__ == '__main__':
    run(Path(__file__).resolve().parents[1])
