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
- `message_record_limit`: 单个聊天 pane 保留的消息条数上限，默认 100；超过后剔除最旧消息
- `chat_list_render_limit`: 左侧列表单次挂载上限
- `cache_group_members_on_open`: 是否在打开群聊时拉全量群成员，默认关闭

`config.py` 只负责读取 `config.json` 并导出常量。

## 数据文件

`data/cache.json` 是本地缓存，包含群成员、最近会话、最后活动时间和消息缓存。这个文件可能很大，修改代码时不要把它当作源码手动重排。

`data/settings.json` 保存 UI 设置，目前主要用于保存 Textual 主题。主题切换快捷键是 `ctrl+t`。

## 主要模块

UI 已从原来的单文件 `tui.py`（已删除）按职责拆进 `ui/` 包，分四层：**纯逻辑**（`logic/`，无 Textual 依赖，可单测）、**网络+解析服务**（`services/`，worker 线程调用）、**UI 控制器**（`controllers/`，可操作 Textual 控件，按职责协调状态和界面）、**控件与 App 入口胶水**（`widgets/` + `app.py`）。

根目录模块（无变化）：

- `main.py`: 入口，`from ui import QQChatApp` 后 `app.run()`
- `onebot.py`: 同步 WebSocket OneBot v11 客户端，内部用 reader 线程接收事件
- `storage.py`: JSON 缓存读写，已加线程锁和唯一临时文件名，避免 Windows 下 `cache.json.tmp` 权限冲突
- `models.py`: `ChatInfo`、`MemberInfo`、`MessageData`
- `pinyin.py`: 名称搜索用的小鹤双拼/简拼工具
- `config.py`: 读取 `config.json`

`ui/` 包：

- `ui/__init__.py`: 暴露 `QQChatApp`
- `ui/app.py`: `QQChatApp`——Textual 主 App。持有 `AppState`、bindings、compose、生命周期、worker 入口、Toast、action 代理；鼠标事件/导航/侧边栏/实时事件/分屏/列表/消息渲染已全部委托给 `controllers/`。`app.py` 仍保留 `__getattr__`/`__setattr__` 兼容映射，但新代码优先使用 `app.state.xxx`
- `ui/state.py`: `AppState`、`ChatPaneState` 和 pane 相关纯 helper
- `ui/controllers/chat_list.py`: `ChatListController`——左侧会话列表渲染、搜索结果选择、单项刷新
- `ui/controllers/messages.py`: `MessageController`——**facade**，继承自 `messages_renderer`/`messages_actions`/`messages_input`/`messages_scroll`
- `ui/controllers/messages_renderer.py`: `MessageRendererMixin`——renderable 构建、写入 log、选择重绘、reply_info 更新
- `ui/controllers/messages_actions.py`: `MessageActionsMixin`——回复/+1/追加/`show_messages` 回调
- `ui/controllers/messages_input.py`: `MessageInputMixin`——输入框可见性、`start_message_input`、`submit_message_input`
- `ui/controllers/messages_scroll.py`: `MessageScrollMixin`——滚动检测、底部滚动按钮显示/隐藏、`force_scroll_end`
- `ui/controllers/mouse.py`: `MouseController`——鼠标命中检测（聊天列表/消息动作/输入框）、右键复制/粘贴/置顶，`app.py` 只转发事件
- `ui/controllers/navigation.py`: `NavigationController`——键盘导航状态机、焦点层切换、会话预览/提交、绑定 action 的主要实现
- `ui/controllers/panes.py`: `PaneController`——分屏查找、增删、布局 class、输入框归属和 pane 标题/按钮状态
- `ui/controllers/sidebar.py`: `SidebarController`——侧边栏显示/隐藏、窄屏自动隐藏、隐藏后的焦点回落
- `ui/controllers/realtime.py`: `RealtimeController`——定时 drain OneBot 事件队列，内部使用 `message_logic.parse_realtime_event` 纯函数解析事件
- `ui/styles.py`: `APP_CSS` 字符串常量（不用 `.tcss`，PyInstaller 友好）
- `ui/theme.py`: `ROLE_STYLES` + 布局常量（`CHAT_LIST_TEXT_WIDTH`、`SIDEBAR_AUTO_HIDE_*` 等）
- `ui/clipboard.py`: PowerShell 剪贴板 get/set，非 Windows 降级 no-op
- `ui/text_utils.py`: 纯函数 `format_time` / `display_width` / `ellipsize` / `extract_text`
- `ui/widgets/message_log.py`: `MessageLog` 控件（基于 `VerticalScroll` + `Static` 行，**不是 RichLog**）
- `ui/logic/chat_logic.py`: 纯函数——过滤/排序/搜索/列表文本/导航索引（无 `self`、无 `query_one`）
- `ui/logic/message_logic.py`: 纯函数 + **OneBot 段类型注册表**（`register_segment`）+ `RealtimeEventUpdate` dataclass + `parse_realtime_event` 纯函数。这是消息扩展点：加新消息段类型只注册 handler，不动 dispatcher
- `ui/services/chat_service.py`: `load_chats`——拉好友/群列表 → `ChatInfo`，吸收防御性解析
- `ui/services/message_service.py`: `load_history` / `send` / `cache_group_members`——网络调用 + 防御性解析，由 App 在 worker 线程调用

## 架构约定（重要）

修改时遵循四层边界：

- **`logic/` 是纯函数**：不允许 `import textual`，不允许 `query_one`/`mount`/`self.storage` 写操作。接收 data + storage（只读）返回结果。App 持有可变状态（如 `_search_cache`）并加锁拷贝后传入。
- **`services/` 调网络**：只能被 App 的 worker 线程调用（`_run_thread`），**绝不在主线程跑**。返回干净 dataclass，UI 回调用 `call_from_thread` 回主线程。
- **`controllers/` 是 UI 协调层**：允许 `query_one`/`focus`/`mount`/`log.write` 等 Textual 操作，但要按职责放到对应 controller。不要把新键盘状态机、侧边栏行为、实时事件分发、分屏管理、列表渲染或消息渲染继续塞回 `app.py`。
- **`app.py` 保持薄胶水**：保留 Textual 生命周期、bindings、compose、worker 入口、全局状态持有和事件入口；具体交互行为优先委托 `controllers/`。如果 App 里新增大段逻辑，先考虑是否应落在已有 controller 或新 controller。

扩展新功能时先想"这是逻辑、网络、UI 协调还是控件"：加新消息段类型→改 `message_logic` 注册表；加新列表过滤规则→改 `chat_logic`；加新 OneBot API 调用→改 `services/` 并从 worker 调用；加新键盘/焦点行为→改 `NavigationController`；加新侧栏行为→改 `SidebarController`；加新实时消息落地规则→改 `RealtimeController`；加新控件→放 `ui/widgets/`。

`app.py` 的 `_run_thread` 是带异常兜底的 worker 入口：未捕获异常会 `call_from_thread(_show_toast)` 而非静默崩溃。新 worker 一律走它。

## 后续优化方向

当前拆分已经把大块 UI 行为移出 `app.py`，并引入了 `AppState` 收敛状态；controller 已改为通过 `app.state.xxx` 读写状态。继续优化时优先按以下顺序推进：

1. 收窄 controller 对 App 的依赖：优先用小型 host/facade 或 `typing.Protocol` 描述 controller 需要的能力，避免 controller 依赖完整 `QQChatApp` 和大量私有字段。
2. **`app.py`** 的兼容映射（`__getattr__`/`__setattr__` + `_STATE_COMPAT_FIELDS`）已不再被 controller 依赖，可以考虑在后续大版本中移除，届时取消映射后所有读写必须走 `app.state.xxx`。
3. 扩展注册表：`message_logic` 已有 OneBot 段类型注册表；后续消息动作（如 reply、plus-one）、右键动作或快捷动作也可做成注册表，减少 dispatcher 分支。
4. 进一步纯化实时消息处理：`RealtimeController.handle_event` 中的消息落地（storage/UI）应用逻辑也可拆成纯数据变更描述，controller 只负责执行。
5. 鼠标/右键交互的 `MouseController` 已被独立，但复选文本、消息 action 点击等行为的动作迁移到注册表模式可继续简化 dispatcher。

## UI 行为

- 左侧列表显示会话名称和最后一条消息内容预览。
- 最近打开的会话置顶，并和其它会话用分隔行隔开。
- 预览只显示消息内容，不显示成员名。
- 长群名使用显示宽度截断，避免中文宽度导致整行消失。
- 聊天区消息都保持左侧布局，自己发出的消息只用颜色区分。
- `MessageLog`（`ui/widgets/message_log.py`）基于 `VerticalScroll` + `Static` 行，不是 RichLog；通过 `ALLOW_SELECT` 支持文本选择。
- 回复目标用 `up`/`down` 键在消息间导航（`reply_previous`/`reply_next`），被选中的消息整条 `reverse` 高亮，底部 `reply_info` 显示回复预览。`escape` 取消。
- `ctrl+b` 只在消息记录 pane 层生效，用于把当前聊天记录滚动到底部。
- 单个聊天 pane 最多保留 `message_record_limit` 条消息，达到上限后自动剔除最旧消息。
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
.\.venv\bin\python.exe -m py_compile main.py config.py models.py onebot.py storage.py pinyin.py ui\app.py ui\state.py ui\styles.py ui\theme.py ui\clipboard.py ui\text_utils.py ui\widgets\chat_pane.py ui\widgets\message_log.py ui\logic\chat_logic.py ui\logic\message_logic.py ui\services\chat_service.py ui\services\message_service.py ui\controllers\__init__.py ui\controllers\chat_list.py ui\controllers\messages.py ui\controllers\messages_renderer.py ui\controllers\messages_actions.py ui\controllers\messages_input.py ui\controllers\messages_scroll.py ui\controllers\mouse.py ui\controllers\navigation.py ui\controllers\panes.py ui\controllers\realtime.py ui\controllers\sidebar.py tests\test_messages.py
```

`logic/` 是纯函数，可脱离 Textual 单测（直接 import + 传 data 调用）。`state.py` 可直接单测；`controllers/` 可以用 fake app/fake widget 做轻量单测，参考 `tests/test_state.py`、`tests/test_navigation_controller.py`、`tests/test_panes.py`。

常规单测：

```powershell
.\.venv\bin\python.exe -m unittest
```

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
