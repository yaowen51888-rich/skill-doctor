# skill-doctor

![python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![zero dependencies](https://img.shields.io/badge/dependencies-0-green)
![License: MIT](https://img.shields.io/badge/license-MIT-yellow)

AI Agent skill（SKILL.md）的体检与成本核算工具。
*Health check & cost accounting for AI agent skills — triggering, description quality, usage stats, token cost.*

回答两个问题：**好不好用**（会不会被触发、description 质量、有没有被别的 skill 抢触发、内容有没有被改过），**费不费钱**（token 成本结构、每次调用的开销）。

零依赖，纯 Python 标准库（Python 3.8+）。既是命令行工具，也是一个可被 Agent 触发的 skill——装进 skills 目录后对 Agent 说"skill 体检"即可使用。

`trigger` 子命令需要 `claude` CLI 在 PATH 且会产生真实模型调用（花钱），其余子命令全程零成本。

## 快速开始

```bash
git clone https://github.com/yaowen51888-rich/skill-doctor.git
python skills/skill-doctor/scripts/doctor.py lint              # 机械体检本机所有 skill
python skills/skill-doctor/scripts/doctor.py usage --days 30   # 谁被用过、谁装了没动
```

真机输出示例（R7 模型可见性检查——这些 skill 在磁盘上，但模型永远看不到，触发率恒为 0）：

```text
$ python scripts/doctor.py lint --platform claude-code
checked 30, flagged 14
R7: setup-matt-pocock-skills  disabled_model_invocation
R7: ubiquitous-language        disabled_model_invocation
R7: zoom-out                   disabled_model_invocation
R7: learned                    no SKILL.md
```

```text
$ python scripts/doctor.py usage --days 30
installed_unused: 25 / 44   # 57% 的已装 skill 三十天零调用
```

## 命令

| 命令 | 干什么 |
|------|--------|
| `list` | 枚举已装 skill 及 frontmatter |
| `lint` | 机械检查：description 长度、场景信号、skill 间竞争重叠率、name 规范、模型可见性（`disable-model-invocation` / 无 SKILL.md = 模型永远看不到）、YAML 多行折叠 |
| `usage` | 历史调用统计。Skill 工具调用与斜杠直展（`<command-name>`）分列，另列窗口内零调用的已装 skill；trigger 测试会话自动剔除，不污染数据 |
| `cases` | 从真实使用历史采样生成触发测试集：正例取目标调用前的用户消息，反例取路由到竞品的 prompt，按 description 重叠率排序 |
| `trigger` | 触发率实测。逐 case 跑 `claude -p`，输出 trigger_rate / false_trigger_rate 与逐条明细 |
| `cost` | token 账单：description / body / 随身文件（scripts、references）三笔估算 + 调用轮 output_tokens 实测与窗口总账 |
| `drift` | 内容漂移检测。首次跑存快照，之后 diff 报告谁改了什么 |
| `visibility` | OpenClaw 配置审计：skill 对哪些 agent 可见 |

语义判断（触发词覆盖、竞争真伪）lint 只做粗检，最终由模型复核——机械规则管确定性部分，不做玄学打分。

## 典型工作流：实测一个 skill 的触发率

```bash
cd skills/skill-doctor
# 1. 体检：先确认模型看得见它、description 没毛病（不花钱）
python scripts/doctor.py lint --skill aihot

# 2. 从你的真实使用历史采样测试集：正例=当初真触发它的用户原话，
#    反例=被竞品抢走的 prompt（不花钱）
python scripts/doctor.py cases --skill aihot --per 5 --out cases.json

# 3. 逐 case 回放，报真触发率 / 误触发率（每个 case 一次真实模型调用）
python scripts/doctor.py trigger --skill aihot --cases cases.json

# 4. 看账单：description / body / 随身文件各占多少 token
python scripts/doctor.py cost --skill aihot
```

## 与同类工具的区别

skill 审计工具已经不少（安全扫描、静态打分、prose 纪律各有赛道），skill-doctor 的差异：

- **trigger 是实测不是打分**——逐 case 跑真实模型调用（`claude -p` headless），报真触发率 / 误触发率
- **测试集从你的真实历史采样**（`cases`）——正例是当初真触发它的用户原话，反例是被竞品抢走的 prompt，不是编造的用例
- **usage / cost 读会话日志**——调用次数、每次调用轮 output_tokens 是实测，估算与实测分口径，不折算金额
- **lint 只做确定性检查**，语义复核明确留给模型，不输出假装客观的 0-100 分

不做：skill 安全扫描（已有大量 OWASP 模式工具）、skill 内容代写、执行质量评测（官方 eval 的事）。

## 平台支持

| 平台 | 状态 |
|------|------|
| Claude Code | 全功能，真机验证 |
| Codex | list / lint / usage / cost 可用（日志形态由 fixture 锁定） |
| DeepSeek Harness / OpenClaw / Hermes | 调用提取逻辑已实现，日志落盘路径待真机确认 |

平台路径与日志格式细节见 [skills/skill-doctor/PLATFORMS.md](skills/skill-doctor/PLATFORMS.md)。

## 安装

三种方式，任选其一：

```bash
# ① skills CLI（Claude Code / Codex / Cursor 等 20+ agent 通用）
npx skills add yaowen51888-rich/skill-doctor

# ② Claude Code 插件（本仓库自带 marketplace，自举式布局）
claude plugin marketplace add yaowen51888-rich/skill-doctor
claude plugin install skill-doctor@skill-doctor-marketplace

# ③ 手动复制
git clone https://github.com/yaowen51888-rich/skill-doctor.git
cp -r skills/skill-doctor ~/.claude/skills/skill-doctor
```

装完输入 `/skill-doctor`（不带参数）即出功能菜单，所有子命令一屏可见。

Windows 可用 junction 免复制、改源即同步：

```bat
mklink /J "%USERPROFILE%\.claude\skills\skill-doctor" "<repo>\skills\skill-doctor"
```

注意：删 junction 只能 `rmdir`，`rm -rf` 会穿透删掉源目录。

## 测试

```bash
cd skills/skill-doctor && python test_doctor.py    # 零框架 assert，全过输出 ALL PASS
```

## 口径约定

- token 为估算 + 实测混合口径，不折算金额
- 触发率、使用统计分平台报告，不跨平台合并
- `trigger` 每个 case 是一次真实模型调用，花钱；`cases` 采样与全流程不花钱

## 仓库结构

```text
skills/skill-doctor/    skill 本体：SKILL.md（Agent 入口）+ scripts/doctor.py（CLI）
                        + PLATFORMS.md（平台适配）/ REFERENCE.md（lint 细则）
.claude-plugin/         Claude Code 插件清单（仓库自带 marketplace，自举式发布）
```

## License

[MIT](LICENSE)
