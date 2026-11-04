"""通用凭据存储：机密值只进系统密钥库，读取接口永远不回原值。

优先使用可选依赖 ``keyring``；不可用时回退到 macOS ``security`` CLI。
两者都不可用时直接报错，绝不把明文写进普通配置文件。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger("workbench.plugins.credentials")

SERVICE_NAME = "ai-short-video-workbench.plugin"


class CredentialStoreUnavailable(RuntimeError):
    """当前系统没有可用的安全凭据存储。"""


@runtime_checkable
class CredentialStore(Protocol):
    def available(self) -> bool:
        ...

    def get(self, ref: str) -> Optional[str]:
        ...

    def set(self, ref: str, secret: str) -> None:
        ...

    def delete(self, ref: str) -> None:
        ...


class InMemoryCredentialStore:
    """测试替身：只在内存里保存，不接触系统密钥库。"""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def get(self, ref: str) -> Optional[str]:
        return self._values.get(ref)

    def set(self, ref: str, secret: str) -> None:
        self._values[ref] = secret

    def delete(self, ref: str) -> None:
        self._values.pop(ref, None)


class KeyringCredentialStore:
    """基于可选依赖 ``keyring`` 的凭据存储。"""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    @staticmethod
    def module():
        import keyring  # noqa: PLC0415 - 可选依赖，按需导入

        return keyring

    def available(self) -> bool:
        try:
            return self.module().get_keyring() is not None
        except Exception:  # noqa: BLE001 - 后端不可用按不可用处理
            return False

    def get(self, ref: str) -> Optional[str]:
        try:
            return self.module().get_password(self._service, ref)
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable("读取系统密钥库失败") from exc

    def set(self, ref: str, secret: str) -> None:
        try:
            self.module().set_password(self._service, ref, secret)
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable("写入系统密钥库失败") from exc

    def delete(self, ref: str) -> None:
        try:
            self.module().delete_password(self._service, ref)
        except Exception:  # noqa: BLE001 - 不存在时忽略
            return


class MacKeychainCredentialStore:
    """macOS 系统密钥库（security CLI）。

    注意：``security`` 不读 stdin，密码以命令行参数传入进程，存在极短暂的
    argv 暴露窗口；相比写入明文文件仍是显著更强的保护，且不留明文落盘。
    """

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service
        self._security = shutil.which("security")

    def available(self) -> bool:
        return bool(self._security)

    def _run(self, args: list[str]):
        if not self._security:
            raise CredentialStoreUnavailable("系统密钥库不可用")
        return subprocess.run(
            [self._security, *args], check=False, capture_output=True, text=True
        )

    def get(self, ref: str) -> Optional[str]:
        if not self._security:
            return None
        result = self._run(["find-generic-password", "-a", ref, "-s", self._service, "-w"])
        if result.returncode == 44:  # errSecItemNotFound
            return None
        if result.returncode != 0:
            raise CredentialStoreUnavailable("读取系统密钥库失败")
        value = result.stdout.rstrip("\n")
        return value or None

    def set(self, ref: str, secret: str) -> None:
        result = self._run(
            ["add-generic-password", "-a", ref, "-s", self._service, "-w", secret, "-U"]
        )
        if result.returncode != 0:
            raise CredentialStoreUnavailable("写入系统密钥库失败")

    def delete(self, ref: str) -> None:
        if not self._security:
            return
        self._run(["delete-generic-password", "-a", ref, "-s", self._service])


def default_credential_store() -> CredentialStore:
    """选择可用的安全凭据存储；没有可用实现时抛错，不做明文回退。"""
    try:
        import keyring  # noqa: F401,PLC0415
    except Exception:  # noqa: BLE001 - 未安装则尝试系统密钥库
        pass
    else:
        store = KeyringCredentialStore()
        if store.available():
            return store
    mac = MacKeychainCredentialStore()
    if mac.available():
        return mac
    raise CredentialStoreUnavailable(
        "当前系统没有可用的安全凭据存储；请安装 keyring，或在 macOS 上启用 security。"
    )


class UnavailableCredentialStore:
    """没有任何安全存储可用时的占位实现：禁止写入，绝不落明文。"""

    def available(self) -> bool:
        return False

    def get(self, ref: str) -> Optional[str]:
        return None

    def set(self, ref: str, secret: str) -> None:
        raise CredentialStoreUnavailable("当前系统没有可用的安全凭据存储，无法保存凭据。")

    def delete(self, ref: str) -> None:
        return None
