"""Git release primitives shared by the publisher and the local updater.

All commands use argument arrays, noninteractive authentication and bounded waits.
Raw Git errors are not returned because remote URLs may contain credentials.
"""
from __future__ import annotations
import os
import re
import subprocess
from .release_feed import REPOSITORY_URL
from pathlib import Path

VERSION_RE = re.compile(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')


class VersionError(RuntimeError):
    pass


def version_key(tag):
    match = VERSION_RE.fullmatch(tag or '')
    return tuple(map(int, match.groups())) if match else None


class Repository:
    def __init__(self, root, verify_origin=True):
        self.root = Path(root).resolve()
        self.verify_origin = verify_origin

    def git(self, *args, timeout=60):
        env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never',
               'GIT_SSH_COMMAND': 'ssh -oBatchMode=yes -oConnectTimeout=15'}
        try:
            result = subprocess.run(['git', '-C', str(self.root), *args], env=env,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VersionError('Git 不可用或操作超时，请检查 Git 安装、网络和仓库访问权限。') from exc
        if result.returncode:
            raise VersionError('Git 操作失败，请检查网络、仓库权限及本地分支状态。')
        return result.stdout.strip()

    def check_root(self):
        if Path(self.git('rev-parse', '--show-toplevel')).resolve() != self.root:
            raise VersionError('当前目录不是独立 Git 仓库根目录，不能执行版本操作。')

    def check_origin(self):
        self.check_root()
        if not self.verify_origin:
            return
        url = self.git('remote', 'get-url', 'origin')
        slug = REPOSITORY_URL.removeprefix('https://github.com/')
        if url not in (REPOSITORY_URL, REPOSITORY_URL + '.git',
                       'git@github.com:' + slug + '.git',
                       'ssh://git@github.com/' + slug + '.git'):
            raise VersionError('更新来源必须是 ' + slug + ' 的 origin 仓库。')

    def remote_tags(self):
        self.check_origin()
        result = {}
        for line in self.git('ls-remote', '--tags', 'origin').splitlines():
            sha, ref = line.split('\t', 1)
            tag = ref.removeprefix('refs/tags/').removesuffix('^{}')
            if version_key(tag):
                entry = result.setdefault(tag, {})
                entry['commit' if ref.endswith('^{}') else 'object'] = sha
        return result

    def latest(self):
        tags = self.remote_tags()
        if not tags:
            return None
        tag = max(tags, key=version_key)
        expected = tags[tag].get('commit', tags[tag]['object'])
        ref = 'refs/workbench/releases/' + tag
        self.git('fetch', '--no-tags', 'origin', f'refs/tags/{tag}:{ref}')
        commit = self.git('rev-parse', ref + '^{commit}')
        if commit != expected:
            raise VersionError('远程版本在检查期间发生变化，请重新检查更新。')
        stored = self.git('show', f'{commit}:VERSION')
        if stored != tag[1:]:
            raise VersionError('版本 Tag 与 VERSION 文件不一致，不能安装。')
        kind = self.git('cat-file', '-t', ref)
        notes = self.git('for-each-ref', '--format=%(contents)', ref) if kind == 'tag' else ''
        if not notes:
            notes = self.git('log', '-1', '--format=%s', commit)
        return {'tag': tag, 'version': tag[1:], 'commit': commit, 'notes': notes[:32000]}

    def running(self):
        try:
            value = (self.root / 'VERSION').read_text(encoding='utf-8').strip()
        except OSError:
            value = ''
        result = {'version': value if version_key('v' + value) else None,
                  'commit': None, 'development': True}
        try:
            result['commit'] = self.git('rev-parse', 'HEAD')
            refs = self.git('for-each-ref', '--points-at=HEAD', '--format=%(refname)',
                            'refs/tags', 'refs/workbench/releases').splitlines()
            exact = any(ref.rsplit('/', 1)[-1] == 'v' + value for ref in refs)
            result['development'] = not exact or bool(self.git('status', '--porcelain', '--untracked-files=all'))
        except VersionError:
            pass
        return result

    def preflight(self, target):
        self.check_root()
        if not re.fullmatch(r'[0-9a-f]{40,64}', target):
            raise VersionError('无效的目标提交。')
        protected = self.git('ls-tree', '-r', '--name-only', target, '--',
                             '.env', 'workspace', 'downloads', 'logs', '.venv', 'venv')
        if protected:
            raise VersionError('目标版本包含本地配置或用户资料目录，已阻止更新以保护资料。')
        if self.git('branch', '--show-current') != 'main':
            raise VersionError('请切换到 main 分支后更新。')
        if self.git('status', '--porcelain', '--untracked-files=all'):
            raise VersionError('本地有未提交修改或未跟踪文件，请处理后再更新。')
        try:
            self.git('merge-base', '--is-ancestor', 'HEAD', target)
        except VersionError as exc:
            raise VersionError('本地有独有提交或无法快进到目标版本，请先处理分支差异。') from exc
        return self.git('rev-parse', 'HEAD')

    def install(self, target):
        self.preflight(target)
        self.git('merge', '--ff-only', target)

    def rollback(self, target, previous):
        if self.git('rev-parse', 'HEAD') != target or self.git('status', '--porcelain', '--untracked-files=all'):
            raise VersionError('检测到后续本地改动，未自动回退，请人工处理。')
        self.git('reset', '--keep', previous)

    def push_release(self, tag):
        self.git('push', '--atomic', 'origin', 'refs/heads/main:refs/heads/main',
                 f'refs/tags/{tag}:refs/tags/{tag}', timeout=120)
