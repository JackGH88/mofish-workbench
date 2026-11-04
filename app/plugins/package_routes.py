"""Generic local package import endpoints and immutable frontend assets."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from .packages import MAX_ARCHIVE, PackageError
from .move_guard import lease


class UninstallPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False


class ConfirmPackage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str
    trusted: bool = False


def build_package_router(manager):
    router = APIRouter(prefix='/api/plugins/packages', dependencies=[Depends(manager.registry.account_dependency)])

    @router.post('/check')
    async def inspect_package(file: UploadFile = File(...)):
        try:
            raw = await file.read(MAX_ARCHIVE + 1)
            return manager.inspect(raw, manager.registry.account_id)
        except PackageError as exc:
            raise HTTPException(exc.status_code, detail=dict(code=exc.code, message=exc.message)) from None
        finally:
            await file.close()

    @router.post('/confirm')
    def confirm_package(payload: ConfirmPackage):
        try:
            return manager.confirm(payload.token, manager.registry.account_id, trusted=payload.trusted)
        except PackageError as exc:
            raise HTTPException(exc.status_code, detail=dict(code=exc.code, message=exc.message)) from None

    @router.post('/{plugin_id}/uninstall')
    async def uninstall_package(plugin_id: str, payload: UninstallPackage):
        try:
            return await manager.uninstall_global(plugin_id, confirmed=payload.confirmed)
        except PackageError as exc:
            raise HTTPException(exc.status_code, detail=dict(code=exc.code, message=exc.message)) from None

    return router


def build_asset_router(manager):
    router = APIRouter()

    @router.get('/api/plugin-assets/{account}/{plugin_id}/{version}/{name:path}', dependencies=[Depends(manager.registry.account_dependency)])
    def plugin_asset(account: str, plugin_id: str, version: str, name: str):
        try:
            path = manager.asset(account, plugin_id, version, name)
            return FileResponse(path, headers={'Cache-Control': 'private, max-age=31536000, immutable',
                                               'X-Content-Type-Options': 'nosniff'})
        except PackageError as exc:
            raise HTTPException(exc.status_code, detail=dict(code=exc.code, message=exc.message)) from None
    return router


class PluginRequestGuard:
    """Dispatch to an owner's runtime; leases include streaming and background work."""
    def __init__(self, app, manager):
        self.app, self.manager = app, manager
        self.runtimes = {}

    async def __call__(self, scope, receive, send):
        from urllib.parse import parse_qs
        from fastapi import FastAPI
        from .registry import PluginError
        parts = scope.get('path', '').split('/')
        if scope['type'] != 'http' or len(parts) < 5 or parts[1:3] != ['api', 'plugins']:
            return await self.app(scope, receive, send)
        pid = parts[3]
        delegated = pid == 'packages' or parts[4] in {'install', 'uninstall', 'enable', 'disable', 'credentials'}
        try:
            accounts = parse_qs(scope.get('query_string', b'').decode()).get('accountId', [])
            if delegated:
                # Keep normal validation in host routes; cover their complete
                # request lifetime just like runtime dispatch, including GET.
                if accounts:
                    from contextlib import ExitStack
                    with ExitStack() as stack:
                        for account in sorted(set(accounts)):
                            stack.enter_context(lease(account))
                        return await self.app(scope, receive, send)
                return await self.app(scope, receive, send)
            if len(accounts) != 1 or not accounts[0] or len(accounts[0]) > 100:
                raise PluginError('account_required', '请先选择工作台。', 422)
            account = accounts[0]
            with lease(account), self.manager.registry.account_scope(account):
                if hasattr(self.manager, 'ensure_account_runtimes'):
                    await self.manager.ensure_account_runtimes(account)
                manager = self.manager._current()
                with manager.request_lease(pid):
                    record = manager.state.read(pid)
                    if record.get('uninstalled') or not manager.registry.state_view(pid)['installed']:
                        raise PluginError('plugin_not_found', '当前工作台未安装此插件。', 404)
                    entry = manager.registry._require_entry(pid)
                    if entry.load_error:
                        raise PluginError('plugin_broken', '插件加载失败。', 409)
                    if (not self.manager.mutation_allowed(pid, scope['method'], scope['path'])
                            if hasattr(self.manager, 'mutation_allowed') else
                            scope['method'] not in ('GET', 'HEAD') and manager.metadata(pid)['restartRequired']):
                        raise PluginError('restart_required', '插件升级待生效，请重启工作台后再操作。', 409)
                    key = (account, pid, id(entry))
                    if key not in self.runtimes:
                        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
                        app.include_router(entry.context.router, prefix='/api/plugins/' + pid)
                        self.runtimes[key] = app
                    return await self.runtimes[key](scope, receive, send)
        except PluginError as exc:
            return await JSONResponse({'detail': {'code': exc.code, 'message': exc.message}}, status_code=exc.status_code)(scope, receive, send)
