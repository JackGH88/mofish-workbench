"""Account onboarding: local evidence only, never invokes login, collection or AI."""
from copy import deepcopy

STEPS = ('preparation', 'sources', 'creation', 'publication', 'review')
DRAFT_FIELDS = ('offer', 'audience', 'goal', 'businessPositioning', 'targetAudience')


def initial(*, new=False, stage='existing'):
    return {'version': 1, 'collapsed': False, 'dismissed': False, 'stage': stage, 'preparationStep': 0,
            'connectionSkipped': False, 'draft': dict.fromkeys(DRAFT_FIELDS, ''), 'milestones': {}}


def load(store):
    if not store._onboarding_path.exists():
        return {"accounts": {}}
    data = store._read_json(store._onboarding_path)
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
        raise ValueError("引导状态文件格式无效，请检查工作区数据。")
    return data


def valid_script(script):
    if script.get('retiredAsBreakdown'):
        return False
    if str((script.get('writingState') or {}).get('content') or '').strip():
        return True
    if script.get('source') == 'link':
        return False
    text = str(script.get('content') or '').strip()
    # A topic handoff creates a nonempty scaffold, not a saved script.
    scaffold = text.startswith('选题：') and '\n一句话大纲：' in text and '\n准备素材：' in text
    return bool(text) and not scaffold


def mark(bucket, step, evidence, now):
    bucket['milestones'].setdefault(step, {'completedAt': now, **evidence})


def remember_script(store, script):
    account = str(script.get('accountId') or '')
    if not account:
        return
    data = load(store)
    bucket = data['accounts'].setdefault(account, initial())
    before = deepcopy(bucket)
    if valid_script(script):
        mark(bucket, 'creation', {'kind': 'saved_script', 'id': script['id']}, store._now())
    if script.get('workflowStatus') == 'published':
        mark(bucket, 'publication', {'kind': 'operator_marked_published', 'id': script['id']}, store._now())
    if bucket != before:
        store._write_json(store._onboarding_path, data)


def view(store, account_id, works, *, content_sources=None):
    account = store._require_account(account_id)
    data = load(store)
    before = deepcopy(data)
    bucket = data['accounts'].setdefault(account_id, initial())
    profile = store._normalize_account_profile(store._read_account_profiles().get(account_id))
    ready = all(str(profile.get(k) or '').strip() and '【待完善】' not in str(profile.get(k))
                for k in ('businessPositioning', 'targetAudience'))
    scripts = sorted(store.list_scripts(account_id), key=lambda s: str(s.get('updatedAt') or ''), reverse=True)
    good = [s for s in scripts if valid_script(s)]
    published = next((s for s in scripts if s.get('workflowStatus') == 'published'), None)
    works = [w for w in works if w.get('platform', 'douyin') == 'douyin'
             and w.get('accountId', account_id) == account_id]
    reviewed = next((w for w in works if str(w.get('note') or '').strip() and w.get('reviewedAt')), None)
    sources = content_sources or {}
    keywords = sources.get('keywordIds') or []
    bloggers = sources.get('bloggerIds') or []
    now = store._now()
    evidence = {
        'preparation': {'kind': 'saved_positioning'} if ready else None,
        'sources': {'kind': 'saved_content_sources', 'keywordId': keywords[0], 'bloggerId': bloggers[0]} if keywords and bloggers else None,
        'creation': {'kind': 'saved_script', 'id': good[0]['id']} if good else None,
        'publication': ({'kind': 'collected_work', 'id': works[0]['id']} if works else
                        {'kind': 'operator_marked_published', 'id': published['id']} if published else None),
        'review': {'kind': 'saved_review', 'id': reviewed['id']} if reviewed else None,
    }
    for step, item in evidence.items():
        if item:
            mark(bucket, step, item, now)
    if data != before:
        store._write_json(store._onboarding_path, data)
    target = next((s for s in good if s.get('workflowStatus') != 'published'), None)
    # Only explicit saved associations can select a review work.
    linked = next((w for w in works if w.get('scriptId') and any(s['id'] == w['scriptId'] for s in good)), None)
    topics = store.list_topics(account_id)['items']
    return {
        'accountId': account_id, 'visible': True,
        **{k: deepcopy(bucket[k]) for k in ('collapsed', 'stage', 'preparationStep', 'connectionSkipped', 'draft')},
        'steps': {k: {'completed': k in bucket['milestones'], 'evidence': deepcopy(bucket['milestones'].get(k))} for k in STEPS},
        'dismissed': bool(bucket.get('dismissed', False)),
        'currentStep': next((k for k in STEPS if k not in bucket['milestones']), 'complete'),
        'current': {'profileReady': bool(ready), 'hasScript': bool(good), 'hasPublished': bool(works or published),
                    'hasReview': bool(reviewed), 'hasTopics': bool(topics),
                    'hasKeywords': bool(keywords), 'hasBloggers': bool(bloggers)},
        'targets': {'scriptId': target['id'] if target else None, 'workId': linked['id'] if linked else None},
    }


def save_preferences(store, account_id, patch):
    store._require_account(account_id)
    allowed = {'collapsed', 'dismissed', 'stage', 'preparationStep', 'connectionSkipped', 'draft'}
    if set(patch) - allowed:
        raise ValueError('不能直接修改引导完成状态。')
    data = load(store)
    bucket = data['accounts'].setdefault(account_id, initial())
    for key, value in patch.items():
        if key == 'draft':
            if set(value) - set(DRAFT_FIELDS) or any(not isinstance(v, str) or len(v) > 2000 for v in value.values()):
                raise ValueError('引导草稿格式无效。')
            bucket['draft'].update(value)
        else:
            bucket[key] = value
    store._write_json(store._onboarding_path, data)
