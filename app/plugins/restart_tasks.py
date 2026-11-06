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


def compatible_unknown_upgrade(hook, context, active, candidate):
    """Bridge the shipped HeyGen guard for compatible upgrades only.

    Re-run the original guard with a read-only studio view that treats dormant
    unknown submissions as preserved records. All its other checks still run.
    Never use this for uninstall, migration, or an ordinary restart.
    """
    import sqlite3
    from contextlib import closing
    from .packages import version_tuple

    old = (active or {}).get('manifest', {})
    new = (candidate or {}).get('manifest', {})
    if (old.get('id') != 'heygen' or new.get('id') != 'heygen'
            or old.get('dataVersion') != 1 or new.get('dataVersion') != 1
            or old.get('packageFormat') != 1 or new.get('packageFormat') != 1
            or not (version_tuple('0.4.109') <= version_tuple(old.get('version'))
                    < version_tuple(new.get('version')))
            or version_tuple(new.get('version')) < version_tuple('0.4.110')):
        return False
    studio = context.studio
    if any(not worker.done() for worker in studio.workers.values()):
        return False
    with closing(sqlite3.connect(studio.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT id,owner,script,data FROM tasks').fetchall()
    tasks = []
    allowed = {'unknown', 'completed', 'failed', 'cancelled', 'saved', 'edit_failed', 'adopt_failed', 'editing'}
    for tid, owner, script, raw in rows:
        task = json.loads(raw)
        if (not isinstance(task, dict) or task.get('id') != tid
                or task.get('accountId') != owner or task.get('scriptId') != script
                or not tid or not owner or not script or task.get('status') not in allowed
                or (task.get('status') == 'unknown' and task.get('editTaskId'))):
            return False
        tasks.append(task)
    if not any(t['status'] == 'unknown' for t in tasks):
        return False

    class StudioView:
        def __getattr__(self, name):
            return getattr(studio, name)

        def has_active(self, account=None):
            # Every row was checked above; only dormant/terminal records remain.
            return False

    class ContextView:
        studio = StudioView()

        def __getattr__(self, name):
            return getattr(context, name)

    return hook(ContextView()) is True
