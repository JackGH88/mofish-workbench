"""Read public identity from the authenticated creator page, never from workspace labels."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

DOUYIN_IDENTITY_SCRIPT = r"""() => {
  const text = el => String(el?.textContent || '').trim();
  const avatar = document.querySelector('[data-e2e="creator-header-avatar"]');
  const header = avatar?.closest('header') || avatar?.parentElement?.parentElement;
  let name = document.querySelector('[data-e2e="creator-header-name"], [data-e2e="creator-header-nickname"]')
    || header?.querySelector('[class*="nickname"], [class*="userName"], [class*="user-name"], [class*="name-"]')
    || document.querySelector('[class*="nickname"], [class*="userName"], [class*="user-name"]');
  // Only an explicit Douyin handle label is used; work-author names are never candidates.
  const handle = Array.from(document.querySelectorAll('span, p, div'))
    .find(el => el.children.length === 0 && /^抖音号[：:]\s*\S+/.test(text(el)));
  // The creator home profile card carries the handle and nickname together.
  // Stay within this card; never use a generic name from a work/feed card.
  let card = handle?.parentElement;
  let profileImage = null;
  for (let depth = 0; !text(name) && card && card !== document.body && depth < 3; depth++, card = card.parentElement) {
    profileImage = card.querySelector('img') || profileImage;
    name = Array.from(card.querySelectorAll('[class*="name"], [class*="Name"]'))
      .find(el => text(el) && text(el).length <= 160 && !text(el).includes('抖音号'));
  }
  profileImage = profileImage || (card && card !== document.body ? card.querySelector('img') : null);
  const img = (avatar?.matches('img') ? avatar : avatar?.querySelector('img')) || profileImage;
  const background = avatar ? getComputedStyle(avatar).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1] : '';
  return {nickname: text(name), uniqueId: text(handle).replace(/^抖音号[：:]\s*/, '').split(/\s/)[0], avatarUrl: img?.getAttribute('src') || background || ''};
}"""


def normalize_identity(raw: Any) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    avatar = str(raw.get('avatarUrl') or '').strip()[:4096]
    try:
        parsed = urlsplit(avatar)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            avatar = ''
    except ValueError:
        avatar = ''
    return {'nickname': str(raw.get('nickname') or '').strip()[:160],
            'uniqueId': str(raw.get('uniqueId') or '').strip()[:100], 'avatarUrl': avatar}


def read_identity(page: Any, adapter: Any, *, known_status: str | None = None) -> dict[str, Any]:
    if known_status is None:
        # The homepage initially paints a login shell before restoring the session.
        # Wait for the authenticated header before interpreting that transient shell.
        try:
            page.wait_for_selector(adapter.logged_in_selector, state="visible", timeout=5000)
        except Exception:
            pass
        status = adapter.login_state(page)
    else:
        status = known_status
    if status != 'logged_in':
        return {'status': status if status == 'login_required' else 'unknown'}
    try:
        # Header login evidence can appear before the asynchronously loaded profile.
        try:
            page.wait_for_function('() => { const profile = (' + DOUYIN_IDENTITY_SCRIPT + ')(); return Boolean(profile.nickname || profile.uniqueId); }', timeout=5000)
        except Exception:
            pass
        identity = normalize_identity(page.evaluate(DOUYIN_IDENTITY_SCRIPT))
    except Exception:
        identity = normalize_identity(None)
    return {'status': 'logged_in', **identity}


class IdentityCache:
    """Public identity only; reads do not create profiles or contact the platform."""

    def __init__(self, workspace):
        from pathlib import Path
        import threading
        self.directory = Path(workspace) / 'publisher-identities'
        self.lock = threading.RLock()
        self.deleted = set()

    def _path(self, account_id, platform):
        from pathlib import Path
        for value in (account_id, platform):
            if not isinstance(value, str) or not value or value in {'.', '..'} or Path(value).name != value:
                raise ValueError('账号身份标识无效。')
        if platform not in {'douyin', 'channels'}:
            raise ValueError('账号平台无效。')
        path = self.directory / f'{account_id}.{platform}.json'
        if self.directory.is_symlink() or path.is_symlink():
            raise ValueError('账号身份缓存路径无效。')
        return path

    def get(self, account_id, platform):
        import json
        with self.lock:
            path = self._path(account_id, platform)
            result = dict(accountId=account_id, platform=platform, status='unread',
                          nickname='', uniqueId='', avatarUrl='', updatedAt='', checkedAt='',
                          attemptedAt='', needsInitialRead=True)
            if account_id in self.deleted:
                return {**result, 'needsInitialRead': False}
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(raw, dict) or raw.get('accountId') != account_id or raw.get('platform') != platform:
                    raise ValueError('invalid cache')
                result.update({key: raw[key] for key in result if key in raw})
                result['needsInitialRead'] = not bool(result['attemptedAt'])
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                # A broken file must not turn every page visit into a remote retry.
                result.update(status='unknown', needsInitialRead=False)
            return result

    def record(self, account_id, platform, outcome):
        import json
        import uuid
        from datetime import datetime, timezone
        with self.lock:
            current = self.get(account_id, platform)
            if account_id in self.deleted:
                return current
            stamp = datetime.now(timezone.utc).isoformat()
            incoming = normalize_identity(outcome)
            status = outcome.get('status', 'unknown')
            if status not in {'logged_in', 'login_required', 'unknown', 'unbound'}:
                status = 'unknown'
            if status == 'logged_in' and (incoming['nickname'] or incoming['uniqueId']):
                old_id, new_id = current['uniqueId'], incoming['uniqueId']
                if new_id and old_id != new_id:
                    current.update(incoming)
                    current['updatedAt'] = stamp
                elif not old_id or new_id == old_id:
                    current.update({key: value for key, value in incoming.items() if value})
                    current['updatedAt'] = stamp
                # Without a handle, do not blend an unverified new name with a known old handle.
            current.update(status=status, checkedAt=stamp,
                           attemptedAt=current['attemptedAt'] or stamp, needsInitialRead=False)
            path = self._path(account_id, platform)
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
            try:
                temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return current

    def delete(self, account_id):
        with self.lock:
            paths = [self._path(account_id, platform) for platform in ('douyin', 'channels')]
            self.deleted.add(account_id)
            for path in paths:
                path.unlink(missing_ok=True)
