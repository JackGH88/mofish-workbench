"""Account checked HTTP surface for unified recommendations."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal
from .topic_recommendation_availability import require_available

class AccountRequest(BaseModel):
    accountId: str

class SettingsRequest(AccountRequest):
    aiEnabled: bool
    aiDailyTime: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    sources: dict[str, bool]

class TopicRequest(AccountRequest):
    title: str = Field(min_length=1,max_length=1000)
    outline: str = Field(default='',max_length=2000)
    category: Literal['highlight','daily','series','test'] = 'highlight'
    format: Literal['video','article'] = 'video'
    weekPlan: Literal['current','next'] = 'current'

class SaveRequest(AccountRequest):
    saved: bool

def build_router(runtime):
    router = APIRouter(prefix='/api/topic-recommendations', dependencies=[Depends(require_available)])
    async def account(aid):
        await runtime.h._require_account(aid)
        await runtime.h.run_io(runtime.ensure, aid)
        return aid
    async def view(aid):
        return await runtime.overview_with_notice(aid)
    async def item(aid,key):
        await account(aid)
        try:
            return await runtime.h.run_io(runtime.store.item,aid,key)
        except KeyError:
            raise HTTPException(404,'选题不存在')
    async def work(aid,key):
        await account(aid)
        rows = await runtime.h.run_io(runtime.works,aid)
        found = next((w for w in rows if w['id']==key),None)
        if not found:
            raise HTTPException(404,'当前账号未采集该作品')
        return found

    @router.get('')
    async def overview(accountId:str):
        await account(accountId)
        return await view(accountId)

    @router.get('/settings')
    async def settings(accountId:str):
        await account(accountId)
        return runtime.store.get(accountId)['settings']

    @router.patch('/settings')
    async def update_settings(payload:SettingsRequest):
        aid = await account(payload.accountId)
        fields = payload.model_dump(exclude={'accountId'})
        fields['sources'] = {k:fields['sources'].get(k,False) for k in ('monitor','radar')}
        runtime.store.update_settings(aid,fields)
        return runtime.store.get(aid)['settings']

    @router.post('/generate')
    async def generate(payload:AccountRequest):
        aid = await account(payload.accountId)
        runtime.h._require_workbench()
        result = await runtime.overview_with_notice(aid, check_cost=True)
        if result['noticeCode'] in {'insufficient_points', 'subscription_required', 'subscription_expired',
                                    'entitlements_unavailable', 'state_changed'}:
            result['started'] = 'blocked'
            return result
        status = await runtime.start(aid)
        result = await view(aid)
        result['started'] = status
        return result

    @router.get('/status')
    async def status(accountId:str):
        await account(accountId)
        return (await view(accountId))['job']

    @router.get('/history')
    async def history(accountId:str):
        await account(accountId)
        return {'items':runtime.store.get(accountId)['history']}

    @router.get('/feed')
    async def feed(accountId:str,source:Literal['all','radar','monitor']='all',page:int=Query(1,ge=1),pageSize:int=Query(6,ge=1,le=100)):
        await account(accountId)
        rows = await runtime.h.run_io(runtime.works,accountId)
        rows = [w for w in rows if source=='all' or source in w['sources']]
        pages = max(1,(len(rows)+pageSize-1)//pageSize)
        page = min(page,pages)
        return {'items':rows[(page-1)*pageSize:page*pageSize], 'total':len(rows),'page':page,'pageSize':pageSize,'pages':pages}

    @router.get('/works/{key}')
    async def detail(key:str,accountId:str):
        return await work(accountId,key)

    @router.post('/works/{key}/saved')
    async def saved(key:str,payload:SaveRequest):
        row = await work(payload.accountId,key)
        for ref in row['sourceRecords']:
            store = getattr(runtime.h,ref['source']+'_store')
            await runtime.h.run_io(store.set_saved,payload.accountId,ref['id'],payload.saved)
        return {'saved':payload.saved}

    async def add(row,payload,recommendation=False):
        fields = runtime.h._original_topic_fields(row,payload)
        try:
            topic = await runtime.h.run_io(runtime.h.workspace_store.create_topic,payload.accountId,fields)
        except ValueError as exc:
            raise HTTPException(400,str(exc))
        if recommendation:
            await runtime.h.run_io(runtime.store.attach_topic,payload.accountId,row['key'],topic['id'])
        return {'topic':topic,'recommendation':await view(payload.accountId)}

    @router.post('/works/{key}/topic')
    async def work_topic(key:str,payload:TopicRequest):
        row = await work(payload.accountId,key)
        return await add({'key':key,'sourceWork':row,'sourceWorkId':key},payload)

    @router.get('/{key}/evidence')
    async def evidence(key:str,accountId:str):
        row = await item(accountId,key)
        return {**row,'analysis':{'scope':row.get('scope'),'gaps':row.get('gaps') or []}}

    @router.post('/{key}/topic')
    async def topic(key:str,payload:TopicRequest):
        row = await item(payload.accountId,key)
        return await add(row,payload,True)

    @router.post('/{key}/dismiss')
    async def dismiss(key:str,payload:AccountRequest):
        await item(payload.accountId,key)
        await runtime.h.run_io(runtime.store.dismiss,payload.accountId,key,True)
        return await view(payload.accountId)

    @router.post('/{key}/restore')
    async def restore(key:str,payload:AccountRequest):
        await item(payload.accountId,key)
        await runtime.h.run_io(runtime.store.dismiss,payload.accountId,key,False)
        return await view(payload.accountId)
    return router
