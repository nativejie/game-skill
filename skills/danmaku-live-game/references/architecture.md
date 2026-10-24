# 架构

## 目录

```
config/game.json          数值、事件轮换、选用的主题 ("theme")
config/theme_<id>.json    所有给人看的字（见 theme-layer.md）
scripts/core/             规则：纯逻辑、只认 id 和数值、无头可测
scripts/view/             画面：只读状态、消费事件
scripts/game.gd           组装层：建画面、把规则事件分发给画面、节流存档
scripts/debug/            模拟观众、主播控制台、截图导演、演示导演（都标明本地模拟）
tests/run_tests.gd        无头规则测试
tools/soak.gd             一小时无头实测
validate.py               导入 + 每个脚本编译检查 + 跑测试
```

## 规则层

### 唯一入口

```gdscript
func command(uid: String, display_name: String, text: String) -> Dictionary  # {ok, message, events}
func tick(delta: float) -> Array  # 事件列表
```

- 弹幕先经 `CommandParser.parse(text)` 变成 `{verb, arg}`，verb 是固定的英文 id。
- 所有规则模块（入侵、幻阵、天雷、商店、炼器、夺宝、世界BOSS、宗门…）都挂在一个 `GameState` 上，由它分派。
- 外部来源（控制台发外观、以后的平台礼物）也走 `GameState` 上的公开函数（例如 `grant_cosmetic(uid, id, days)`、`gift(uid, 昵称, gift_id, count)`、`like(uid, count)`），不要直接改玩家对象。
- 平台消息先经过**适配层**变成统一事件再进规则：抖音、本地控制台、模拟观众、录像回放各一个适配器，规则层不知道消息从哪来（`platform-integration.md`）。

### 弹幕洪峰

大直播间一秒几十上百条消息，绝大多数是聊天：

- 适配层把消息放进队列，规则层每帧最多处理固定条数（例如 50），剩下的下一帧；队列超长先丢普通评论，礼物永远不丢。
- 解析失败的评论只计数，不回复、不飘字。
- 同一 uid 一秒内重复的指令合并，每人每秒有效指令数设上限。
- 按 `msg_id` 去重，礼物结算幂等（平台会重推）。
- uid → 席位、昵称 → uid 都用字典查，不要每条弹幕遍历 30 个席位。
- 所有收到的统一事件按行写 jsonl，出问题时用回放适配器复现。

### 事件

普通字典，`type` + 需要的 id 和数值：

```gdscript
{"type": "kill", "uid": uid, "seat": 3, "qi": 18988, "stones": 12, "toughest": false}
{"type": "loot", "uid": uid, "seat": 3, "item": "herb", "amount": 1, "stones": 0}
{"type": "phase", "phase": Phase.EVENT, "kind": "invasion", "round": 5}
```

不在事件里放显示文案；画面层用主题取名字。唯一例外是玩家昵称这类本来就是数据的字符串。

### 玩家对象

- 一个 `Cultivator`（或同类）存一个观众的永久进度：等级、货币、物品 `{id: 数量}`、装备 `{部位: 品质}`、外观 `owned {id: 到期时间, 0 = 永久}` / `wearing {类别: id}`、各种计数器（击杀、破阵、夺宝中奖…）。
- `to_dict()` / `from_dict()`：读取时每个字段都给默认值并校验（id 不在目录里就丢掉），这样旧存档、手改的存档都不会把游戏弄崩。
- 加成统一走一个函数，例如 `extra(stat)` = 外观 + 神器 + 灵宠 + …，各处只调它，加新系统时不会漏。

### 存档

- 顶层 `{"schema": N, "roster": …, "heart": …, "boss": …, "sect": …}`；`restore` 接受 1..N 的所有版本。
- 节流写盘（例如 15 秒一次），在后台线程写，主线程只做快照。
- 截图、演示、测试模式不写存档。

## 画面层

- 每个视图只读 `GameState`、响应事件，不改规则。
- 大场景（例如整屏的五行幻阵）可以盖住棋盘；被盖住时其它视图不要在棋盘上飘字。
- 事件叠层（商店、炼器、夺宝…）共用一个基类：半透明压暗棋盘 + 中间主体 + 卡片。
- 美术：运行时直接读 PNG（不走引擎导入），先查主题目录再查通用目录，启动时预载全部贴图（第一次显示某个图标时读盘会卡 40–70 ms）。
- 飘字、伤害数字、弹道用对象池并设同屏上限（例如 60 个），超出时合并成「×N」；大礼物的全屏效果进队列逐个播放。

## Godot 4 的具体坑

- **不能把类命名为 `Theme`**：和引擎自带的 Theme 资源重名。这里的主题加载器叫 `Words`。
- 新增 `class_name` 以后，无头跑脚本前要先 `Godot --headless --path <proj> --import --quit` 刷新全局类缓存，否则报「Identifier not declared」。
- 无头脚本出错时不会退出，会一直挂着。macOS 没有 `timeout` 命令，用 `perl -e 'alarm 60; exec @ARGV' Godot …` 给它加超时。
- `static var` 可以用来做全局只读配置（主题数据、贴图缓存）。
- macOS 在窗口被遮挡或在别的桌面时停止绘制：截图会卡住，帧时间会出现巨大尖峰。截图/演示时把窗口设为置顶，用 `DisplayServer.window_can_draw()` 检测并打印出来。
- 不要用引擎自带的 Movie Maker 录演示：1080p AVI 每帧近 3 MB，会写满磁盘。用 ffmpeg 录屏，按窗口位置裁剪，压成 720×1280、约 4 Mbps 的 mp4。

## 调试工具（都值得第一阶段就做）

- **模拟观众**：按当前事件随机发合理的指令（打怪时「击退 / a编号」，幻阵时选阵，商店时购买…）；所有指令关键词都从主题取，这样换主题后模拟观众照样能玩。
- **主播控制台**：独立窗口（不进直播画面）：建宗、改名、给当前昵称发外观、模拟送礼 / 点赞（走适配层，代替真实礼物测试）、跳到下一阶段、连接状态（`streamer-ops.md`）。
- **截图导演**（`--capture`）：用短时长跑一整轮事件，在固定时刻截图，并记录事件期间的帧时间（P50 / P99 / 超过 33 ms 的帧）。
- **演示导演**（`--demo`）：按剧本让几名展示观众依次发指令，底部有标着「演示 · 模拟观众」的弹幕栏。
- **展示观众进度**：一个函数给模拟观众设置混合进度（各境界、各品阶外观、宠物、称号），截图和演示共用。
