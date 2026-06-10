# AGENTS.md

## 项目概况

这是一个基于 Textual 的 NapBot/OneBot v11 QQ 聊天 TUI 前端。入口是 `main.py`，核心界面在 `tui.py`，OneBot WebSocket 客户端在 `onebot.py`。

当前工作区路径：

`E:\PYQT\tui-qq`

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

- `main.py`: 启动 `QQChatApp`
- `tui.py`: Textual UI、会话列表、聊天窗口、回复选择、主题保存
- `onebot.py`: 同步 WebSocket OneBot v11 客户端，内部用 reader 线程接收事件
- `storage.py`: JSON 缓存读写，已加线程锁和唯一临时文件名，避免 Windows 下 `cache.json.tmp` 权限冲突
- `models.py`: `ChatInfo`、`MemberInfo`、`MessageData`
- `pinyin.py`: 名称搜索用的小鹤双拼/简拼工具
- `config.py`: 读取 `config.json`

## UI 行为

- 左侧列表显示会话名称和最后一条消息内容预览。
- 最近打开的会话置顶，并和其它会话用分隔行隔开。
- 预览只显示消息内容，不显示成员名。
- 长群名使用显示宽度截断，避免中文宽度导致整行消失。
- 聊天区消息都保持左侧布局，自己发出的消息只用颜色区分。
- RichLog 支持文本选择。
- 双击消息会把该消息设为回复目标，只更新底部回复提示，不重绘聊天记录。

## 性能注意事项

群和好友很多时，避免在列表渲染路径中做以下操作：

- 不要对每个会话调用 `get_messages()` 反序列化完整历史。
- 预览应使用 `Storage.get_last_message()`。
- 不要在每条实时消息到达时立刻完整写 `cache.json`。

当前实现中实时消息只标记缓存 dirty，由 TUI 定时批量保存，退出时强制保存。

## 验证建议

修改后至少跑：

```powershell
.\.venv\bin\python.exe -m py_compile main.py tui.py onebot.py storage.py models.py pinyin.py config.py
```

如果改了 UI 交互，建议用 Textual headless/autopilot 做最小验证，避免真实 NapBot 未启动时误判。

## 修改约束

- 优先保持 Textual 单主界面结构，不要轻易恢复多 Screen 结构。
- 不要在主线程做网络 API 调用。
- 不要在高频消息事件里同步写大 JSON。
- 不要默认在打开群聊时拉全量成员列表，除非明确需要群成员缓存。
- 不要把 `data/cache.json`、`dist/`、`dist_single/` 当作源码维护。
