# Chat UI 开发规范（Cursor / PySide6 Fluent）

## 1. 文档目的

本文件用于指导 **AI 代码助手（Cursor / Codex）** 实现桌面 IM 客户端的聊天界面。

AI 在生成代码前 **必须阅读并遵守本文件规则**。

适用范围：

* PySide6 桌面客户端
* PySide6-Fluent-Widgets UI
* 即时通讯聊天系统

---

# 2. 技术栈

客户端 UI 技术栈：

* Python
* PySide6
* PySide6-Fluent-Widgets
* WebSocket

UI 风格：

* Fluent Design
* 现代桌面 UI

---

# 3. 聊天界面整体布局

聊天界面采用经典 IM 布局：

```
┌───────────────────────────┬──────────────────────────────┐
│ 会话列表区域               │ 聊天区域                     │
│                           │                              │
│  ┌─────────────────────┐  │  ┌────────────────────────┐  │
│  │ 搜索框               │  │  │ 聊天顶部栏              │  │
│  ├─────────────────────┤  │  ├────────────────────────┤  │
│  │                     │  │  │                        │  │
│  │ 会话列表             │  │  │ 聊天消息列表            │  │
│  │                     │  │  │                        │  │
│  │                     │  │  │                        │  │
│  └─────────────────────┘  │  ├────────────────────────┤  │
│                           │  │ 消息输入区域            │  │
│                           │  └────────────────────────┘  │
└───────────────────────────┴──────────────────────────────┘
```

---

# 4. 主窗口结构

主窗口必须使用 `QSplitter` 实现左右布局。

结构：

```
MainWindow
└── QSplitter
    ├── SessionPanel
    └── ChatPanel
```

---

# 5. AI 开发规则（必须遵守）

AI 在实现代码时必须遵守以下规则：

1. 聊天消息列表必须使用 `QListView`
2. 数据管理必须使用 `QAbstractListModel`
3. 消息渲染必须使用 `QStyledItemDelegate`
4. 禁止使用 `QTextBrowser` 实现聊天消息
5. 禁止使用 `QVBoxLayout` 构建消息列表
6. 每种消息类型必须使用独立 Widget
7. UI 组件优先使用 Fluent Widgets
8. 所有 UI 必须使用 Layout 管理
9. 会话列表必须支持搜索

---

# 6. Fluent UI 组件规范

优先使用以下组件：

按钮：

* PushButton
* TransparentToolButton

文本：

* BodyLabel
* CaptionLabel
* TitleLabel

容器：

* CardWidget

头像：

* AvatarWidget

菜单：

* RoundMenu

搜索框：

* SearchLineEdit

---

# 7. 会话列表区域（SessionPanel）

## 7.1 UI 结构

```
SessionPanel
│
├── SearchLineEdit
└── SessionListView
```

---

## 7.2 Layout 结构

```
QVBoxLayout
│
├── SearchLineEdit
└── ListView
```

---

## 7.3 会话列表项 UI

每个会话项包含：

```
[头像] 用户名 未读数
      最后一条消息         时间   
```

组件：

* AvatarWidget
* BodyLabel
* CaptionLabel
* Badge

---

# 8. 会话搜索功能

组件：

```
SearchLineEdit
```

实现：

```
SessionModel
     │
QSortFilterProxyModel
     │
ListView
```

搜索范围：

* 用户名
* 群名称
* 最后一条消息

---

# 9. 聊天区域（ChatPanel）

```
ChatPanel
│
├── ChatHeader
├── MessageList
└── MessageInput
```

---

# 10. ChatPanel Layout

```
QVBoxLayout
│
├── ChatHeader
├── MessageList
└── MessageInput
```

---

# 11. 聊天顶部栏（ChatHeader）

UI：

```
用户名 输入状态              更多按钮
```

组件：

* TitleLabel
* CaptionLabel
* TransparentToolButton

---

# 12. 聊天消息列表（MessageList）

必须使用：

```
QListView
+ QAbstractListModel
+ QStyledItemDelegate
```

---

# 13. 消息类型设计

定义枚举：

```
MessageType
```

支持：

```
TEXT
IMAGE
FILE
VIDEO
```

未来扩展：

```
AUDIO
AI
SYSTEM
```

---

# 14. 消息数据结构

消息对象字段：

```
id
sender_id
receiver_id
timestamp
message_type
content
status
```

---

# 15. 消息气泡布局

对方消息：

```
头像  消息气泡
```

自己消息：

```
       消息气泡  头像
```

---

# 16. 文本消息

组件：

* CardWidget
* BodyLabel

---

# 17. 图片消息

组件：

* CardWidget
* QLabel

规则：

* 自动缩放
* 最大宽度 300px
* 点击预览

---

# 18. 文件消息

组件：

* CardWidget
* QLabel
* PushButton

UI：

```
report.pdf
2.3 MB
[下载]
```

---

# 19. 视频消息

组件：

* CardWidget
* QLabel
* ToolButton

播放：

Qt Multimedia

---

# 20. 消息输入区域（MessageInput）

组件：

* TextEdit
* TransparentToolButton
* PrimaryPushButton

---

# 21. MessageInput Layout

```
QVBoxLayout
│
├── ToolBar
└── InputArea
```

ToolBar：

```
EmojiButton
FileButton
ImageButton
```

---

# 22. 右键菜单

组件：

```
RoundMenu
```

菜单：

* 复制
* 删除
* 转发
* 引用

---

# 23. 滚动行为

新消息：

```
scrollToBottom()
```

---

# 24. 性能规则

聊天消息可能达到：

```
1000+
```

必须：

* 使用 QListView
* 使用 Model + Delegate
* 图片缩放

---

# 25. 推荐代码结构

```
client/
│
├── ui/
├── models/
├── proxies/
├── delegates/
└── widgets/
```

---

# 26. AI 实现顺序

1. MessageType
2. Message 数据类
3. MessageModel
4. MessageDelegate
5. 各类 MessageWidget
6. SessionPanel
7. ChatPanel
8. MessageInput
9. MainWindow

---

# 27. 架构总结

IM UI 核心结构：

```
Model + View + Delegate
```

---

# 28. 聊天列表性能优化

聊天窗口可能包含：

```
1000+
5000+
10000+
```

必须进行性能优化。

---

# 29. 虚拟列表渲染

必须使用：

```
QListView
```

禁止：

```
QScrollArea
QVBoxLayout
QTextBrowser
```

---

# 30. Model-View 架构

```
MessageModel
     │
QListView
     │
MessageDelegate
```

---

# 31. Delegate 渲染规则

必须使用：

```
QStyledItemDelegate
```

---

# 32. 图片加载优化

图片最大宽度：

```
300px
```

---

# 33. 图片缓存

实现缓存：

```
ImageCache
```

缓存策略：

```
LRU
```

---

# 34. 视频封面缓存

封面来源：

```
视频第一帧
```

缓存：

```
VideoThumbnailCache
```

---

# 35. 历史消息分页加载

分页：

```
20 条 / 页
```

流程：

```
滚动到顶部
↓
loadMoreMessages()
↓
加载历史
```

---

# 36. UI 更新策略

禁止：

```
modelReset()
```

必须使用：

```
beginInsertRows()
endInsertRows()
```

---

# 37. 气泡宽度限制

最大宽度：

```
60%
```

---

# 38. 文本自动换行

规则：

```
wordWrap = True
```

---

# 39. 输入框优化

组件：

```
QTextEdit
```

关闭富文本：

```
setAcceptRichText(False)
```

---

# 40. 滚动优化

推荐：

```
UniformItemSizes
```

---

# 41. 图片后台加载

必须使用：

```
QThreadPool
QRunnable
```

---

# 42. 内存控制

图片缓存：

```
100
```

视频封面：

```
50
```

---

# 43. 性能目标

聊天 UI 必须满足：

| 指标   | 目标      |
| ---- | ------- |
| 消息数量 | 10000   |
| 滚动   | 流畅      |
| 图片加载 | 即时      |
| 内存占用 | < 500MB |

---

---

# 44. 消息状态系统

每条消息必须包含发送状态。

状态枚举：

```
MessageStatus
```

支持状态：

```
PENDING
SENDING
SENT
DELIVERED
READ
FAILED
```

状态说明：

| 状态        | 说明      |
| --------- | ------- |
| PENDING   | 本地创建    |
| SENDING   | 正在发送    |
| SENT      | 已发送到服务器 |
| DELIVERED | 对方设备收到  |
| READ      | 对方已读    |
| FAILED    | 发送失败    |

---

# 45. 消息状态 UI

消息气泡右下角显示状态。

示例：

```
✓      已发送
✓✓     已读
⏳     发送中
❗     发送失败
```

组件：

```
CaptionLabel
```

---

# 46. 消息重发机制

当消息状态为：

```
FAILED
```

必须支持点击重发。

实现方式：

```
点击状态图标
↓
重新发送消息
```

---

# 47. 未读消息系统

会话列表必须显示未读数量。

UI：

```
用户名        (3)
最后一条消息
```

组件：

```
Badge
```

规则：

未读数量 > 99 时：

```
99+
```

---

# 48. 未读消息分割线

聊天窗口需要显示未读分割线。

UI：

```
──────── 未读消息 ────────
```

作用：

帮助用户定位未读消息位置。

---

# 49. 时间分割线

当两条消息间隔超过：

```
5 分钟
```

需要显示时间分割线。

示例：

```
────── 10:32 ──────
```

组件：

```
CaptionLabel
```

---

# 50. 时间显示规则

时间显示规则：

| 时间差  | 显示         |
| ---- | ---------- |
| 1分钟内 | 刚刚         |
| 1小时内 | 10:23      |
| 当天   | 10:23      |
| 昨天   | 昨天 10:23   |
| 一周内  | 星期二        |
| 更久   | 2024-05-12 |

---

# 51. 图片预览系统

点击图片消息必须打开图片查看器。

组件：

```
ImageViewerDialog
```

功能：

* 放大
* 缩小
* 拖动
* 保存图片

推荐组件：

```
QGraphicsView
```

---

# 52. 图片加载策略

图片加载需要支持：

```
缩略图
```

规则：

聊天列表：

```
缩略图
```

图片查看器：

```
原图
```

---

# 53. 文件下载系统

文件消息需要支持下载。

UI：

```
report.pdf
2.3MB
[下载]
```

下载中：

```
[进度条]
```

下载完成：

```
[打开]
```

组件：

```
ProgressBar
PushButton
```

---

# 54. 视频播放

视频消息点击后：

```
打开视频播放器
```

推荐：

```
Qt Multimedia
QMediaPlayer
```

---

# 55. 输入快捷键

输入框必须支持快捷键。

| 快捷键           | 功能   |
| ------------- | ---- |
| Enter         | 发送   |
| Shift + Enter | 换行   |
| Ctrl + Enter  | 发送   |
| Ctrl + V      | 粘贴图片 |
| Ctrl + C      | 复制   |
| Ctrl + X      | 剪切   |

---

# 56. 历史消息加载

聊天窗口必须支持加载历史记录。

触发条件：

```
滚动到顶部
```

加载流程：

```
scrollTop
↓
loadMoreMessages()
↓
请求服务器
↓
插入历史消息
```

---

# 57. 空聊天页面

当没有选择会话时显示空页面。

UI：

```
请选择一个聊天
```

组件：

```
BodyLabel
```

---

# 58. 会话置顶

会话列表必须支持置顶。

右键菜单：

```
置顶会话
取消置顶
删除会话
```

规则：

置顶会话始终在列表顶部。

---

# 59. 会话排序规则

会话排序规则：

1. 置顶会话
2. 最近消息时间

排序方式：

```
timestamp DESC
```

---

# 60. Cursor / Codex AI 代码生成规则

当 AI 生成聊天 UI 代码时必须遵守：

1. 所有 UI 使用 Layout 管理
2. 禁止硬编码位置
3. 消息列表必须使用 QListView
4. 数据必须使用 Model
5. 消息渲染必须使用 Delegate
6. UI 代码必须模块化
7. 每种消息类型独立 Widget
8. 禁止 QTextBrowser

AI 在生成代码前必须完整阅读本规范。

61. 消息引用（Reply）

聊天消息必须支持 引用回复。

引用结构：

reply_to_message_id

消息 UI：

┌─────────────────────┐
 回复：你好
─────────────────────
 我现在在开发客户端
└─────────────────────┘

引用区域包含：

原消息发送者

原消息内容摘要

组件：

CaptionLabel
CardWidget

62. 引用消息交互

点击引用区域需要定位到原消息。

实现流程：

点击引用
↓
查找原消息 ID
↓
滚动到对应消息

方法：

scrollTo(index)

63. 消息编辑（Edit Message）

用户可以编辑自己发送的消息。

限制：

只能编辑自己消息
编辑时间限制 2 分钟

右键菜单：

编辑

编辑后 UI：

(已编辑)

组件：

CaptionLabel

64. 消息撤回（Recall Message）

用户可以撤回已发送消息。

限制：

2 分钟内允许撤回

右键菜单：

撤回

撤回后消息变为：

你撤回了一条消息

类型：

SYSTEM

65. 消息多选模式

聊天窗口需要支持 消息多选模式。

触发方式：

长按消息
或
右键 → 多选

UI：

[✓] 消息1
[✓] 消息2
[✓] 消息3

顶部工具栏：

删除
转发

66. 输入状态（Typing Indicator）

当对方正在输入时需要显示提示。

UI：

对方正在输入...

组件：

CaptionLabel

动画：

...

更新频率：

2 秒

67. 表情系统（Emoji）

聊天输入框必须支持表情。

输入方式：

点击 EmojiButton

弹出面板：

EmojiPanel

结构：

EmojiButton
↓
EmojiPopup
↓
EmojiGrid

点击表情：

插入 TextEdit

68. 拖拽发送文件

聊天窗口需要支持 拖拽文件发送。

交互流程：

拖拽文件到聊天窗口
↓
显示拖拽遮罩
↓
释放鼠标
↓
发送文件消息

实现方法：

dragEnterEvent
dropEvent

支持文件类型：

图片
文档
视频
压缩包

69. 消息出现动画

新消息出现时需要动画。

动画类型：

淡入

实现方式：

QPropertyAnimation

动画时间：

150ms

作用：

提升用户体验

减少 UI 突然变化

70. AI 消息 UI

AI 聊天消息需要使用独立样式。

AI 消息结构：

AIMessageWidget

UI 示例：

🤖 AI
你好，我可以帮助你开发 IM 客户端。

组件：

AvatarWidget
CardWidget
BodyLabel

AI 消息可以包含：

文本
代码
Markdown

71. AI 思考状态

AI 回复前需要显示思考状态。

UI：

🤖 AI 正在思考...

动画：

...

组件：

CaptionLabel

触发流程：

用户发送消息
↓
显示思考状态
↓
收到 AI 回复
↓
替换为 AI 消息

72. UI 模块拆分规则

聊天 UI 必须拆分为独立模块。

推荐结构：

ui/
│
├── main_window.py
├── session_panel.py
├── chat_panel.py
├── chat_header.py
├── message_list.py
├── message_input.py

消息组件：

widgets/
│
├── message_text.py
├── message_image.py
├── message_file.py
├── message_video.py
├── message_ai.py

规则：

每个 UI 模块只负责一个功能

73. 聊天 UI 完整模块结构

完整聊天 UI 模块：

Chat UI
│
├── SessionPanel
├── ChatPanel
│
├── ChatHeader
├── MessageList
├── MessageInput
│
├── MessageWidgets
│   ├── Text
│   ├── Image
│   ├── File
│   ├── Video
│   └── AI

74. 聊天 UI 最终目标

聊天 UI 需要达到以下体验：

指标	目标
消息数量	10000+
滚动	流畅
图片加载	即时
历史加载	秒级
UI 响应	< 16ms
总结

聊天 UI 系统包含：

会话系统
消息系统
输入系统
媒体系统
AI系统
性能优化

所有代码生成必须遵守本规范。

75. UI 目录结构规范

客户端 UI 代码必须按照以下目录结构组织：

ui/
│
├── controllers/
├── widgets/
└── windows/

每个目录职责必须明确。

75.1 windows 目录

windows 目录用于存放 窗口级 UI。

特点：

独立窗口

页面级 UI

负责整体布局

示例：

ui/windows/
│
├── main_window.py
├── chat_window.py
├── login_window.py
└── settings_window.py

说明：

文件	作用
main_window.py	主程序窗口
chat_window.py	聊天界面窗口
login_window.py	登录界面
settings_window.py	设置界面

75.2 widgets 目录

widgets 目录用于存放 可复用 UI 组件。

特点：

可复用

独立功能

不直接依赖窗口

示例：

ui/widgets/
│
├── message_bubble.py
├── message_text.py
├── message_image.py
├── message_file.py
├── message_video.py
│
├── session_item.py
├── chat_header.py
├── message_input.py
└── emoji_panel.py

说明：

组件	作用
message_text	文本消息
message_image	图片消息
message_file	文件消息
message_video	视频消息
session_item	会话列表项
chat_header	聊天顶部栏
message_input	输入框
emoji_panel	表情面板

75.3 controllers 目录

controllers 目录用于存放 UI 逻辑控制层。

作用：

管理 UI 交互

连接数据与 UI

处理用户行为

示例：

ui/controllers/
│
├── chat_controller.py
├── session_controller.py
├── message_controller.py
└── input_controller.py

说明：

控制器	作用
chat_controller	聊天界面逻辑
session_controller	会话列表逻辑
message_controller	消息处理
input_controller	输入框行为
75.4 控制层职责

Controller 负责：

用户点击
↓
调用业务逻辑
↓
更新 UI

示例：

发送按钮点击
↓
controller.send_message()
↓
message_manager.send()
↓
更新 MessageModel

75.5 UI 架构关系

完整 UI 关系：

Window
  │
  ▼
Widgets
  │
  ▼
Controller
  │
  ▼
Managers / Services

说明：

层级	作用
Windows	页面级 UI
Widgets	组件
Controllers	UI 逻辑
Managers	业务逻辑

75.6 AI 代码生成规则

AI 在生成 UI 代码时必须遵守：

Window 代码只能放在 windows

可复用组件必须放在 widgets

UI 逻辑必须放在 controllers

禁止把所有代码写在一个文件

Window 不应包含复杂业务逻辑

总结

UI 代码必须按照以下结构组织：

ui/
├── controllers
├── widgets
└── windows

该结构可以保证：

UI 代码清晰

模块可复用

AI 生成代码稳定

当 AI 生成聊天 UI 代码时必须遵守：

所有 UI 使用 Layout 管理

禁止硬编码位置

消息列表必须使用 QListView

数据必须使用 Model

消息渲染必须使用 Delegate

UI 代码必须模块化

每种消息类型独立 Widget

禁止 QTextBrowser

AI 在生成代码前必须完整阅读本规范。


