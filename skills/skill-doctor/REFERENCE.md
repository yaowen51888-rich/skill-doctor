# 参考细则（Lint 完整规则 + 报告模板 + 示例）

SKILL.md 只留规则一览，本文件是执行细则。体检时按需读取。

## Lint 规则细则

### R1 description 长度
50~500 字符为宜。太短没信息量，太长烧目录 token 预算（每个 skill 的
description 都会进系统提示的目录）。

### R2 双信号
description 必须同时含：
- 做什么（能力描述）
- 何时用（触发场景 / 用户会说的原话）

只有"做什么"没有"何时用" = 触发靠运气。

### R3 触发词显式化
用户嘴里的词要原样出现在 description 里（"体检"别只写"诊断"）。

### R4 竞争分析
对比同目录所有其他 skill 的 description：
- 词重叠率 > 40% → 标记同池竞争，报告谁会抢谁的触发
- name 语义相近 → 同样标记

重叠率估算：取两份 description 的分词集合，交集/较短者集合大小。

### R5 name 规范
kebab-case、可读名词或动词短语，与目录名一致。

### R6 平台特有
- **OpenClaw**：检查 `~/.openclaw/openclaw.json` 的 `agents.defaults.skills`
  / `agents.entries.*.skills`——skill 可能根本没配置可见（触发第一因是配置不是文案）
- **Hermes**：skill 可能被 agent 自己改写过，报告当前内容与 git/备份的差异（漂移）
- **dsh**：catalog 是 durable 去重的，description 只在列表变化时重发，长度权重可放宽

### R7 模型可见性（跨平台）
磁盘上存在但模型永远看不到的 skill，触发率恒为 0——description 调优前先查这里：
- `disable-model-invocation: true` — 刻意只留斜杠直展。是设计则报告注明（不算病），
  用户以为是自动触发则需去掉该标志
- 无 SKILL.md / frontmatter 缺失 / 目录读不了 — 安装残缺，重装或删目录

## 报告模板

```markdown
# Skill 体检报告：<name>

**平台**: claude-code | **目录**: <dir>

## Lint
| 规则 | 结果 | 说明 |
|---|---|---|
| R1 长度 | ✅/⚠️ | N 字符 |
| R2 双信号 | ... | ... |
| R3 触发词 | ... | ... |
| R4 竞争 | ... | 与 X 重叠 52%，X 的 description 覆盖了"YYY"场景 |
| R5 name | ... | ... |
| R7 可见性 | ... | disable-model-invocation / 无 SKILL.md / ✅ 模型可见 |

## 历史触发（30 天）
- 调用 N 次，分布于 M 个会话
- 最近一次：<日期>
- 未被调用过 → 触发失败或场景未出现，结合 lint 判断

## 建议
1. <具体到可直接执行的改法，禁止空话>
```

## 示例报告（节选）

```markdown
# Skill 体检报告：aihot

**平台**: claude-code | **目录**: ~/.claude/skills/aihot

## Lint
| 规则 | 结果 | 说明 |
|---|---|---|
| R1 长度 | ⚠️ | 528 字符，超建议上限，目录内每次注入成本偏高 |
| R2 双信号 | ✅ | 能力（拉 API 出简报）+ 场景（中文 AI 资讯查询）双全 |
| R3 触发词 | ✅ | "AI 日报"、"AI 圈"等用户原话均显式列出 |
| R4 竞争 | ✅ | 同目录无资讯类 skill，无同池竞争 |
| R5 name | ✅ | aihot，与目录一致 |

## 历史触发（30 天）
- 调用 1 次，1 个会话（2026-08-18）

## 建议
1. description 砍到 ~300 字符：保留触发词清单，删"不需要 API Key"等安装说明
   （那是 README 的事，不是目录文案的事）
```
