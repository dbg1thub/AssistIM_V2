# 客户端 UI 设计系统规范

本文档用于统一客户端的 QFluentWidgets 选型、布局容器、Tooltip、QSS、Acrylic 使用方式与扩展边界。

官方参考文档：

- QFluentWidgets API: https://pyqt-fluent-widgets.readthedocs.io/en/latest/autoapi/qfluentwidgets/index.html
- Gallery / 示例风格: https://pyqt-fluent-widgets.readthedocs.io/

## 1. 总体原则

客户端 UI 设计系统遵守以下原则：

- 先复用现成组件，再考虑自定义实现
- 风格统一优先于局部“看起来更特别”
- 容器层级尽量少，避免层层嵌套的随机 `QWidget` / `QFrame`
- 视觉材质统一，交互反馈统一，Tooltip 行为统一
- 样式集中管理，避免各页面自行发明一套规则
- 除非指明使用粗体，否则一律不准使用粗体

## 2. 组件选型顺序

新增 UI 时按以下顺序选型：

1. 先查 QFluentWidgets 是否已有现成组件
2. 如果存在 Acrylic 版本且适合该交互，优先选择 Acrylic 版本
3. 如果没有直接组件，优先组合多个现成组件
4. 只有现成组件明显无法满足需求时，才新增自定义 widget

新增自定义 widget 时必须回答两个问题：

- 为什么现有 QFluentWidgets 组件不够用
- 为什么组合现有组件仍然不够用

## 3. 容器类组件规范

### 3.1 默认容器统一使用 `CardWidget`

容器类业务 widget 默认统一使用 `CardWidget`。

适用场景：

- 页面内卡片容器
- 列表项卡片
- 表单区块
- 信息摘要区块
- 空状态容器
- 自定义业务面板

禁止默认使用以下方式充当业务卡片：

- 原生 `QFrame`
- 自定义“伪卡片” QWidget
- 多层嵌套 QWidget + setStyleSheet 拼背景
- 未经说明随意改用 `ElevatedCardWidget`

### 3.2 `ElevatedCardWidget` 不是默认方案

如果确实需要特殊层级强调，可以使用 `ElevatedCardWidget`，但必须满足：

- 有明确的视觉层级理由
- 不破坏页面整体卡片体系
- 不形成“每个页面都一套阴影”的样式漂移

默认情况下，新业务容器仍应使用 `CardWidget`。

### 3.3 样式参考 Gallery

卡片布局、间距、圆角、阴影、标题层级与对象命名方式，统一参考 QFluentWidgets Gallery 示例与项目中的 `style_sheet.py` 组织方式。

## 4. Tooltip 规范

### 4.1 默认 Tooltip 使用 Acrylic 方案

项目默认 Tooltip 方案为 Acrylic 系列。

优先顺序：

1. `AcrylicToolTip`
2. `AcrylicToolTipFilter`
3. 仅在 Acrylic 不适用时，才退回普通 `ToolTipFilter`

### 4.2 Tooltip 绑定使用 Filter，而不是手写 hover 逻辑

设置 Tooltip 时，优先通过 QFluentWidgets 的 Filter 机制统一处理，而不是每个控件自己重写 enter / leave / mouseMove。

推荐方式：

- 交互控件设置 `setToolTip(...)`
- 为控件安装 `AcrylicToolTipFilter` 或 `ToolTipFilter`
- 统一 Tooltip 位置、延迟与显示时长

### 4.3 Tooltip 文案要求

Tooltip 文案必须：

- 简短
- 动词或动作导向
- 不重复按钮本身已完整表达的信息
- 统一使用国际化资源，不写死字符串

## 5. 优先复用的 QFluentWidgets 组件

新增页面或交互时，优先评估以下现成组件：

- 导航：`FluentWindow`、`NavigationInterface`
- 设置页：`SettingCard`、`SettingCardGroup`
- 反馈：`InfoBar`、`StateToolTip`、`Flyout`、`TeachingTip`
- 菜单：`RoundMenu`
- 按钮：`PushButton`、`PrimaryPushButton`、`ToolButton`、`TransparentToolButton`
- 输入：`LineEdit`、`TextEdit`、`SearchLineEdit`
- 容器：`CardWidget`

原则：

- 只要 QFluentWidgets 已经把交互和视觉语言定义好了，就不要重复发明一套本地组件
- 自定义组件应建立在这些原子组件之上，而不是完全重造基础部件

## 6. QSS 与视觉 token 规范

样式统一通过共享样式系统管理：

- 使用 `client/ui/styles/style_sheet.py` 维护统一入口
- 页面样式拆分到对应 QSS 文件
- 颜色、圆角、透明度等使用共享 token
- 通过 `objectName` 区分具体卡片和控件

禁止：

- 在业务代码中大量拼接 `setStyleSheet`
- 把一个页面的局部颜色常量散落在多个 Python 文件里
- 直接复制一份相似 QSS 再轻微改色

## 7. Acrylic / Mica 使用原则

Acrylic 和 Mica 的使用要克制，不是“能用就全用”。

推荐使用场景：

- Navigation 面板
- Tooltip / Flyout / Menu
- 需要明显材质层次的顶部或浮层区域

不推荐：

- 在一个页面里叠很多层半透明卡片
- 在滚动区域里到处堆叠 Acrylic，导致性能和可读性变差
- 为了追求“炫”而牺牲文字可读性

## 8. 页面结构规范

典型页面结构建议如下：

- 页面根：业务页面容器或 Fluent 子页面
- 区块容器：`CardWidget`
- 区块标题：QFluentWidgets 文本组件
- 操作区：QFluentWidgets 按钮 / 菜单 / 输入组件
- 样式：共享 QSS + objectName

这套结构的目标是：

- 页面形态一眼可识别
- 样式复用成本低
- 后续替换皮肤或 token 时不需要改业务逻辑

## 9. 性能与可维护性原则

UI 系统还必须满足：

- 列表项避免层层嵌套复杂布局
- AI 流式更新做节流，不让 UI 每个 token 都重排
- Tooltip / Flyout / Menu 使用统一机制，避免每个页面重复造轮子
- 一个 widget 只负责一个明确职责，不在 widget 内混入网络与业务流程

## 10. 代码评审时的 UI 检查清单

看到新增 UI 时，优先检查：

- 是否优先复用了 QFluentWidgets 现成组件
- 容器是否统一收敛为 `CardWidget`
- Tooltip 是否使用 Acrylic 方案与 Filter 机制
- 是否沿用了共享样式系统，而不是内联 setStyleSheet
- 是否参考了 Gallery 风格，而不是页面各写一套视觉语言
- 是否把业务逻辑偷偷放进 widget 中
