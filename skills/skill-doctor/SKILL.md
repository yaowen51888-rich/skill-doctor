---
name: skill-doctor
description: 子命令：/skill-doctor list、lint、usage、cases、trigger、cost、drift、visibility（无参出菜单）。skill 体检与优化：会不会触发、description 质量、抢触发、使用统计、内容漂移；费不费钱：token 成本与调用开销。支持 Claude Code/Codex/DeepSeek Harness/OpenClaw/Hermes 五平台。说"skill 体检/诊断/lint/触发率/使用统计/成本"时必用。
---

# Skill Doctor — 跨平台 Skill 体检

回答两类问题：**这 skill 好不好用（A：触发）**、**费不费钱（B：成本）**。
不做：skill 内容代写、执行质量评测（官方 eval 的事）。

## 用户问题 → 能力路由

| 用户在问 | 域 | 命令 |
|---|---|---|
| "这 skill 的 description 写得好不好" | 体检 | `lint` |
| "别的 skill 会不会抢它的触发" | 体检 | `lint`（R4 竞争） |
| "这 skill 被用过多少次、什么时候用的" | 体检 | `usage` |
| "这 skill 会不会被触发 / 怎么测触发率" | 触发 | `trigger` |
| "这 skill 每次花多少 token / 值不值" | 成本 | `cost` |
| "skill 内容怎么变了 / 被谁改了" | 漂移 | `drift` |
| "OpenClaw 里这 skill 怎么不触发" | 可见性 | `visibility` |

用户问题横跨多域（典型："全面体检一下 X"）→ 按体检→触发→成本顺序全跑。

## 斜杠直展子命令（ARGUMENTS 直通）

| 用户输入 | 执行 |
|---|---|
| `/skill-doctor`（无参数）或参数不识别 | 渲染上面能力路由表作菜单，问用户要查哪个 skill |
| `list` | `list` 全平台枚举 |
| `lint <名>` | `lint --skill <名>` + 语义复核 |
| `usage <名>` | `usage --skill <名>` |
| `cases <名>` | `cases --skill <名>` 采样预览（不花钱） |
| `trigger <名>` | 先跑 `cases` 采样给用户确认，再 `trigger`（花钱须确认） |
| `cost <名>` | `cost --skill <名>` |
| `drift [<名>]` | `drift [--skill <名>]` |
| `visibility [<名>]` | `visibility [--skill <名>]` |

直展参数与自然语言问题走同一套路由：参数匹配上表就直接跑，没匹配就当自然语言问题处理。

## 通用步骤

1. **确定平台**：用户没说就推断当前 harness。CLI 值域：
   `claude-code` / `codex` / `dsh`(=DeepSeek Harness) / `openclaw` / `hermes`
2. 按上表路由，进入对应域执行
3. 报告套 [REFERENCE.md](REFERENCE.md) 模板，建议必须具体到可直接执行的改法，禁止空话

## 体检域（lint + usage）

```bash
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py lint [--skill <名>]   # 机械检查
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py usage --skill <名>    # 历史统计
```

lint 输出 R1 长度/R2 信号/R4 竞争/R5 name/R7 模型可见性（`disable-model-invocation: true`
或无 SKILL.md = 模型永远看不到，触发率恒为 0，description 调优前先查它）的 verdict 后，
**你对 flagged 项做语义复核**：R2 粗检漏掉的"何时用"语义、R3 触发词是否
覆盖用户原话、R4 竞争对是真竞争还是误报。规则细则见 REFERENCE.md。

## 触发域（trigger + cases）

**优先从历史采样**（真实分布，非编造）：

```bash
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py cases --skill <名> [--per 5] [--boundary 边界词1,词2] [--out cases.json]
```

正例=目标调用前最近用户消息（真实触发语境），反例=路由到其他 skill 的 prompt，
按竞争度排序（desc 重叠率 + prompt 点名目标加权，竞品/点名场景优先测"抢触发"），
带 routed_to 溯源。R4 边界词再精筛加 `--boundary`。历史太薄（<3 正例）再手写
补齐——应触发 5~8 条（不同说法）+ 不应触发 3~5 条（近似场景）：

```json
[{"prompt": "帮我体检 aihot skill", "expect": true},
 {"prompt": "用 python 写个快排", "expect": false}]
```

```bash
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py trigger --skill <名> --cases <cases.json> [--max-turns N] [--repeats N]
```

每个 case × repeats = 真实模型调用次数（花钱），跑前告知用户。输出 trigger_rate /
false_trigger_rate 及 Wilson 置信区间（--repeats ≥3 才有意义）与逐 case 明细
（stable_hit / intermittent / miss）；附环境快照（claude 版本、模型、已装 skill 数）
保证跨时间可比；测试会话自动进黑名单不污染 usage。

## 成本域（cost）

```bash
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py cost --skill <名> [--days 30]
```

输出 description/body/随身文件（scripts、references 等按需读取文件）三笔 token
估算 + 调用轮 output_tokens 实测 + **注入成本实测**（调用后一轮 input_tokens 差分
= skill 正文进上下文的真实开销，斜杠直展同样计）。
渲染报告必须带"估算口径、不折算金额"说明。

## 专项（drift / visibility）

```bash
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py drift [--skill <名>] [--reset]
$(command -v python3 || command -v python || command -v py) <本skill目录>/scripts/doctor.py visibility [--skill <名>]
```

- drift：首跑建基线，之后 diff 增删改；快照存 `~/.skill-doctor/snapshots/`
- visibility：OpenClaw 触发失败第一查——被 disable 的 skill 文案再好也不触发；
  `null`=配置未提及，`false`=显式禁用

## 注意

- 触发率/统计**禁止跨平台合并口径**，只分平台报告
- usage 统计口径：`calls`=Skill 工具调用，`slash_calls`=`<command-name>` 斜杠直展，
  两者都算真实使用；`scenarios`=工具调用前 prompt 的语义聚类场景（斜杠直展无 NL
  语境，不计入）；`installed_unused`=窗口内零调用的已装 skill（"装了没动"清单）；
  trigger 测试会话（session 黑名单 `~/.skill-doctor/trigger_sessions.json`）
  自动剔除，不计入

平台路径/日志格式/adapter 施工图见 [PLATFORMS.md](PLATFORMS.md)。

## 路线图（勿提前实现）

- 扩展 trigger/usage/cost 到 codex / dsh / openclaw / hermes（照 PLATFORMS.md 施工）
- dsh fork 中段重放（需真机环境）
