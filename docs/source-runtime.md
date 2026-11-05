# 源码安装运行时工具

运行时发布状态以**所安装正式 Tag** 的 `distribution/source-runtime.json` 为准，而非 main、本文的编写时间或本地构建产物。读取当前平台的 `windows-x64` / `macos-arm64` 条目：存在有效发布条目时自动使用；无条目时明确说明并走官方依赖准备回退。不要固定宣称运行时“永未发布”或假定两个平台同时可用。

## Agent 安装流程

先通过 HTTP 阅读官方 README，再检查和准备 Git、核对正式 Release 的 Tag 与提交，随后读取该目标版本的 README、本文件、清单和安装脚本。已有安装保留配置、数据和本地修改，先检查后按失败阶段续跑，不重复克隆或全量重装。完整命令、Chrome 安装、服务和本地媒体/浏览器冒烟及能力报告要求见同版本 [README](../README.md)。

运行时通过同一个官方仓库的 Release assets 分发，包含独立 Python 3.11/3.12、预编译 wheel 依赖及 FFmpeg/ffprobe；无需增加仓库或另建安装器。Git 是首次由 Agent 准备的源码工具，Chrome 是另外安装和验收的浏览器。 清单中的下载地址按顺序尝试：官网镜像优先、GitHub Release 备用，两者使用相同的大小和 SHA-256 校验。

- 目标版本有匹配有效条目时，使用其官方 `install.sh` / `install.ps1` 入口自动获取、校验并使用运行时；核心 Python 已包含在包内，首次没有系统 Python 也应走该版本的无 Python 准备流程。不要先要求用户手动安装 Python。
- 必须检查目标版本入口实际支持的流程；旧 Tag 若仍要求前置 Python，明确报告版本限制，按其 README 准备官方 Python，不能盲用新版脚本或参数。
- 无当前平台发布条目时，明确报告该目标版本的缺项，由 Agent 按 README 的 Python 和 FFmpeg 官方来源准备匹配预编译依赖后继续。不从源码编译，不假定未发布状态永久不变。
- 条目非法、下载或校验失败均为错误，不能按“无条目”静默回退或绕过验证；保留已有环境和失败日志，只恢复受影响阶段。

本文描述发布与消费约定，不代替实际清单和目标平台测试结果；有本地候选包不等于已发布。安装成功也不代表付费或发布能力已验证，验收仅使用本地素材与页面。

## 集成 API（标准库；运行时固定使用 Python 3.11/3.12）

从 `scripts/source_runtime.py` 导入：

- `prepare_runtime(root: Path) -> Path | None`：读取源码目录中的 manifest；没有当前平台条目时返回 `None`。存在条目时验证 requirements 指纹、下载大小和 SHA-256，安全解包并返回缓存中的运行时根目录。下载失败、指纹不匹配、非法清单或解包失败会抛异常，不能当成“未发布”。
- `python_path(runtime, key=None) -> Path`：返回独立 Python 路径。
- `install_wheels(root, python, runtime) -> None`：重新验证运行时，向调用者传入的独立虚拟环境 Python 离线安装 requirements.txt 和 tzdata==2025.2；失败抛异常。请先用运行时 Python 执行 `-I -B -m venv <用户数据目录中的venv>`，再传入该 venv 的 Python。禁止安装到不可变 bundle 自身。

精确布局：

```text
runtime/
  python/python.exe       # Windows x64
  python/pythonw.exe      # Windows 服务要求；构建时也检查 venv/Scripts/pythonw.exe
  python/bin/python3      # macOS arm64（二者按平台择一）
  wheelhouse/*.whl        # 全部直接/间接依赖，含 tzdata==2025.2
  tools/ffmpeg[.exe]
  tools/ffprobe[.exe]
  licenses/               # 固定哈希的许可证、媒体来源说明、源码与构建配方
  build-inputs.json
```

缓存位于 macOS `~/Library/Caches/Mofish/source-runtime` 或 Windows `%LOCALAPPDATA%/Mofish/source-runtime`。下载放在 `archives/<sha256>.bundle`，运行时放在 `runtimes/<sha256>/`。缓存不得位于源码目录内部；重复使用前校验归档和解包文件清单，归档损坏时重新下载；已解包目录损坏或 seal 缺失时明确报错并保留目录，绝不就地删除可能被 venv 引用的运行时。进程间锁保护缓存更新。调用方应以 `-B` 使用运行时 Python，避免在不可变运行时写入 pyc；应用依赖、虚拟环境和应用数据放在其它用户目录。

## 无系统 Python 的入口与模块边界

`scripts/source_runtime.py` 是供 Python 安装流程使用的模块，不能自行解决解释器尚不存在的问题。支持无系统 Python 安装的目标版本，须由其官方 shell / PowerShell 安装入口先按可信清单下载、校验和准备独立 Python，再继续 Python 安装流程；不要直接让无 Python 的机器执行该模块。检查目标 Tag 是否具备此入口，旧版缺少时按 README 明确回退。无需另建 bootstrap 产品。

入口准备与模块准备必须遵循同一份目标清单及校验规则。无条目可回退；有条目的错误必须报告。后续 `prepare_runtime` / `install_wheels` 的 API 约定如下文和源码所述，首次准备流程也不得跳过归档与依赖完整性检查。

## 发布前门禁

没有真实发布条目就不能宣称 bundle 安装已可用。发布前须分别完成 Windows x64 和 macOS arm64 的真实独立 Python 构建、全部 wheel 目标标签与版本验证、实际离线依赖闭包安装、ffmpeg/ffprobe 执行，以及干净机器上的重定位与安装验证。取得真实 URL 后才能填写发布清单。README 和本文件须随正式 Tag 一同发布，清单只填已完成目标平台验证并实际发布的资产。

## 发布清单 schemaVersion 1

`platforms` 键仅使用 `windows-x64`、`macos-arm64`；缺省或空条目表示无发布。非空条目需要：

| 字段 | 内容 |
| --- | --- |
| `urls` | 1–4 个真实发布的 HTTPS 下载地址；不接受本地文件、凭据、HTTP 或降级重定向 |
| `sha256` | 归档真实 SHA-256，小写 64 位 |
| `bytes` | 归档真实正整数大小，最多 2 GiB |
| `requirementsSha256` | 源码 requirements.txt 的原始字节 SHA-256 |

manifest 是随可信源码分发的信任根，哈希提供完整性校验，不提供额外签名认证。stderr 输出已下载/总字节进度。持久化分片仅在服务端提供强 ETag 或 Last-Modified 时使用 Range/If-Range 续传；严格验证 Content-Range，200 响应重新开始，最终 SHA-256 不符删除分片。最多三轮下载尝试、全局 900 秒预算，每次连接/读取超时 30 秒、流式检查总时限 600 秒；每次读取后检查时间，故超时最多再加一次读取超时。POSIX 缓存锁最多等待 30 秒；Windows 使用系统有界锁重试。下载预检剩余下载字节数加 64 MiB 余量；ZIP 按元数据汇总实际展开大小预检，tar 每个成员写入前检查实际大小加同样余量，均不要求固定 6 GiB 空间。展开上限 6 GiB、100000 项。ZIP/tar 只允许普通文件和目录，拒绝所有符号链接/硬链接、设备文件、稀疏文件、重复路径、大小写别名、Windows 特殊路径和路径穿越。

## 安装恢复

通过目标 Tag 的 README 选择检查、续跑或仅注册服务模式。运行环境包不包含 Git 和 Chrome：Git 由 Agent 首次准备，Chrome 从 Google 官方来源安装后做本地浏览器启动检查。无系统 Python 时检查命令会报告需先正常安装，不把检查失败误判为包不可用。完整安装后须按 README 验收；不能仅凭退出码 0 或 degraded 状态宣称成功。
