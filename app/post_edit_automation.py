"""Durable, opt-in post-edit pipeline. All paid submission intents are saved first."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import uuid

LOGGER = logging.getLogger(__name__)
TERMINAL = {'completed', 'failed', 'paused'}
MESSAGES = {'title': '正在生成标题', 'prompt': '正在生成提示词与参考帧',
            'covers': '正在生成 3:4、4:3 封面', 'completed': '标题和封面已生成，待确认',
            'failed': '自动生成失败，可手动处理', 'paused': '内容已修改，自动流程已暂停'}
CONFLICT = '标题、提示词、参考图或关联视频已修改，自动流程已暂停，请手动继续。'


def snapshot(script):
    cover = script.get('coverState') or {}
    return json.dumps({'accountId': script.get('accountId'), 'title': script.get('title'), 'content': script.get('content'),
                      'source': script.get('source'), 'titleState': script.get('titleState'),
                      'prompt': cover.get('prompt', ''), 'images': cover.get('uploadedImages', []),
                      'ratio': cover.get('ratio', 'both'),
                      'publishAssets': script.get('publishAssets')},
                     ensure_ascii=False, sort_keys=True)


def owner(script, job_id):
    return next((state for state in (script.get('postEditAutomations') or {}).values()
                 if job_id and job_id in [state.get(k) for k in ('titleJobId', 'promptJobId', 'coverJobId')]), None)


def allowed(script, job_id, store=None, *, recover_output=False):
    state = owner(script, job_id)
    if state is None:
        return True
    if state.get('stage') in TERMINAL and not (recover_output and state['stage'] in {'completed', 'failed'}):
        return False
    changed = state.get('expected') != snapshot(script)
    if store is not None:
        try:
            stat = store.resolve_publish_asset_path(script['id'], script['publishAssets']['video']['path']).stat()
            changed = changed or state.get('videoStamp') != [stat.st_size, stat.st_mtime_ns]
        except (OSError, ValueError, KeyError):
            changed = True
    if changed:
        state.update(stage='paused', error=CONFLICT)
        return False
    return True


def accepted(script, job_id, **fields):
    state = owner(script, job_id)
    if state is not None:
        state.update(expected=snapshot(script), **fields)


def pause(script, message=CONFLICT):
    for state in (script.get('postEditAutomations') or {}).values():
        if state.get('stage') not in TERMINAL:
            state.update(stage='paused', error=message)


class PostEditAutomation:
    def __init__(self, host):
        self.host = host
        self.store = host.workspace_store
        self.tasks = {}

    def public(self, state):
        return {**{key: state.get(key, '') for key in
                   ('stage', 'error', 'resultId', 'titleJobId', 'promptJobId', 'coverJobId')},
                'message': '已结束等待，后续生成已停止' if state.get('stoppedByUser') else MESSAGES.get(state.get('stage'), ''),
                'failedStage': state.get('failedStage') or ('covers' if state.get('coverJobId') else 'prompt' if state.get('promptJobId') or state.get('titleDone') else 'title') if state.get('stage') == 'failed' else '',
                'failedAspects': state.get('failedAspects', []),
                'stoppedByUser': state.get('stoppedByUser') is True}

    def _write(self, sid, script):
        self.store._write_json(self.store._script_path(sid), script)

    def _state(self, sid, schedule_id):
        return self.store.get_script(sid)['postEditAutomations'][schedule_id]

    def _change(self, sid, schedule_id, **fields):
        with self.store._lock:
            script = self.store.get_script(sid)
            state = script['postEditAutomations'][schedule_id]
            # Never turn a user conflict into an ordinary generation failure.
            if state.get('stage') == 'paused':
                return state
            if fields.get('stage') == 'failed' and state.get('stage') in ('title', 'prompt', 'covers'):
                fields.setdefault('failedStage', state['stage'])
            state.update(fields)
            self._write(sid, script)
            return state

    def _check(self, script, state):
        if state.get('stage') in TERMINAL:
            return False
        if state.get('expected') != snapshot(script):
            state.update(stage='paused', error=CONFLICT)
            return False
        # Detect same-path video replacements too. Cover synchronization copies
        # the video with copy2, preserving size/mtime; inode is intentionally ignored.
        try:
            video = script['publishAssets']['video']
            stat = self.store.resolve_publish_asset_path(script['id'], video['path']).stat()
            if state.get('videoStamp') != [stat.st_size, stat.st_mtime_ns]:
                state.update(stage='paused', error=CONFLICT)
                return False
        except (OSError, ValueError, KeyError):
            state.update(stage='paused', error='关联视频已丢失或变更，请手动继续。')
            return False
        return True

    def _valid(self, sid, schedule_id):
        with self.store._lock:
            script = self.store.get_script(sid)
            state = script['postEditAutomations'][schedule_id]
            valid = self._check(script, state)
            if not valid:
                self._write(sid, script)
            return valid

    def stop_schedule(self, account_id, sid, schedule_id, result_id):
        """Persist a stop tombstone before acknowledging; never cancel upstream work."""
        with self.store._lock:
            script = self.store.get_script(sid)
            if script.get('accountId') != account_id:
                raise ValueError('脚本不属于当前账号。')
            states = script.setdefault('postEditAutomations', {})
            state = states.setdefault(schedule_id, {'resultId': result_id})
            if state.get('resultId') != result_id:
                raise ValueError('任务关联成片已变更，请刷新后重试。')
            # Existing material is left untouched; late outputs cannot overwrite it.
            state.update(stage='paused', stoppedByUser=True,
                         error='已结束等待，不再启动后续生成步骤。已提交的平台请求可能仍会完成。')
            self._write(sid, script)
            if state.get('titleJobId') and not state.get('titleDone'):
                self.store.fail_title_generation(sid, state['titleJobId'], code='stopped_by_user', message=state['error'])
            if state.get('promptJobId') and not state.get('promptDone'):
                self.store.fail_cover_title_generation(sid, state['promptJobId'], code='stopped_by_user', message=state['error'])
            # Do not mark in-flight image submissions failed: their accepted IDs
            # must still be persisted for reconciliation, without submitting more.
            return self.public(state)

    async def ensure(self, account_id, sid, schedule_id, result_id):
        with self.store._lock:
            script = self.store.get_script(sid)
            if script.get('accountId') != account_id:
                raise ValueError('脚本不属于当前账号。')
            states = script.setdefault('postEditAutomations', {})
            state = states.get(schedule_id)
            if state is None:
                # An older pending workflow may not overwrite a newer return.
                pause(script, '新的视频制作任务已回传，旧自动流程已暂停。')
                video = (script.get('publishAssets') or {}).get('video') or {}
                stat = self.store.resolve_publish_asset_path(sid, video.get('path', '')).stat()
                state = states[schedule_id] = {
                    'stage': 'title', 'error': '', 'resultId': result_id,
                    'expected': snapshot(script), 'videoStamp': [stat.st_size, stat.st_mtime_ns],
                }
                self._write(sid, script)
            if state['resultId'] != result_id:
                return self.public(state)  # one run per schedule, even for repeated/new return files
            key = (sid, schedule_id)
            if state['stage'] not in TERMINAL and (key not in self.tasks or self.tasks[key].done()):
                task = asyncio.create_task(self._run(sid, schedule_id))
                self.tasks[key] = task
                task.add_done_callback(lambda done: self.tasks.pop(key, None) if self.tasks.get(key) is done else None)
            return self.public(state)

    async def _run(self, sid, schedule_id):
        try:
            if not self._valid(sid, schedule_id):
                return
            state = self._state(sid, schedule_id)
            if state['stage'] == 'title':
                await self._title(sid, schedule_id)
            if not self._valid(sid, schedule_id):
                return
            if self._state(sid, schedule_id)['stage'] == 'prompt':
                await self._prompt(sid, schedule_id)
            if not self._valid(sid, schedule_id):
                return
            if self._state(sid, schedule_id)['stage'] == 'covers':
                await self._covers(sid, schedule_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception('post_edit_automation_failed script=%s schedule=%s', sid, schedule_id)
            detail = getattr(exc, 'detail', None)
            message = detail.get('message') if isinstance(detail, dict) else str(exc)
            message = message or '自动生成失败，请手动继续。'
            self._valid(sid, schedule_id)
            state = self._state(sid, schedule_id)
            if state.get('titleJobId'):
                self.store.fail_title_generation(sid, state['titleJobId'], code='post_edit_failed', message=message)
            if state.get('promptJobId'):
                self.store.fail_cover_title_generation(sid, state['promptJobId'], code='post_edit_failed', message=message)
            self._change(sid, schedule_id, stage='failed', error=message)

    async def _title(self, sid, schedule_id):
        host = self.host
        with self.store._lock:
            script = self.store.get_script(sid)
            state = script['postEditAutomations'][schedule_id]
            if state.get('titleDone'):
                self._change(sid, schedule_id, stage='prompt')
                return
            if state.get('titleJobId'):
                # Text requests have no queryable upstream task. Never replay.
                error = (script.get('titleGeneration') or {}).get('error') or {}
                raise ValueError(error.get('message') or '标题生成中断，未自动重试，请手动生成。')
            source = host._title_generation_input(script)
            if not source:
                raise ValueError('标题和话题尚未准备好。')
            job = uuid.uuid4().hex
            state['titleJobId'] = job
            self._write(sid, script)
            self.store.start_title_generation(sid, job)
        business_context = await host._script_business_context(script, 'generate_title')
        if not self._valid(sid, schedule_id):
            return
        await host.run_title_generation_job(sid, job, title=source[0], topics=source[1],
            system_prompt=host.load_settings().title_rewrite_system_prompt, business_context=business_context)
        if not self._valid(sid, schedule_id):
            return
        state = self._state(sid, schedule_id)
        if not state.get('titleDone'):
            error = (self.store.get_script(sid).get('titleGeneration') or {}).get('error') or {}
            raise ValueError(error.get('message') or '标题生成失败，已保留现有结果。')
        self._change(sid, schedule_id, stage='prompt')

    async def _prompt(self, sid, schedule_id):
        host = self.host
        state = self._state(sid, schedule_id)
        if state.get('promptDone'):
            self._change(sid, schedule_id, stage='covers')
            return
        if state.get('promptJobId'):
            raise ValueError('封面提示词生成中断，未自动重试，请手动生成。')
        extracted = await host.cover_reference_from_video(sid)
        ref = extracted.get('reference')
        if not ref:
            raise ValueError('未能从本次回传视频提取参考帧，未提交封面生成。')
        with self.store._lock:
            if not self._valid(sid, schedule_id):
                return
            script = self.store.get_script(sid)
            cover = copy.deepcopy(script.get('coverState') or {})
            images = [image for image in cover.get('uploadedImages', []) if image.get('source') != 'publish-video']
            if len(images) >= 10:
                raise ValueError('已有 10 张手动参考图，请删除一张后手动生成。')
            names = {image.get('name') for image in images}
            base = ref['name']
            suffix = 2
            while ref['name'] in names:
                ref['name'] = f'{base} {suffix}'
                suffix += 1
            images.append(ref)
            cover.update(uploadedImages=images, activeImageId=ref['id'], ratio='both', generatedReference='upload')
            script['coverState'] = cover
            state = script['postEditAutomations'][schedule_id]
            state.update(expected=snapshot(script), referenceId=ref['id'])
            title = host._cover_title_source(script)
            if not title:
                raise ValueError('新标题尚未准备好，未提交封面生成。')
            job = uuid.uuid4().hex
            state['promptJobId'] = job
            self._write(sid, script)
            self.store.start_cover_title_generation(sid, job, reference_id=ref['id'])
        host._register_cover_title_job(host.CoverTitleJobRecord(job_id=job, script_id=sid))
        business_context = await host._script_business_context(script, 'generate_cover_title')
        if not self._valid(sid, schedule_id):
            return
        await host.run_cover_title_job(job, title, business_context=business_context)
        if not self._valid(sid, schedule_id):
            return
        if not self._state(sid, schedule_id).get('promptDone'):
            error = (self.store.get_script(sid).get('coverTitleGeneration') or {}).get('error') or {}
            raise ValueError(error.get('message') or '封面提示词生成失败，未提交封面生成。')
        self._change(sid, schedule_id, stage='covers')

    async def _covers(self, sid, schedule_id):
        host = self.host
        with self.store._lock:
            if not self._valid(sid, schedule_id):
                return
            script = self.store.get_script(sid)
            state = script['postEditAutomations'][schedule_id]
            job = state.get('coverJobId')
            fresh = not job
            if fresh:
                current = self.store.get_cover_generation(sid)
                if current and current['status'] == 'running':
                    raise ValueError('已有封面正在生成，自动流程已停止，请手动处理。')
                cover = script.get('coverState') or {}
                prompt = str(cover.get('prompt') or '').strip()
                images = cover.get('uploadedImages') or []
                ref = next((i for i in images if i.get('id') == state.get('referenceId')), None)
                if not prompt or not ref or ref.get('sourceVideoPath') != script['publishAssets']['video']['path']:
                    raise ValueError('提示词或本次视频参考帧缺失，未提交封面生成。')
                paths = host._cover_reference_paths([i['url'] for i in images])
                # Match the manual button's named-reference conversion.
                for index, image in enumerate(images, 1):
                    prompt = re.sub(r'@' + re.escape(image['name']) + r'（第\d+张参考图）', f'第{index}张参考图', prompt)
                job = uuid.uuid4().hex
                state['coverJobId'] = job
                self._write(sid, script)
                self.store.start_cover_generation(sid, job, ['3:4', '4:3'])
        existing = host._cover_generation_tasks.get(job)
        if existing and not existing.done():
            return
        if fresh:
            # Register before yielding, so page polling cannot interrupt an
            # unsubmitted ratio while the automation is still submitting it.
            async def submit():
                business_context = await host._script_business_context(script, 'generate_cover')
                if not self._valid(sid, schedule_id):
                    self.store.interrupt_unsubmitted_cover_aspects(sid, job)
                    return
                await host.run_persisted_cover_generation(sid, job, prompt, paths, host.load_settings(),
                    business_context=business_context)
            worker = asyncio.create_task(submit())
        else:
            worker = asyncio.create_task(host.resume_cover_generation(sid, job))
        host._cover_generation_tasks[job] = worker
        try:
            await worker
        finally:
            if host._cover_generation_tasks.get(job) is worker:
                host._cover_generation_tasks.pop(job, None)
        if not self._valid(sid, schedule_id):
            return
        generation = self.store.get_cover_generation(sid, job)
        if not generation:
            raise ValueError('封面任务状态已变更，未自动重新提交。')
        if generation['status'] == 'running':
            return  # query/download transient failure: next tick resumes same task IDs
        failed = [item['aspect'] for item in generation['aspects'] if item['status'] != 'success']
        if len(generation['aspects']) != 2 or failed:
            timeout = any((item.get('error') or {}).get('code') == 'image_generation_timeout'
                          for item in generation['aspects'])
            self._change(sid, schedule_id, stage='failed', failedAspects=failed,
                         error=('封面生成超过 30 分钟。' if timeout else '') + f'{"、".join(failed) or "部分"} 封面未生成成功，已保留原有及成功结果。' + ' '.join(f"{item['aspect']}：{str((item.get('error') or {}).get('message') or '')[:300]}" for item in generation['aspects'] if item['status'] != 'success' and (item.get('error') or {}).get('message')))
        else:
            self._change(sid, schedule_id, stage='completed', error='')

    async def stop(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
