"""Data-v1 compatibility migration. Keep original records/media as recovery backup."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path

_lock = threading.RLock()


def prepare_runtime(root, account, pid):
    """Partition legacy v1 task lists/drafts without moving published media paths."""
    root = Path(root)
    target = root / 'accounts' / hashlib.sha256(account.encode()).hexdigest() / pid
    with _lock:
        if (target / '.ready').is_file(): return target
        legacy = root / pid
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='.runtime-', dir=target.parent))
        try:
            tasks = legacy / 'tasks.json'
            if tasks.exists():
                data = json.loads(tasks.read_text(encoding='utf-8'))
                if not isinstance(data, list) or any(not isinstance(x, dict) or not x.get('accountId') for x in data):
                    raise ValueError('Unowned or damaged task data; explicit recovery required')
                (tmp / 'tasks.json').write_text(json.dumps([x for x in data if x['accountId'] == account], ensure_ascii=False), encoding='utf-8')
            drafts = legacy / 'spoken-drafts.sqlite3'
            if drafts.exists():
                source = sqlite3.connect(drafts.as_uri() + '?mode=ro', uri=True)
                dest = sqlite3.connect(tmp / drafts.name)
                try:
                    source.backup(dest)
                    dest.execute('DELETE FROM drafts WHERE owner != ?', (json.dumps(account),))
                    dest.commit()
                finally:
                    dest.close(); source.close()
            # Stable media refs (<plugin>/media/<uuid>) are used by publishing/history.
            media = legacy / 'media'
            media.mkdir(parents=True, exist_ok=True)
            (tmp / 'media').symlink_to(media.resolve(), target_is_directory=True)
            (tmp / '.ready').write_text('1')
            os.replace(tmp, target)
        finally:
            if tmp.exists(): shutil.rmtree(tmp)
    return target
