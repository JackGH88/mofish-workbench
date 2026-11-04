"""只读平台权益校验与监控阻断恢复，不负责支付或发放积分。"""
import asyncio
import logging
import time

from .subscription import points

logger = logging.getLogger("douyin-downloader")


class MonitorSubscriptionRecovery:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_key = None
        self._last_check = 0.0

    async def check(self, store, service, *, balance=None, subscription=None, owner=None):
        if service.mode != "live" or not service.session_view().get("loggedIn"):
            return 0
        identity = owner if owner is not None else service.payment_owner()
        async with self._lock:
            if not store.has_subscription_blocks():
                return 0
            key = (id(store), identity)
            supplied = balance is not None
            # 页面刷新可复用刚取得的权威结果；后台失败和余额未恢复时一分钟最多查一次。
            if not supplied and key == self._last_key and time.monotonic() - self._last_check < 60:
                return 0
            self._last_key, self._last_check = key, time.monotonic()
            try:
                if balance is None:
                    balance = await service.balance()
                if points(balance.get("available")) <= 0:
                    return 0
                if service.payment_owner() != identity or not service.session_view().get("loggedIn"):
                    return 0
                # 身份复核和写入间不让出事件循环，避免登录切换穿插。
                return store.release_subscription_blocks(str(balance["available"]))
            except Exception:
                logger.warning("monitor_subscription_recovery_unavailable")
                return 0
