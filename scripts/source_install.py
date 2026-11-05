#!/usr/bin/env python3
"""Resumable source installation; never deletes an existing environment or user data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.service import InstanceLock, state_dir, read_json, write_json


def execute(args, *, root=ROOT, timeout=120, capture=False):
    try:
        result = subprocess.run([str(a) for a in args], cwd=root, timeout=timeout,
                                capture_output=capture, text=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('命令无法完成或超时：' + str(args[0])) from exc
    if result.returncode:
        raise RuntimeError('步骤执行失败：' + ' '.join(str(a) for a in args[:3]))
    return result.stdout if capture else ''


def supported_python(python, root=ROOT):
    try:
        info = json.loads(execute([python, '-c', 'import sys,struct,venv,ensurepip; print(__import__("json").dumps([list(sys.version_info[:2]),struct.calcsize("P")*8]))'], root=root, capture=True, timeout=15))
        return info[0] in ([3, 11], [3, 12]) and info[1] == 64
    except (RuntimeError, ValueError, IndexError):
        return False


def requirements_satisfied(root, python):
    # Check actual distributions, not just a marker left by an earlier run.
    code = '''import importlib.metadata as m, pathlib, re, sys
from zoneinfo import ZoneInfo
ZoneInfo('Asia/Shanghai')
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
 line=line.strip()
 if not line or line.startswith('#'): continue
 match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^ ;]+)',line)
 if not match or m.version(match[1]) != match[2]: sys.exit(1)
import fastapi,uvicorn,pydantic,playwright.sync_api
'''
    try:
        execute([python, '-c', code, root / 'requirements.txt'], root=root, capture=True, timeout=30)
        execute([python, '-m', 'pip', 'check'], root=root, capture=True, timeout=30)
        return True
    except RuntimeError:
        return False


def ensure_dependencies(root, python, runtime=None):
    if requirements_satisfied(root, python):
        print('Python 依赖已通过检查，跳过重复安装。', flush=True)
        return
    if runtime:
        from scripts.source_runtime import install_wheels
        install_wheels(root, python, runtime)
    else:
        execute([python, '-m', 'pip', 'install', '--only-binary=:all:', '--disable-pip-version-check',
                 '--no-input', '--timeout', '30', '--retries', '2', '-r', root / 'requirements.txt'], root=root, timeout=900)
    if not requirements_satisfied(root, python):
        raise RuntimeError('Python 依赖或时区检查未通过；保留环境，请检查上述错误后续跑。')


def verify_service(root, python):
    status = json.loads(execute([python, root / 'scripts/service.py', 'status'], root=root, capture=True, timeout=30))
    if not all(status.get(key) is True for key in ('registered', 'running', 'pageAccessible', 'enabled')):
        raise RuntimeError('服务状态未全部就绪，请检查后台日志后续跑。')
    if Path(status.get('project', '')).resolve() != root.resolve():
        raise RuntimeError('响应的服务不属于本次安装目录。')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8001/api/health', timeout=10) as response:
        health = json.load(response)
    expected = (root / 'VERSION').read_text().strip()
    if (health.get('status') != 'ok' or health.get('downloadDirWritable') is not True
            or health.get('runningVersion', {}).get('version') != expected
            or health.get('plugins', {}).get('ok') is not True):
        raise RuntimeError('服务已响应，但版本、数据目录或插件健康检查未通过。')
    return {'service': status, 'health': health}


def verify_capabilities(root, python, skip_chrome=False):
    # Failure of an optional smoke check degrades its capability, not the installed app.
    args = [str(python), '-m', 'app.dependency_diagnostics', '--verify-media']
    if not skip_chrome:
        args.append('--verify-browser')
    result = subprocess.run(args, cwd=root, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120,
                            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode not in (0, 1):
        raise RuntimeError('能力检查未能完成，请查看安装日志。')
    report = json.loads(result.stdout)
    if not isinstance(report.get('dependencies'), dict):
        raise RuntimeError('能力检查没有返回有效报告。')
    return report


def chrome_guidance(root, python):
    from app.dependency_diagnostics import collect
    report = collect(root)
    chrome = report.get('dependencies', report).get('chrome', {})
    if chrome.get('ok'):
        print('Chrome 已检测到；安装验收将验证实际启动。', flush=True)
        return True
    print('未检测到可用 Chrome。请 Agent 从 https://www.google.com/chrome/ 安装稳定版，'
          '完成系统安装提示后执行 --chrome-only（Windows: -ChromeOnly）。'
          '不需要安装 Playwright Chromium，也不需要登录第三方账号。', flush=True)
    return False


def validate_platform():
    machine = platform.machine().lower()
    if sys.platform == 'win32':
        native = os.environ.get('PROCESSOR_ARCHITEW6432', os.environ.get('PROCESSOR_ARCHITECTURE', machine)).lower()
        if native not in ('amd64', 'x86_64') or sys.getwindowsversion().major < 10:
            raise RuntimeError('完整自动安装目前支持 Windows 10/11 x64；此系统或架构尚未验证。')
    elif sys.platform == 'darwin':
        if machine != 'arm64' or int(platform.mac_ver()[0].split('.')[0]) < 13:
            raise RuntimeError('完整自动安装目前支持 macOS 13+ Apple Silicon；此系统或架构尚未验证。')
    else:
        raise RuntimeError('完整自动安装目前支持 Windows x64 和 macOS Apple Silicon。')


def install(args, root=ROOT):
    from app.dependency_diagnostics import collect
    root = Path(root).resolve()
    if args.check:
        print(json.dumps(collect(root), ensure_ascii=False, indent=2))
        return 0
    validate_platform()
    record_path = root / 'workspace/install/state.json'
    lock = InstanceLock(state_dir(root) / 'install.lock')
    if not lock.acquire():
        raise RuntimeError('另一个安装操作正在进行，请等待完成后再续跑。')
    record = read_json(record_path)
    if not isinstance(record, dict) or any(not isinstance(record.get(key, {}), dict) for key in ('stages', 'tools')):
        lock.release()
        raise RuntimeError('安装记录格式无效，请 Agent 检查 workspace/install/state.json；未更改环境。')
    record.setdefault('stages', {})
    record.setdefault('tools', {})
    def stage(name, action):
        print(f'正在执行：{name}', flush=True)
        start = time.monotonic()
        record.update(phase=name, status='running')
        write_json(record_path, record)
        try:
            value = action()
        except Exception as exc:
            record['stages'][name] = {'seconds': round(time.monotonic()-start, 2), 'ok': False}
            record.update(status='failed', error=str(exc), nextAction='修复原因后重新运行原安装命令或 --resume；已完成步骤会重新验证并复用。')
            write_json(record_path, record)
            raise
        record['stages'][name] = {'seconds': round(time.monotonic()-start, 2), 'ok': True}
        write_json(record_path, record)
        return value
    try:
        pending_update = root / 'workspace/system-update/transaction.json'
        if pending_update.exists() or pending_update.is_symlink():
            raise RuntimeError('检测到未完成的更新事务，请 Agent 先按 workspace/system-update/transaction.json 恢复并验证原环境；未继续安装。')
        python = root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        if args.chrome_only:
            if not python.exists():
                raise RuntimeError('请先完成基础安装，再执行 Chrome 验收。')
            if not chrome_guidance(root, python):
                record.update(status='degraded', report=collect(root), nextAction='请 Agent 从 Chrome 官方渠道安装后重试 --chrome-only / -ChromeOnly。')
                write_json(record_path, record)
                return 2
            text = stage('Chrome 本地启动检查', lambda: execute([python, '-m', 'app.dependency_diagnostics', '--verify-browser'], root=root, capture=True, timeout=60))
            report = json.loads(text)
            record.update(status='complete' if report.get('ok') else 'degraded', report=report)
            record.pop('error', None)
            record.pop('nextAction', None)
            write_json(record_path, record)
            print(text)
            return 0
        # Inspect ownership before touching dependencies or service registration.
        from scripts.service import MacService, WindowsService, check_owner, check_port
        adapter = MacService(root) if sys.platform == 'darwin' else WindowsService(root)
        owner = adapter.owner()
        check_owner(owner, root, relocate=args.relocate)
        if owner and not adapter.enabled():
            raise RuntimeError('现有后台服务已停用；已保留用户选择。请明确启用后再安装修复。')
        if not owner:
            check_port(8001)
        if shutil.disk_usage(root).free < 512 * 1024 * 1024:
            raise RuntimeError('可用空间不足 512 MiB，请先释放空间；完整运行环境包还会按解压大小检查空间。')
        if (root / '.venv').exists() and not python.exists():
            raise RuntimeError('已有 .venv 缺少解释器，已保留环境；请 Agent 检查是否为中断安装，不能直接覆盖。')
        if python.exists() and not supported_python(python, root):
            raise RuntimeError('已有 .venv 不是可用的 Python 3.11/3.12 64 位环境；已保留原环境和数据，请 Agent 先制定迁移方案。')
        runtime = None
        if args.register_only:
            if not python.exists() or not requirements_satisfied(root, python):
                raise RuntimeError('仅注册服务需要已有可用虚拟环境和完整依赖；请先运行普通安装入口。')
        else:
            from scripts.source_runtime import prepare_runtime
            dependencies_ok = python.exists() and requirements_satisfied(root, python)
            if owner and not dependencies_ok:
                current = json.loads(execute([python, root / 'scripts/service.py', 'status'], root=root, capture=True, timeout=30))
                if current.get('running'):
                    raise RuntimeError('现有服务仍在运行且依赖需要变更；未修改环境。请 Agent 在任务空闲时使用 service stop 停止原服务，再续跑安装；保留原环境和数据。')
            # A healthy environment must not depend on a fresh bundle download.
            tools = collect(root).get('dependencies', {})
            media_ok = all(tools.get(name, {}).get('ok') for name in ('ffmpeg', 'ffprobe'))
            if not dependencies_ok or not media_ok:
                runtime = stage('准备运行环境', lambda: prepare_runtime(root))
            else:
                print('已有 Python 依赖与媒体工具通过检查，跳过运行环境下载。', flush=True)
            if not python.exists():
                creator = sys.executable
                if runtime:
                    creator = runtime / ('python/python.exe' if os.name == 'nt' else 'python/bin/python3')
                if not supported_python(creator, root):
                    raise RuntimeError('需要 Python 3.11/3.12 64 位及 venv/pip；请 Agent 按 README 补齐，不使用 Store 占位别名。')
                stage('创建虚拟环境', lambda: execute([creator, '-m', 'venv', root / '.venv'], root=root))
            stage('安装和检查 Python 依赖', lambda: ensure_dependencies(root, python, runtime))
        for name in ('git', 'ffmpeg', 'ffprobe'):
            bundled = runtime / 'tools' / (name + ('.exe' if os.name == 'nt' else '')) if runtime else None
            resolved = str(bundled) if bundled and bundled.is_file() else shutil.which(name)
            if resolved:
                record['tools'][name] = str(Path(resolved).absolute())
        write_json(record_path, record)
        if not (root / '.env').exists():
            shutil.copyfile(root / '.env.example', root / '.env')
        if not args.skip_chrome:
            chrome_guidance(root, python)
        if owner and not args.register_only:
            current = json.loads(execute([python, root / 'scripts/service.py', 'status'], root=root, capture=True, timeout=30))
            action = 'restart' if current.get('running') else 'start'
        else:
            action = 'install'
        stage('注册并启动后台服务', lambda: execute([python, root / 'scripts/service.py', action, *(['--relocate'] if args.relocate and action == 'install' else [])], root=root, timeout=120))
        verification = stage('服务状态和健康检查', lambda: verify_service(root, python))
        record['verification'] = verification
        report = stage('媒体和浏览器能力检查', lambda: verify_capabilities(root, python, args.skip_chrome))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        record.update(status='complete' if report.get('ok', report.get('status') == 'ready') else 'degraded', report=report)
        record.pop('error', None)
        record.pop('nextAction', None)
        write_json(record_path, record)
        print('基础安装已完成。能力是否全部就绪请查看上方报告；安装记录：' + str(record_path), flush=True)
        return 0
    except Exception as exc:
        record.update(status='failed', error=str(exc), nextAction='修复错误后使用 --resume 或 Windows -Resume；不要删除原环境或配置。')
        write_json(record_path, record)
        raise
    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true')
    group.add_argument('--register-only', action='store_true')
    group.add_argument('--chrome-only', action='store_true')
    parser.add_argument('--resume', action='store_true', help='重新检查并复用已完成步骤；普通重跑同样安全')
    parser.add_argument('--skip-chrome', action='store_true')
    parser.add_argument('--relocate', action='store_true')
    args = parser.parse_args()
    try:
        return install(args)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('安装未完成：' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
