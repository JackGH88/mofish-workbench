"""Process-wide, non-waiting exclusion between plugin HTTP requests and moves.

This does not cover plugin background workers. Recovery blocks deny new request
leases, but allow exclusive recovery work; the move service must check pending
recovery before accepting a new move.
"""
from contextlib import contextmanager
import threading

from .registry import PluginError


class MoveGuard:
    def __init__(self):
        self._condition = threading.Condition()
        self._requests: dict[str, int] = {}
        self._exclusive: set[str] = set()
        self._blocked: set[str] = set()

    @contextmanager
    def lease(self, account: str):
        with self._condition:
            if account in self._exclusive or account in self._blocked:
                raise PluginError('script_move_busy', '脚本正在迁移或等待恢复，请稍后再试。', 409)
            self._requests[account] = self._requests.get(account, 0) + 1
        try:
            yield
        finally:
            with self._condition:
                remaining = self._requests[account] - 1
                if remaining:
                    self._requests[account] = remaining
                else:
                    del self._requests[account]
                self._condition.notify_all()

    @contextmanager
    def exclusive(self, accounts):
        accounts = {accounts} if isinstance(accounts, str) else set(accounts)
        with self._condition:
            if accounts & self._exclusive or any(self._requests.get(a, 0) for a in accounts):
                raise PluginError('script_move_busy', '工作台插件正在处理请求，请稍后再移动脚本。', 409)
            self._exclusive.update(accounts)
        try:
            yield
        finally:
            with self._condition:
                self._exclusive.difference_update(accounts)
                self._condition.notify_all()

    def set_blocked(self, accounts, blocked: bool):
        accounts = {accounts} if isinstance(accounts, str) else set(accounts)
        with self._condition:
            if blocked:
                self._blocked.update(accounts)
            else:
                self._blocked.difference_update(accounts)
            self._condition.notify_all()

    def is_blocked(self, account: str) -> bool:
        with self._condition:
            return account in self._blocked


move_guard = MoveGuard()
lease = move_guard.lease
exclusive = move_guard.exclusive
set_blocked = move_guard.set_blocked
is_blocked = move_guard.is_blocked
