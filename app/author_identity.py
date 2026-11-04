"""Read saved author identity without network requests or nickname guessing."""
from urllib.parse import urlsplit
import re


def read_author_identity(metadata, share_text=''):
    saved = metadata.get('authorIdentity')
    saved = saved if isinstance(saved, dict) else {}
    raw = metadata.get('mediaMetadata')
    raw = raw if isinstance(raw, dict) else {}
    author = raw.get('author')
    author = author if isinstance(author, dict) else {}
    platform = str(saved.get('platform') or raw.get('site') or '').strip().lower()
    if not platform:
        match = re.search(r'https?://[^\s]+', share_text or '')
        host = (urlsplit(match.group(0)).hostname or '').lower() if match else ''
        if host == 'douyin.com' or host.endswith('.douyin.com') or host == 'iesdouyin.com' or host.endswith('.iesdouyin.com'):
            platform = 'douyin'
    if saved.get('uid') or saved.get('uniqueId'):
        return {'platform': platform, 'uid': str(saved.get('uid') or '').strip(), 'uniqueId': str(saved.get('uniqueId') or '').strip()}
    return {'platform': platform, 'uid': str(author.get('id') or '').strip(), 'uniqueId': str(author.get('username') or '').strip()}
