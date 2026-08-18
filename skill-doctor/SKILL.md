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
python <本skill目录>/scripts/doctor.py list --platform claude-code
python <本skill目录>/scripts/doctor.py usage --skill aihot --days 30
```

然后按 [REFERENCE.md](REFERENCE.md) 的 R1~R6 规则逐条检查，套报告模板输出。

## 能力（v1）

| 功能 | 命令 | 状态 |
|---|---|---|
| L1 静态 lint | `doctor.py list` + 规则 | ✅ |
| L3 历史触发审计 | `doctor.py usage`（仅 claude-code） | ✅ cc / ⬜ 其余平台 |
| L2 回放触发测试 | headless 跑模拟任务 | ⬜ v2 |
| 成本账单 | token 归因 | ⬜ v2 |

## 工作流

1. **确定平台**：用户没说就推断——当前会话跑在什么 harness 上，默认体检该平台。
   CLI 值域：`claude-code` / `codex` / `dsh`(=DeepSeek Harness) / `openclaw` / `hermes`
2. **枚举 + lint**：`doctor.py list --platform <值>`，按 REFERENCE.md 的 R1~R6 检查
3. **历史审计**（仅 cc）：`doctor.py usage --skill <名> --days 30`
4. **出报告**：套 REFERENCE.md 模板。建议必须具体到可直接执行的改法，禁止空话

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

- v2：L2 回放触发测试（`claude -p` / `codex exec` / dsh fork 跑模拟任务集）、成本账单
- v3：OpenClaw 可见性审计、Hermes 漂移检测脚本化

平台路径/日志格式/adapter 约定见 [PLATFORMS.md](PLATFORMS.md)。
