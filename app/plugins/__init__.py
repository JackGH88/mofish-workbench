"""通用插件宿主基础能力。

宿主只认识插件清单、生命周期状态与通用凭据引用，不依赖任何具体供应商
（例如 HeyGen）的字段、端点或业务实现；供应商实现全部落在各自插件包内。
"""
from __future__ import annotations

# 宿主与插件之间的接口版本。插件清单声明兼容范围，宿主只加载兼容版本。
PLUGIN_HOST_API_VERSION = "1"

__all__ = ["PLUGIN_HOST_API_VERSION"]
