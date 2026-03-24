# 客户端 UI 设计系统规范

本文档用于统一 AssistIM 客户端的 Fluent Design 视觉语言、QFluentWidgets 组件选型、材质使用、交互反馈、QSS 约束与 IM 场景下的页面层级。

本文档的目标不是“描述当前代码长什么样”，而是给后续 UI 重构和新增功能提供一套成熟、常见、可扩展、低耦合的正式规则。

官方参考文档：

- QFluentWidgets API: https://pyqt-fluent-widgets.readthedocs.io/en/latest/autoapi/qfluentwidgets/index.html
- QFluentWidgets Gallery: https://pyqt-fluent-widgets.readthedocs.io/

## 1. 适用范围与设计目标

本规范适用于：

- 主窗口
- 导航与会话列表
- 聊天页头部、消息流、输入区
- 联系人、发现、设置、资料等业务页面
- Tooltip、Flyout、Context Menu、ComboBox Dropdown、InfoBar、Dialog 等浮层与提示组件

设计目标只有六条：

- 视觉层级清楚：用户能一眼分辨基底层、内容层、浮层
- 交互反馈明确：hover、pressed、focus、cursor、disabled 一致
- 组件选型稳定：优先复用 QFluentWidgets，而不是每页单独造轮子
- 材质语义正确：Mica、Acrylic、Smoke、Card 各司其职
- 长时间使用耐看：作为 IM 软件，高频区域必须低噪声、低压迫、可持续使用
- 样式收敛可维护：优先共享 token、QSS 和公共 widget，不把样式散落在业务代码中

## 2. Fluent Design 五大支柱

AssistIM 的视觉系统遵循 Fluent Design System 的五个支柱：Light、Depth、Material、Motion、Scale & Geometry。

### 2.1 Light

光感用于告诉用户“哪里可以操作、当前焦点在哪里、操作是否已被响应”。

必须满足：

- hover 有轻量反馈，不能完全静止
- pressed 有即时反馈，不能点击无感
- 键盘 focus 可见，不能只依赖系统默认虚线框
- 重要操作的聚焦要清楚，尤其是按钮、列表项、输入区与弹层入口

推荐：

- 使用符合 Fluent 风格的轻量 hover 背光或表面强调
- 对键盘导航路径保留 reveal focus 或等价焦点高亮

### 2.2 Depth

深度用于建立信息层级，降低认知负担。

正式层级分为：

- Base：窗口或页面大背景
- Content：会话区、聊天区、卡片、表单、资料区块
- Overlay：Tooltip、Flyout、Menu、Dropdown、InfoBar、Dialog

必须满足：

- 不允许所有区域都做成同一层平面
- Overlay 必须明显浮于 Content 之上
- Content 层优先通过卡片、间距、描边、轻阴影建立分层
- Base 不参与过度争夺视觉注意力

### 2.3 Material

材质用于建立重量感、空间感和交互语义。

项目只使用以下四类核心材质：

- Mica：窗口背景或大页面基底
- Acrylic：瞬时性、轻量级、浮于内容之上的叠加层
- Smoke：模态遮罩
- Card：常驻内容组织容器

材质不是装饰，必须对应明确语义：

- Mica 传达“这是应用窗口的基底”
- Acrylic 传达“这是短暂停留的浮层”
- Smoke 传达“当前流程需要强聚焦”
- Card 传达“这是一组稳定内容”

### 2.4 Motion

动画在 Fluent 中是功能性过渡，不是装饰。

必须满足：

- 弹层出现有方向感或来源感
- 点击和切换有克制的响应反馈
- 页面切换或区域展开收起不突兀

禁止：

- 高噪声、长时间、无信息量动画
- 多处元素同时剧烈运动
- 为了“炫”而牺牲可读性或性能

### 2.5 Scale & Geometry

比例与几何用于建立统一的现代视觉秩序。

必须满足：

- 顶级窗口、卡片、按钮、浮层使用统一圆角体系
- 字阶稳定，不允许每页各发明一套字号
- 图标风格统一，优先 FluentIcon / Segoe Fluent Icons
- 字体优先使用 `Segoe UI Variable`

字体优先顺序：

1. `Segoe UI Variable`
2. `Segoe UI`
3. 中文补充 `Microsoft YaHei UI`
4. emoji 补充 `Segoe UI Emoji`、`Apple Color Emoji`、`Noto Color Emoji`

## 3. 组件选型原则

新增 UI 时，按以下顺序选型：

1. 优先查找 QFluentWidgets 是否已有现成组件
2. 如果有符合语义的 Acrylic 版本，优先使用 Acrylic 版本
3. 如果没有直接组件，优先组合多个现成组件
4. 只有现成组件明显不满足时，才新增自定义 widget

新增自定义 widget 时必须能回答：

- 为什么现有 QFluentWidgets 组件不够用
- 为什么组合现有组件仍然不够用
- 它的职责是否稳定、可复用，而不是一次性页面特例

## 4. 容器与内容层规范

### 4.1 容器类 widget 默认统一使用 `CardWidget`

所有容器类业务 widget 默认使用 `CardWidget`。

适用场景：

- 资料区块
- 设置区块
- 摘要卡片
- 空状态卡片
- 列表容器
- 详情区块
- 表单区块

禁止默认使用以下方式充当业务卡片：

- 原生 `QFrame`
- 纯 `QWidget` + 大段 `setStyleSheet`
- 多层嵌套 QWidget 拼背景
- 无理由直接改成 `ElevatedCardWidget`

### 4.2 `ElevatedCardWidget` 不是默认容器

只有在明确需要更高层级强调时，才允许使用 `ElevatedCardWidget`。

必须满足：

- 有明确层级理由
- 不破坏页面整体卡片体系
- 不制造“每个模块都不同阴影”的风格漂移

### 4.3 风格参考 Gallery

卡片间距、标题层级、圆角、阴影、分组方式、对象命名，统一优先参考 QFluentWidgets Gallery 示例，而不是项目内各模块自行发挥。

## 5. 材质使用规范

### 5.1 Mica

用途：

- 主窗口背景
- 顶级页面基底

规则：

- 只用于大背景，不用于局部小卡片
- 不在滚动内容区层层叠加
- 不把聊天气泡、资料卡片、工具条做成 Mica

### 5.2 Acrylic

Acrylic 是半透明、带模糊、允许底层内容被感知的浮层材质。它表达的是“瞬时性”和“叠加感”。

主要用途：

- Flyout
- Context Menu / RoundMenu
- Tooltip
- ComboBox Dropdown
- 轻量浮层型 InfoBar
- 其他短暂停留的上方浮层

规则：

- Acrylic 只用于临时性、轻量级、浮在当前内容之上的 UI
- 不把主内容区、常驻侧栏、常驻卡片做成 Acrylic
- 使用 Acrylic 时必须检查内部子 widget 是否透明，不能被不透明背景盖住
- 如果一个面板要长期常驻，它就不应该用 Acrylic

设计原则：

- 层级感知：让用户知道它“浮”在当前内容之上
- 视觉聚焦：通过模糊背景，把注意力集中在当前弹出内容上

### 5.3 Smoke

用途：

- 模态对话框背景遮罩
- 截图确认、危险操作确认、强制中断流程

规则：

- 只在需要阻断底层操作时使用
- 不把普通提示做成重模态

### 5.4 Card

用途：

- 组织常驻内容
- 承载信息层
- 明确区块边界

规则：

- 内容层优先使用 Card
- Card 通过圆角、描边、间距和轻阴影建立边界
- 不用大面积重色块替代真正的层级设计

## 6. Tooltip、Flyout、Menu、Dropdown 规范

### 6.1 Tooltip 默认使用 Acrylic

推荐顺序：

1. `AcrylicToolTip`
2. `AcrylicToolTipFilter`
3. 只有 Acrylic 不适用时，才退回普通 `ToolTipFilter`

### 6.2 Tooltip 统一从上方弹出

规则：

- Tooltip 默认使用顶部弹出位置
- 同一操作区域内的 Tooltip 位置必须一致
- 不同页面不要各自发明 left、right、bottom 的随机策略

### 6.3 Tooltip 使用 Filter，不手写 hover 逻辑

推荐方式：

- 先设置 `setToolTip(...)`
- 再安装 `AcrylicToolTipFilter`
- 统一延迟、位置、显示时长

### 6.4 Tooltip 文案要求

Tooltip 文案必须：

- 使用国际化资源
- 优先显示动作名称或对象名称
- 不显示 emoji 本身、原始 key、技术字段名
- 对图标按钮补足语义

### 6.5 Flyout / Menu / Dropdown 规范

规则：

- 轻量弹出内容优先使用 Fluent 体系现成 Flyout / Menu / Dropdown
- 弹层默认采用 Acrylic 视觉路径
- 内容区域保持简洁，不在 Flyout 内塞长驻复杂面板
- 弹层要有清晰的来源控件和关闭语义

## 7. 用户反馈规范

所有需要用户知晓的信息、警告、错误，统一优先通过 `InfoBar` 提示。

适用场景：

- 操作成功
- 输入校验失败
- 网络失败
- 权限不足
- 风险警告
- 状态同步说明
- 后台任务完成或失败

禁止：

- 用控制台输出代替用户提示
- 用静态文本偷偷替代正式反馈
- 用 MessageBox 滥用普通成功提示

原则：

- 成功提示简短
- 错误和警告可读、明确、可行动
- 轻提示优先非阻断，重风险再考虑模态

## 8. 鼠标手势与交互反馈规范

所有交互控件都必须设置合适的鼠标手势。

最低要求：

- 可点击：`PointingHandCursor`
- 文本输入：`IBeamCursor`
- 拖动分隔条：对应 resize cursor
- 禁用态：不保留误导性的点击 cursor

同时必须具备：

- hover 反馈
- pressed 反馈
- disabled 反馈
- focus 可见性

不允许：

- 能点但像不能点
- 不能点但 cursor 仍像能点
- 只有颜色变化、没有状态层级

## 9. 排版、图标与几何规范

### 9.1 字阶

统一使用稳定字阶：

- Caption
- Body
- Subtitle
- Title
- Headline

禁止每个页面自己硬编码一套大小体系。

### 9.2 图标

规则：

- 优先使用 FluentIcon / Segoe Fluent Icons
- 图标风格统一
- 避免一个页面线性、一个页面拟物、一个页面实心

### 9.3 圆角

规则：

- 顶级窗口、按钮、卡片、弹层使用统一圆角体系
- 小型 hover tile、icon button、badge、bubble 都应服从统一几何节奏
- 不允许一个页面 4px、6px、8px、14px、18px 无规则混用

## 10. IM 场景专用规则

作为 IM 软件，页面层级建议如下：

- 窗口基底：Mica 或稳定基底材质
- 左侧导航 / 会话区：内容层，可使用 Card 或轻描边分区
- 右侧聊天区：内容层，头部、消息流、输入区层级清楚
- 临时操作：Tooltip、菜单、Emoji Picker、Dropdown 使用 Acrylic
- 截图确认、编辑消息、危险操作：对话框 + Smoke 遮罩

IM 额外要求：

- 会话列表 hover / selected / unread 状态清楚
- 聊天气泡与头像、状态、时间关系稳定，不跳动
- 输入区是高频使用区域，必须耐看、清晰、低噪声
- 消息列表滚动、窗口缩放、splitter 拖动时不能出现明显闪空
- 大量重复元素依靠共享 token 和几何统一，而不是逐个手调

### 10.1 会话列表

规则：

- 当前选中项必须明显强于 hover 态
- unread、置顶、草稿、静音、时间等信息层级清楚
- 列表项应有明确的卡片化边界或表面反馈，而不是平面填色

### 10.2 聊天头部

规则：

- 当前会话身份信息必须清楚，支持标题、状态、副信息分层
- 操作按钮应统一 hover、tooltip、对齐与命中区
- 头部是内容层，不应被做成无边界的裸文字条

### 10.3 消息气泡

规则：

- 气泡几何要稳定，内容增长统一向下扩展
- 头像、气泡角、状态、时间的相对关系保持一致
- 文本、图片、视频、文件消息保持统一的 bubble token
- 系统提示、撤回提示、时间分隔和普通消息在层级上必须可区分

### 10.4 输入区

规则：

- 输入框、工具条、待发送附件区应形成清晰的一组内容层
- 输入区优先保持轻量、克制、可持续使用，不堆砌重背景和重描边
- Emoji、附件、截图、发送等高频入口必须具备统一 hover、tooltip、cursor 规则

## 11. QSS 与 token 管理规范

样式统一通过共享样式系统管理：

- 使用 `client/ui/styles/style_sheet.py` 维护统一入口
- 页面样式拆分到对应 QSS 文件
- 颜色、圆角、透明度、间距使用共享 token
- 通过 `objectName` 区分具体控件和卡片

禁止：

- 在业务代码里大量拼接 `setStyleSheet`
- 把一个页面的颜色和几何常量散落在多个 Python 文件
- 直接复制一份相似 QSS 再轻微改色

## 12. 性能与可维护性原则

UI 系统必须同时满足：

- 列表项避免层层嵌套复杂布局
- Delegate 绘制与 QWidget 方案边界清楚
- 滚动列表在 resize、splitter 拖动时不能明显闪空或消失
- Tooltip / Flyout / Menu / Dropdown 使用统一机制
- 一个 widget 只负责一个明确职责，不在 widget 内混入网络与业务流程

## 13. 代码评审时的 UI 检查清单

看到新增 UI 时，优先检查：

- 是否优先复用了 QFluentWidgets 现成组件
- 是否把 Mica / Acrylic / Smoke / Card 用在了正确层级
- 容器是否统一收敛为 `CardWidget`
- Tooltip 是否使用 Acrylic 方案、顶部弹出、Filter 机制
- 用户提示是否统一通过 `InfoBar`
- 所有交互控件是否有正确 cursor、hover、pressed、disabled、focus 状态
- 是否沿用了共享样式系统，而不是内联 `setStyleSheet`
- 是否使用国际化文案，而不是写死英文或原始字符串
- 是否参考了 Gallery 风格，而不是页面各写一套视觉语言
- 是否把业务逻辑偷偷放进 widget 中
