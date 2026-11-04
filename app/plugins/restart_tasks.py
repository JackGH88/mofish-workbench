"""Compatibility for shipped plugins predating the optional restart polling hook."""
import json


async def refresh_legacy_tasks(pid, context):
    # Existing HeyGen packages have no background poller. Query only submitted
    # tasks, never generate, retry submissions, download, or adopt paid output.
    if pid != 'heygen' or not hasattr(context, 'heygen_tasks'): return
    path = context.media_dir() / 'tasks.json'
    if not path.exists(): return
    tasks = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError('插件任务数据无法确认')
    for task in tasks:
        if (task.get('accountId') == context.account_id and task.get('officialId')
                and task.get('id') and task.get('status') not in {'completed', 'failed', 'cancelled'}):
            await context.heygen_tasks.refresh(task['id'])
