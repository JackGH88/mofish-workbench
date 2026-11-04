"""Ephemeral, account-scoped invalidations for the single-process local host.

Reconnect always sends ready so clients re-read durable state; no replay ledger
or task polling is needed. Notification streams do not acquire plugin leases.
"""
import asyncio
import json
from contextlib import contextmanager
from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse


class EventHub:
    def __init__(self):
        self.subscribers = {}
        self.accepting = True

    def pause(self):
        """Close every account's idle stream before the HTTP server starts draining."""
        self.accepting = False
        for queues in self.subscribers.values():
            for queue in queues:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    def resume(self):
        self.accepting = True

    @contextmanager
    def subscribe(self, account):
        queue = asyncio.Queue(maxsize=32)
        self.subscribers.setdefault(account, set()).add(queue)
        try:
            yield queue
        finally:
            self.subscribers[account].discard(queue)
            if not self.subscribers[account]:
                del self.subscribers[account]

    def publish(self, account, plugin_id, script_id, notice=None):
        # Called on the request event loop, after the durable mutation completes.
        if not self.accepting:
            return
        for queue in self.subscribers.get(account, ()):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({'resync': True})
            else:
                queue.put_nowait({'pluginId': plugin_id, 'scriptId': script_id, **({'notice': notice} if notice else {})})

    async def stream(self, account):
        if not self.accepting:
            return
        with self.subscribe(account) as queue:
            yield 'retry: 5000\nevent: ready\ndata: {}\n\n'
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20)
                    if data is None:
                        return
                    yield 'event: change\ndata: ' + json.dumps(data) + '\n\n'
                except asyncio.TimeoutError:
                    yield ': keepalive\n\n'


hub = EventHub()


def build_router(registry):
    router = APIRouter(dependencies=[Depends(registry.account_dependency)])

    @router.get('/api/plugin-events')
    async def events():
        if not hub.accepting:
            # End immediately without subscribing, but keep EventSource retrying.
            return Response('retry: 1000\n: restarting\n\n', media_type='text/event-stream',
                            headers={'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no'})
        return StreamingResponse(hub.stream(registry.account_id), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no'})
    return router
