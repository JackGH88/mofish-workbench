"""Reversible source-only quarantine. Caller must pause Radar writers first."""
from copy import deepcopy
from .radar import source_channels, now_iso


def isolate_sources(store, candidates, batch_id):
    with store._lock:
        data = store._read()
        isolated = 0
        for candidate in candidates:
            work = data['works'].get(candidate['workId'])
            if not work:
                continue
            key = candidate['keywordId']
            source = work.get('sources', {}).get(key)
            if not source:
                continue
            channels = source_channels(source)
            low = channels.get('lowfans')
            if not low or low.get('lastSeenAt') != candidate.get('lastSeenAt'):
                continue
            archive_key = batch_id + ':' + key
            archive = work.setdefault('quarantinedSources', {})
            if archive_key in archive:
                continue
            archive[archive_key] = {'batchId': batch_id, 'keywordId': key, 'source': deepcopy(low),
                                    'evidenceTaskId': candidate.get('taskId', ''), 'isolatedAt': now_iso()}
            channels.pop('lowfans')
            if channels:
                work['sources'][key] = {**(channels.get('search') or next(iter(channels.values()))), 'channels': channels}
            else:
                work['sources'].pop(key)
            isolated += 1
        store._write(data)
        return {'batchId': batch_id, 'isolated': isolated}


def restore_sources(store, batch_id):
    with store._lock:
        data = store._read()
        restored = 0
        for work in data['works'].values():
            for entry in work.get('quarantinedSources', {}).values():
                if entry.get('batchId') != batch_id or entry.get('restoredAt'):
                    continue
                key = entry['keywordId']
                if key not in data['keywords']:
                    continue
                current = work.setdefault('sources', {}).get(key)
                channels = source_channels(current) if current else {}
                if 'lowfans' in channels:
                    continue  # never overwrite results collected since quarantine
                channels['lowfans'] = deepcopy(entry['source'])
                work['sources'][key] = {**(channels.get('search') or channels['lowfans']), 'channels': channels}
                entry['restoredAt'] = now_iso()
                restored += 1
        store._write(data)
        return {'batchId': batch_id, 'restored': restored}
