# skill-doctor

AI Agent skill（SKILL.md）的体检与成本核算工具。回答两个问题：**好不好用**（会不会被触发、description 质量、有没有被别的 skill 抢触发、内容有没有被改过），**费不费钱**（token 成本结构、每次调用的开销）。

零依赖，纯 Python 标准库（3.8+）。既是命令行工具，也是一个可被 Agent 触发的 skill——装进 skills 目录后对 Agent 说"skill 体检"即可使用。

## 命令

| 命令 | 干什么 |
|------|--------|
| `list` | 枚举已装 skill 及 frontmatter |
| `lint` | 机械检查：description 长度、场景信号、skill 间竞争重叠率、name 规范、YAML 多行折叠 |
| `usage` | 历史调用统计。Skill 工具调用与斜杠直展（`<command-name>`）分列；trigger 测试会话自动剔除，不污染数据 |
| `cases` | 从真实使用历史采样生成触发测试集：正例取目标调用前的用户消息，反例取路由到竞品的 prompt，按 description 重叠率排序 |
| `trigger` | 触发率实测。逐 case 跑 `claude -p`，输出 trigger_rate / false_trigger_rate 与逐条明细 |
| `cost` | token 账单：description / body 估算 + 调用轮 output_tokens 实测与窗口总账 |
| `drift` | 内容漂移检测。首次跑存快照，之后 diff 报告谁改了什么 |
| `visibility` | OpenClaw 配置审计：skill 对哪些 agent 可见 |

语义判断（触发词覆盖、竞争真伪）lint 只做粗检，最终由模型复核——机械规则管确定性部分，不做玄学打分。

## 平台支持

| 平台 | 状态 |
|------|------|
| Claude Code | 全功能，真机验证 |
| Codex | list / lint / usage / cost 可用（日志形态由 fixture 锁定） |
| DeepSeek Harness / OpenClaw / Hermes | 调用提取逻辑已实现，日志落盘路径待真机确认 |

平台路径与日志格式细节见 [skill-doctor/PLATFORMS.md](skill-doctor/PLATFORMS.md)。

## 安装

```bash
git clone <repo>
cp -r skill-doctor ~/.claude/skills/        # Claude Code
```

装完输入 `/skill-doctor`（不带参数）即出功能菜单，所有子命令一屏可见。

Windows 可用 junction 免复制、改源即同步：

```bat
mklink /J "%USERPROFILE%\.claude\skills\skill-doctor" "<repo>\skill-doctor"
```

注意：删 junction 只能 `rmdir`，`rm -rf` 会穿透删掉源目录。

## 测试

```bash
python test_doctor.py    # 零框架 assert，全过输出 ALL PASS
```

## 口径约定

- token 为估算 + 实测混合口径，不折算金额
- 触发率、使用统计分平台报告，不跨平台合并
- `trigger` 每个 case 是一次真实模型调用，花钱；`cases` 采样与全流程不花钱
