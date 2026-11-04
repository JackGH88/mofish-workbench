"""Read-only, task-scoped lookup of local assistant conversations."""
import json
import os
import re
import sqlite3
from pathlib import Path

from .writing_assistants import AssistantError


def resolve_session(agent, home, directory, bound_id=''):
    home, directory = Path(home), Path(directory).resolve()
    marker = str(directory / 'context.md')
    markers = {marker}
    if marker.startswith('/private/var/'):
        markers.add(marker.removeprefix('/private'))
    root = Path(os.environ.get('CODEX_HOME') or home / '.codex') if agent == 'codex' else home / '.workbuddy'
    if agent not in ('codex', 'workbuddy'):
        raise AssistantError('此任务的助手类型不受支持。')
    if agent == 'codex':
        paths = list(root.glob('state_*.sqlite'))
        paths.sort(key=lambda p: int(re.search(r'state_(\d+)', p.name)[1]) if re.search(r'state_(\d+)', p.name) else -1)
        db = paths[-1] if paths else root / 'state_5.sqlite'
        table, deleted = 'threads', 'archived = 0'
    else:
        db, table, deleted = root / 'workbuddy.db', 'sessions', 'deleted_at IS NULL'
    if not db.is_file():
        raise AssistantError('暂时无法读取助手会话索引，请启动助手后重试。', 'assistant_session_unavailable')
    try:
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=1) as conn:
            conn.row_factory = sqlite3.Row
            if bound_id:
                rows = conn.execute(f'SELECT * FROM {table} WHERE id = ? AND {deleted}', (bound_id,)).fetchall()
                if not rows:
                    raise AssistantError('原会话已删除或归档，无法打开。', 'assistant_session_not_found')
                return bound_id
            rows = conn.execute(f'SELECT * FROM {table} WHERE {deleted} ORDER BY created_at DESC LIMIT 2000').fetchall()
    except sqlite3.Error:
        raise AssistantError('暂时无法读取助手会话索引，请稍后重试。') from None
    matches = set()
    logs = {}
    if agent == 'workbuddy':
        for log in (root / 'projects').glob('*/*.jsonl'):
            logs.setdefault(log.stem, []).append(log)
    for row in rows:
        if agent == 'codex' and (dict(row).get('thread_source') not in (None, '', 'user') or 'subagent' in (dict(row).get('source') or '')):
            continue
        if Path(row['cwd']).resolve() == directory:
            matches.add(row['id']); continue
        if agent == 'codex':
            if any(m in (dict(row).get('first_user_message') or '') for m in markers):
                matches.add(row['id'])
        else:
            # WorkBuddy may launch from its home directory. Match only the first
            # user message, never tool output quoting another task's context.
            sid = row['id']
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', sid): continue
            for log in logs.get(sid, []):
                try:
                    with log.open(encoding='utf-8') as stream:
                        budget = 1024 * 1024
                        while budget > 0:
                            line = stream.readline(min(budget + 1, 1024 * 1024 + 1))
                            budget -= len(line)
                            if not line or budget < 0: break
                            entry = json.loads(line)
                            if entry.get('role') == 'user':
                                if any(m in json.dumps(entry.get('content', ''), ensure_ascii=False) for m in markers): matches.add(sid)
                                break
                except (OSError, ValueError): continue
    if len(matches) > 1:
        raise AssistantError('找到多个对应会话，暂时无法唯一定位，请在助手中手动选择。')
    if not matches:
        raise AssistantError('尚未找到对应会话，请先在助手中发送剪辑任务；会话被删除后也无法打开。', 'assistant_session_not_found')
    return matches.pop()
