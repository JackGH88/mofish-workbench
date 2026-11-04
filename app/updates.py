"""Public release checks; legacy state and local restart coordination helpers."""
from __future__ import annotations
import asyncio
import contextlib
from http.client import HTTPException as HTTPProtocolError
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from .versioning import Repository, VersionError, version_key
from .runtime import DESKTOP, release_info, UPDATE_MESSAGE
from .release_feed import fetch_feed, upgrade_prompt

ACTIVE_PHASES = {'waiting', 'starting', 'installing', 'dependencies', 'restarting', 'verifying', 'recovering'}


def read_state(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_state(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


class FileLock:
    def __init__(self, path):
        self.path, self.file = Path(path), None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0)
        if self.file.read(1) == b'':
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            return False
        return True

    def release(self):
        if self.file:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


class UpdateManager:
    def __init__(self, root):
        self.root = Path(root)
        self.repo = Repository(root)
        self.current = release_info() if DESKTOP else self.repo.running()  # immutable identity of this process
        self.directory = self.root / 'workspace/system-update'
        self.state_path = self.directory / 'job.json'
        self.token = secrets.token_urlsafe(32)
        self.target = None
        self.checked_at = None
        self.last_successful_check_at = None
        self.last_check_attempt = None
        self.check_error = ''
        self._locks = {}
        self.waiter = None
        self.checker = None
        self.resume_task = None
        self.active_count = lambda: 0
        self.requests = 0
        self.schedulers = 0
        self.restart_manager = None

    def lock(self, name):
        loop = asyncio.get_running_loop()
        key = (loop, name)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def job(self):
        return read_state(self.state_path)

    @property
    def maintenance(self):
        return self.job().get('phase') in ACTIVE_PHASES or bool(self.restart_manager and self.restart_manager.maintenance)

    def view(self):
        current_key = version_key('v' + (self.current['version'] or ''))
        available = bool(not self.check_error and self.target and current_key is not None
                         and version_key(self.target['tag']) > current_key)
        return {'distribution': 'desktop' if DESKTOP else 'source',
                'updateMethod': 'download' if DESKTOP else 'instructions',
                'updateMessage': UPDATE_MESSAGE if DESKTOP else '请按升级步骤操作，或复制升级指令交给 Agent。',
                'current': {key: self.current.get(key) for key in ('version', 'development')},
                'latest': self.target, 'available': available,
                'checkedAt': self.checked_at, 'checkError': self.check_error,
                'lastSuccessfulCheckAt': self.last_successful_check_at,
                'upgradePrompt': upgrade_prompt(self.target) if not DESKTOP else ''}

    async def check(self, throttle=False):
        async with self.lock('check'):
            # Public check requests cannot cause unbounded upstream traffic.
            if throttle and self.last_check_attempt is not None and time.monotonic() - self.last_check_attempt < 30:
                return self.view()
            self.last_check_attempt = time.monotonic()
            try:
                feed = await asyncio.to_thread(fetch_feed)
                self.target = feed['desktop' if DESKTOP else 'source']
                if self.target:
                    self.target = dict(self.target, tag='v' + self.target['version'])
                self.check_error = ''
                self.last_successful_check_at = time.time()
            except (OSError, HTTPProtocolError, ValueError, KeyError, TypeError, AttributeError):
                self.check_error = '暂时无法检查，请稍后重试。'
            self.checked_at = time.time()
        return self.view()

    def service_ready(self):
        if DESKTOP:
            raise VersionError('请退出并重新打开墨鱼工作台，使插件变更生效。')
        script = self.root / 'scripts/service.py'
        interpreter = self.root / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        if sys.platform not in ('darwin', 'win32') or not script.exists() or not interpreter.exists():
            raise VersionError('请先通过本项目安装入口配置 macOS 或 Windows 后台服务及虚拟环境。')
        try:
            result = subprocess.run([str(interpreter), str(script), 'status'], capture_output=True,
                                    text=True, timeout=20)
            state = json.loads(result.stdout)
            if result.returncode or not state.get('registered') or not state.get('running') or not state.get('pageAccessible') or Path(state.get('project', '')).resolve() != self.root.resolve():
                raise ValueError()
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise VersionError('后台服务尚未正确注册到当前项目，无法安全自动重启。') from exc

    async def start(self):
        raise VersionError(UPDATE_MESSAGE if DESKTOP else '网页内更新已停用，请使用升级指引。')

    def cancel(self):
        raise VersionError('网页内更新已停用，请使用升级指引。')

    def recover_orphan(self):
        job = self.job()
        phase = job.get('phase')
        if phase not in ACTIVE_PHASES:
            return
        if phase == 'waiting' and self.waiter and not self.waiter.done():
            return
        if phase != 'waiting' and time.time() - job.get('updatedAt', 0) < 30:
            return
        lock = FileLock(self.directory / 'worker.lock')
        if lock.acquire():
            try:
                job.update(phase='failed', error='更新进程意外中断。请检查当前代码与后台服务状态后重试；本地资料已保留。', updatedAt=time.time())
                write_state(self.state_path, job)
            finally:
                lock.release()

    async def background(self):
        last_check = float('-inf')
        while True:
            self.recover_orphan()
            if not self.maintenance and time.monotonic() - last_check >= 1800:
                await self.check()
                last_check = time.monotonic()
            await asyncio.sleep(5)

    async def startup(self):
        self.recover_orphan()
        self.checker = asyncio.create_task(self.background())

    async def shutdown(self):
        for task in (self.checker, self.waiter, self.resume_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def authorize_local_operation(request, manager, write=False):
    parsed = urlsplit(str(request.url))
    if parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise HTTPException(403, '仅允许本机操作工作台。')
    if request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, '仅允许本机操作工作台。')
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != f'{parsed.scheme}://{parsed.netloc}':
        raise HTTPException(403, '不允许跨站操作工作台。')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '不允许跨站操作工作台。')
    if write and not secrets.compare_digest(request.headers.get('x-workbench-update-token', ''), manager.token):
        raise HTTPException(403, '操作令牌无效，请刷新页面。')


def attach_update_routes(app, manager):
    def authorize_read(request):
        parsed = urlsplit(str(request.url))
        origin = request.headers.get('origin')
        if ((origin and origin.rstrip('/') != f'{parsed.scheme}://{parsed.netloc}')
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            raise HTTPException(403, '不允许跨站检查工作台。')

    @app.get('/api/system/update/status')
    async def status(request: Request):
        authorize_read(request)
        return JSONResponse(manager.view(), headers={'Cache-Control': 'no-store'})

    @app.post('/api/system/update/{action}')
    async def action(action: str, request: Request):
        if action in {'start', 'cancel'}:
            raise HTTPException(410, '网页内更新已停用，请使用升级指引。')
        authorize_read(request)
        if action != 'check':
            raise HTTPException(404, '未知操作。')
        return JSONResponse(await manager.check(throttle=True), headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def maintenance_gate(request, call_next):
        path = request.url.path
        business = path.startswith('/api/') and not path.startswith(('/api/system/update/', '/api/system/restart/')) and path != '/api/health'
        restarting = bool(manager.restart_manager and manager.restart_manager.maintenance)
        update_active = manager.job().get('phase') in ACTIVE_PHASES
        if business and restarting and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return JSONResponse({'detail': '工作台正在等待重启或重启中，请稍后重试；等待期间可取消重启。'}, status_code=503)
        if business and update_active:
            return JSONResponse({'detail': '工作台正在等待更新或安装更新，请稍后重试；等待阶段可以取消更新。'}, status_code=503)
        # Account-scoped invalidations are reconnectable notifications, not work.
        # Keep maintenance gating, but never wait for this endless GET stream.
        tracked = business and not (path in {'/api/plugin-events', '/api/script-import/events'} and request.method == 'GET')
        if tracked:
            manager.requests += 1
        try:
            response = await call_next(request)
        except BaseException:
            if tracked:
                manager.requests -= 1
            raise
        if tracked:
            original = response.body_iterator
            async def complete_body():
                try:
                    async for chunk in original:
                        yield chunk
                finally:
                    manager.requests -= 1
            response.body_iterator = complete_body()
        return response

    app.add_event_handler('startup', manager.startup)
    app.add_event_handler('shutdown', manager.shutdown)
