"""Durable, local-only success chimes. Producers never scan/replay legacy results.

Claims serialize playback across desktop and browser clients. A crashed client's
lease expires; an unacknowledged sound remains pending for reconnection.
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
import uuid


class ReturnNotifications:
    LEASE_SECONDS = 30

    def __init__(self, workspace: Path):
        self.path = workspace / 'return-notifications.sqlite3'
        self.outbox = workspace / 'return-notifications-outbox'

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('CREATE TABLE IF NOT EXISTS notices (id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0, token TEXT, lease REAL NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS delivery (id INTEGER PRIMARY KEY CHECK(id=1), native_until REAL NOT NULL DEFAULT 0)')
            db.execute('INSERT OR IGNORE INTO delivery(id) VALUES(1)')
            db.commit()
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def record(self, key, *, account_id, script_id, message, kind):
        identity = hashlib.sha256(key.encode()).hexdigest()
        data = dict(id=identity, accountId=account_id, scriptId=script_id,
                    message=message, kind=kind)
        created = time.time()
        try:
            with self.db() as db:
                self._insert(db, data, created)
        except (sqlite3.Error, OSError):
            # The content is already saved. Preserve notification retry separately
            # instead of reporting the successful return as a failed upload.
            logging.getLogger(__name__).warning('return_sound_deferred id=%s', identity)
            temp = self.outbox / (identity + '.' + uuid.uuid4().hex + '.tmp')
            try:
                self.outbox.mkdir(parents=True, exist_ok=True)
                with temp.open('x', encoding='utf-8') as stream:
                    json.dump({'data': data, 'created': created}, stream, ensure_ascii=False)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temp, self.outbox / (identity + '.json'))
            except OSError:
                logging.getLogger(__name__).exception('return_sound_outbox_failed id=%s', identity)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
        return identity

    @staticmethod
    def _insert(db, data, created):
        db.execute('INSERT OR IGNORE INTO notices(id,data,created) VALUES(?,?,?)',
                   (data['id'], json.dumps(data, ensure_ascii=False), created))

    def _recover(self):
        for path in sorted(self.outbox.glob('*.json')):
            try:
                entry = json.loads(path.read_text(encoding='utf-8'))
                with self.db() as db:
                    self._insert(db, entry['data'], entry['created'])
                path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass  # Another delivery client already recovered the same record.

    def pending(self):
        self._recover()
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute(
                'SELECT data FROM notices WHERE done=0 ORDER BY created,id LIMIT 100')]

    def claim(self, client_id, native=False):
        self._recover()
        now = time.time()
        with self.db() as db:
            if native:
                db.execute('UPDATE delivery SET native_until=? WHERE id=1', (now + 5,))
            elif db.execute('SELECT native_until FROM delivery WHERE id=1').fetchone()[0] > now:
                return None
            # One outstanding sound globally, not one per tab or account.
            if db.execute('SELECT 1 FROM notices WHERE done=0 AND lease>?', (now,)).fetchone():
                return None
            row = db.execute('SELECT * FROM notices WHERE done=0 ORDER BY created,id LIMIT 1').fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute('UPDATE notices SET token=?,lease=? WHERE id=?',
                       (token, now + self.LEASE_SECONDS, row['id']))
            return {**json.loads(row['data']), 'token': token}

    def finish(self, identity, token, played):
        with self.db() as db:
            row = db.execute('SELECT token,done FROM notices WHERE id=?', (identity,)).fetchone()
            if row is None or row['token'] != token:
                return False
            if played:
                db.execute('UPDATE notices SET done=1,lease=0 WHERE id=?', (identity,))
            elif not row['done']:
                db.execute('UPDATE notices SET token=NULL,lease=0 WHERE id=?', (identity,))
            return True
