"""Generic local assistant handoff for installed plugins. No plugin business state."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from .writing_assistants import launch_uri, open_assistant_uri, atomic_json, AssistantError, assistant_mismatch_message

WORKBUDDY_PREVIEW_PATH = '/static/assistant-task-preview.html'
DEFAULT_WORKBUDDY_SIDEBAR = 'http://127.0.0.1:8001' + WORKBUDDY_PREVIEW_PATH


class PluginAssistantService:
    def __init__(self, manager):
        self.manager = manager

    def ready(self, agent=None):
        return self.manager.ready(agent) if agent is not None else self.manager.ready()

    def codex_cli_path(self, app_path=None):
        """Locate the Codex app-server CLI without assuming the PATH wrapper is current."""
        candidates = []
        if app_path:
            app = Path(app_path)
            candidates.extend([
                app / 'Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                app / 'Contents/Resources/codex-cli/codex',
                app / 'resources/codex-cli/codex.exe',
                app / 'resources/codex-cli/bin/codex.exe',
            ])
        found = shutil.which('codex')
        if found:
            candidates.append(Path(found))
        for candidate in candidates:
            try:
                if Path(candidate).is_file():
                    return str(Path(candidate))
            except OSError:
                continue
        return ''

    def _workbuddy_permission_mode(self):
        path = self.manager.home / '.workbuddy' / 'workbuddy.db'
        if not path.is_file():
            return ''
        try:
            with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=2) as db:
                row = db.execute(
                    "select permission_mode from sessions "
                    "where deleted_at is null and permission_mode is not null "
                    "order by updated_at desc limit 1"
                ).fetchone()
            return str(row[0] or '') if row else ''
        except sqlite3.Error:
            return ''

    def unattended_status(self, agent=None):
        """Whether the assistant can run a scheduled task without a human clicking send."""
        app = self.ready(agent)
        agent_id = app['id']
        if agent_id == 'workbuddy':
            mode = self._workbuddy_permission_mode()
            if mode != 'fullAccess':
                return {
                    'ok': False,
                    'agentId': agent_id,
                    'permissionMode': mode,
                    'message': 'WorkBuddy 当前权限不是 fullAccess，定时任务无法无人值守执行。请先在 WorkBuddy 中调整权限。',
                }
            from .native_send import NativeSendClient
            return {**NativeSendClient().status(), 'agentId': agent_id, 'permissionMode': mode}
        cli = self.codex_cli_path(app.get('path', ''))
        if not cli:
            return {
                'ok': False,
                'agentId': agent_id,
                'message': '未找到 Codex 命令行，暂时无法创建定时任务。',
            }
        return {
            'ok': True,
            'agentId': agent_id,
            'cliPath': cli,
            'message': 'Codex 将自动打开任务会话并执行，可在窗口实时查看。',
        }

    def native_send_action(self, action):
        from .native_send import NativeSendClient
        return NativeSendClient().action(action)

    def native_send_download(self):
        from .runtime import RESOURCE_ROOT
        path = RESOURCE_ROOT / 'downloads/workbench-assistant-local.dmg'
        if not path.is_file():
            raise ValueError('助手安装包尚未提供，请联系工作台维护者。')
        return path

    def native_send_guidance(self, code):
        from .native_send import guidance
        from .runtime import DESKTOP
        return guidance(code, DESKTOP)

    def submit_scheduled(self, task_id, prompt, directory):
        from .native_send import NativeSendClient, NativeSendError
        if self._workbuddy_permission_mode() != 'fullAccess':
            raise NativeSendError('workbuddy_permission')
        return NativeSendClient().submit(task_id, prompt, directory)

    def record_return(self, agent):
        """A real video/writing return is proof the installed skill works end to end."""
        return self.manager.record_return(agent, source='return')

    def install_skill(self, agent, source):
        """Never overwrite existing skills. Frozen task copies remain authoritative."""
        source = Path(source)
        target = self.manager.skill_directory(agent).parent / source.name
        if target.exists() or target.is_symlink():
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.install-' + uuid.uuid4().hex)
        try:
            shutil.copytree(source, temp)
            # Another task may have installed it while this copy was prepared.
            if not target.exists(): temp.rename(target)
        finally:
            if temp.exists(): shutil.rmtree(temp)
        return str(target)

    def prepare(self, directory, prompt, skills, working_directory=None, agent=None, sidebar_url=None):
        app = self.ready(agent)
        for skill in skills: self.install_skill(app['id'], skill)
        directory = Path(directory).resolve()
        uri = (self.workbuddy_draft_uri(prompt, sidebar_url) if app['id'] == 'workbuddy' else
               launch_uri(app['id'], prompt, Path(working_directory).resolve() if working_directory is not None else directory))
        prepared = {'agentId': app['id'], 'assistantName': app['name'],
                    'contextPath': str(directory / 'context.md'), 'prompt': prompt,
                    'uri': uri, 'sidebarUrl': sidebar_url or DEFAULT_WORKBUDDY_SIDEBAR}
        atomic_json(directory / 'launch.json', prepared)
        return prepared

    @staticmethod
    def workbuddy_draft_uri(prompt, sidebar_url=None):
        # task?action=start immediately sends; conversation/open supports drafts.
        uri = 'workbuddy://conversation/open?' + urlencode({
            'promptContentBlocks': json.dumps([{'type': 'text', 'text': prompt}], ensure_ascii=False),
            'autoSend': 'false',
            'sidebarUrl': sidebar_url or DEFAULT_WORKBUDDY_SIDEBAR,
        })
        if len(uri.encode('utf-8')) > 6000:
            raise AssistantError('任务指令过长，无法完整预填。', 'assistant_link_too_long', 400)
        return uri

    def launch(self, prepared, working_directory=None, agent=None):
        if working_directory is not None and prepared['agentId'] == 'codex':
            prepared = {**prepared, 'uri': launch_uri('codex', prepared['prompt'], Path(working_directory).resolve())}
        if prepared['agentId'] == 'workbuddy':
            # Rebuild cached launches too, preserving the latest prompt without a sidebar.
            prepared = {**prepared, 'uri': self.workbuddy_draft_uri(prepared['prompt'], prepared.get('sidebarUrl'))}
            app = self.ready(agent)
            if app['id'] != prepared['agentId']:
                raise AssistantError(assistant_mismatch_message(prepared['agentId'], app['id']))
            # WorkBuddy 5.5.3 can consume/clear a draft while leaving an existing
            # conversation. Navigate first so its home composer can receive it.
            open_assistant_uri(app['id'], 'workbuddy://home', app['path'], self.manager.platform)
            time.sleep(1)
        if agent is None:
            self.manager.launch(prepared)
        else:
            self.manager.launch(prepared, agent=agent)

    def resolve_session(self, agent, directory, bound_id=''):
        from .assistant_sessions import resolve_session
        return resolve_session(agent, self.manager.home, directory, bound_id)

    def activate(self, agent):
        """Bring the app forward without replacing an unsent composer draft."""
        settings = self.manager.settings()
        app = self.manager.inspect_app(agent, settings.get('apps', {}).get(agent, {}).get('path', ''))
        if not app.get('installed'):
            raise AssistantError('未找到此任务使用的助手，请先安装或配置该助手。')
        try:
            if self.manager.platform == 'darwin':
                subprocess.run(['/usr/bin/open', '-a', app['path']], check=True, timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self.manager.platform == 'win32':
                os.startfile(app['path'])
            else:
                raise AssistantError('目前仅支持 macOS 和 Windows 原生桌面。')
        except (OSError, subprocess.SubprocessError):
            raise AssistantError('未能打开助手，原任务已保留。', 'assistant_launch_failed', 503) from None

    def open_session(self, agent, session_id, directory):
        from urllib.parse import quote
        if agent not in ('codex', 'workbuddy') or not session_id:
            raise AssistantError('原会话信息无效。')
        settings = self.manager.settings()
        app = self.manager.inspect_app(agent, settings.get('apps', {}).get(agent, {}).get('path', ''))
        if not app.get('installed'):
            raise AssistantError('未找到此任务使用的助手，请先安装或配置该助手。')
        if agent == 'codex':
            uri = 'codex://threads/' + quote(session_id, safe='')
        else:
            uri = 'workbuddy://conversation/open?' + urlencode({
                'taskId': session_id, 'autoSend': 'false', 'sidebarUrl': DEFAULT_WORKBUDDY_SIDEBAR})
        open_assistant_uri(agent, uri, app['path'], self.manager.platform)

    def environment(self):
        def available(name):
            path = shutil.which(name)
            if not path and os.name != 'nt':
                path = next((str(p) for p in (Path('/opt/homebrew/bin')/name, Path('/usr/local/bin')/name) if p.is_file()), None)
            return path
        node = available('node'); node_ok = False
        if node:
            try:
                node_ok = int(subprocess.check_output([node, '--version'], timeout=5, text=True).strip().lstrip('v').split('.')[0]) >= 22
            except (ValueError, OSError, subprocess.SubprocessError): pass
        return {'node': node_ok, 'ffmpeg': bool(available('ffmpeg')), 'ffprobe': bool(available('ffprobe')),
                'alignment': '待在助手中验证逐词对齐能力',
                'message': '预设需要 Node.js 22+、FFmpeg/ffprobe；HyperFrames 和逐词对齐由助手在任务工程中检测并准备。'}
