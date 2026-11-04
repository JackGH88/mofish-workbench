"""Process-local invalidations; durable import receipts remain the source of truth."""
import asyncio


class ImportEventHub:
    def __init__(self):
        self.queues = set()
        self.accepting = True

    def publish(self):
        for queue in self.queues:
            if queue.empty():
                queue.put_nowait(True)

    def pause(self):
        self.accepting = False
        for queue in self.queues:
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)

    def resume(self):
        self.accepting = True

    async def stream(self):
        if not self.accepting:
            yield 'retry: 1000\n: restarting\n\n'
            return
        queue = asyncio.Queue(maxsize=1)
        self.queues.add(queue)
        try:
            yield 'retry: 1000\nevent: ready\ndata: {}\n\n'
            while True:
                try:
                    change = await asyncio.wait_for(queue.get(), 20)
                    if change is None:
                        return
                    yield 'event: change\ndata: {}\n\n'
                except asyncio.TimeoutError:
                    yield ': keepalive\n\n'
        finally:
            self.queues.discard(queue)


hub = ImportEventHub()
