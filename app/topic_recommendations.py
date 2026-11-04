"""Account-isolated recommendation snapshots and pure, evidence-bound AI inputs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from threading import RLock

from .recommendation_quality import enrich_performance, rank_recommendations

_LOCK = RLock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def work_key(work):
    """Identity is platform + provider work id, never collection source."""
    ident = str(work.get('sourceWorkId') or work.get('workId') or work.get('id') or '').strip()
    platform = str(work.get('platform') or 'douyin').strip().lower()
    while ident.startswith(('monitor:', 'radar:')):
        ident = ident.split(':', 1)[1]
    for prefix in ('douyin:', 'channels:', 'tiktok:'):
        if ident.startswith(prefix):
            platform, ident = ident.split(':', 1)
            break
    if not ident:
        raise ValueError('作品缺少 ID')
    return f'{platform}:{ident}'


def merge_candidates(monitor_works, radar_works, *, account_id=None, now=None, selection_stats=None):
    moment = now or datetime.now(timezone.utc)
    tz = ZoneInfo("Asia/Shanghai")
    first_day = moment.astimezone(tz).date() - timedelta(days=6)
    candidates = {}
    discovered_dates = {}
    queues = {}
    for source, rows in (('monitor', monitor_works), ('radar', radar_works)):
        queue = []
        for raw in rows:
            if account_id and raw.get('accountId') and str(raw['accountId']) != str(account_id):
                continue
            if raw.get('kind', 'video') != 'video':
                continue
            row = deepcopy(raw)
            discovered = row.get('discoveredAt') or row.get('firstSeenAt')
            try:
                date = datetime.fromisoformat(str(discovered).replace('Z', '+00:00'))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                if date > moment or date.astimezone(tz).date() < first_day:
                    continue
            except (ValueError, TypeError):
                continue
            key = work_key(row)
            row.update(id=key, sourceWorkId=key,
                       publishedAt=row.get('publishedAt') or row.get('publishedAtIso'),
                       firstSeenAt=row.get('firstSeenAt') or discovered,
                       windowDays=7,
                       hotEligible=not bool(row.get('baseline') or row.get('imported') or row.get('isBaseline')))
            discovered_dates[key] = min(discovered_dates.get(key, date), date)
            row.pop('sources', None)
            row.pop('quarantinedSources', None)
            previous = candidates.get(key)
            if previous:
                sources = sorted(set(previous['sources']) | {source})
                first_seen = min(str(previous['firstSeenAt']), str(row['firstSeenAt']))
                hot_eligible = previous['hotEligible'] and row['hotEligible']
                if str(row.get('statsUpdatedAt') or row.get('collectedAt') or '') > str(previous.get('statsUpdatedAt') or previous.get('collectedAt') or ''):
                    candidates[key] = row
                candidates[key].update(sources=sources, firstSeenAt=first_seen, hotEligible=hot_eligible)
            else:
                row['sources'] = [source]
                candidates[key] = row
            if key not in queue:
                queue.append(key)
        queues[source] = queue
    # Each Beijing calendar day has one shared quota after identity deduplication.
    daily = {}
    for key, date in discovered_dates.items():
        daily.setdefault(date.astimezone(tz).date().isoformat(), []).append(key)
    selected, day_counts = [], {}
    for day, keys in sorted(daily.items(), reverse=True):
        members = set(keys)
        source_queues = {
            source: sorted((key for key in queue if key in members),
                           key=lambda key: discovered_dates[key], reverse=True)
            for source, queue in queues.items()
        }
        # Reserve half for each source, then fill unused slots from either source.
        chosen = list(dict.fromkeys(source_queues['monitor'][:50] + source_queues['radar'][:50]))
        chosen_set = set(chosen)
        for key in source_queues['monitor'][50:] + source_queues['radar'][50:]:
            if len(chosen) >= 100:
                break
            if key not in chosen_set:
                chosen.append(key)
                chosen_set.add(key)
        selected.extend(chosen)
        day_counts[day] = {'available': len(keys), 'submitted': len(chosen)}
    result = [candidates[key] for key in selected]
    if selection_stats is not None:
        selection_stats.update(windowDays=7, dailyLimit=100, timezone='Asia/Shanghai',
                               dateBasis='discoveredAt', available=len(candidates),
                               submitted=len(result), truncated=len(result) < len(candidates),
                               days=day_counts)
    enrich_performance(result, now=moment)
    return result


def input_fingerprint(context):
    def stable(value, parent=''):
        if isinstance(value, dict):
            return {k: stable(v, k) for k, v in sorted(value.items())
                    if k not in {'now', 'today', 'generatedAt', 'preparedAt', 'inputFingerprint', 'dataAgeHours', 'freshness'}
                    and not (parent in {'window', 'review'} and k in {'from', 'to'})}
        if isinstance(value, list):
            rows = [stable(v, parent) for v in value]
            return sorted(rows, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
        return value
    return hashlib.sha256(json.dumps(stable(context), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def validate_recommendations(value, context):
    """Reject the entire response on invented evidence; bind all snapshots locally."""
    rows = value.get('items') if isinstance(value, dict) else value
    if not isinstance(rows, list) or len(rows) > 6:
        raise ValueError('选题建议应为最多6条的列表')
    account = str((context.get('account') or {}).get('id') or context.get('accountId') or '')
    def index(rows):
        result = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                raise ValueError('输入缺少 ID')
            if account and row.get('accountId') and str(row['accountId']) != account:
                raise ValueError('输入不属于当前账号')
            result[str(row['id'])] = deepcopy(row)
        return result
    works = index(context.get('works') or [])
    # Retain validation of frozen inputs for old paid tasks being recovered.
    content_topics = context.get('recommendationMode') == 'content-topic-v1'
    hooks = {} if content_topics else index(context.get('hooks') or [])
    reviews = index((context.get('review') or {}).get('works') or [])
    # Use frozen performance from prepared inputs, including its original observation time.
    if any('performance' not in work for work in works.values()):
        enrich_performance(list(works.values()))
    generate_evidence = context.get('generateEvidence') is not False
    result, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError('选题格式无效')
        sid = raw.get('sourceWorkId')
        hid = None if content_topics else raw.get('hookId')
        section = raw.get('section', 'more')
        if section not in {'today', 'more'}:
            raise ValueError('推荐分区无效')
        if sid not in works or sid in seen or (hid and hid not in hooks) or (not content_topics and section == 'today' and hid not in hooks):
            raise ValueError('原作品或钩子不在本次输入中')
        seen.add(sid)
        refs = raw.get('references', [])
        review_refs = raw.get('reviewReferenceIds', raw.get('reviewReferences', []))
        def ids(values, allowed):
            if not isinstance(values, list):
                raise ValueError('引用格式无效')
            values = [v.get('id') if isinstance(v, dict) else v for v in values]
            if any(not isinstance(v, str) or v not in allowed for v in values):
                raise ValueError('引用不在本次输入中')
            return list(dict.fromkeys(values))
        refs, review_refs = ids(refs, works), ids(review_refs, reviews)
        category = raw.get('category')
        if category not in {'hot', 'continuation', 'evergreen'} or (category == 'continuation' and not review_refs):
            raise ValueError('推荐类别或延续依据无效')
        if category == 'hot' and not works[sid].get('hotEligible', True):
            category = 'evergreen'
            section = 'more'
        title = (raw.get('generatedTitle') or raw.get('title')) if section == 'today' else works[sid].get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('缺少生成选题标题')
        if section == 'today' and title.strip() == str(works[sid].get('title') or '').strip():
            raise ValueError('主推荐必须生成新标题')
        item = {}
        for field in (('reason', 'angle', 'evidence') if generate_evidence else ('reason', 'angle')):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ValueError('缺少推荐说明')
            item[field] = (raw.get('rawEvidence', raw[field]) if field == 'evidence' else raw[field]).strip()
        if raw.get('relevance') not in {'direct', 'adjacent', 'weak'} or raw.get('priority') not in {'primary', 'worth', 'backup'}:
            raise ValueError('推荐相关度或优先级无效')
        if raw['relevance'] == 'weak':
            continue
        item['evidence'] = item.get('evidence', '')
        item['rawEvidence'] = item['evidence']
        item.update(key=work_key(works[sid]), sourceWorkId=sid, sourceWork=deepcopy(works[sid]),
                    title=title.strip(), generatedTitle=title.strip() if section == 'today' else '',
                    hookId=hid or '', hook=deepcopy(hooks.get(hid)), section=section,
                    references=refs, referenceSnapshots=[deepcopy(works[r]) for r in refs],
                    reviewReferenceIds=review_refs, reviewReferences=[deepcopy(reviews[r]) for r in review_refs],
                    category=category, priority=raw['priority'], relevance=raw['relevance'], schemaVersion=3,
                    sources=deepcopy(works[sid].get('sources') or []),
                    accountSnapshot=deepcopy(context.get('account') or {}),
                    audience=str(raw.get('audience') or '') if generate_evidence else '',
                    reviewEvidence=str(raw.get('reviewEvidence') or '') if generate_evidence else '',
                    hookReason='' if content_topics else str(raw.get('hookReason') or ''),
                    recommendationMode=context.get('recommendationMode', 'hook-title-legacy'),
                    production=str(raw.get('production') or ''),
                    firstSeenAt=works[sid].get('firstSeenAt') or works[sid].get('discoveredAt'),
                    scope=works[sid].get('analysisScope') or ('已提供作品正文' if any(works[sid].get(k) for k in ('transcript', 'content')) else '仅依据标题与互动数据，未提供作品正文'),
                    gaps=deepcopy((context.get('review') or {}).get('gaps') or []))
        result.append(item)
    result = rank_recommendations(result, works, include_evidence=generate_evidence)
    today_count = 0
    for item in result:
        requested = item['section'] == 'today'
        item['today'] = requested and today_count < 3 and item['priority'] != 'backup'
        if item['today']:
            today_count += 1
        item['section'] = 'today' if item['today'] else 'more'
        item['gaps'] += item['evidence'].split('\n')[1:]
        if not item['today']:
            item['title'] = item['sourceWork']['title']
            item['generatedTitle'] = ''
        item['production'] = item['production'] if item['today'] else ''
    return result


class TopicRecommendationStore:
    def __init__(self, workspace_dir):
        self.path = Path(workspace_dir) / 'topic-recommendations.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        if not self.path.exists():
            return {'accounts': {}}
        return json.loads(self.path.read_text(encoding='utf-8'))

    def _write(self, data):
        fd, name = tempfile.mkstemp(prefix='.topic-recommendations-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _archive_into(bucket, legacy):
        history = {row['key']: deepcopy(row) for row in bucket['history']}
        current = {row['key'] for row in bucket['items']}
        # Import feedback only when a key first enters the unified store. Later
        # legacy snapshots may update evidence, but cannot undo unified feedback.
        known_before_archive = set(history) | current
        dismissed = set(bucket['dismissed'])
        for source, record in legacy.items():
            rejected = set(record.get('dismissed') or [])
            entries = [(row, False) for row in record.get('items') or []]
            entries += [(row, True) for row in record.get('dismissedItems') or []]
            for old, in_dismissed in entries:
                row = deepcopy(old)
                try:
                    key = work_key(row.get('sourceWork') or row)
                except ValueError:
                    key = 'legacy:' + hashlib.sha256(str(row.get('title') or '').encode()).hexdigest()[:24]
                if key not in known_before_archive and (in_dismissed or row.get('dismissed') or row.get('key') in rejected):
                    dismissed.add(key)
                if key in current:
                    # Already generated items stay immutable; the complete legacy record
                    # remains in the archive backup rather than overwriting the new result.
                    continue
                previous = history.get(key, {})
                topic_id = previous.get('topicId') or row.get('topicId') or ''
                sources = sorted(set(previous.get('sources') or []) | {source})
                stamp = row.get('generatedAt') or record.get('generatedAt') or ''
                source_records = deepcopy(previous.get('sourceRecords') or [])
                evidence_record = {'source': source, 'generatedAt': stamp, 'item': deepcopy(old)}
                if evidence_record not in source_records:
                    source_records.append(evidence_record)
                references = deepcopy(previous.get('references') or [])
                for ref in row.get('references') or []:
                    if ref not in references:
                        references.append(deepcopy(ref))
                if previous and str(previous.get('generatedAt') or '') > str(stamp):
                    row = previous
                row.update(key=key, today=False, section='more', production='', sources=sources,
                           topicId=topic_id, generatedAt=row.get('generatedAt') or stamp,
                           firstSeenAt=previous.get('firstSeenAt') or row.get('firstSeenAt') or stamp,
                           references=references, sourceRecords=source_records, legacy=True)
                if (row.get('sourceWork') or {}).get('title'):
                    row['title'] = row['sourceWork']['title']
                history[key] = row
        bucket['history'] = list(history.values())
        bucket['dismissed'] = sorted(dismissed)

    def ensure_account(self, account_id, legacy_monitor=None, legacy_radar=None, settings=None):
        with _LOCK:
            data = self._read()
            if account_id not in data['accounts']:
                legacy = {'monitor': deepcopy(legacy_monitor or {}), 'radar': deepcopy(legacy_radar or {})}
                bucket = {'items': [], 'history': [], 'dismissed': [],
                          'settings': dict(settings or {}), 'job': {'status': 'idle'}, 'generatedAt': '',
                          'inputFingerprint': '', 'migrationBackup': legacy, 'migratedAt': _now()}
                self._archive_into(bucket, legacy)
                data['accounts'][account_id] = bucket
                self._write(data)
            return self.get(account_id)

    def archive_legacy(self, account_id, legacy_monitor=None, legacy_radar=None):
        """Archive results of legacy jobs that settled after initial migration."""
        legacy = {'monitor': deepcopy(legacy_monitor or {}), 'radar': deepcopy(legacy_radar or {})}
        def archive(bucket):
            self._archive_into(bucket, legacy)
            backups = bucket.setdefault('legacyArchiveBackups', [])
            if legacy not in backups:
                backups.append(legacy)
        return self._mutate(account_id, archive)

    def get(self, account_id):
        with _LOCK:
            bucket = deepcopy(self._read()['accounts'].get(account_id) or {})
            bucket.pop('migrationBackup', None)
            bucket.pop('legacyArchiveBackups', None)
            rejected = set(bucket.get('dismissed') or [])
            for row in bucket.get('items', []) + bucket.get('history', []):
                row['dismissed'] = row['key'] in rejected
            return bucket

    def _mutate(self, account_id, callback):
        with _LOCK:
            data = self._read()
            bucket = data['accounts'][account_id]
            callback(bucket)
            self._write(data)
            return self.get(account_id)

    def update_settings(self, account_id, settings=None, **fields):
        values = {**(settings or {}), **fields}
        if 'time' in values and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(values['time'])):
            raise ValueError('每日更新时间无效')
        return self._mutate(account_id, lambda b: b['settings'].update(values))

    def set_job(self, account_id, status, **fields):
        if 'error' in fields and 'errorCode' not in fields:
            fields['errorCode'] = ''
        return self._mutate(account_id, lambda b: b['job'].update(status=status, updatedAt=_now(), **deepcopy(fields)))

    def save(self, account_id, items, prepared):
        context = prepared.get('context', prepared)
        prepared_account = str((context.get('account') or {}).get('id') or context.get('accountId') or '')
        if prepared_account and prepared_account != str(account_id):
            raise ValueError('推荐输入账号不匹配')
        validated = validate_recommendations(items, context)
        def save_bucket(bucket):
            old = {r['key']: r for r in bucket['history'] + bucket['items']}
            for row in validated:
                previous = old.get(row['key'], {})
                row['topicId'] = previous.get('topicId', '')
                row['isNewRecommendation'] = row['key'] not in old
                row['firstSeenAt'] = previous.get('firstSeenAt') or row.get('firstSeenAt') or _now()
                row['generatedAt'] = _now()
            keys = {r['key'] for r in validated}
            bucket['history'] = [{**r, 'today': False, 'section': 'more', 'production': '', 'title': (r.get('sourceWork') or {}).get('title') or r['title']} for k, r in old.items() if k not in keys]
            bucket.update(items=validated, scope=deepcopy(context.get('window') or {}), gaps=deepcopy((context.get('review') or {}).get('gaps') or []), generatedAt=_now(), inputFingerprint=prepared.get('inputFingerprint') or input_fingerprint(context))
            bucket['job'].update(status='succeeded', error='', errorCode='', completedAt=_now())
            bucket['job'].pop('prepared', None)
        return self._mutate(account_id, save_bucket)

    def item(self, account_id, key):
        bucket = self.get(account_id)
        for row in bucket.get('items', []) + bucket.get('history', []):
            if row['key'] == key:
                return row
        raise KeyError(key)

    def dismiss(self, account_id, key, dismissed=True):
        self.item(account_id, key)
        def change(bucket):
            values = set(bucket['dismissed'])
            values.add(key) if dismissed else values.discard(key)
            bucket['dismissed'] = sorted(values)
        return self._mutate(account_id, change)

    def attach_topic(self, account_id, key, topic_id):
        self.item(account_id, key)
        def change(bucket):
            for row in bucket['items'] + bucket['history']:
                if row['key'] == key:
                    row['topicId'] = topic_id
        return self._mutate(account_id, change)
