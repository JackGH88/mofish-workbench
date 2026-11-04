"""Metadata-only sidecar for editable Markdown memory files."""
from __future__ import annotations
import hashlib
import json
import os
import uuid
from pathlib import Path

INDEX = '.memory-index.json'
BACKUP = '.memory-index.backup.json'
CATEGORY_DIRECTORIES = {'preference': '写作偏好', 'reference_copy': '爆款文案'}
FIELDS = ('memoryFormat', 'id', 'accountId', 'title', 'category', 'scope', 'enabled',
          'source', 'sourceBreakdownId', 'sourceUrl', 'createdAt', 'updatedAt', 'evidence')

def fingerprint(text):
    return hashlib.sha256(text.strip().encode('utf-8')).hexdigest()

def identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, getattr(stat, 'st_birthtime', 0)]

def load(root, owner=None):
    for name in (INDEX, BACKUP):
        path = root / name
        try:
            if path.is_symlink():
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('files'), dict):
                continue
            if not isinstance(data.get('notices', {}), dict):
                continue
            pending = data.get('pendingMoves', {})
            if not isinstance(pending, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                or key not in data['files'] or any(Path(n).is_absolute() or '..' in Path(n).parts for n in (key, value))
                for key, value in pending.items()
            ):
                continue
            if owner is not None and data.get('accountId') != owner:
                continue
            for key, value in data['files'].items():
                if Path(key).is_absolute() or '..' in Path(key).parts or not isinstance(value, dict):
                    raise ValueError('invalid entry')
                if (value.get('accountId') != data.get('accountId') or not isinstance(value.get('id'), str) or not value['id'] or value.get('category') not in ('preference', 'experience', 'reference_copy')
                    or value.get('scope') not in ('structure', 'content', 'both') or type(value.get('enabled')) is not bool):
                    raise ValueError('invalid metadata')
            return data, name == BACKUP
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return {'version': 1, 'accountId': owner or '', 'files': {}}, (root / INDEX).exists() or (root / BACKUP).exists()

def save(root, data):
    from app.memory_store import _write_text
    # Backup holds metadata only, never Markdown bodies.
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    for name in (BACKUP, INDEX):
        path = root / name
        try:
            if not path.is_symlink() and path.exists() and path.read_text(encoding='utf-8') == text:
                continue
        except (OSError, UnicodeError):
            pass
        _write_text(path, text)

def metadata(item, path, content):
    value = {key: item.get(key, '') for key in FIELDS}
    value.update(fingerprint=fingerprint(content), identity=identity(path))
    return value

def record(root, path, item):
    data, _ = load(root, item['accountId'])
    # Remove the old name when an edit renamed this memory.
    data['files'] = {key: value for key, value in data['files'].items() if value['id'] != item['id']}
    relative = str(path.relative_to(root))
    data.get('notices', {}).pop(relative, None)
    data['files'][relative] = metadata(item, path, item['content'])
    save(root, data)

def category_directory(root, category):
    directory = root / CATEGORY_DIRECTORIES[category] if category in CATEGORY_DIRECTORIES else root
    if directory.is_symlink():
        raise OSError('分类目录不能是符号链接，原文件已保留。')
    directory.mkdir(exist_ok=True)
    return directory

def finish_moves(root, data):
    """Journal metadata before linking; unlink only our own identical inode.

    A crash at either filesystem step can be retried without re-importing a
    paused memory or overwriting an unrelated destination.
    """
    warnings = []
    pending = data.setdefault('pendingMoves', {})
    for source_name, target_name in list(pending.items()):
        try:
            for name in (source_name, target_name):
                if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts:
                    raise OSError('分类迁移路径无效。')
                path = root / name
                if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
                    raise OSError('分类路径不能是符号链接。')
            source, target = root / source_name, root / target_name
            if source.exists():
                if not target.exists():
                    os.link(source, target)
                if not source.samefile(target):
                    raise OSError('分类目标文件已存在，原文件已保留。')
                source.unlink()
            elif not target.is_file():
                raise OSError('分类迁移文件暂时不可用。')
            data['files'][target_name] = data['files'].pop(source_name)
            if source_name in data.get('notices', {}):
                data['notices'][target_name] = data['notices'].pop(source_name)
            del pending[source_name]
            save(root, data)
        except OSError as exc:
            warnings.append({'file': source_name, 'reason': f'分类整理未完成：{exc}'})
    return warnings

def organize(root, owner, items):
    data, _ = load(root, owner)
    warnings = []
    for category in CATEGORY_DIRECTORIES:
        try:
            category_directory(root, category)
        except OSError as exc:
            warnings.append({'file': CATEGORY_DIRECTORIES[category], 'reason': str(exc)})
    for item in items:
        if item['category'] not in CATEGORY_DIRECTORIES:
            continue
        source = Path(item['path']).relative_to(owner)
        target = Path(CATEGORY_DIRECTORIES[item['category']]) / source.name
        if source == target:
            continue
        # Never replace an existing name, even if its contents happen to match.
        if (root / target).exists() or (root / target).is_symlink():
            warnings.append({'file': str(source), 'reason': '分类目标文件已存在，原文件已保留。'})
            continue
        data.setdefault('pendingMoves', {})[str(source)] = str(target)
    save(root, data)
    warnings.extend(finish_moves(root, data))
    by_id = {value['id']: name for name, value in data['files'].items()}
    for item in items:
        if item['id'] in by_id:
            item['path'] = str(Path(owner) / by_id[item['id']])
    return warnings

def reconcile(library, root, owner):
    from app.memory_store import parse_memory_file, MemoryStoreError, now_stamp, _write_text, _split_sections, derive_title
    data, recovered = load(root, owner)
    move_warnings = finish_moves(root, data)
    old = data['files']
    paths = list(library._iter_files(root))
    names = {str(path.relative_to(root)) for path in paths}
    missing = {key: value for key, value in old.items() if key not in names}
    matched = set()
    updates = dict(old)  # Retain missing metadata so a temporarily moved file can return.
    notices = data.setdefault('notices', {})
    items, warnings, seen = [], [], set()
    if recovered:
        notices[INDEX] = '管理索引缺失或损坏，已尝试恢复；请检查分类及启停状态。'
    for path in paths:
        name = str(path.relative_to(root))
        if name in data.get('pendingMoves', {}).values():
            # An interrupted link/unlink still represents the original memory.
            continue
        try:
            text = path.read_text(encoding='utf-8')
            # Ordinary Markdown headings/frontmatter are content, not required configuration.
            legacy = parse_memory_file(text) if text.lstrip('\ufeff').startswith('---') and 'memoryFormat:' in text.split('---', 2)[1] else None
            if legacy and legacy['accountId'] != owner:
                warnings.append({'file': name, 'reason': '记忆归属与当前工作台不符，未读取。'})
                continue
            if legacy:
                legacy['content'], legacy['evidence'] = _split_sections(text)
            content = legacy['content'] if legacy else text.strip()
            if not content:
                warnings.append({'file': name, 'reason': '文件正文为空，未加入记忆。'})
                continue
            item = legacy or old.get(name)
            if item is None:
                candidates = [(key, value) for key, value in missing.items() if key not in matched
                              and identity(path)[2] and value.get('identity') == identity(path)]
                if not candidates:
                    candidates = [(key, value) for key, value in missing.items() if key not in matched
                                  and value.get('fingerprint') == fingerprint(content)]
                if len(candidates) == 1:
                    key, item = candidates[0]
                    matched.add(key)
                    updates.pop(key, None)
                else:
                    stamp = now_stamp()
                    category = 'reference_copy' if Path(name).parts[0] == CATEGORY_DIRECTORIES['reference_copy'] else 'preference'
                    item = dict(memoryFormat=1, id=uuid.uuid4().hex, accountId=owner, title=path.stem,
                                category=category, scope='content' if category == 'reference_copy' else 'both', enabled=not candidates, source='manual',
                                sourceBreakdownId='', sourceUrl='', createdAt=stamp, updatedAt=stamp, evidence='')
                    warning = ('无法唯一匹配原记忆，已暂停；请检查后启用。' if candidates
                               else ('未找到对应索引，按「爆款文案 · 启用」导入，请检查设置。' if category == 'reference_copy' else '未找到对应索引，按「写作偏好 · 结构和正文 · 启用」导入，请检查设置。'))
                    notices[name] = warning
            item = {key: item.get(key, '') for key in FIELDS}
            if item['id'] in seen:
                warnings.append({'file': name, 'reason': '重复的记忆 ID，未读取。'})
                continue
            seen.add(item['id'])
            if item['category'] == 'reference_copy':
                if len(content) > 4000:
                    warnings.append({'file': name, 'reason': '爆款文案最多 4000 个字，内容未截断，请精简后使用。'})
                    continue
                if not item.get('title'):
                    resolver = library.reference_title_resolver
                    recovered_title = resolver(owner, item.get('sourceBreakdownId', '')) if resolver else ''
                    item['title'] = recovered_title or derive_title(content)
            item.update(accountId=owner, content=content, path=str(Path(owner) / name), summary=library._summary(content))
            updates[name] = metadata(item, path, content)
            if legacy:
                # Persist management data before stripping frontmatter; retries remain recoverable.
                data['files'] = updates
                save(root, data)
                _write_text(path, content + '\n')
                updates[name] = metadata(item, path, content)
            items.append(item)
        except (OSError, UnicodeError, MemoryStoreError) as exc:
            warnings.append({'file': name, 'reason': str(exc) or '文件无法读取。'})
    data['files'] = updates
    save(root, data)
    warnings += move_warnings + [{'file': key, 'reason': value} for key, value in notices.items() if key == INDEX or key in names]
    warnings.extend(organize(root, owner, items))
    return items, warnings

def indexed_file(path, boundary):
    """Resolve a plain file during legacy/global scans and directory migration."""
    for parent in (path.parent, *path.parent.parents):
        if not parent.is_relative_to(boundary):
            break
        if (parent / INDEX).exists() or (parent / BACKUP).exists():
            data, _ = load(parent)
            item = data['files'].get(str(path.relative_to(parent)))
            if item:
                result = {key: item.get(key, '') for key in FIELDS}
                if result['category'] == 'reference_copy' and not result.get('title'):
                    from app.memory_store import derive_title
                    result['title'] = derive_title(path.read_text(encoding='utf-8'))
                return result
    return None
