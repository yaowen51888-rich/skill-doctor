# 五平台事实卡 + Adapter 接口约定

skill-doctor 的跨平台策略：**平台无关内核（lint 规则/报告）+ 每平台薄 adapter**。
本文件是 adapter 的唯一事实源，改路径/格式先改这里。

## 平台矩阵

| 平台 | skill 目录 | 项目级目录 | 会话日志 | headless | 现状 |
|---|---|---|---|---|---|
| claude-code | `~/.claude/skills/` | `./.claude/skills/` | `~/.claude/projects/**/*.jsonl`（转录含 tool_use+usage） | `claude -p` | list ✅ usage ✅ trigger ✅ |
| codex | `~/.codex/skills/` | `./.codex/skills/` | `~/.codex/sessions/` rollout jsonl | `codex exec` | list ✅ usage ⬜ |
| dsh | — | `./.agents/skills/` | JSONL + SQLite（`ctx.sessionQuery`，最干净） | CLI headless + **fork** | list ✅ usage ⬜ |
| openclaw | `~/.openclaw/workspace/skills/` | — | `.openclaw/agents/*/sessions/` | 常驻 agent 消息接口 | list ✅ usage ⬜ |
| hermes | `./skills/`（仓库根） | — | `~/.hermes`（sessions/memories/logs/cron） | 常驻 agent 消息接口 | list ✅ usage ⬜ |

`list ✅` = 目录扫描 + frontmatter 解析（五家 SKILL.md 格式同源，一套解析通吃）。
`usage ⬜` = 日志 reader 未实现。

## 三类 Adapter 接口

### 1. SkillDirAdapter（已由 doctor.py 的 PLATFORM_DIRS/PROJECT_DIRS 覆盖）

职责：枚举某平台全部已装 skill + 解析 frontmatter。
新平台接入 = 在 `PLATFORM_DIRS` 加一行路径。

### 2. SessionLogReader（v2 实现）

职责：给定平台，产出统一事件流：

```
SkillEvent { platform, session_id, ts, kind: invoke|inject, skill, usage? }
```

- `invoke` = 模型调用了 skill 工具（触发成功的铁证）
- `inject` = 目录/skill body 被注入上下文（成本相关）
- 各平台从自家日志解析：cc 转录里的 tool_use 块 / codex rollout /
  dsh 走 `ctx.sessionQuery`（最干净，优先做）/ OpenClaw sessions / Hermes `~/.hermes`

**纪律**：日志格式无稳定性承诺。reader 必须：格式探测 + 解析失败降级（跳过行不崩）
+ 样本文件锁进测试。

### 3. HeadlessRunner（cc 进程族已实现：`run_claude_headless`）

职责：`sendAndCollect(prompt, {skills: [on/off 列表]}) → 事件流`

- 进程族：`claude -p --output-format stream-json --max-turns N` ✅（doctor.py trigger）
  / `codex exec` ⬜ / dsh CLI ⬜（一次性会话）
- 常驻族：OpenClaw / Hermes 向运行中 agent 发消息。
  **测试必须用独立 agent 实例**，防止测试消息污染生产 agent 的记忆（Hermes 有
  memories/cron，OpenClaw 用 agents.entries 开测试实例）

L2 触发测试 = HeadlessRunner × 模拟任务集（应触发 N 条 + 不应触发 M 条），
输出触发率/误触发率。对照实验（带/不带 skill 各跑一遍）三家 headless 都能做；
dsh fork 的独占优势是从真实会话**中段**重放。

## 铁律

1. 触发率/统计数据禁止跨平台合并口径——五家发现机制全不同（cc 每轮注入目录 /
   dsh durable 去重 / OpenClaw per-agent 可见性配置 / Hermes agent 自主加载），
   只分平台报告
2. "56,804 个技能争 100 个触发位"是 claude-code 生态数字，引用必须标平台
3. usage 字段完备度：cc ✅ dsh ✅ 其余未验证——账单功能在验证前只出 token 数不出钱

## 已知局限

- doctor.py 的 frontmatter 解析只认单行 `name:`/`description:`，
  多行 YAML 折叠（`>`/`|`）截断为首行——lint 时遇此类报告用户改单行
