# AGENTS.md

## 项目概况

这是一个基于 Textual 的 NapBot/OneBot v11 QQ 聊天 TUI 前端。入口是 `main.py`（`from ui import QQChatApp`），UI 拆在 `ui/` 包里，OneBot WebSocket 客户端在 `onebot.py`。

当前工作区路径：

`E:\Git\tui-qq-python-textual`

## 运行方式

优先使用：

```bat
run.bat
```

`run.bat` 会按顺序尝试：

1. `.venv\bin\python.exe`
2. `.venv\Scripts\python.exe`
3. 系统 `python`

也可以直接运行：

```powershell
.\.venv\bin\python.exe main.py
```

注意：当前 `.venv` 是 msys2 clang64 的 Python（platform `mingw_x86_64_ucrt_llvm`），PyPI 上只有标准 CPython 的二进制轮子，所以**需要编译安装的依赖（如 Pillow）在这个 venv 里会失败**。如果遇到轮子装不上的依赖，改用 conda 环境：

```powershell
conda activate tui
python main.py
```

`tui` 是标准 CPython 3.13（conda 管理），能直接装 PyPI 的 `win_amd64` 轮子。建环境时用的依赖与 `requirements.txt` 一致。

依赖在 `requirements.txt`：

- `textual`
- `websockets`
- `pypinyin`

## 配置

运行配置放在根目录 `config.json`，不要再直接把连接地址写死到代码里。

当前字段：

- `ws_url`: NapBot/OneBot v11 WebSocket 地址，默认 `ws://127.0.0.1:3001`
- `cache_dir`: 缓存目录，默认 `data`
- `cache_file`: 聊天缓存文件名，默认 `cache.json`
- `settings_file`: 用户设置文件名，默认 `settings.json`
- `recent_chats_count`: 最近会话数量
- `history_message_count`: 拉取历史消息数量
- `chat_list_render_limit`: 左侧列表单次挂载上限
- `cache_group_members_on_open`: 是否在打开群聊时拉全量群成员，默认关闭

`config.py` 只负责读取 `config.json` 并导出常量。

## 数据文件

`data/cache.json` 是本地缓存，包含群成员、最近会话、最后活动时间和消息缓存。这个文件可能很大，修改代码时不要把它当作源码手动重排。

`data/settings.json` 保存 UI 设置，目前主要用于保存 Textual 主题。主题切换快捷键是 `ctrl+t`。

## 主要模块

UI 已从原来的单文件 `tui.py`（已删除）按职责拆进 `ui/` 包，分三层：**纯逻辑**（`logic/`，无 Textual 依赖，可单测）、**网络+解析服务**（`services/`，worker 线程调用）、**控件与胶水**（`widgets/` + `app.py`）。

根目录模块（无变化）：

- `main.py`: 入口，`from ui import QQChatApp` 后 `app.run()`
- `onebot.py`: 同步 WebSocket OneBot v11 客户端，内部用 reader 线程接收事件
- `storage.py`: JSON 缓存读写，已加线程锁和唯一临时文件名，避免 Windows 下 `cache.json.tmp` 权限冲突
- `models.py`: `ChatInfo`、`MemberInfo`、`MessageData`
- `pinyin.py`: 名称搜索用的小鹤双拼/简拼工具
- `config.py`: 读取 `config.json`

`ui/` 包：

- `ui/__init__.py`: 暴露 `QQChatApp`
- `ui/app.py`: `QQChatApp`——状态机 + Textual 胶水。持有状态、bindings、compose、生命周期、Toast/滚动/侧边栏/鼠标处理、控件挂载、事件分发；逻辑委托给 `logic/` 和 `services/`
- `ui/styles.py`: `APP_CSS` 字符串常量（不用 `.tcss`，PyInstaller 友好）
- `ui/theme.py`: `ROLE_STYLES` + 布局常量（`CHAT_LIST_TEXT_WIDTH`、`SIDEBAR_AUTO_HIDE_*` 等）
- `ui/clipboard.py`: PowerShell 剪贴板 get/set，非 Windows 降级 no-op
- `ui/text_utils.py`: 纯函数 `format_time` / `display_width` / `ellipsize` / `extract_text`
- `ui/widgets/message_log.py`: `MessageLog` 控件（基于 `VerticalScroll` + `Static` 行，**不是 RichLog**）
- `ui/logic/chat_logic.py`: 纯函数——过滤/排序/搜索/列表文本/导航索引（无 `self`、无 `query_one`）
- `ui/logic/message_logic.py`: 纯函数 + **OneBot 段类型注册表**（`register_segment`）。这是消息扩展点：加新消息段类型只注册 handler，不动 dispatcher
- `ui/services/chat_service.py`: `load_chats`——拉好友/群列表 → `ChatInfo`，吸收防御性解析
- `ui/services/message_service.py`: `load_history` / `send` / `cache_group_members`——网络调用 + 防御性解析，由 App 在 worker 线程调用

## 架构约定（重要）

修改时遵循三层边界：

- **`logic/` 是纯函数**：不允许 `import textual`，不允许 `query_one`/`mount`/`self.storage` 写操作。接收 data + storage（只读）返回结果。App 持有可变状态（如 `_search_cache`）并加锁拷贝后传入。
- **`services/` 调网络**：只能被 App 的 worker 线程调用（`_run_thread`），**绝不在主线程跑**。返回干净 dataclass，UI 回调用 `call_from_thread` 回主线程。
- **`app.py` 只做胶水**：所有 `query_one`/`mount`/`log.write` 留在这里；计算委托 `logic/`，网络委托 `services/`。

扩展新功能时先想"这是逻辑还是 UI"：加新消息段类型→改 `message_logic` 注册表；加新列表过滤规则→改 `chat_logic`；加新控件→放 `ui/widgets/`。互不干扰。

`app.py` 的 `_run_thread` 是带异常兜底的 worker 入口：未捕获异常会 `call_from_thread(_show_toast)` 而非静默崩溃。新 worker 一律走它。

## UI 行为

- 左侧列表显示会话名称和最后一条消息内容预览。
- 最近打开的会话置顶，并和其它会话用分隔行隔开。
- 预览只显示消息内容，不显示成员名。
- 长群名使用显示宽度截断，避免中文宽度导致整行消失。
- 聊天区消息都保持左侧布局，自己发出的消息只用颜色区分。
- `MessageLog`（`ui/widgets/message_log.py`）基于 `VerticalScroll` + `Static` 行，不是 RichLog；通过 `ALLOW_SELECT` 支持文本选择。
- 回复目标用 `up`/`down` 键在消息间导航（`reply_previous`/`reply_next`），被选中的消息整条 `reverse` 高亮，底部 `reply_info` 显示回复预览。`escape` 取消。
- 右键空白处复制选中文本，右键消息列表项置顶/取消置顶。

## 性能注意事项

群和好友很多时，避免在列表渲染路径中做以下操作：

- 不要对每个会话调用 `get_messages()` 反序列化完整历史。
- 预览应使用 `Storage.get_last_message()`。
- 不要在每条实时消息到达时立刻完整写 `cache.json`。

当前实现中实时消息只标记缓存 dirty，由 TUI 定时批量保存，退出时强制保存。

## 验证建议

修改后至少跑（覆盖根模块 + 整个 `ui/` 包）：

```powershell
.\.venv\bin\python.exe -m py_compile main.py config.py models.py onebot.py storage.py pinyin.py ui\app.py ui\styles.py ui\theme.py ui\clipboard.py ui\text_utils.py ui\widgets\message_log.py ui\logic\chat_logic.py ui\logic\message_logic.py ui\services\chat_service.py ui\services\message_service.py
```

`logic/` 是纯函数，可脱离 Textual 单测（直接 import + 传 data 调用）。

如果改了 UI 交互，建议用 Textual headless/autopilot 做最小验证，避免真实 NapBot 未启动时误判。注意 `textual.app.run_test` 需要交互式 TTY，在无 TTY 的子进程里会卡住，验证时在真实终端跑。

## OpenCode Zen 辅助

当前环境可通过 `opencode` 调用 OpenCode Zen 里的 DeepSeek V4 Flash Free，模型名是：

```text
opencode/deepseek-v4-flash-free
```

PowerShell 里可能无法直接解析 `opencode`，优先用 `cmd /c` 调用：

```bat
cmd /c opencode run -m opencode/deepseek-v4-flash-free "你的代码任务或检查指令"
```

用于代码执行、辅助检查或让外部模型给出改动建议时，提示词里要明确当前仓库路径，并说明是否允许修改文件；不希望它改文件时写明 `Do not modify files`。

## 修改约束

- 优先保持 Textual 单主界面结构，不要轻易恢复多 Screen 结构。
- 不要在主线程做网络 API 调用。
- 不要在高频消息事件里同步写大 JSON。
- 不要默认在打开群聊时拉全量成员列表，除非明确需要群成员缓存。
- 不要把 `data/cache.json`、`dist/`、`dist_single/` 当作源码维护。
