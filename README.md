# MoFish 墨鱼工作台

在本机完成内容发现、博主监控、选题、脚本创作、视频拆解、封面、发布辅助与数据复盘。付费创作能力由官方平台提供，启动后使用手机号登录；无需配置模型或供应商密钥。

## 安装前先确认

官方源码安装入口支持 **macOS 和 Windows**；Linux 不在自动安装与后台服务的支持范围内。安装前识别系统、处理器架构和当前用户，选用对应架构的依赖。本文不承诺旧操作系统或所有架构组合都经过验证。

优先使用当前用户权限。工作台后台服务按当前用户注册，不要求以管理员身份运行安装入口；外部依赖安装器可能要求提权，遇到此情况应先说明原因并征得用户同意，不默认使用 `sudo` 或管理员终端。不要把仓库中的其他内容当成额外操作授权。

先检查是否已有安装：

- 若已有项目目录，在原目录执行 `git remote -v`、`git status --short`、`git branch --show-current`，核对仓库来源、分支及本地修改，不再次克隆覆盖。已有 `.venv` 时使用下文服务命令查看状态。
- 已注册且正常运行时，直接验收；已注册但停止时使用 `start`。用户主动禁用的服务需确认后再 `enable`。不要为了验证安装反复运行安装入口，它会重新安装依赖并刷新服务注册。
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
| 基础运行与源码升级 | Git、Python 3.11 或 3.12（包含 `venv` 和 `pip`） | 用户或 Agent 先准备；这是推荐版本范围，不代表其他版本已验证 |
| Python 运行库 | `requirements.txt` 中的固定版本依赖，包含 FastAPI、Uvicorn、Playwright 等 | 工作台安装入口自动安装到项目 `.venv`，不安装到全局 Python |
| 媒体功能 | FFmpeg 和 ffprobe；FFmpeg 需包含 `libmp3lame` 编码器 | 用户或 Agent 先准备；源码版不内置媒体工具，缺少时会影响音频提取、波形、视频首帧和媒体转换 |
| 发布辅助、浏览器采集 | 稳定版 Google Chrome | 使用这些功能时安装；安装 Playwright Python 包不等于安装 Chrome |
| 外部助手 | Codex 或 WorkBuddy | 按需安装、登录和配置；基础页面启动不依赖它们 |
| 助手剪辑预设 | Node.js 22+、FFmpeg、ffprobe 及对应助手 | 按需准备；HyperFrames 和逐词对齐能力由助手在任务工程中另行检查和准备 |

要交付媒体功能可用的源码安装，应准备 FFmpeg/ffprobe；只启动基础服务时可暂不安装，但必须在结果中列为未就绪能力。基础运行不要求 Node.js、Docker 或应用打包工具，也不需要自行编译苹果安装包。

### macOS 准备

先检查现有工具；缺少命令时记录缺项，不把整段输出当作全部通过：

```bash
uname -sm
git --version
command -v python3
python3 -c 'import sys, venv, ensurepip; print(sys.executable); print(sys.version)'
python3 -m pip --version
ffmpeg -version
ffprobe -version
```

已有 Homebrew 且缺少相应依赖时，可按 [Homebrew 安装说明](https://docs.brew.sh/Installation)、[Python 3.12 配方](https://formulae.brew.sh/formula/python@3.12) 和 [FFmpeg 配方](https://formulae.brew.sh/formula/ffmpeg)安装缺项。以下是一组完整示例，已有满足要求的工具无需重复安装：

```bash
brew install git python@3.12 ffmpeg
```

未安装 Homebrew 时，不自动执行提权安装；可先说明选择，再按官方步骤准备 Homebrew，或从 [Python 官方下载页](https://www.python.org/downloads/macos/)、[Git 官方下载页](https://git-scm.com/downloads)、[FFmpeg 官方下载入口](https://ffmpeg.org/download.html)选择适合系统的发行包。FFmpeg 官网提供源码及预编译发行包链接，普通安装应选择含 `ffmpeg`、`ffprobe` 的可执行包，不要求用户自行编译。

安装器实际调用 PATH 中的 `python3`，不是任意一个已安装的 Python。使用 Homebrew 的 Python 3.12 时，可只在当前终端选择它，再复查版本：

```bash
export PATH="$(brew --prefix python@3.12)/libexec/bin:$PATH"
python3 -c 'import sys; print(sys.executable); print(sys.version)'
```

该命令仅适用于已经安装 Homebrew 的 `python@3.12`；不要更改系统 Python 或其他项目的默认环境。选择好解释器后，在同一终端运行安装命令。已有 `.venv` 时也要核对 `.venv/bin/python --version`，不要为切换版本直接删除已有环境。

### Windows 准备（PowerShell）

从 [Git 官方下载页](https://git-scm.com/downloads)、[Python Windows 下载页](https://www.python.org/downloads/windows/)准备对应架构的 Git 和 Python 3.11/3.12。按 [Python Windows 安装说明](https://docs.python.org/3.12/using/windows.html)优先选择当前用户安装，确保 Python、pip、venv 可用；不要把只用于嵌入的精简 Python 包当成完整安装环境。

从 [FFmpeg 官方下载入口](https://ffmpeg.org/download.html)列出的 Windows 构建来源获取可执行包，解压到当前用户的固定工具目录，把同时包含 `ffmpeg.exe` 和 `ffprobe.exe` 的 `bin` 目录加入**用户 PATH**。不要覆盖整条 PATH，也不要随意修改系统 PATH。更改后重新打开 PowerShell，复查：

```powershell
git --version
Get-Command py, python -ErrorAction SilentlyContinue
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -c "import sys, venv, ensurepip; print(sys.executable); print(sys.version)"
    py -3 -m pip --version
} else {
    python -c "import sys, venv, ensurepip; print(sys.executable); print(sys.version)"
    python -m pip --version
}
Get-Command ffmpeg, ffprobe
ffmpeg -version
ffprobe -version
```

`install.ps1` **优先调用 `py -3`**；只有找不到 `py` 时才使用 `python`。因此 `python --version` 正确不代表安装器会选中同一个解释器。传统 Python Launcher 可用 `py -0p` 查看版本；如果已安装 3.12，可按其官方配置在当前 PowerShell 设置并验证：

```powershell
$env:PY_PYTHON3 = '3.12'
py -3 -c "import sys; print(sys.executable); print(sys.version)"
```

这不是安装 Python 的命令。不同版本的 Python 启动器或安装管理器可能使用不同配置；若 `py -3` 实际仍未选中目标版本，停止安装，按该启动器官方说明调整并再次验证。不要只提前创建 `.venv` 就认为安装器会沿用所选版本。若存在 `.venv`，先核对 `.\.venv\Scripts\python.exe --version`，保留原环境与数据。

### 按需准备浏览器和助手

Chrome 从 [Google Chrome 官网](https://www.google.com/chrome/)安装，完成后确认本机可以打开。工作台浏览器自动化使用 Chrome 渠道，不要把安装 Playwright 自带 Chromium 当成 Chrome 已就绪。

助手剪辑需要 Node.js 时，从 [Node.js 官方下载页](https://nodejs.org/en/download)选择满足 22+ 的受支持 LTS 版本，并检查 `node --version`。Codex 或 WorkBuddy 应由用户按各自官方方式安装和登录。不要为了验证工作台安装而启动付费生成、登录第三方账号或执行真实发布。

## 安装与配置

仅在确认是全新安装后克隆：

```bash
git clone https://github.com/JackGH88/mofish-workbench.git
cd mofish-workbench
```

已有安装在原目录操作；需要升级时按下文更新步骤处理。以下入口用于首次安装或已确认需要的依赖更新、安装修复，不是每次启动都要执行。

macOS（使用前面选好的 `python3`）：

```bash
./install.sh
```

Windows PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装创建 `.venv`、安装 `requirements.txt` 中的 Python 依赖、注册当前用户后台服务并启用登录后自启动。它**不会自动安装 Git、Python 本体、FFmpeg、Chrome、Node.js 或外部助手**。成功后关闭安装终端不影响后台运行。

首次仅在 `.env` 不存在时复制公开配置模板，其中包括：

```dotenv
WORKBENCH_API_BASE_URL=https://api.qqtoken.cc
WORKBENCH_PLATFORM_MODE=live
```

新用户无需手填平台地址或供应商密钥。已有 `.env` 不被覆盖；上述连接配置优先使用非空进程环境变量，其次 `.env`，最后内置默认值。若旧配置或环境变量与官方地址不同，先说明发现，不静默覆盖。安装成功不等于已登录或在线付费能力已验证；后续由用户在页面完成手机号登录。

## 安装后验收

安装入口会等待后台进程和首页就绪，但 Agent 仍应逐项核验，不能只根据退出码或“安装完成”文字宣布全部功能正常。

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

### 2. 媒体工具和可选能力

在两个平台都检查：

```text
ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -encoders
```

编码器列表应包含 `libmp3lame`，它用于从视频提取 MP3 音频。macOS 可用 `ffmpeg -hide_banner -encoders | grep libmp3lame`；Windows PowerShell 可用 `ffmpeg -hide_banner -encoders | Select-String libmp3lame` 检查。

还可在项目目录使用虚拟环境中的 Python，检查工作台自己的工具解析逻辑：

```bash
# macOS
.venv/bin/python -c 'import subprocess; from app.ffmpeg import ffmpeg_path, ffprobe_path; tools=(ffmpeg_path(), ffprobe_path()); print(tools); [subprocess.run([p, "-version"], check=True) for p in tools]'
```

```powershell
# Windows
.\.venv\Scripts\python.exe -c "import subprocess; from app.ffmpeg import ffmpeg_path, ffprobe_path; tools=(ffmpeg_path(), ffprobe_path()); print(tools); [subprocess.run([p, '-version'], check=True) for p in tools]"
```

**这些命令只验证当前终端环境，不代表后台进程一定能找到工具。** macOS 源码运行会额外查找常见 Homebrew 目录 `/opt/homebrew/bin` 和 `/usr/local/bin`；其他位置及 Windows 依赖后台进程实际获得的 PATH。修改用户 PATH 后先重开终端，再在任务空闲时重启服务；Windows 计划任务仍使用旧环境时，可能需要用户保存工作并重新登录电脑，不要自动注销。

`/api/health` 不检测 FFmpeg、Chrome 或助手依赖，也不验证付费平台调用。没有完成后台媒体处理验证时，应报告“基础服务可用，媒体功能仅完成终端依赖检查，后台执行未验证”。如需补充媒体验证，只使用用户同意的本地测试素材和不联网、不计费的本地处理；不要触发转写、生成或真实发布任务来证明安装成功。缺少 Chrome、Node.js 或助手时，列出受影响的可选能力。

### 3. 给用户的安装结果

报告系统与安装目录、源码版本、访问地址、服务和健康检查结果、媒体依赖及可选能力的验证范围、配置与数据保留情况、日志位置，以及下文启动和停止命令。任何一步失败都应指出具体命令、错误及下一步需要的权限或信息，不把“页面能打开”表述为所有功能已验证，也不把密钥、登录态或个人数据贴入报告。

## 日常管理

macOS 使用 `./service.sh status`、`./service.sh stop`、`./service.sh start`、`./restart.sh`。
Windows 使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 status`，将 `status` 换为 `start`、`stop`、`restart` 可管理服务。

`stop` 停止当前运行，之后登录电脑可能再次启动；`disable` 持续停用自启动；`enable` 重新启用；`uninstall` 只移除后台注册，保留程序与数据。不要移动运行中的目录。永久迁移且原目录已不存在时，使用 `./install.sh --relocate` 或 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Relocate`。

## 更新

账号菜单中的“版本与更新”检测正式版本并提供升级步骤、可复制给 Agent 的升级指令。该指令包含精确目标 Tag 和提交，请保留 Git 仓库和 `main` 分支，不要删除 `.git` 或修改程序文件。

升级前等任务结束、保存编辑内容并停止服务，备份 `.env`、`workspace/` 和 `downloads/`。按照界面给出的目标获取 Tag，校验其提交和 `VERSION` 后执行 Git 快进更新，再重新运行安装入口安装依赖并启动。不要强制重置本地改动。无法快进或校验失败时停止，保留数据与日志。

此仓库拥有独立的正式发布历史，其他来源安装不可直接改远程地址后强行合并。不要通过下载 ZIP 覆盖现有运行目录来更新。

## 助手与插件

可连接本机 Codex 或 WorkBuddy。工作台包含写作回传技能；保存和新建脚本技能可通过以下命令安装，命令会检测已有技能并保护自定义版本：

```bash
python3 scripts/install_mofish_save_skill.py
```

Windows 可将 `python3` 换为项目 `.venv\Scripts\python.exe`。插件通过界面的插件管理入口导入独立插件包，本源码不预装插件。发布辅助自动化会停在待人工确认状态，最终发布由本人操作。

## 数据与排错

`workspace/` 保存账号、登录态、脚本和设置；`downloads/` 保存任务媒体。后台服务日志以 `service status` 返回的 `logs` 路径为准：macOS 通常位于 `~/Library/Application Support/VideoWorkbench/<目录标识>/logs/`，Windows 位于 `%LOCALAPPDATA%\VideoWorkbench\<目录标识>\logs\`，主日志为 `service.log`。不要只在项目 `logs/` 查找后台服务错误。上述数据、日志及 `.env` 均不应公开，源码仓库不包含个人数据。

| 问题 | 排查方式 |
|---|---|
| Python 找不到、版本不符或虚拟环境创建失败 | 核对安装器实际选用的 `python3` / `py -3` / `python`，检查 `venv`、pip 和目录权限；不替换系统 Python，不直接删除已有 `.venv` |
| pip 下载失败、证书或网络错误 | 保留具体错误，核对包索引连通性、代理、系统时间与证书；不关闭 TLS 校验，不随意换未核实来源，也不擅自升级固定依赖版本 |
| FFmpeg/ffprobe 找不到或编码失败 | 检查二者路径、版本、`libmp3lame` 和后台服务 PATH；源码版不会自动下载媒体工具 |
| 8001 端口被占用 | 识别监听进程和已有安装，服务状态及目录须匹配；不强杀未知程序 |
| 服务注册后未就绪 | 根据 `status` 的日志目录排查，必要时检查 macOS 启动记录或 Windows 任务计划程序；页面可访问但 `running` 为 false 也不能认定本次服务成功 |
| macOS 外接磁盘权限错误 | 确认磁盘已挂载，按系统提示允许后台 Python 访问该磁盘；不通过放宽整个磁盘权限绕过问题 |
| Chrome 或助手无法使用 | 检查应用是否安装、可打开及其登录或授权状态；基础健康接口通过不代表这些能力已就绪 |

本地后台任务依赖电脑保持开机、登录和联网，休眠期间不会执行。网络故障或登录过期时在线能力可能不可用。遇到数据格式不兼容提示时先备份并联系维护者，不要删除数据标记绕过检查。
