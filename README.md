# skill-doctor

![python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![zero dependencies](https://img.shields.io/badge/dependencies-0-green)
![License: MIT](https://img.shields.io/badge/license-MIT-yellow)

**你的 skill 库健康吗？** AI Agent skill（SKILL.md）的体检与成本核算工具——告诉你哪些 skill 模型根本看不见、哪些在抢别人的触发、哪些装了从没用过、每个费多少 token。

*Health check & cost accounting for AI agent skills.*

| 好不好用 | 费不费钱 |
|---|---|
| 触发率**实测**（逐 case 跑真实模型调用，非静态打分） | description / body / 随身文件三笔 token 账 |
| lint：description 质量、skill 间竞争、模型可见性 | 每次调用轮 output_tokens 实测 |
| usage：谁被用过、谁装了没动 | 估算与实测分口径，不折算金额 |

零依赖，纯 Python 标准库（3.8+）。既是 CLI，也是可被 Agent 触发的 skill——装进 skills 目录后说"skill 体检"即可使用。

## 安装

```bash
# skills CLI（Claude Code / Codex / Cursor 等 20+ agent 通用）
npx skills add yaowen51888-rich/skill-doctor

# Claude Code 插件（本仓库自带 marketplace）
claude plugin marketplace add yaowen51888-rich/skill-doctor
claude plugin install skill-doctor@skill-doctor-marketplace

# 手动复制
git clone https://github.com/yaowen51888-rich/skill-doctor.git
cp -r skills/skill-doctor ~/.claude/skills/skill-doctor
```

Windows 可用 junction 免复制、改源即同步（删链接只能 `rmdir`，`rm -rf` 会穿透删源）：

```bat
mklink /J "%USERPROFILE%\.claude\skills\skill-doctor" "<repo>\skills\skill-doctor"
```

## 30 秒见效

真机输出（R7 = 这些 skill 在磁盘上，但模型永远看不到，触发率恒为 0）：

```text
$ python scripts/doctor.py lint --platform claude-code
checked 30, flagged 14
R7: setup-matt-pocock-skills  disabled_model_invocation
R7: ubiquitous-language       disabled_model_invocation
R7: zoom-out                  disabled_model_invocation
R7: learned                   no SKILL.md

$ python scripts/doctor.py usage --days 30
installed_unused: 25 / 44   # 57% 的已装 skill 三十天零调用
```

## 触发率实测工作流

skill-doctor 的核心差异：测试集从你的真实使用历史采样，再逐条回放给真实模型。

```bash
cd skills/skill-doctor
# 1. 体检：模型看得见它吗、description 有没有毛病（不花钱）
python scripts/doctor.py lint --skill aihot

# 2. 采样测试集：正例=当初真触发它的用户原话，反例=被竞品抢走的 prompt（不花钱）
python scripts/doctor.py cases --skill aihot --per 5 --out cases.json

# 3. 回放：报真触发率 / 误触发率（每个 case 一次真实模型调用，花钱）
python scripts/doctor.py trigger --skill aihot --cases cases.json

# 4. 账单：这个 skill 常驻 / 触发 / 随身文件各占多少 token
python scripts/doctor.py cost --skill aihot
```

装成 skill 后输入 `/skill-doctor`（无参）即出功能菜单。

## 命令

| 命令 | 干什么 |
|------|--------|
| `list` | 枚举已装 skill 及 frontmatter |
| `lint` | 机械检查：description 长度、场景信号、竞争重叠率、name 规范、**模型可见性**、YAML 多行折叠 |
| `usage` | 历史调用统计：Skill 工具调用与斜杠直展分列，零调用已装 skill 单列 |
| `cases` | 从真实历史采样触发测试集，反例按竞争度排序 |
| `trigger` | 触发率实测：trigger_rate / false_trigger_rate + 逐条明细 |
| `cost` | token 三笔账 + 调用轮 output_tokens 实测与窗口总账 |
| `drift` | 内容漂移检测：快照 diff，谁改了什么 |
| `visibility` | OpenClaw 配置审计：skill 对哪些 agent 可见 |

语义判断 lint 只做粗检，最终由模型复核——机械规则管确定性部分，不做玄学打分。

## 与同类工具的区别

skill 审计工具已不少（安全扫描、静态打分、prose 纪律各有赛道）：

- **实测不编造**——trigger 跑真实模型，测试集采自真实历史，不是手写用例
- **读会话日志**——usage / cost 的数字来自日志实测，不是估分
- **口径诚实**——估算/实测分开标注，不折算金额，不输出假装客观的 0-100 分

不做：安全扫描（已有大量 OWASP 工具）、内容代写、执行质量评测（官方 eval 的事）。

## 平台支持

| 平台 | 状态 |
|------|------|
| Claude Code | 全功能，真机验证 |
| Codex | list / lint / usage / cost 可用（fixture 锁定日志形态） |
| DeepSeek Harness / OpenClaw / Hermes | 提取逻辑已实现，落盘路径待真机确认 |

细节见 [PLATFORMS.md](skills/skill-doctor/PLATFORMS.md)（平台适配）与 [REFERENCE.md](skills/skill-doctor/REFERENCE.md)（lint 细则）。

## 细节

- 口径：触发率/统计分平台报告，不跨平台合并
- 测试：`cd skills/skill-doctor && python test_doctor.py`（零框架 assert，全过 ALL PASS）
- 结构：`skills/skill-doctor/` skill 本体（SKILL.md + doctor.py）；`.claude-plugin/` 插件清单

## License

[MIT](LICENSE)
