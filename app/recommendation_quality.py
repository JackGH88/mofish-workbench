"""Evidence derived only from submitted works; no collection or model calls."""
from datetime import datetime, timezone
from math import isfinite
from statistics import median

METRICS = ('likes', 'comments', 'collects', 'shares')


def _date(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _count(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0 else None


def enrich_performance(works, now=None):
    now = now or datetime.now(timezone.utc)
    for work in works:
        metrics = work.get('metrics') or {}
        values = {key: _count(metrics.get(key)) for key in METRICS}
        published = _date(work.get('publishedAt') or work.get('publishedAtIso'))
        collected = _date(work.get('statsUpdatedAt') or work.get('collectedAt'))
        age = (collected - published).total_seconds() / 3600 if collected and published else None
        if age is not None and age < 0:
            age = None
        freshness = (now - collected).total_seconds() / 3600 if collected else None
        known = [v for v in values.values() if v is not None]
        work['performance'] = {
            'ageAtCollectionHours': round(age, 1) if age is not None else None,
            'dataAgeHours': round(freshness, 1) if freshness is not None and freshness >= 0 else None,
            'stage': 'unknown' if age is None else 'early' if age < 24 else 'settled' if age <= 168 else 'older',
            'freshness': 'unknown' if freshness is None or freshness < 0 else 'stale' if freshness > 48 else 'recent',
            'engagement': 'positive' if any(v > 0 for v in known) else 'zero' if len(known) == 4 else 'unknown',
            'observedZeroOnly': bool(known) and not any(v > 0 for v in known),
            'missingMetrics': [key for key, value in values.items() if value is None],
            'peerSampleCount': 0, 'relativeLikes': None,
        }
    for work in works:
        signal = work['performance']
        author = work.get('bloggerId') or work.get('authorId')
        published = _date(work.get('publishedAt') or work.get('publishedAtIso'))
        peers = []
        for other in works:
            other_date = _date(other.get('publishedAt') or other.get('publishedAtIso'))
            likes = _count((other.get('metrics') or {}).get('likes'))
            if (other.get('id') != work.get('id') and author and author == (other.get('bloggerId') or other.get('authorId'))
                    and published and other_date and abs((published-other_date).days) <= 30
                    and signal['stage'] in ('early', 'settled', 'older')
                    and other['performance']['stage'] == signal['stage'] and likes is not None):
                a, b = signal['ageAtCollectionHours'], other['performance']['ageAtCollectionHours']
                if max(a, b) <= max(1, min(a, b)) * 2:
                    peers.append(likes)
        signal['peerSampleCount'] = len(peers)
        likes = _count((work.get('metrics') or {}).get('likes'))
        if len(peers) >= 3 and median(peers) > 0 and likes is not None:
            signal['relativeLikes'] = round(likes / median(peers), 2)


def rank_recommendations(items, works, *, include_evidence=True):
    """Relevance first; evidence may demote, never promote an unrelated topic."""
    for item in items:
        signal = works[item['sourceWorkId']]['performance']
        uncertain = (signal['engagement'] != 'positive' or signal['freshness'] != 'recent'
                     or signal['stage'] in ('unknown', 'early') or len(signal['missingMetrics']) > 2)
        cap = 'backup' if signal['observedZeroOnly'] else 'worth' if uncertain or item['relevance'] == 'adjacent' else 'primary'
        levels = {'primary': 0, 'worth': 1, 'backup': 2}
        if levels[item['priority']] < levels[cap]:
            item['priority'] = cap
        item['performance'] = dict(signal)
        if not include_evidence:
            continue
        gaps = []
        if signal['freshness'] != 'recent':
            gaps.append('指标采集时间未知或距今超过48小时，更新建议不会自动同步作品，请先同步后再判断当前表现。')
        if signal['missingMetrics']:
            gaps.append('部分互动指标缺失，不代表零。')
        if signal['observedZeroOnly']:
            gaps.append('已采集互动指标为零，尚无互动表现支持；仅作主题观察。')
        if signal['stage'] == 'early':
            gaps.append('指标采集时发布不足24小时，表现尚未稳定。')
        if signal['relativeLikes'] is None:
            gaps.append('缺少至少3条同博主、发布时间及观察时长可比的作品，不判断超出该博主通常水平。')
        item['evidence'] = item['evidence'] + ('\n' + '\n'.join(gaps) if gaps else '')
    def key(item):
        p = item['performance']
        return (0 if item['relevance'] == 'direct' else 1,
                {'primary': 0, 'worth': 1, 'backup': 2}[item['priority']],
                0 if p['engagement'] == 'positive' else 2 if p['observedZeroOnly'] else 1,
                -(min(p['relativeLikes'], 10) if p['relativeLikes'] is not None else 0))
    return sorted(items, key=key)
