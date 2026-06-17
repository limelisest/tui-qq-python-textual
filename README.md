# TUI-QQ

TUI-QQ 是一个基于 [Textual](https://textual.textualize.io/) 的 QQ 聊天终端前端，用于连接 NapCat / OneBot v11 WebSocket 后端。它提供群聊和好友会话列表、消息历史、实时消息、回复、搜索、置顶、主题保存和本地缓存等功能。

## 功能

- 连接 NapCat / OneBot v11 WebSocket 服务。
- 显示群聊和好友会话列表，支持名称、QQ 号、简拼和小鹤双拼搜索。
- 左侧会话列表支持手动置顶 / 取消置顶。
- 聊天记录支持鼠标选择文字，右键复制选中文本。
- 右键无选中文本时可从系统剪贴板粘贴到输入框。
- 支持拉取历史消息和接收实时消息。
- 支持回复消息，使用上下键在聊天记录中选择回复目标。
- 支持自动置底；手动向上滚动后会显示置底按钮。
- 顶部按钮可隐藏 / 显示左侧会话列表。
- 窗口宽度小于 700px 时自动隐藏侧边栏，`Ctrl+Left` / `Ctrl+Right` 切换会话时会临时显示列表。
- 支持 Textual 主题切换并保存到本地设置。

## 运行环境

需要 Python 3.10+，依赖见 `requirements.txt`：

```powershell
pip install -r requirements.txt
```

推荐先启动 NapCat，并确认 OneBot v11 WebSocket 地址可访问。

## 快速启动

Windows 下优先使用：

```bat
run.bat
```

也可以直接运行：

```powershell
.\.venv\bin\python.exe main.py
```

如果你的虚拟环境在 Windows 默认路径，也可以使用：

```powershell
.\.venv\Scripts\python.exe main.py
```

## 配置

配置文件是项目根目录下的 `config.json`：

```json
{
  "ws_url": "ws://127.0.0.1:3001",
  "ws_token": "",
  "cache_dir": "data",
  "cache_file": "cache.json",
  "settings_file": "settings.json",
  "recent_chats_count": 5,
  "history_message_count": 50,
  "chat_list_render_limit": 300,
  "cache_group_members_on_open": false
}
```

字段说明：

- `ws_url`: NapCat / OneBot v11 WebSocket 地址。
- `ws_token`: WebSocket 鉴权 token，没有鉴权时留空。
- `cache_dir`: 本地缓存目录。
- `cache_file`: 聊天缓存文件名。
- `settings_file`: UI 设置文件名。
- `recent_chats_count`: 最近会话数量配置。
- `history_message_count`: 打开会话时拉取的历史消息数量。
- `chat_list_render_limit`: 左侧会话列表单次渲染上限。
- `cache_group_members_on_open`: 打开群聊时是否拉取群成员缓存，默认关闭。

## 快捷键

- `Ctrl+R`: 刷新会话列表。
- `Ctrl+T`: 切换 Textual 主题。
- `Ctrl+S`: 搜索
- `Ctrl+D`: 新建会话窗口
- `Ctrl+W`: 关闭当前选择的会话窗口
- `Ctrl+E`: 切换窗口布局
- `ESC`: 返回上一级
- `Enter`: 选择
- `小键盘方向键`：移动选择
- `TAB`: 切换群聊列表选择

## 数据文件

运行时会在 `data/` 目录生成本地数据：

- `cache.json`: 群成员、最近会话、最后活动时间、消息缓存和置顶会话。
- `settings.json`: UI 设置，目前主要保存 Textual 主题。

这些文件是运行数据，不建议手动重排或作为源码维护。

## 项目结构

- `main.py`: 应用入口。
- `tui.py`: Textual UI、会话列表、聊天窗口、快捷键和交互逻辑。
- `onebot.py`: 同步 OneBot v11 WebSocket 客户端。
- `storage.py`: 本地 JSON 缓存读写。
- `models.py`: 会话、成员和消息数据模型。
- `pinyin.py`: 名称搜索使用的拼音和小鹤双拼工具。
- `config.py`: 读取并解析 `config.json`。

## 开发验证

修改后建议至少运行：

```powershell
.\.venv\bin\python.exe -m py_compile main.py tui.py onebot.py storage.py models.py pinyin.py config.py
```

如果修改了 UI 交互，建议补充 Textual headless 测试，避免在 NapCat 未启动时误判连接问题。
