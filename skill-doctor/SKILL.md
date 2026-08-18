---
name: skill-doctor
description: 体检与优化 AI Agent 的 skill (SKILL.md)，用户的问题分两类找它。①好不好用：skill 会不会被触发、description 质量、与其他 skill 抢触发、历史使用统计、内容是否被改过。②费不费钱：skill 的 token 成本结构、每次调用的开销。支持 Claude Code / Codex / DeepSeek Harness / OpenClaw / Hermes Agent 五平台。当用户说"skill 体检"、"skill 诊断"、"skill lint"、"触发率"、"skill 会触发吗"、"skill 使用统计"、"skill 成本"、"skill 花多少 token"时必须使用本 skill。
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

## 通用步骤

1. **确定平台**：用户没说就推断当前 harness。CLI 值域：
   `claude-code` / `codex` / `dsh`(=DeepSeek Harness) / `openclaw` / `hermes`
2. 按上表路由，进入对应域执行
3. 报告套 [REFERENCE.md](REFERENCE.md) 模板，建议必须具体到可直接执行的改法，禁止空话

## 体检域（lint + usage）

```bash
python <本skill目录>/scripts/doctor.py lint [--skill <名>]   # 机械检查
python <本skill目录>/scripts/doctor.py usage --skill <名>    # 历史统计
```

lint 输出 R1 长度/R2 信号/R4 竞争/R5 name/YAML 截断的 verdict 后，
**你对 flagged 项做语义复核**：R2 粗检漏掉的"何时用"语义、R3 触发词是否
覆盖用户原话、R4 竞争对是真竞争还是误报。规则细则见 REFERENCE.md。

## 触发域（trigger）

你先起草 cases——应触发 5~8 条（覆盖用户不同说法）+ 不应触发 3~5 条
（近似场景），写入临时 json：

```json
[{"prompt": "帮我体检 aihot skill", "expect": true},
 {"prompt": "用 python 写个快排", "expect": false}]
```

```bash
python <本skill目录>/scripts/doctor.py trigger --skill <名> --cases <cases.json>
```

每个 case = 1 次真实模型调用（花钱），跑前告知用户。输出 trigger_rate /
false_trigger_rate / 逐 case 明细。

## 成本域（cost）

```bash
python <本skill目录>/scripts/doctor.py cost --skill <名> [--days 30]
```

输出 description/body token 估算 + 调用轮 output_tokens 实测。
渲染报告必须带"估算口径、不折算金额"说明。

## 专项（drift / visibility）

```bash
python <本skill目录>/scripts/doctor.py drift [--skill <名>] [--reset]
python <本skill目录>/scripts/doctor.py visibility [--skill <名>]
```

- drift：首跑建基线，之后 diff 增删改；快照存 `~/.skill-doctor/snapshots/`
- visibility：OpenClaw 触发失败第一查——被 disable 的 skill 文案再好也不触发；
  `null`=配置未提及，`false`=显式禁用

## 注意

- `doctor.py` frontmatter 解析不认多行 YAML 折叠（`>`/`|-`），此类 skill 的
  description 显示截断——提醒用户改单行
- 触发率/统计**禁止跨平台合并口径**，只分平台报告
- slash command（如 `/aihot` 直展）不走 Skill 工具，不计入 usage——报告时
  向用户说明统计口径

平台路径/日志格式/adapter 施工图见 [PLATFORMS.md](PLATFORMS.md)。

## 路线图（勿提前实现）

- 扩展 trigger/usage/cost 到 codex / dsh / openclaw / hermes（照 PLATFORMS.md 施工）
- dsh fork 中段重放（需真机环境）
