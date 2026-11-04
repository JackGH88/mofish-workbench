"""Local service restart coordination; shares admission control with updates."""
from __future__ import annotations
import asyncio
import contextlib
import os
import subprocess
import sys
import time
import uuid
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from .updates import ACTIVE_PHASES, read_state, write_state, authorize_local_operation
from .versioning import VersionError
from .runtime import DESKTOP

ACTIVE = {'waiting', 'starting', 'restarting', 'verifying'}


class RestartManager:
    def __init__(self, update):
        self.update = update
        update.restart_manager = self
        self.root = update.root
        self.directory = self.root / 'workspace/system-restart'
        self.state_path = self.directory / 'job.json'
        self.instance_id = uuid.uuid4().hex
        self.waiter = None
        self.watcher = None
        self.plugin_blockers = lambda: []
        self.refresh_plugins = None
        self.pause_notifications = lambda: None
        self.resume_notifications = lambda: None
        self.notifications_paused = False

    def prepare_restart(self, job):
        stamp = time.time()
        job.update(stage='stopping', stageStartedAt=stamp, restartDeadline=stamp+120,
                   stageTimes={'stopRequestedAt': stamp}, message='正在停止服务…')
        self.pause_notifications()
        self.notifications_paused = True

    def restore_notifications(self):
        if self.notifications_paused:
            self.resume_notifications()
            self.notifications_paused = False

    def job(self):
        return read_state(self.state_path)

    @property
    def maintenance(self):
        return self.job().get('phase') in ACTIVE

    def view(self):
        job = self.job()
        if (DESKTOP and job.get('transport') == 'desktop'
                and job.get('phase') in {'starting', 'restarting'}
                and job.get('instanceId') != self.instance_id):
            job.update(phase='complete', newInstanceId=self.instance_id,
                       message='工作台已重启。', updatedAt=time.time())
            write_state(self.state_path, job)
        # Never leave admission closed forever after a lost worker or old waiter.
        if job.get('phase') in ACTIVE and (
            (job.get('phase') == 'waiting' and job.get('instanceId') != self.instance_id)
            or (job.get('phase') != 'waiting' and job.get('restartDeadline')
                and time.time() > job['restartDeadline'])
            or time.time() - job.get('updatedAt', time.time()) > 180
        ):
            job.update(phase='failed', error='重启操作中断或超时，请重新检查连接后重试。')
            write_state(self.state_path, job)
        if job.get('phase') not in ACTIVE:
            self.restore_notifications()
        return dict(job=job, instanceId=self.instance_id, operationToken=self.update.token,
                    transport='desktop' if DESKTOP else 'service',
                    desktopInstance=os.environ.get('MOFISH_INSTANCE', '') if DESKTOP else '')

    async def start(self, force=False):
        async with self.update.lock('start'):
            self.view()
            if self.maintenance:
                job = self.job()
                if force and job.get('phase') == 'waiting':
                    return self.launch_forced(job)
                return job
            if self.update.job().get('phase') in ACTIVE_PHASES:
                raise VersionError('工作台正在更新，请等待更新完成。')
            if not DESKTOP:
                await asyncio.to_thread(self.update.service_ready)
            elif not force:
                raise VersionError('请使用强制重启重新打开墨鱼工作台。')
            job = dict(id=uuid.uuid4().hex, phase='waiting', instanceId=self.instance_id,
                       startedAt=time.time(), updatedAt=time.time(), error='',
                       message='正在等待现有任务完成；等待期间可取消重启。')
            write_state(self.state_path, job)
            if force:
                return self.launch_forced(job)
            self.waiter = asyncio.create_task(self.drain(job['id']))
            return job

    async def force(self, job_id):
        async with self.update.lock('start'):
            if self.update.job().get('phase') in ACTIVE_PHASES:
                raise VersionError('工作台正在更新，请等待更新完成。')
            await asyncio.to_thread(self.update.service_ready)
            job = self.job()
            if job.get('id') != job_id or job.get('instanceId') != self.instance_id:
                raise VersionError('重启记录已变化，请重新检查后再确认。')
            if job.get('phase') in {'starting', 'restarting', 'verifying', 'complete'}:
                return job
            if job.get('phase') != 'waiting':
                raise VersionError('当前没有等待中的重启，请重新发起重启。')
            return self.launch_forced(job)

    def launch_forced(self, job):
        job.update(phase='starting', forced=True, updatedAt=time.time(),
                   transport='desktop' if DESKTOP else 'service',
                   message='正在强制重启工作台，恢复后将自动刷新…')
        self.prepare_restart(job)
        write_state(self.state_path, job)
        if self.waiter:
            self.waiter.cancel()
        try:
            if not DESKTOP:
                self.spawn_worker()
        except Exception as exc:
            job.update(phase='failed', error='无法启动重启，请重试。', updatedAt=time.time())
            write_state(self.state_path, job)
            self.restore_notifications()
            raise VersionError(job['error']) from exc
        return job

    def cancel(self):
        job = self.job()
        if job.get('phase') != 'waiting':
            raise VersionError('已经开始重启，不能取消。')
        job.update(phase='cancelled', message='已取消重启。', updatedAt=time.time())
        write_state(self.state_path, job)
        self.restore_notifications()
        return job

    async def drain(self, job_id):
        try:
            while True:
                job = self.job()
                if job.get('id') != job_id or job.get('phase') != 'waiting': return
                if self.refresh_plugins:
                    await self.refresh_plugins()
                blockers = await asyncio.to_thread(self.plugin_blockers)
                # Cancellation may happen while plugin hooks run off-thread.
                job = self.job()
                if job.get('id') != job_id or job.get('phase') != 'waiting': return
                count = self.update.active_count() + self.update.requests + self.update.schedulers
                if not count and not blockers:
                    job.update(phase='starting', message='正在重启工作台，恢复后将自动刷新…', updatedAt=time.time())
                    self.prepare_restart(job)
                    write_state(self.state_path, job)
                    self.spawn_worker()
                    return
                message = '；'.join(blockers[:3]) if blockers else f'等待 {count} 项正在执行的操作完成'
                job.update(message=message + '；等待期间可取消重启。', activeTasks=count, updatedAt=time.time())
                write_state(self.state_path, job)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            job = self.job()
            if job.get('id') == job_id and job.get('phase') in ACTIVE:
                job.update(phase='failed', error='无法安全启动重启，请检查后台服务日志后重试。', updatedAt=time.time())
                write_state(self.state_path, job)
                self.restore_notifications()

    def spawn_worker(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        kwargs = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        with (self.directory / 'worker.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(self.root / 'scripts/restart_workbench.py')],
                             cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=log,
                             stderr=log, close_fds=True, **kwargs)

    async def watch(self):
        while True:
            self.view()
            await asyncio.sleep(5)

    async def startup(self):
        self.view()
        self.watcher = asyncio.create_task(self.watch())

    async def shutdown(self):
        for task in (self.waiter, self.watcher):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError): await task


def attach_restart_routes(app, manager):
    @app.get('/api/system/restart/status')
    async def status(request: Request):
        authorize_local_operation(request, manager.update)
        return JSONResponse(manager.view(), headers={'Cache-Control':'no-store'})

    @app.post('/api/system/restart/{action}')
    async def action(action: str, request: Request):
        authorize_local_operation(request, manager.update, True)
        try:
            if action == 'start':
                raw = await request.body()
                try:
                    import json
                    payload = json.loads(raw) if raw else {}
                except ValueError:
                    raise HTTPException(400, '重启参数无效。') from None
                if not isinstance(payload, dict) or ('force' in payload and not isinstance(payload['force'], bool)):
                    raise HTTPException(400, '重启参数无效。')
                if payload.get('force') and payload.get('confirmed') is not True:
                    raise HTTPException(400, '请确认强制重启。')
                return await manager.start(force=payload.get('force', False))
            if action == 'native-failed':
                payload = await request.json()
                job = manager.job()
                if (not DESKTOP or not isinstance(payload, dict) or job.get('id') != payload.get('jobId')
                        or job.get('instanceId') != manager.instance_id or job.get('phase') != 'starting'):
                    raise HTTPException(409, '重启记录已变化。')
                job.update(phase='failed', error='无法启动桌面重启，请重试。', updatedAt=time.time())
                write_state(manager.state_path, job)
                return job
            if action == 'cancel': return manager.cancel()
            if action == 'force':
                try:
                    payload = await request.json()
                except ValueError:
                    raise HTTPException(400, '请确认强制重启。') from None
                if not isinstance(payload, dict) or payload.get('confirmed') is not True or not isinstance(payload.get('jobId'), str) or not payload['jobId']:
                    raise HTTPException(400, '请确认强制重启并提供当前重启记录。')
                return await manager.force(payload['jobId'])
            raise HTTPException(404, '未知操作。')
        except VersionError as exc:
            raise HTTPException(409, str(exc)) from exc

    app.add_event_handler('startup', manager.startup)
    app.add_event_handler('shutdown', manager.shutdown)
