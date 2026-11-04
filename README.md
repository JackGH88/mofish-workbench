# MoFish 墨鱼工作台

在本机完成内容发现、博主监控、选题、脚本创作、视频拆解、封面、发布辅助与数据复盘。付费创作能力由官方平台提供，启动后使用手机号登录；无需配置模型或供应商密钥。

## 安装

支持 macOS 和 Windows。先安装 Git、Python 3（建议 3.11 或 3.12），需要发布辅助功能时安装稳定版 Google Chrome。保持安装目录固定，不要放在临时目录。

```bash
git clone https://github.com/JackGH88/mofish-workbench.git
cd mofish-workbench
```

macOS：

```bash
./install.sh
```

Windows PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装创建 `.venv`、安装依赖、注册当前用户后台服务并启用登录后自启动。首次自动创建 `.env`，使用 `https://api.qqtoken.cc` 和 `live` 模式；无需手动填写。完成后打开 http://127.0.0.1:8001 。无需管理员权限，关闭安装终端不影响后台运行。

已有 `.env` 不被覆盖。配置优先级为系统环境变量、`.env`、内置默认值。需要发布自动填充或复盘采集时，请先安装 Chrome；自动化会停在待人工确认状态，最终发布由本人操作。

## 日常管理

macOS 使用 `./service.sh status`、`./service.sh stop`、`./service.sh start`、`./restart.sh`。
Windows 使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 status`，将 `status` 换为 `start`、`stop`、`restart` 可管理服务。

`disable` 持续停用自启动；`enable` 重新启用；`uninstall` 只移除后台注册，保留程序与数据。不要移动运行中的目录。永久迁移且原目录已不存在时，使用 `./install.sh --relocate` 或 `.\install.ps1 -Relocate`。

## 更新

账号菜单中的“版本与更新”检测正式版本并提供升级步骤、可复制给 Agent 的升级指令。该指令包含精确目标 Tag 和提交，请保留 Git 仓库和 `main` 分支，不要删除 `.git` 或修改程序文件。

升级前等任务结束、保存编辑内容并停止服务，备份 `.env`、`workspace/` 和 `downloads/`。按照界面给出的目标获取 Tag，校验其提交和 `VERSION` 后执行 Git 快进更新，再重新运行安装入口安装依赖并启动。不要强制重置本地改动。无法快进或校验失败时停止，保留数据与日志。

此仓库拥有独立的正式发布历史，其他来源安装不可直接改远程地址后强行合并。不要通过下载 ZIP 覆盖现有运行目录来更新。

## 助手与插件

可连接本机 Codex 或 WorkBuddy。工作台包含写作回传技能；保存和新建脚本技能可通过以下命令安装，命令会检测已有技能并保护自定义版本：

```bash
python3 scripts/install_mofish_save_skill.py
```

Windows 可将 `python3` 换为 `python`。插件通过界面的插件管理入口导入独立插件包，本源码不预装插件。

## 数据与排错

`workspace/` 保存账号、登录态、脚本和设置；`downloads/` 保存任务媒体；`logs/` 保存运行日志。不要公开或分享这些目录及 `.env`。每个用户安装时自行生成，源码仓库不包含个人数据。

先用服务管理命令 `status` 查看注册、运行状态和日志目录。端口被其他程序占用时先确认进程，不要强行关闭未知程序。macOS 放在外接磁盘时需允许后台 Python 访问该磁盘。

本地后台任务依赖电脑保持开机、登录和联网，休眠期间不会执行。不保证网络故障或登录过期时付费能力可用。遇到数据格式不兼容提示时先备份并联系维护者，不要删除数据标记绕过检查。
