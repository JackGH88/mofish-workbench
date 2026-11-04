"""Unified account recommendation orchestration; never collects or dissects videos."""
from __future__ import annotations
import asyncio
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .topic_recommendations import TopicRecommendationStore, merge_candidates, input_fingerprint, work_key
from .radar_ai import build_account_inputs
from .text_service import TextServiceError
from .subscription import points, SubscriptionError
from . import workbench, topic_recommendation_availability as availability

TZ = ZoneInfo('Asia/Shanghai')

class TopicRecommendationRuntime:
    def __init__(self, host):
        self.host = host
        self.jobs = {}
        self.waiting = {}

    @property
    def h(self):
        return self.host()

    @property
    def store(self):
        store = self.h.topic_recommendation_store
        workspace_dir = getattr(self.h.workspace_store,'_workspace_dir',store.path.parent)
        # Follow the workspace dependency when an isolated workspace is mounted.
        return store if workspace_dir == store.path.parent else TopicRecommendationStore(workspace_dir)

    def ensure(self, account):
        settings = [self.h.monitor_store.get_settings(), self.h.radar_store.get_settings()]
        active = [s for s in settings if s.get('aiEnabled', True)]
        custom_times = [s['aiDailyTime'] for s in active if s.get('aiDailyTime') and s['aiDailyTime'] != '10:30']
        return self.store.ensure_account(account,
            self.h.monitor_store.get_recommendation(account), self.h.radar_store.get_recommendation(account),
            {'aiEnabled': bool(active), 'aiDailyTime': min(custom_times, default='10:30'),
             'sources': {'monitor': True, 'radar': True}})

    def works(self, account):
        merged = {}
        for origin in ('monitor', 'radar'):
            store = getattr(self.h, origin + '_store')
            with store._lock:
                data = store._read()
                allowed = set(store.account_blogger_ids(account) if origin == 'monitor' else store.account_keyword_ids(account))
                for raw in data.get('works', {}).values():
                    own = [v for k,v in (raw.get('sources') or {}).items() if k in allowed] if origin == 'radar' else []
                    if (origin == 'monitor' and raw.get('bloggerId') not in allowed) or (origin == 'radar' and not own):
                        continue
                    row = store.work_view(data, raw, account_id=account)
                    row.pop('publishedText', None)
                    row.pop('isNew', None)
                    row.update(accountId=account, platform=raw.get('platform') or 'douyin', snapshots=deepcopy(raw.get('snapshots') or []))
                    row['authorName'] = row.get('authorName') or row.get('bloggerName') or ''
                    row['originalId'] = str(raw['id'])
                    row['id'] = work_key(row)
                    row['saved'] = bool((data.get('accounts',{}).get(account,{}).get('actions',{}).get(str(raw['id']),{}) or {}).get('saved')) if origin == 'radar' else str(raw['id']) in (data.get('accounts',{}).get(account,{}).get('saves') or {})
                    row['source'] = origin
                    if own:
                        row['discoveredAt'] = min((v.get('firstSeenAt') or '' for v in own), default='')
                        row['imported'] = all(v.get('imported', False) for v in own)
                    row['sourceRecords'] = [{'source': origin, 'id': str(raw['id'])}]
                    row['sources'] = [origin]
                    previous = merged.get(row['id'])
                    if previous:
                        discovered = min((v for v in [previous.get('discoveredAt'),row.get('discoveredAt')] if v),default='')
                        keywords = list(dict.fromkeys((previous.get('keywords') or []) + (row.get('keywords') or [])))
                        saved = previous.get('saved') or row.get('saved')
                        historical = bool(previous.get('baseline') or previous.get('imported') or row.get('baseline') or row.get('imported'))
                        records = previous['sourceRecords'] + row['sourceRecords']
                        sources = previous['sources'] + row['sources']
                        if str(previous.get('statsUpdatedAt') or '') > str(row.get('statsUpdatedAt') or ''):
                            row = previous
                        row['sourceRecords'], row['sources'] = records, sources
                        row.update(discoveredAt=discovered,keywords=keywords,saved=bool(saved),baseline=historical)
                    merged[row['id']] = row
        return sorted(merged.values(), key=lambda w: str(w.get('discoveredAt') or ''), reverse=True)

    def prepare(self, account):
        view = self.ensure(account)
        all_works = self.works(account)
        selected = view['settings'].get('sources') or {'monitor': True, 'radar': True}
        excluded = set(view.get('dismissed') or [])
        topics = self.h.workspace_store.list_topics(account)
        for topic in topics.get('items',[]):
            source = topic.get('sourceWork') or {}
            if source.get('id'):
                excluded.add(work_key(source))
            for source_id in topic.get('sourceWorkIds') or []:
                if source_id:
                    excluded.add(work_key({'id': source_id, 'platform': source.get('platform') or 'douyin'}))
            for source_id in self.h.workspace_store._source_link_ids(topic.get('materials') or ''):
                excluded.add('douyin:' + source_id)
        eligible = [w for w in all_works if w['id'] not in excluded and any(selected.get(origin,True) for origin in w['sources'])]
        selection_stats = {}
        works = merge_candidates(*[[w for w in eligible if origin in w['sources']] if selected.get(origin, True) else [] for origin in ('monitor','radar')], account_id=account, selection_stats=selection_stats)
        # Only reuse content owned by this account and joined by exact video identity.
        breakdowns = self.h.workspace_store.list_breakdowns(account)['items']
        content_budget = 120000
        for w in works:
            w['analysisScope'] = '基于标题及指标'
            source_id = w['id'].split(':',1)[-1]
            for record in breakdowns:
                ids = self.h.workspace_store._source_link_ids(record.get('shareText') or '')
                if source_id not in ids or record.get('accountId') != account:
                    continue
                if record.get('analysisStatus') in ('completed', 'complete', 'succeeded') and record.get('analysis'):
                    w['analysis'] = record['analysis']
                    w['analysisScope'] = '基于已有拆解内容、标题及指标'
                try:
                    task = self.h.task_store.workspace(record['taskId'])
                    transcript = task.get('transcript') or ''
                    if transcript:
                        limit = min(6000,content_budget)
                        w['transcript'] = str(transcript)[:limit]
                        content_budget -= len(w['transcript'])
                        w['transcriptTruncated'] = len(str(transcript)) > limit
                        w['analysisScope'] = '基于已有转写摘录、标题及指标' if w['transcript'] else w['analysisScope']
                except (KeyError, ValueError, FileNotFoundError):
                    pass
        inputs = build_account_inputs(account, self.h.workspace_store, self.h.review_store)
        if self.collecting(account):
            inputs['review']['gaps'].append('部分采集任务仍未完成，本轮仅使用已完成的数据。')
        profile = self.h.workspace_store.read_account_profile(account)
        context = {**inputs, 'account': {'id': account, 'profile': profile}, 'works': works,
                   'recommendationMode': 'content-topic-v1', 'generateEvidence': False,
                   'trends': [{k:v for k,v in row.items() if k != 'updatedText'} for row in self.h.radar_store.trend_rows(account)[:40]] if selected.get('radar',True) else [],
                   'plans': topics.get('plans') or {}, 'topics': topics.get('items') or [],
                   'feedback': {'dismissed': sorted(excluded)}, 'sources': selected,
                   'candidateSelection': selection_stats}
        return {'context': context, 'inputFingerprint': input_fingerprint(context)}

    def overview(self, account):
        view = self.ensure(account)
        # Prepared prompts/task IDs remain private; GET only reads/migrates local state.
        for row in view.get('items',[]) + view.get('history',[]):
            if row.get('sourceWork'):
                adopted = self.h.workspace_store.find_topic_for_source(account,row['sourceWork'])
                if adopted:
                    row['topicId'] = adopted['id']
        job = view.get('job') or {}
        view['job'] = {k:v for k,v in job.items() if k not in ('prepared','taskId')}
        profile = self.h.workspace_store.read_account_profile(account)
        reviews = build_account_inputs(account, self.h.workspace_store, self.h.review_store)['review']
        view['summary'] = {'positioning': profile.get('businessPositioning') or profile.get('contentDirection') or '' if isinstance(profile,dict) else str(profile),
                           'audience': profile.get('targetAudience') or '' if isinstance(profile,dict) else '',
                           'reviewCount': reviews['total'], 'week': '结合本周计划与已加入选题生成'}
        view['summary']['setup'] = {
            'profileReady': isinstance(profile, dict) and all(
                str(profile.get(key) or '').strip() and '【待完善】' not in str(profile.get(key))
                for key in ('businessPositioning', 'targetAudience')),
            'keywordCount': len(self.h.radar_store.account_keyword_ids(account)),
            'bloggerCount': len(self.h.monitor_store.account_blogger_ids(account)),
            'workCount': len(self.works(account)),
        }
        view['analysis'] = view.get('analysis') or {'gaps': reviews['gaps']}
        return view

    def notice_view(self, view, account):
        """Presentation only: never overwrite the original task error/recovery state."""
        job = view['job']
        code = job.get('errorCode') or ''
        message = str(job.get('error') or '')
        if not code and message in {'积分不足，请先订阅套餐。', '积分不足，请先订阅。'}:
            code = 'insufficient_points'
        if job.get('status') == 'unconfirmed':
            code, message = 'status_pending', '上次任务状态待确认，暂时无法更新，已有推荐已保留'
        if code == 'insufficient_points':
            message = '积分不足，请订阅积分套餐'
        view.update(notice=message, noticeCode=code, noticeAction='subscribe' if code in {
            'insufficient_points', 'subscription_required', 'subscription_expired'} else '')
        task = self.jobs.get(account)
        if task and not task.done() and job.get('status') not in ('running', 'pending'):
            view['job'] = {**job, 'status': 'checking'}
        return view

    async def overview_with_notice(self, account, *, check_cost=False):
        """Check current rights independently of historical errors; never submit paid work."""
        view = self.notice_view(await self.h.run_io(self.overview, account), account)
        job = view['job']
        try:
            service = self.h._subscription_service()
            if not service.session_view().get('loggedIn'):
                return view
            owner = service.payment_owner()
            balance = await service.balance()
            available = points(balance.get('available'))
            code, message = '', ''
            if 'available' not in balance:
                raise ValueError('Missing available points')
            if available <= 0:
                code, message = 'insufficient_points', '积分已用完，请订阅积分套餐'
            elif check_cost or view['noticeCode'] == 'insufficient_points':
                try:
                    quoted = await workbench.quote_with_retry(service.business_client(),
                        workbench.text_spec('radar_topics'), workbench.SPEC_TEXT_QUANTITY)
                    if 'pointsAmount' not in quoted:
                        raise ValueError('Missing quote amount')
                    if available < points(quoted['pointsAmount']):
                        code, message = 'insufficient_points', '积分不足，请订阅积分套餐'
                except SubscriptionError as exc:
                    if exc.code not in {'insufficient_points', 'subscription_required', 'subscription_expired'}:
                        raise
                    code = exc.code
                    message = '积分不足，请订阅积分套餐' if code == 'insufficient_points' else exc.message
            latest = self.notice_view(await self.h.run_io(self.overview, account), account)
            if latest['job'] != job or service.payment_owner() != owner or not service.session_view().get('loggedIn'):
                if check_cost:
                    latest.update(notice='状态已变化，请重新点击更新推荐。', noticeCode='state_changed', noticeAction='')
                return latest
            if code:
                latest.update(notice=message, noticeCode=code, noticeAction='subscribe')
            elif latest['noticeCode'] in {'insufficient_points', 'subscription_required', 'subscription_expired'}:
                latest.update(notice='', noticeCode='', noticeAction='')
            return latest
        except Exception:
            self.h.logger.warning('topic_recommendation_notice_unavailable')
            if check_cost:
                view.update(notice='暂时无法检查积分或订阅状态，请稍后重试。', noticeCode='entitlements_unavailable', noticeAction='')
            return view

    async def start(self, account, trigger='manual'):
        availability.require_available()
        # No await before registering the task: concurrent manual/scheduler calls share one job.
        running = self.jobs.get(account)
        if running and not running.done():
            return 'running'
        self.ensure(account)
        task = asyncio.create_task(self.run(account, trigger))
        self.jobs[account] = task
        task.add_done_callback(lambda done: self.jobs.pop(account, None) if self.jobs.get(account) is done else None)
        return 'started'

    async def run(self, account, trigger):
        if availability.TOPIC_RECOMMENDATIONS_PAUSED:
            return
        h = self.h
        transport_started = False
        try:
            # Already submitted legacy work must settle before starting a new paid request.
            for registry in (h._monitor_ai_jobs, h._radar_ai_jobs):
                old = registry.get(account)
                if old and not old.done():
                    await asyncio.shield(old)
            legacy = await h.run_io(h.monitor_store.get_recommendation, account)
            if legacy.get('status') == 'pending':
                recovery = await h.run_io(h.monitor_store.recommendation_recovery,account)
                if not recovery.get('taskId'):
                    self.store.set_job(account,'blocked',error='旧任务缺少可恢复的任务信息，已保留历史结果，避免重复收费。')
                    return
                await h._run_monitor_recommendation(account, trigger='reconcile')
                legacy = await h.run_io(h.monitor_store.get_recommendation, account)
            radar_legacy = await h.run_io(h.radar_store.get_recommendation, account)
            radar_job = radar_legacy.get('job') or radar_legacy
            if legacy.get('status') in ('pending', 'unconfirmed', 'running') or radar_job.get('status') in ('pending', 'unconfirmed', 'running') or radar_job.get('errorCode') == 'status_pending':
                self.store.set_job(account, 'blocked', error='旧推荐任务尚未确认，确认完成后再更新。')
                return
            await h.run_io(self.store.archive_legacy, account, legacy, radar_legacy)
            view = self.ensure(account)
            job = view.get('job') or {}
            recovery = job.get('status') in ('pending','running','unconfirmed')
            if recovery and not job.get('taskId'):
                self.store.set_job(account, 'unconfirmed')
                return
            prepared = job.get('prepared') if recovery else None
            if recovery and not prepared:
                self.store.set_job(account,'unconfirmed',error='原任务输入快照缺失，已保留旧结果，避免重复提交。')
                return
            prepared = prepared or await h.run_io(self.prepare, account)
            context = prepared['context']
            if not recovery:
                skip = ('当前没有合适的未选参考作品。' if not context['works'] else
                        '输入未变化，已保留上次结果。' if prepared['inputFingerprint'] == view.get('inputFingerprint') else '')
                if skip:
                    self.store.set_job(account,'skipped',error=skip,lastAttemptDay=datetime.now(TZ).date().isoformat())
                    return
            self.store.set_job(account,'running',error='',prepared=prepared, taskId=job.get('taskId','') if recovery else '',lastAttemptDay=datetime.now(TZ).date().isoformat())
            client = h._text_service_client()
            async def remember(task_id):
                await h.run_io(self.store.set_job, account, 'running', taskId=task_id, prepared=prepared)
            async def transport(**kwargs):
                nonlocal transport_started
                transport_started = True
                return await workbench.generate_text_result(h._workbench_service(), **kwargs,
                    resume_task_id=job.get('taskId','') if recovery else '',on_created=remember)
            client._platform = transport
            client.business_context = await h._business_context('topic_recommendations',account_id=account,trigger=trigger)
            items = await client.suggest_topic_recommendations(context)
            await h.run_io(self.store.save, account, items, prepared)
            self.store.set_job(account,'succeeded',completedDay=datetime.now(TZ).date().isoformat(),taskId='',error='')
        except asyncio.CancelledError:
            raise
        except TextServiceError as exc:
            job = self.store.get(account).get('job') or {}
            ambiguous = exc.code == 'status_pending' or any(word in exc.code for word in ('timeout','unavailable','network','connection','upstream'))
            status = ('pending' if job.get('taskId') else 'unconfirmed') if ambiguous and (transport_started or job.get('taskId')) else 'failed'
            self.store.set_job(account,status,error=exc.message,errorCode=exc.code)
        except Exception as exc:
            h.logger.exception('topic_recommendation_failed account=%s',account)
            job = self.store.get(account).get('job') or {}
            status = ('pending' if job.get('taskId') else 'unconfirmed') if transport_started and not isinstance(exc, ValueError) else 'failed'
            self.store.set_job(account,status,error='本次结果尚未确认，已保留旧建议。' if status != 'failed' else str(exc)[:300])

    def collecting(self, account):
        h = self.h
        bloggers = set(h.monitor_store.account_blogger_ids(account))
        keywords = set(h.radar_store.account_keyword_ids(account))
        return any(not t.done() for k,t in h._monitor_jobs.items() if k in bloggers) or any(not t.done() for k,t in h._radar_jobs.items() if k in keywords)

    async def schedule(self, now=None):
        if availability.TOPIC_RECOMMENDATIONS_PAUSED:
            return
        h = self.h
        if not h._workbench_ready():
            return
        moment = now or datetime.now(TZ)
        for account in await h.run_io(h.workspace_store.list_accounts):
            aid = str(account['id'])
            view = await h.run_io(self.ensure, aid)
            job, settings = view['job'], view['settings']
            legacy = await h.run_io(h.monitor_store.get_recommendation, aid)
            if (job.get('status') in ('pending','running') or legacy.get('status') == 'pending') and aid not in self.jobs:
                await self.start(aid, 'reconcile')
                continue
            if not settings.get('aiEnabled') or moment.strftime('%H:%M') < settings.get('aiDailyTime','10:30'):
                continue
            if job.get('completedDay') == moment.date().isoformat() or job.get('lastAttemptDay') == moment.date().isoformat():
                continue
            if self.collecting(aid):
                since = self.waiting.setdefault(aid, moment)
                if moment - since < timedelta(minutes=10):
                    continue
            self.waiting.pop(aid,None)
            await self.start(aid,'schedule')

    async def stop(self):
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
