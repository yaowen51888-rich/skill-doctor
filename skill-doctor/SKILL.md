---
name: skill-doctor
description: 体检 AI Agent 的 skill (SKILL.md)。当用户想检查/优化某个 skill 的触发效果、description 质量、与其他已装 skill 的竞争冲突，或想知道某个 skill 的历史使用统计时使用。支持 Claude Code / Codex / DeepSeek Harness / OpenClaw / Hermes Agent 五平台。触发词包括"skill 体检"、"skill 诊断"、"skill lint"、"触发率"、"skill 会触发吗"、"skill 使用统计"、"skill 成本"。
---

# Skill Doctor — 跨平台 Skill 体检

给 SKILL.md 做体检：**会不会被触发、和谁竞争、历史上被用了多少**。
不做：skill 内容代写、执行质量评测（那是官方 eval 的事）。

## Quick start

用户说"帮我体检 aihot 这个 skill"时：

```bash
python <本skill目录>/scripts/doctor.py lint --skill aihot --platform claude-code
python <本skill目录>/scripts/doctor.py usage --skill aihot --days 30
```

然后按 [REFERENCE.md](REFERENCE.md) 的 R1~R6 规则逐条检查，套报告模板输出。

## 能力（v1）

| 功能 | 命令 | 状态 |
|---|---|---|
| L1 静态 lint | `doctor.py lint`（机械部分）+ R2/R3 模型判断 | ✅ |
| L3 历史触发审计 | `doctor.py usage`（`--platform claude-code/codex`） | ✅ cc+codex / ⬜ 其余 |
| L2 回放触发测试 | `doctor.py trigger`（仅 claude-code，花真钱） | ✅ cc / ⬜ 其余平台 |
| 成本账单 | `doctor.py cost`（估算+实测，不出钱） | ✅ cc / ⬜ 其余平台 |
| 漂移检测 | `doctor.py drift`（快照 diff，平台无关） | ✅ |
| 可见性审计 | `doctor.py visibility`（OpenClaw） | ✅ |

## 工作流

1. **确定平台**：用户没说就推断——当前会话跑在什么 harness 上，默认体检该平台。
   CLI 值域：`claude-code` / `codex` / `dsh`(=DeepSeek Harness) / `openclaw` / `hermes`
2. **机械体检**：`doctor.py lint --platform <值> [--skill <名>]`
   脚本输出 R1 长度 / R2 场景信号粗检 / R4 竞争对（重叠率）/ R5 name / YAML 截断
3. **语义复核**（模型做）：对 flagged 项逐个判断——R2 粗检漏掉的"何时用"语义、
   R3 触发词是否覆盖用户原话、R4 竞争对是真竞争还是误报
4. **历史审计**（仅 cc）：`doctor.py usage --skill <名> --days 30`
5. **触发测试**（仅 cc，可选，每次 case = 1 次真实模型调用）：
   你先起草 cases——应触发 5~8 条（覆盖用户不同说法）+ 不应触发 3~5 条（近似场景），
   写入临时 json 后跑：
   ```json
   [{"prompt": "帮我体检 aihot skill", "expect": true},
    {"prompt": "用 python 写个快排", "expect": false}]
   ```
   ```bash
   python <本skill目录>/scripts/doctor.py trigger --skill <名> --cases <cases.json>
   ```
   输出 trigger_rate / false_trigger_rate / 逐 case 明细
6. **成本账单**（仅 cc，可选）：`doctor.py cost --skill <名> [--days 30]`
   输出 description/body token 估算 + 调用轮 output_tokens 实测。
   渲染报告时必须带上"估算口径、不折算金额"的说明
7. **漂移检测**（任何平台）：`doctor.py drift [--platform X] [--skill <名>]`
   首跑建基线，之后每次跑 diff 出增删改文件；变更后自动以新版本为基线。
   快照存 `~/.skill-doctor/snapshots/`，`--reset` 重建。适合 Hermes 自改 skill
   或多人共享 skill 目录的变更审计
8. **可见性审计**（OpenClaw）：`doctor.py visibility [--skill <名>]`
   读 `openclaw.json` 报告每个 skill 的 global / default_agent / 具名 agent 三层可见性。
   触发失败时先查这个——配置里被 disable 的 skill description 写再好也不会触发。
   `null` = 配置未提及（通常即默认可见），`false` = 显式禁用
9. **出报告**：套 REFERENCE.md 模板。建议必须具体到可直接执行的改法，禁止空话

## Lint 规则一览

| 规则 | 一句话 |
|---|---|
| R1 长度 | description 50~500 字符 |
| R2 双信号 | 做什么 + 何时用，缺一触发靠运气 |
| R3 触发词 | 用户原话显式写进 description |
| R4 竞争 | 同目录 description 词重叠 >40% 标记同池竞争 |
| R5 name | kebab-case、与目录名一致 |
| R6 平台特有 | OpenClaw 查可见性配置 / Hermes 查漂移 / dsh 长度放宽 |

细则与重叠率算法见 [REFERENCE.md](REFERENCE.md)。

## 注意

- `doctor.py` 的 frontmatter 解析不认多行 YAML 折叠语法（`>`/`|-`），
  这类 skill 的 description 显示为截断——发现此类输出时提醒用户改单行
- 触发率/统计**禁止跨平台合并口径**，各家发现机制不同，只分平台报告
- 会话日志格式随官方版本变化，`usage` 出现 0 结果时先确认日志路径没挪

## 路线图（勿提前实现）

- v2/v3 已落地（cc + 平台无关项）；扩展 trigger/usage/cost 到 codex / dsh / openclaw / hermes
- dsh fork 中段重放（需装 dsh 环境后再做，设计见 PLATFORMS.md）

平台路径/日志格式/adapter 约定见 [PLATFORMS.md](PLATFORMS.md)。
