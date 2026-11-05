# MoFish 墨鱼工作台

在本机完成内容发现、博主监控、选题、脚本创作、视频拆解、封面、发布辅助与数据复盘。付费创作能力由官方平台提供，启动后使用手机号登录；无需配置模型或供应商密钥。

## 安装前先确认

默认完整源码安装支持 **Windows 10/11 x64、macOS 13+ Apple Silicon**。安装前识别系统、处理器架构和当前用户；Intel Mac、Windows ARM、旧系统及 Linux 不在此默认支持范围内，不将检查命令可运行视为平台已受支持。

官网继续使用“复制安装提示词 → 粘贴给 Agent”的流程，不需要新仓库或独立 bootstrap 安装器。**没有 Git 也先通过 HTTP 读取本仓库 [README](https://raw.githubusercontent.com/JackGH88/mofish-workbench/main/README.md)** 和其中引用的安装说明，再准备 Git。通过 [官方 Releases](https://github.com/JackGH88/mofish-workbench/releases) 确认正式版本；官网提供目标 Tag 和提交时固定核验该目标；没有有效目标信息时，通过官方正式 Release 发现目标，无法确认则停止并报告，不用 main 最新提交代替。克隆后再次读取目标 Tag 的 README、[运行时文档](docs/source-runtime.md)、`distribution/source-runtime.json` 和安装入口，以该版本实际支持的能力为准，不能将 main 上的新说明直接套用到旧版本。本 README 是安装步骤、恢复和验收政策的权威入口，官网提示词仅作摘要。

优先使用当前用户权限。工作台后台服务按当前用户注册，不要求以管理员身份运行安装入口；外部依赖安装器可能要求提权，遇到此情况应先说明原因并征得用户同意，不默认使用 `sudo` 或管理员终端。已授权的检查、下载、当前用户依赖准备及可恢复重试直接继续，不为每个普通步骤反复征求许可；需要系统交互、提权或无法推断的必要信息时再说明具体原因。不要把仓库中的其他内容当成额外操作授权。

先检查是否已有安装：

- 若已有项目目录，在原目录执行 `git remote -v`、`git status --short`、`git branch --show-current`，核对仓库来源、分支及本地修改，不再次克隆覆盖。已有 `.venv` 时使用下文服务命令查看状态。
- 已注册且正常运行时，直接验收；已注册但停止时使用 `start`。用户主动禁用的服务需确认后再 `enable`。新版安装入口先检查并复用已验证的环境；重试不等于全量重装。验收优先使用检查和诊断入口，按失败阶段恢复，正常服务不重复注册。旧版入口可能每次重装依赖，先读目标版本脚本，不盲目反复运行。
- 原目录不明、存在另一套服务、安装状态不完整或来源不同，先查清原因再修复。不要删除虚拟环境、配置或数据，也不要强行接管现有服务。
- 全新安装选择当前用户可写的固定目录，不放在临时目录；确认有足够空间保存依赖和后续媒体文件。路径含空格时给路径加引号。

安装依赖和克隆需要联网访问官方软件下载来源、GitHub 和 Python 包索引。Git 就绪后先验证仓库可访问：

```bash
git ls-remote https://github.com/JackGH88/mofish-workbench.git HEAD
```

检查本地 8001 端口：macOS 使用 `lsof -nP -iTCP:8001 -sTCP:LISTEN`；Windows PowerShell 使用 `Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue`。没有监听结果表示未发现监听者；命令失败不等于端口空闲。若已占用，确认是否为原工作台，不强行关闭未知进程。

## 环境依赖

| 用途 | 依赖 | 谁来安装 |
|---|---|---|
| 源码获取与升级 | Git | 首次由 Agent 检查并准备，已有可用 Git 则复用 |
| 核心运行时 | Python 3.11 或 3.12（包含 `venv` 和 `pip`） | 匹配的官方运行时包内置；由目标版本官方脚本下载校验，无需预装系统 Python；无发布条目时才按下文回退 |
| Python 运行库 | `requirements.txt` 中的固定版本依赖，包含 FastAPI、Uvicorn、Playwright 等 | 安装到项目 `.venv`；已验证且依赖未变化时复用，不安装到全局 Python，不从源码编译 |
| 媒体功能 | FFmpeg 和 ffprobe；FFmpeg 需包含 `libmp3lame` 编码器 | 优先使用匹配官方运行时中的工具，或复用已验证工具；无匹配条目时准备官方来源预编译包；缺少时会影响音频提取、波形、视频首帧和媒体转换 |
| 发布辅助、浏览器采集 | 稳定版 Google Chrome | 默认完整安装必须准备并验收；安装 Playwright Python 包不等于安装 Chrome |
| 外部助手 | Codex 或 WorkBuddy | 按需安装、登录和配置；基础页面启动不依赖它们 |
| 助手剪辑预设 | Node.js 22+、FFmpeg、ffprobe 及对应助手 | 按需准备；HyperFrames 和逐词对齐能力由助手在任务工程中另行检查和准备 |

默认交付包含 Python 依赖、FFmpeg/ffprobe 和 Chrome；仅启动基础服务属于未完成或明确选择的降级结果，缺失能力必须列明，不能当作完整安装完成。基础运行不要求 Node.js、Docker 或应用打包工具，也不需要自行编译苹果安装包。

### Git 先就绪，再克隆

macOS 先运行 `git --version` 验证实际可用性。仅发现 `/usr/bin/git` 不代表 Git 已安装，该路径可能只是触发 Command Line Tools（CLT）安装的系统入口。已有可用 Git 就复用；缺失时由 Agent 引导运行 `xcode-select --install`，说明系统对话框和用户必须完成的步骤，完成后重新验证。不要宣称 CLT 可以无人值守完成，也不要仅为安装 Git 引入整套包管理器。

Windows 先运行 `git --version`。缺失时从 [Git for Windows 官方下载入口](https://git-scm.com/downloads/win) 及其链接的官方 Release 获取匹配架构的 **PortableGit**，解压到当前用户可写的固定工具目录；验证来源及官方提供的校验信息，再用绝对路径执行 `git.exe --version`。将其 `cmd` 目录加入当前进程 PATH，必要时追加用户 PATH，保留原值，不改系统 PATH。不要假设电脑已有 Git 或管理员权限。

### Python 与媒体运行时

以**目标正式 Tag** 的 `distribution/source-runtime.json` 为准，按当前平台读取 `windows-x64` 或 `macos-arm64` 条目；不要根据 main 清单、其他版本资产或本文文字推断目标版本的发布状态。运行时与源码属于同一个官方仓库，通过官方 Release assets 分发，不需要额外仓库或另做安装器。核心 Python、预编译 wheel 依赖和 FFmpeg/ffprobe 包含在匹配的运行时中，Chrome 单独准备。

- **有匹配有效条目**：按目标 Tag 的官方 `install.sh` / `install.ps1` 入口自动下载、校验和使用运行时，包括首次没有系统 Python 的电脑；不要求用户先手动安装 Python 或查找下载包。先读取目标版本入口及[运行时文档](docs/source-runtime.md)，确认其无 Python 准备流程；旧 Tag 没有此能力时明确说明限制，并按该版本说明准备官方 Python，不能将新入口能力套用到旧版。
- **没有当前平台条目**：明确报告该目标版本未提供匹配运行时，按下面官方来源准备依赖，然后继续目标版本安装流程；不推断所有版本都未发布，也不编造包名、URL 或校验值。
- **条目存在但无效，或下载、大小、SHA-256、依赖指纹校验失败**：保留具体错误并修复该阶段，不将失败当作“无条目”而静默回退，不关闭校验。已有环境通过验证时优先复用，不为使用 bundle 而重装。

无匹配发布条目或旧版入口需要前置解释器时，回退准备方式如下：

- Python：从 [macOS 官方下载页](https://www.python.org/downloads/macos/) 或 [Windows 官方下载页](https://www.python.org/downloads/windows/) 选择适配的 Python 3.11/3.12，包含 `venv`、`ensurepip` 和 pip。Windows 优先当前用户安装；嵌入式精简包不等于可用的 venv 环境。
- FFmpeg：从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html) 链接的预编译发行来源获取适配的 FFmpeg 和 ffprobe，确认支持 `libmp3lame`。放在固定用户工具目录并让后台服务能够解析，不只检查当前终端 PATH。
- 若已有 Homebrew，可复用其已安装工具；只有存在适配 bottle 时才采用预编译安装，不因为缺少 bottle 转为源码编译。无需为本任务新装 Homebrew。

先验证项目已有 `.venv` 的解释器和依赖。macOS 使用 `.venv/bin/python`，Windows 使用 `.\.venv\Scripts\python.exe`，检查版本为 3.11/3.12，运行 `-c "import sys, venv, ensurepip; print(sys.executable); print(sys.version)"` 和 `-m pip --version`。**普通安装复用通过验证的 .venv**，不因系统默认 Python 版本变化而重建。环境不完整时诊断具体缺项，保留原环境、配置和数据，不能直接删除 `.venv`。

没有可用环境时，Agent 验证候选解释器的绝对路径、版本和 venv/pip 能力，再按目标版本入口的选择规则创建环境。旧入口可能选择 PATH 中的 `python3` 或优先 `py -3`，不要仅凭 `python --version` 推断实际选择；Windows 可用 `py -0p` 列出候选，分别验证 `py -3.12` / `py -3.11`。不要替换系统 Python、全局安装项目依赖或改变其他项目环境。

Python 依赖应使用匹配平台的预编译 wheel；缺少 wheel 或下载失败时报告具体包、解释器、架构和错误，不启动源码编译、不擅自升级固定版本。网络失败只恢复受影响的阶段，已有有效下载和通过验证的依赖继续复用。

### 默认准备 Chrome；助手按需准备

Chrome 属于默认完整安装的验收项。缺少 Chrome 时，Agent 引导从 [Google Chrome 官网](https://www.google.com/chrome/)安装，说明必须由用户完成的系统交互，不保证无人值守安装。已安装时仅执行本地启动、打开本地测试页并关闭的冒烟检查，不访问第三方、不登录或发布。只有用户明确选择跳过时才使用 `--skip-chrome` / `-SkipChrome`，并报告“基础服务可用，完整安装未完成：浏览器能力未就绪”。需要系统交互时保留进度，待完成官方安装后用 Chrome 专项检查验收，不默认跳过。工作台浏览器自动化使用 Chrome 渠道，不要把安装 Playwright 自带 Chromium 当成 Chrome 已就绪。

助手剪辑需要 Node.js 时，从 [Node.js 官方下载页](https://nodejs.org/en/download)选择满足 22+ 的受支持 LTS 版本，并检查 `node --version`。Codex 或 WorkBuddy 应由用户按各自官方方式安装和登录。不要为了验证工作台安装而启动付费生成、登录第三方账号或执行真实发布。

## 安装与配置

仅在确认是全新安装后克隆官方仓库。先通过 HTTP 核对官方正式 Release 的 Tag、提交和版本（不是桌面安装包版本，也不是 main 最新提交）。源码版本仅选择 `vX.Y.Z` 格式；`runtime-*` 是独立依赖附件的版本，不能作为源码安装目标。下面的 `vX.Y.Z` 必须替换为已核验的正式 Tag，不可直接照抄：

```bash
git clone --no-checkout https://github.com/JackGH88/mofish-workbench.git
cd mofish-workbench
git fetch origin tag vX.Y.Z
git rev-parse 'vX.Y.Z^{commit}'
git show vX.Y.Z:VERSION
```

将结果与官方发布信息核对后，仅在这个全新且没有本地修改的克隆中执行：

```bash
git switch -C main vX.Y.Z
git branch --set-upstream-to=origin/main main
```

这样运行正式 Tag 的源码，同时保留本地 `main` 分支，兼容后续按正式 Tag 快进升级。不要停留在 detached HEAD，不使用浅克隆限制后续历史，也不要为了跟踪 `origin/main` 就拉取未发布提交。已有安装在原目录操作，不执行上述重建分支命令；更新遵循下文步骤。

### 检查、安装与恢复

先读取所选 Tag 的安装入口。下表是新版安装入口的参数约定；旧正式 Tag 若尚未提供这些参数或诊断模块，按该版本文档检查、修复并说明限制，**不要盲传新参数**。

| 操作 | Windows PowerShell 参数 | macOS 参数 | 用途 |
|---|---|---|---|
| 仅检查 | `-Check` | `--check` | 查看环境和缺项，不作为完整安装成功的证明 |
| 恢复 | `-Resume` | `--resume` | 从失败阶段继续，复用已验证的环境和下载 |
| 仅注册服务 | `-RegisterOnly` | `--register-only` | 环境已就绪时修复后台注册，不重装运行依赖 |
| 仅处理 Chrome | `-ChromeOnly` | `--chrome-only` | 检查浏览器，缺失时引导安装，不重装工作台 |
| 跳过 Chrome | `-SkipChrome` | `--skip-chrome` | 仅用户明确选择时降级完成基础安装；不代表完整安装 |

macOS 正常安装及可用时的检查、恢复示例（每次按目的选择一条）：

```bash
./install.sh --check
./install.sh
./install.sh --resume
```

Windows PowerShell 对应示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Resume
```

普通安装验证并复用 Python 3.11/3.12 的 `.venv`，只补齐需要的依赖，注册当前用户后台服务并启用登录后自启动；已有正常服务无需重复注册。重试不是全量重装：Python 环境有效就保留，只有服务注册失败时使用仅注册模式，只有 Chrome 缺失时处理 Chrome。Git 首次由 Agent 准备；Python 本体和媒体工具优先由官方入口按目标运行时清单准备，Chrome 按前文安装并验收。无匹配条目时才走明确回退，实际能力以目标版本为准。成功后关闭安装终端不影响后台运行。

已有 Python 依赖及 FFmpeg/ffprobe 均通过检查时，普通安装会跳过运行时准备，不要求重新下载 bundle。若已注册服务仍在运行且依赖需要变更，安装器会在下载和 pip 之前停止并保留原环境。Agent 等待任务空闲、保存编辑内容后，在本项目目录停止服务并确认状态，再续跑：

```bash
# macOS：确认任务空闲后
./service.sh stop
./service.sh status
./install.sh --resume
```

```powershell
# Windows：确认任务空闲后
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 stop
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Resume
```

只有确认 stop 成功且服务不再运行，才执行恢复命令；停止失败时先排查日志，不强杀未知进程、不删除环境。Windows 跨版本依赖变更仍按“更新”章节使用项目外 Python 做停机迁移，不能用普通续跑绕过自动更新保护。

首次仅在 `.env` 不存在时复制公开配置模板，其中包括：

```dotenv
WORKBENCH_API_BASE_URL=https://api.qqtoken.cc
WORKBENCH_PLATFORM_MODE=live
```

新用户无需手填平台地址或供应商密钥。已有 `.env` 不被覆盖；上述连接配置优先使用非空进程环境变量，其次 `.env`，最后内置默认值。若旧配置或环境变量与官方地址不同，先说明发现，不静默覆盖。安装成功不等于已登录或在线付费能力已验证；后续由用户在页面完成手机号登录。

## 安装后验收

安装入口会等待后台进程和首页就绪，但 Agent 仍应逐项核验。当前入口在依赖报告为 `degraded` 时也可能返回 0，不能只根据退出码或“基础安装已完成”文字宣布完整安装完成。Chrome 与媒体检查必须读取实际报告。

### 1. 服务、页面和版本

macOS：

```bash
./service.sh status
curl --noproxy '*' --fail --silent --show-error --max-time 10 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/
curl --noproxy '*' --fail --silent --show-error --max-time 10 http://127.0.0.1:8001/api/health
cat VERSION
```

Windows PowerShell（用 `curl.exe` 避免旧 PowerShell 的 `curl` 别名）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 status
curl.exe --noproxy "*" --fail --silent --show-error --max-time 10 -o NUL -w "%{http_code}\n" http://127.0.0.1:8001/
curl.exe --noproxy "*" --fail --silent --show-error --max-time 10 http://127.0.0.1:8001/api/health
Get-Content .\VERSION
```

若系统没有 `curl.exe`，使用明确绕过本地代理的 HTTP 客户端完成同样检查，不因缺少此检查工具重装工作台。PowerShell 中外部命令失败后应检查 `$LASTEXITCODE`，不能只看最后一条命令成功。

应确认服务状态中的 `registered`、`running`、`pageAccessible` 为 `true`，`project` 对应本次安装目录；记录 `enabled` 是否符合用户的自启动选择及 `logs` 路径。首页应返回 HTTP 200，并实际打开 http://127.0.0.1:8001 确认工作台页面可访问。

健康接口应返回 JSON：`status` 为 `ok`、`downloadDirWritable` 为 `true`、`runningVersion` 与当前目录 `VERSION` 一致、`plugins.ok` 为 `true`。无插件的新安装也应正常；若插件状态异常，保留失败明细排查，不擅自删除插件。仅收到 HTTP 200 不足以判定这些字段正常。

### 2. 媒体工具、Chrome 与按需助手

在两个平台都检查：

```text
ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -encoders
```

编码器列表应包含 `libmp3lame`，它用于从视频提取 MP3 音频。macOS 可用 `ffmpeg -hide_banner -encoders | grep libmp3lame`；Windows PowerShell 可用 `ffmpeg -hide_banner -encoders | Select-String libmp3lame` 检查。

在提供诊断能力的版本中，使用项目虚拟环境运行依赖诊断 CLI（即 `python -m app.dependency_diagnostics`）：

```bash
# macOS
.venv/bin/python -m app.dependency_diagnostics --verify-media --verify-browser
curl --noproxy '*' --fail --silent --show-error --max-time 10 http://127.0.0.1:8001/api/diagnostics/dependencies
```

```powershell
# Windows
.\.venv\Scripts\python.exe -m app.dependency_diagnostics --verify-media --verify-browser
curl.exe --noproxy "*" --fail --silent --show-error --max-time 10 http://127.0.0.1:8001/api/diagnostics/dependencies
```

CLI 的 `--verify-media --verify-browser` 使用临时本地素材和页面进行实际冒烟；只运行无参数 CLI 是依赖检测，不能替代冒烟。明确跳过 Chrome 时省略 `--verify-browser` 并报告降级。CLI 验证当前进程环境，`/api/diagnostics/dependencies` 检查实际后台进程的依赖状态；记录缺项与失败明细，不能只看 HTTP 200。旧 Tag 不提供这些入口时，明确报告限制，按该版本的工具解析和服务日志逐项核验，不将模块缺失或 404 判为整个安装损坏。

修改用户 PATH 后先重开终端，再在任务空闲时重启服务；Windows 计划任务仍使用旧环境时，可能需要用户保存工作并重新登录电脑，不要自动注销。终端工具可用不代表后台可用。

`/api/health` 不替代依赖诊断，也不验证付费平台调用。Chrome 仅做本地启动/关闭检查；媒体测试仅用本地测试素材做不联网、不计费的处理，不触发转写、生成或真实发布。未完成后台媒体执行验证时明确报告验证范围；Chrome 缺失或本地冒烟失败意味着默认完整安装尚未完成；Node.js 或助手按需准备，缺少时列出受影响的助手能力。

### 3. 给用户的安装结果

报告系统与安装目录、源码版本、访问地址、服务和健康检查结果、媒体、Chrome 及按需助手的验证范围、配置与数据保留情况、日志位置，以及下文启动和停止命令。任何一步失败都应指出具体命令、错误及下一步需要的权限或信息，不把“页面能打开”表述为所有功能已验证，也不把密钥、登录态或个人数据贴入报告。

## 日常管理

macOS 使用 `./service.sh status`、`./service.sh stop`、`./service.sh start`、`./restart.sh`。
Windows 使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 status`，将 `status` 换为 `start`、`stop`、`restart` 可管理服务。

`stop` 停止当前运行，之后登录电脑可能再次启动；`disable` 持续停用自启动；`enable` 重新启用；`uninstall` 只移除后台注册，保留程序与数据。不要移动运行中的目录。永久迁移且原目录已不存在时，使用 `./install.sh --relocate` 或 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Relocate`。

## 更新

账号菜单中的“版本与更新”检测正式版本并提供升级步骤、可复制给 Agent 的升级指令。该指令包含精确目标 Tag 和提交，请保留 Git 仓库和 `main` 分支，不要删除 `.git` 或修改程序文件。

升级前核对正式目标 Tag、提交、`VERSION`、本地修改及依赖差异，等待任务结束并备份 `.env`、`workspace/` 和 `downloads/`。不要强制重置本地改动；无法快进或校验失败时停止，保留数据与日志。

**Windows 自动更新：依赖未变化时照常更新；依赖变化时会在修改代码、依赖环境或服务之前拒绝更新。** `scripts/update_workbench.py` 检查 requirements、约束文件及运行时清单等依赖变化；拒绝后会记录错误，但不会替换当前代码或停止原服务。不要通过反复点击更新、忽略提示或直接运行旧 `.venv` 中的 pip 绕过保护。

Windows 依赖变更交给 Agent 做停机离线安全迁移：“离线”指退出工作台运行进程后操作，不承诺所有依赖已能断网获取。Agent 应先用**项目外**的 Python 3.11/3.12 64 位准备目标版本的预编译依赖，确认源码与依赖可用、备份空间和回退点；再等任务完成、停止服务及更新进程，备份原代码版本、`.venv`、配置与数据，在最终 `.venv` 路径创建并验证新环境，按已核验 Tag 快进更新后启动验收。不要将临时位置创建好的 venv 直接搬到最终目录（脚本可能含绝对路径），不要由待替换的 `.venv` 内 Python 执行迁移。失败时停止新服务并恢复原代码、原环境和必要的数据备份，再验证旧版本可用；保留失败日志与备份，不做破坏性清理。

macOS 或不涉及依赖变化的 Agent 更新同样需校验正式目标，停止服务后按 Tag 快进；使用目标版本入口验证并复用环境，按需补齐依赖、启动并检查健康和能力报告。普通安装重试的环境复用，不等于 Windows 运行中依赖升级安全。

此仓库拥有独立的正式发布历史，其他来源安装不可直接改远程地址后强行合并。不要通过下载 ZIP 覆盖现有运行目录来更新。

## 助手与插件

可连接本机 Codex 或 WorkBuddy。工作台包含写作回传技能；保存和新建脚本技能可通过以下命令安装，命令会检测已有技能并保护自定义版本：

```bash
.venv/bin/python scripts/install_mofish_save_skill.py
```

Windows 可将 `.venv/bin/python` 换为项目 `.venv\Scripts\python.exe`。插件通过界面的插件管理入口导入独立插件包，本源码不预装插件。发布辅助自动化会停在待人工确认状态，最终发布由本人操作。

## 数据与排错

安装阶段、耗时、工具路径和验收报告记录在 `workspace/install/state.json`（位于 workspace 子目录内，适配数据目录 schema），不是 `workspace/install.json`。记录会被诊断工具读取；不要手动删除、覆盖或将旧路径内容盲目迁入。Chrome 专项检查会写入当前报告及最终状态：缺失时为 degraded 并提示安装；检查执行成功后按报告更新 complete/degraded 并清除旧错误。仍需区分专项验收与服务、媒体的完整验收范围。

`workspace/` 保存账号、登录态、脚本和设置；`downloads/` 保存任务媒体。后台服务日志以 `service status` 返回的 `logs` 路径为准：macOS 通常位于 `~/Library/Application Support/VideoWorkbench/<目录标识>/logs/`，Windows 位于 `%LOCALAPPDATA%\VideoWorkbench\<目录标识>\logs\`，主日志为 `service.log`。不要只在项目 `logs/` 查找后台服务错误。上述数据、日志及 `.env` 均不应公开，源码仓库不包含个人数据。

| 问题 | 排查方式 |
|---|---|
| Python 找不到、版本不符或虚拟环境创建失败 | 先核对已有 `.venv` 是否为可用的 Python 3.11/3.12，再检查目标版本安装器的解释器选择、`venv`、pip 和目录权限；不替换系统 Python，不直接删除已有 `.venv` |
| pip 下载失败、证书或网络错误 | 保留具体错误，核对包索引连通性、代理、系统时间与证书；不关闭 TLS 校验，不随意换未核实来源，也不擅自升级固定依赖版本 |
| FFmpeg/ffprobe 找不到或编码失败 | 检查二者路径、版本、`libmp3lame` 和后台服务 PATH；目标 Release 缺少运行时资产时由 Agent 按官方入口准备预编译工具，不从源码编译 |
| 8001 端口被占用 | 识别监听进程和已有安装，服务状态及目录须匹配；不强杀未知程序 |
| 服务注册后未就绪 | 根据 `status` 的日志目录排查，必要时检查 macOS 启动记录或 Windows 任务计划程序；页面可访问但 `running` 为 false 也不能认定本次服务成功 |
| macOS 外接磁盘权限错误 | 确认磁盘已挂载，按系统提示允许后台 Python 访问该磁盘；不通过放宽整个磁盘权限绕过问题 |
| Chrome 或助手无法使用 | 检查应用是否安装、可打开及其登录或授权状态；基础健康接口通过不代表这些能力已就绪 |

本地后台任务依赖电脑保持开机、登录和联网，休眠期间不会执行。网络故障或登录过期时在线能力可能不可用。遇到数据格式不兼容提示时先备份并联系维护者，不要删除数据标记绕过检查。
