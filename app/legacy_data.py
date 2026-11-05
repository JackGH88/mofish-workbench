"""One-way compatibility rules for pre-schema-2 local records.

Legacy identifiers here are data keys only, never upstream clients or endpoints.
Derived from the independently tested private maintenance converter.
"""
import json
import math
import os
from pathlib import Path
import re


def identifiers(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    return re.search(r'(?<![a-zA-Z0-9])(?:Tik\s?Hub|Snap\s?Any|KIE|Deep\s?Seek|doubao|bytedance|volces|volcengine)(?![a-zA-Z0-9])|豆包', text, re.I)

SCHEMA_MARKER = '.core-data-schema.json'
SCHEMA_VERSION = 2

ALIASES = {'deepseek': 'text-default', 'gpt56': 'text-option-2', 'kimi': 'text-option-3'}
RENAMES = {'rewrite-gpt56.json': 'rewrite-text-option-2.json', 'rewrite-kimi.json': 'rewrite-text-option-3.json'}
# Only these application-owned containers are traversed. Unknown/user JSON is opaque.
RECORD_CONTAINERS = {'task', 'platform', 'creationService', 'parse', 'transcription',
                     'coverGeneration', 'generation', 'job', 'error', 'state'}
LIST_CONTAINERS = {'scripts', 'tasks', 'items', 'aspects', 'images'}
MAP_CONTAINERS = {'accounts'}
DIAGNOSTIC_KEYS = {'warningCode', 'warningMessage', 'message', 'lastError', 'lastErrorCode', 'error'}
DIAGNOSTIC_CONTEXTS = {'task', 'job', 'platform', 'parse', 'transcription', 'collection',
                       'trend', 'recommendationJob', 'recommendation'}
OWNED_MAPS = {'monitor': {'bloggers': 'blogger'},
              'radar': {'keywords': 'keyword', 'trendCache': 'trend'}}
OWNED_RECORDS = {'blogger': {'collection'}, 'keyword': {'collection', 'trend'},
                 'account': {'recommendation', 'recommendationJob'}}
MODEL_MAPS = {'rewrites', 'rewriteModels', 'rewrite_models'}
KEY_ALIASES = {'kieTaskId': 'imageTaskId', 'kieTaskIds': 'imageTaskIds',
               'kie_task_id': 'image_task_id', 'kie_task_ids': 'image_task_ids'}
ERROR_KEYS = {'errorCode', 'errorMessage', 'parseErrorCode', 'parseErrorMessage',
              'transcriptionErrorCode', 'transcriptionErrorMessage', 'error_code', 'error_message'}
PRUNE_DIRS = {'plugins', 'plugin_dist', 'plugin_sources', 'publisher-profiles',
              'browser-profiles', 'macos', 'backups', 'backup', 'repair-backups',
              'repair-snapshots', 'system-repair', '.git', '.venv', 'venv',
              'migration-backups', '__pycache__', 'node_modules', 'logs', 'cache', 'caches', '.cache',
              '.pytest_cache', 'writing-agent-tasks', 'memory-library'}
STORE_FILES = {'workspace.json', 'index.json', 'script.json', 'breakdowns.json',
               'manual-tasks.json', 'monitor-data.json', 'radar-data.json',
               'topic-plans.json', 'inspirations.json', 'writing-pending.json'}
TASK_FILES = {'task.json', 'video.json', 'rewrite.json', *RENAMES, *RENAMES.values()}


def selected_file(root, path):
    relative = path.relative_to(root)
    if path.name == SCHEMA_MARKER:
        return False
    if any(part.lower() in PRUNE_DIRS for part in relative.parts[:-1]):
        return False
    if re.search(r'(?:^|[._-])(?:before|backup|bak|snapshot|repair)(?:[._-]|$)', path.name, re.I):
        return False
    if path.suffix.lower() != '.json' or path.name == 'transcript.json':
        return False
    if len(relative.parts) == 1:
        return root.name == 'scripts' or path.name in STORE_FILES | TASK_FILES
    return (len(relative.parts) == 2 and
            (relative.parts[0] == 'scripts' or path.name in TASK_FILES))


class Conflict(ValueError):
    """Fail closed without embedding record contents in diagnostics."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Conflict('duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Conflict('non-finite JSON number')))
    except (UnicodeError, ValueError) as exc:
        raise Conflict('invalid JSON; no data written') from None


def scalar(value):
    return isinstance(value, (str, int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value))


def allowed_metadata(source):
    if not isinstance(source, dict):
        return {}
    result = {k: v for k, v in source.items() if k in {
        'title', 'desc', 'description', 'text', 'site', 'published_at', 'created_at',
        'create_time', 'publishedAt', 'duration_seconds'} and scalar(v)}
    author = source.get('author')
    if isinstance(author, str):
        result['author'] = author
    elif isinstance(author, dict):
        result['author'] = {k: v for k, v in author.items() if k in {
            'nickname', 'name', 'display_name', 'id', 'username', 'uid', 'uniqueId'} and scalar(v)}
    stats = source.get('stats')
    if isinstance(stats, dict):
        result['stats'] = {k: v for k, v in stats.items() if k in {
            'like_count', 'comment_count', 'share_count', 'collect_count'} and
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0}
    return result


def merge_fallback(primary, fallback):
    for key, value in fallback.items():
        if key not in primary or primary[key] in (None, '', 'douyin_video'):
            primary[key] = value
        elif isinstance(primary[key], dict) and isinstance(value, dict):
            merge_fallback(primary[key], value)
    return primary


def media_proxy(parse_task_id):
    if not isinstance(parse_task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', parse_task_id):
        return ''
    return f'/workbench/v1/tasks/{parse_task_id}/media/mediaUrl'


def platform_media(value, directory):
    result = dict(value)
    if 'mediaUrl' in result:
        result['mediaUrl'] = media_proxy(result.get('parseTaskId'))
    if 'mediaCoverUrl' in result:
        expected = f'/api/files/{directory.name}/cover.jpg' if directory else ''
        cover = directory / 'cover.jpg' if directory else None
        result['mediaCoverUrl'] = expected if expected and (
            result['mediaCoverUrl'] == expected or
            cover is not None and not cover.is_symlink() and cover.is_file()) else ''
    return result


def transform(value, directory=None, context='record'):
    if isinstance(value, list):
        return [transform(item, directory, context) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        target_key = KEY_ALIASES.get(key, key)
        if target_key != key and target_key in value:
            raise Conflict('image task key collision')
        if key == 'snapany_response':
            continue
        if key in ('model', 'selectedRewriteModel') and isinstance(child, str):
            result[target_key] = ALIASES.get(child, child)
        elif key in MODEL_MAPS and isinstance(child, dict):
            migrated = {}
            for model, rewrite in child.items():
                target = ALIASES.get(model, model)
                if target in migrated:
                    raise Conflict('rewrite model key collision')
                migrated[target] = transform(rewrite, directory, 'task')
            result[target_key] = migrated
        elif (key in ERROR_KEYS or key in DIAGNOSTIC_KEYS and context in DIAGNOSTIC_CONTEXTS) and isinstance(child, str) and (identifiers(child) or re.search(
                r'(?<![a-zA-Z0-9])(?:gpt56|kimi)(?![a-zA-Z0-9])', child, re.IGNORECASE)):
            result[target_key] = 'upstream_error' if key.endswith(('Code', '_code')) else '上游服务暂不可用，请稍后重试。'
        elif key in OWNED_MAPS.get(context, {}) and isinstance(child, dict):
            child_context = OWNED_MAPS[context][key]
            result[target_key] = {identifier: transform(record, directory, child_context)
                                  for identifier, record in child.items()}
        elif (key in RECORD_CONTAINERS or key in OWNED_RECORDS.get(context, set())) and isinstance(child, dict):
            converted = transform(child, directory, key)
            result[target_key] = platform_media(converted, directory) if key == 'platform' else converted
        elif key in LIST_CONTAINERS and isinstance(child, list):
            result[target_key] = [transform(item, directory, {'tasks': 'task', 'scripts': 'script'}.get(key, 'record')) for item in child]
        elif key in MAP_CONTAINERS | LIST_CONTAINERS and isinstance(child, dict):
            result[target_key] = {identifier: transform(record, directory, {'accounts': 'account', 'tasks': 'task', 'scripts': 'script'}.get(key, 'record')) for identifier, record in child.items()}
        else:
            # Scalar user text and unknown structured content are copied verbatim.
            result[target_key] = child
    if 'snapany_response' in value:
        existing = value.get('mediaMetadata', {})
        if not isinstance(existing, dict):
            raise Conflict('mediaMetadata is not an object')
        raw = allowed_metadata(value['snapany_response'])
        fallback = merge_fallback(raw, allowed_metadata(value))
        if not fallback.get('title') or fallback.get('title') == 'douyin_video':
            fallback['title'] = next((fallback[k] for k in ('description', 'desc', 'text') if fallback.get(k)), '')
        if not fallback.get('published_at'):
            fallback['published_at'] = fallback.get('created_at') or fallback.get('create_time') or ''
        result['mediaMetadata'] = merge_fallback(allowed_metadata(existing), fallback)
    return result


def transform_file(parsed, path):
    context = {'task.json': 'task', 'monitor-data.json': 'monitor', 'radar-data.json': 'radar'}.get(path.name, 'record')
    result = transform(parsed, path.parent, context)
    if path.name == 'video.json' and isinstance(result, dict) and 'mediaUrl' in result:
        sibling = safe(path.with_name('task.json'))
        task = decode(sibling.read_bytes()) if sibling.is_file() else {}
        platform = task.get('platform', {}) if isinstance(task, dict) else {}
        parse_id = platform.get('parseTaskId') if isinstance(platform, dict) else None
        result['mediaUrl'] = media_proxy(parse_id)
    return result


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def safe(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise Conflict('symlink paths are not supported')
    return path

