#!/usr/bin/env python3
"""Detached update worker. Target and previous revision come from local state only."""
from __future__ import annotations
import json
import os
import shlex
import signal
import tempfile
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updates import FileLock, read_state, write_state
from app.versioning import Repository, VersionError
from scripts.service import InstanceLock, state_dir


def urlopen(url, timeout):
    """Keep the patchable health seam while ignoring proxy environment settings."""
    return build_opener(ProxyHandler({})).open(url, timeout=timeout)


def persist_transaction(path, record):
    """Write ahead of mutations; an unreadable/incomplete marker also blocks retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='transaction-', suffix='.tmp', delete=False) as out:
        temporary = Path(out.name)
        try:
            json.dump(record, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def interpreter(root):
    return root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')


def command(args, root, timeout):
    try:
        # A bundle helper may spawn pip. Kill the entire POSIX process group on
        # timeout so no installer survives to race environment restoration.
        with subprocess.Popen([str(arg) for arg in args], cwd=str(root),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              start_new_session=os.name != 'nt') as process:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name != 'nt':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait()
                raise
            if code:
                raise VersionError('执行失败，请检查项目依赖、网络或后台服务日志。')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VersionError('执行失败或超时，请检查项目依赖、网络或后台服务日志。') from exc


def dependencies_changed(root, changed):
    paths = set(changed.splitlines())
    manifests = {'requirements.txt', 'distribution/source-runtime.json',
                 'pyproject.toml', 'poetry.lock', 'uv.lock', 'Pipfile.lock'}
    pending = [root / 'requirements.txt']
    seen = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            manifests.add(path.relative_to(root).as_posix())
        except ValueError:
            raise VersionError('依赖文件引用了项目外路径，请交由 Agent 检查后更新。')
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').replace('\\\n', '').splitlines():
            words = shlex.split(line, comments=True)
            for index, word in enumerate(words):
                for flag in ('-r', '-c', '--requirement', '--constraint'):
                    if word == flag and index + 1 < len(words):
                        pending.append(path.parent / words[index + 1])
                    elif word.startswith(flag + '='):
                        pending.append(path.parent / word.split('=', 1)[1])
                    elif flag in ('-r', '-c') and word.startswith(flag) and len(word) > 2:
                        pending.append(path.parent / word[2:])
    return bool(paths & manifests) or any(
        Path(name).name.startswith(('requirements', 'constraints')) for name in paths)


def dependency_preflight(root):
    if sys.platform == 'win32':
        raise VersionError('Windows 暂不支持自动依赖升级：运行中的更新程序可能占用 .venv。'
                           '请让 Agent 使用项目外 Python 停止服务、备份原环境、在最终路径重建依赖，'
                           '并验证启动；失败时恢复原环境和代码。当前代码和服务未更改。')
    if sys.platform != 'darwin' or sys.version_info[:2] not in ((3, 11), (3, 12)):
        raise VersionError('依赖变更更新需要 macOS 上运行的 Python 3.11/3.12；'
                           '请让 Agent 使用兼容解释器执行更新。当前代码和服务未更改。')
    base = Path(sys._base_executable).resolve()
    if not base.is_file() or base.is_relative_to(root / '.venv'):
        raise VersionError('无法确认项目外的基础 Python，请让 Agent 检查解释器。')
    if not interpreter(root).is_file() or (root / '.venv').is_symlink():
        raise VersionError('原虚拟环境不存在或是目录链接，请让 Agent 检查。')
    return base


class DependencyUpdate:
    """Never relocate a prepared venv: console scripts contain absolute paths.

    Keep both staging and the untouched original under ignored workspace. The
    staging interpreter also manages service recovery when final .venv is broken.
    """
    def __init__(self, root, base):
        self.root, self.base = root, base
        parent = root / 'workspace/system-update'
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='dependencies-', dir=parent))
        self.stage = self.directory / 'stage'
        self.python = self.stage / 'bin/python'
        self.wheels = self.directory / 'wheels'
        self.backup = self.directory / 'original-venv'
        self.moved = False
        self.checkpoint = lambda step: None

    def pip(self, python, action, *args):
        command([python, '-I', '-m', 'pip', '--isolated', action,
                 '--disable-pip-version-check', '--no-input', '--only-binary=:all:',
                 '--timeout', '30', '--retries', '2', *args], self.root, 600)

    def prepare(self):
        command([self.base, '-I', '-m', 'venv', self.stage], self.root, 120)
        # A child keeps runtime helper imports out of this long-lived worker and
        # bounds bundle verification/download AND install_wheels as one operation.
        record = self.directory / 'runtime.json'
        command([self.python, '-I', '-c',
                 'import sys,json; from pathlib import Path; '
                 'root=Path(sys.argv[1]); sys.path.insert(0,str(root)); '
                 'from scripts.source_runtime import prepare_runtime,install_wheels; '
                 'runtime=prepare_runtime(root); '
                 'install_wheels(root,Path(sys.executable),runtime) if runtime is not None else None; '
                 'Path(sys.argv[2]).write_text(json.dumps(str(runtime) if runtime is not None else None))',
                 self.root, record], self.root, 900)
        runtime = json.loads(record.read_text())
        self.wheels.mkdir()
        source = ['--no-index', '--find-links', str(Path(runtime) / 'wheelhouse')] if runtime else []
        self.pip(self.python, 'download', *source, '--dest', self.wheels,
                 '-r', self.root / 'requirements.txt')
        self.install(self.python)

    def install(self, python):
        wheels = sorted(self.wheels.glob('*.whl'))
        if not wheels:
            raise VersionError('暂存依赖中没有可安装的二进制 wheel。')
        # Install exactly the downloaded resolution, without re-reading direct
        # URLs or local paths from requirements after the service is stopped.
        self.pip(python, 'install', '--no-index', '--find-links', self.wheels, *wheels)
        command([python, '-I', '-m', 'pip', '--isolated', 'check'], self.root, 120)

    def stop(self):
        command([self.python, self.root / 'scripts/service.py', 'stop'], self.root, 120)

    def activate(self):
        self.checkpoint('stopping-service')
        self.stop()
        self.checkpoint('backing-up-environment')
        (self.root / '.venv').rename(self.backup)
        self.moved = True
        self.checkpoint('creating-final-environment')
        command([self.base, '-I', '-m', 'venv', self.root / '.venv'], self.root, 120)
        self.checkpoint('installing-final-dependencies')
        self.install(interpreter(self.root))

    def restore(self):
        if self.moved:
            self.checkpoint('restoring-environment')
            # A failed restart may have left the target service running.
            self.stop()
            if not self.backup.is_dir():
                raise VersionError('原环境备份丢失，不能声明恢复成功；请让 Agent 检查。')
            live = self.root / '.venv'
            if live.exists():
                live.rename(self.directory / 'failed-venv')
            self.backup.rename(live)
            self.moved = False


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
    install_lock = None
    marker = directory / 'transaction.json'
    record = None
    installed = False
    transaction = None

    def phase(value, message):
        job.update(phase=value, message=message, updatedAt=time.time())
        write_state(path, job)

    def checkpoint(step):
        record.update(step=step, updatedAt=time.time())
        persist_transaction(marker, record)

    try:
        install_lock = InstanceLock(state_dir(root) / 'install.lock')
        if not install_lock.acquire():
            raise VersionError('另一个安装或更新操作正在进行，请等待完成后重试。')
        # This marker is independent of job.json: starting a new UI job must not
        # erase evidence of a killed worker, even if the marker JSON is corrupt.
        if marker.exists() or marker.is_symlink():
            job['needsManualRecovery'] = True
            raise VersionError('检测到未完成的更新事务：' + str(marker) +
                               '。请让 Agent 检查事务记录中的原提交、目标提交和环境备份，'
                               '确认没有遗留安装进程后恢复代码与原环境、重启并验证健康；'
                               '验证完成后才能移除事务标记并重试。不要直接重置或覆盖 .venv。')
        if job.get('phase') != 'starting':
            return
        repo = Repository(root)
        target = job['target']
        actual = repo.remote_tags().get(target['tag'], {})
        if actual.get('commit', actual.get('object')) != target['commit']:
            raise VersionError('远程版本已变化或移除，请重新检查更新。')
        if repo.preflight(target['commit']) != job['previous']:
            raise VersionError('本地代码在等待期间发生变化，请重新检查更新。')
        phase('installing', '正在安装目标版本…')
        changed = repo.git('diff', '--name-only', job['previous'], target['commit'])
        deps_changed = dependencies_changed(root, changed)
        base = dependency_preflight(root) if deps_changed else None
        if deps_changed:
            transaction = DependencyUpdate(root, base)
            job['dependencyBackup'] = str(transaction.backup)
            transaction.checkpoint = checkpoint
        record = {'schemaVersion': 1, 'root': str(root), 'previous': job['previous'],
                  'target': target, 'environment': str(root / '.venv'),
                  'backup': str(transaction.backup) if transaction else None,
                  'staging': str(transaction.stage) if transaction else None}
        checkpoint('checking-out-target')
        repo.install(target['commit'])
        installed = True
        if deps_changed:
            checkpoint('preparing-dependencies')
            phase('dependencies', '正在暂存并验证依赖，原环境尚未修改…')
            transaction.prepare()
            transaction.activate()
        checkpoint('restarting-target')
        phase('restarting', '正在重启工作台…')
        restart(root)
        phase('verifying', '正在验证新版本是否正常运行…')
        verify_health(root, target['commit'], target['version'])
        phase('succeeded', '更新成功，工作台已运行新版本。')
        marker.unlink()
    except Exception as exc:
        job['error'] = str(exc) if isinstance(exc, VersionError) else '更新发生异常，请查看本地更新记录。'
        job['failedPhase'] = job.get('phase')
        job['recovered'] = False
        if installed:
            phase('recovering', '更新失败，正在尝试恢复更新前代码…')
            try:
                if transaction is not None:
                    transaction.restore()
                checkpoint('restoring-source')
                repo.rollback(job['target']['commit'], job['previous'])
                restart(root)
                verify_health(root, job['previous'])
                marker.unlink()
                job['recovered'] = True
            except Exception as recovery:
                job['recoveryError'] = str(recovery) if isinstance(recovery, VersionError) else '自动恢复失败，请人工检查后台服务。'
        if marker.exists() or marker.is_symlink():
            job['needsManualRecovery'] = True
            job['recoveryInstruction'] = ('请让 Agent 检查 ' + str(marker) +
                '，恢复并验证代码、环境和后台服务后移除标记；不要直接重置或覆盖 .venv。')
        phase('failed', '更新失败；' + ('已恢复更新前代码。' if job['recovered'] else '请按错误说明处理后重试，本地资料已保留。'))
    finally:
        try:
            if install_lock is not None:
                install_lock.release()
        finally:
            lock.release()


if __name__ == '__main__':
    run(Path(__file__).resolve().parents[1])
