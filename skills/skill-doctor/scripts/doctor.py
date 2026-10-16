#!/usr/bin/env python3
"""skill-doctor v1: 跨平台 skill 体检脚本。

子命令:
  list   枚举已装 skill + 解析 frontmatter(claude-code/codex/dsh/openclaw/hermes 目录探测,
         格式同为 SKILL.md)
  usage  扫会话日志统计 skill 调用: Skill 工具 + 斜杠直展 command-name 形态,
         并列出零调用的已装 skill; 调用前 prompt 语义聚类出真实使用场景(top3)
         (trigger 测试会话已剔除; claude-code/codex 有日志路径; dsh/openclaw/hermes
         提取逻辑已支持但落盘路径待真机确认, 见 PLATFORMS.md)
  lint   机械体检 R1/R2粗检/R4/R5/R7(可见性: disable-model-invocation/无SKILL.md=
         模型永远看不到, 触发率恒为0; R2/R3 语义判断留给模型, 见 SKILL.md)
  trigger 回放触发测试: 用 cases.json 逐条跑 claude -p, 统计触发率/误触发,
         --repeats N 重复测量出 Wilson 置信区间, 附环境快照保证跨时间可比
         (v2, 仅 claude-code)
  cases  从 usage 历史真实会话采样生成 trigger 测试集(正例=调过目标 skill 的会话
         首条 prompt, 反例=调了其他 skill 的会话 prompt, 数据驱动非编造)
  ablate description 逐句消融: 逐句删掉跑正例, 触发率掉幅=该句边际贡献,
         哪句保命哪句白占 token 的因果证据(跑 claude -p 花真钱, 仅 claude-code)
  steal  抢触发实证: prompt 命中目标 description 却路由别处的真实统计,
         won/stolen/missed + 竞品排行, R4 重叠率的判决版(不花钱)
  cost   成本账单: desc/body/随身文件(脚本、参考资料)三笔 token 估算 +
         调用轮 output_tokens 实测 + 注入成本 input_tokens 差分实测
         (不出钱, 仅 claude-code)
  drift  漂移检测: 对 skill 目录做内容快照, 对比上次快照报告增删改(平台无关, Hermes 自改场景主用)
  visibility 可见性审计: 读 openclaw.json, 报告 skill 对哪些 agent 可见(默认 OpenClaw)

用法:
  python doctor.py list [--platform claude-code]
  python doctor.py usage [--skill NAME] [--days 30]

纯标准库, 无第三方依赖。
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ponytail: 目录约定只列默认路径, 自定义路径等真实需求出现再加 --dir 参数
PLATFORM_DIRS = {
    "claude-code": [Path.home() / ".claude" / "skills"],
    "codex": [Path.home() / ".codex" / "skills"],
    "dsh": [Path.cwd() / ".agents" / "skills"],
    "openclaw": [Path.home() / ".openclaw" / "workspace" / "skills"],
    "hermes": [Path.cwd() / "skills"],
}

# 项目级 skill 目录(优先于全局, 仅 cc/codex 有此约定)
PROJECT_DIRS = {
    "claude-code": [Path.cwd() / ".claude" / "skills"],
    "codex": [Path.cwd() / ".codex" / "skills"],
}


def parse_frontmatter(text):
    """简易 frontmatter 解析, 只取 name/description, 不引 yaml 依赖。

    支持多行折叠: description: >- / | 后吃连续缩进行, > 折叠为空格连接, | 保留换行。
    """
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if not m:
        return out
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        kv = re.match(r'^(name|description|disable-model-invocation):\s*(.*)$',
                      lines[i].strip())
        if not kv:
            i += 1
            continue
        val = kv.group(2).strip()
        if val and val[0] in ">|" and set(val) <= {">", "|", "-", "+"}:
            block = []
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j][:1].isspace()):
                block.append(lines[j].strip())
                j += 1
            joiner = " " if val[0] == ">" else "\n"
            val = joiner.join(block).strip()
            i = j - 1
        if val:
            out[kv.group(1)] = val.strip('"').strip("'")
        i += 1
    return out


def split_sentences(desc):
    """description 切句(中英标点均可), 滤空。消融的最小单元。"""
    parts = re.split(r'[。；;.!？?\n]+', desc)
    return [p.strip() for p in parts if p.strip()]


def rewrite_description(text, new_desc):
    """文本手术: 只替换 frontmatter 的 description 值, 其余字节不动。

    兼容单行值与 >-/>/| 折叠块(整块吞掉); 新值压成单行; 无 frontmatter
    或无 description 键时原样返回(调用方据此中止消融)。
    """
    lines = text.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "---")
    except StopIteration:
        return text
    out, i, replaced = [], start + 1, False
    while i < len(lines) and lines[i].strip() != "---":
        if not replaced and re.match(r'^description\s*:', lines[i]):
            out.append("description: " + " ".join(new_desc.split()))
            replaced = True
            val = lines[i].split(":", 1)[1].strip()
            if val and val[0] in ">|":  # 折叠块: 连续缩进行整体属于旧值
                i += 1
                while i < len(lines) and (not lines[i].strip() or lines[i][:1].isspace()):
                    i += 1
                continue
        else:
            out.append(lines[i])
        i += 1
    if not replaced:
        return text
    out.extend(lines[i:])
    return "\n".join(out)


def scan_skills(platform):
    bases = PROJECT_DIRS.get(platform, []) + PLATFORM_DIRS[platform]
    skills, missing = [], []
    for base in bases:
        if not base.is_dir():
            missing.append(str(base))
            continue
        for md in sorted(base.glob("*/SKILL.md")):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
                fm = parse_frontmatter(text)
            except OSError as e:
                skills.append({"dir": str(md.parent), "error": str(e)})
                continue
            desc = fm.get("description", "")
            skills.append({
                "dir": str(md.parent),
                "name": fm.get("name") or md.parent.name,
                "description": desc,
                "description_chars": len(desc),
                "frontmatter_ok": text.startswith("---"),
                # disable-model-invocation: true = 只留斜杠直展, 模型永远看不到
                "model_invocable": str(fm.get("disable-model-invocation", "")
                                       ).lower() not in ("true", "1"),
            })
        # 有目录没 SKILL.md = 安装残缺, 模型同样看不到
        for child in sorted(base.iterdir()):
            if child.is_dir() and not (child / "SKILL.md").is_file():
                skills.append({"dir": str(child), "error": "no SKILL.md"})
    return skills, missing


def cmd_list(args):
    result = {}
    platforms = [args.platform] if args.platform != "all" else list(PLATFORM_DIRS)
    for p in platforms:
        skills, missing = scan_skills(p)
        result[p] = {"found": len(skills), "skills": skills, "dirs_not_found": missing}
    print(json.dumps(result, ensure_ascii=False, indent=2))


# 各平台会话日志根目录(None=路径未确认, 只支持提取逻辑不支持扫描)
SESSION_LOG_DIRS = {
    "claude-code": Path.home() / ".claude" / "projects",
    "codex": Path.home() / ".codex" / "sessions",
    "dsh": None,        # 事件格式已知(seq/time/data 信封), 落盘路径待真机确认
    "openclaw": None,   # .openclaw/agents/*/sessions, 结构细节未验证
    "hermes": None,     # ~/.hermes, 结构细节未验证
}


# trigger 测试会话黑名单: 测试调用不得计入 usage/cost 真实统计
TRIGGER_BLOCKLIST = Path.home() / ".skill-doctor" / "trigger_sessions.json"


def load_trigger_blocklist():
    try:
        data = json.loads(TRIGGER_BLOCKLIST.read_text(encoding="utf-8"))
        return set(data.get("sessions", []))
    except (OSError, json.JSONDecodeError, ValueError):
        return set()


def save_trigger_blocklist(ids):
    TRIGGER_BLOCKLIST.parent.mkdir(parents=True, exist_ok=True)
    TRIGGER_BLOCKLIST.write_text(
        json.dumps({"sessions": sorted(ids)}, ensure_ascii=False), encoding="utf-8")


def iter_logs(platform, days):
    """产出某平台日志根下 N 天内修改过的 jsonl 文件(剔除 trigger 测试会话)。"""
    root = SESSION_LOG_DIRS.get(platform)
    if root is None or not Path(root).is_dir():
        return
    blocked = load_trigger_blocklist()
    cutoff = datetime.now().timestamp() - days * 86400
    for f in Path(root).rglob("*.jsonl"):
        if f.stem in blocked:
            continue
        try:
            if f.stat().st_mtime >= cutoff:
                yield f
        except OSError:
            continue


def _walk_skill_calls(node):
    """深度优先找"工具名为 skill"的调用节点, 产出被调用的 skill 名。

    覆盖三家同构形态: cc tool_use 块 / dsh 事件 data / codex function_call。
    """
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str) and name.strip().lower() in ("skill", "skills"):
            args = node.get("input") or node.get("arguments") \
                or node.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            if isinstance(args, dict):
                for key in ("skill", "skill_name", "name", "command"):
                    v = args.get(key)
                    if isinstance(v, str) and v:
                        yield v.lstrip("/").split()[0]
                        return
                for v in args.values():  # 无明确字段名, 取第一个字符串值
                    if isinstance(v, str) and v:
                        yield v.split()[0]
                        return
            return  # 命中工具节点后不再深挖该子树
        for v in node.values():
            yield from _walk_skill_calls(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_skill_calls(v)


def extract_skill_calls(line_text):
    """从一行日志 JSON 提取 skill 工具调用名。找不到返回空列表。"""
    try:
        obj = json.loads(line_text)
    except (json.JSONDecodeError, ValueError):
        return []
    return list(_walk_skill_calls(obj))


# 斜杠直展形态: 用户消息内容含 <command-name>/NAME</command-name>, 不走 Skill 工具
COMMAND_NAME_RE = re.compile(r'<command-name>\s*/?([^\s<]+)')


def extract_slash_commands(line_text):
    """提取斜杠命令名(/NAME 取首词)。是否为 skill 由调用方对已装名单过滤。"""
    return COMMAND_NAME_RE.findall(line_text)


def known_skill_names(platform):
    """{调用名: 规范名} — 覆盖 plugin:name 全名与尾段两种写法。"""
    known = {}
    for s in scan_skills(platform)[0]:
        n = s.get("name")
        if n:
            known[n] = n
            known[n.split(":")[-1]] = n
    return known


def slash_calls_in_line(line_text, known):
    """行内斜杠直展调用(映射到已装 skill 规范名), 供 usage/cases 共用。"""
    out = []
    if "<command-name>" in line_text:
        for name in extract_slash_commands(line_text):
            c = known.get(name)
            if c:
                out.append(c)
    return out


def cmd_usage(args):
    counter = Counter()
    slash_counter = Counter()
    sessions = {}
    prompts_by_skill = {}  # {name: [去重的触发前用户 prompt]} — 场景聚类原料
    total_lines = 0
    known = known_skill_names(args.platform)
    for f in iter_logs(args.platform, args.days):
        used_here = set()
        last_prompt = None
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"type":"user"' in line:
                    p = first_user_prompt(line)
                    if p:
                        last_prompt = p
                if '"Skill"' in line or '"skill"' in line:
                    total_lines += 1
                    for name in extract_skill_calls(line):
                        counter[name] += 1
                        used_here.add(name)
                        if last_prompt:
                            seen = prompts_by_skill.setdefault(name, [])
                            if last_prompt not in seen:
                                seen.append(last_prompt)
                for name in slash_calls_in_line(line, known):
                    slash_counter[name] += 1
                    used_here.add(name)
                    if last_prompt:
                        seen = prompts_by_skill.setdefault(name, [])
                        if last_prompt not in seen:
                            seen.append(last_prompt)
        except OSError:
            continue
        for n in used_here:
            sessions[n] = sessions.get(n, 0) + 1

    all_names = set(counter) | set(slash_counter)
    # 已装但窗口内零调用: 装了没动的 skill 在 skill_calls 里不可见, 单列才看得见
    unused = sorted({v for v in known.values() if v not in all_names})
    entries = []
    for n in sorted(all_names, key=lambda k: -(counter[k] + slash_counter[k])):
        e = {"skill": n, "calls": counter.get(n, 0),
             "slash_calls": slash_counter.get(n, 0),
             "sessions": sessions.get(n, 0),
             # 历史计数里目录已删的 skill 标 false, 不静默剔除(历史趋势仍有参考价值)
             "installed": n in known}
        sc = scenarios_for(prompts_by_skill.get(n, []))
        if sc:
            e["scenarios"] = sc
        entries.append(e)
    result = {
        "platform": args.platform,
        "window_days": args.days,
        "files_scanned_hint_lines": total_lines,
        "installed_unused": {"count": len(unused), "skills": unused},
        "skill_calls": entries,
    }
    if args.skill:
        result["skill_calls"] = [x for x in result["skill_calls"] if args.skill.lower() in x["skill"].lower()]
    print(json.dumps(result, ensure_ascii=False, indent=2))


# 中文高频虚词 bigram, 重叠率计算时剔除(否则人人都含"使用/可以", 竞争虚高)
STOP_BIGRAMS = {
    "使用", "可以", "一个", "用户", "当用", "用户", "这个", "什么", "如何", "以及",
    "用于", "包括", "或者", "如果", "需要", "时候", "情况", "以下", "上述", "所有",
    "任何", "生成", "处理", "进行", "支持", "提供", "创建", "分析",
}

# R2 场景信号(粗检): description 里应出现"何时用"类语言
SCENE_SIGNAL = re.compile(r'使用|当.{0,12}时|适用|场景|触发|Use when|when user|when to', re.I)


def tokens(text):
    """英文小写词 + 中文 bigram 集合, 用于重叠率粗算。"""
    words = set(re.findall(r'[a-z0-9][a-z0-9_]{2,}', text.lower()))
    han = re.findall(r'[一-鿿]', text)
    bigrams = {han[i] + han[i + 1] for i in range(len(han) - 1)}
    return (words | bigrams) - STOP_BIGRAMS


def overlap_rate(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / min(len(ta), len(tb)), 3)


def cosine_sets(a, b):
    """集合余弦相似度。"""
    if not a or not b:
        return 0.0
    return len(a & b) / ((len(a) * len(b)) ** 0.5)


def cluster_prompts(prompts, threshold=0.25):
    """leader 聚类, 返回索引簇列表(按 size 降序, 同 size 按代表 prompt 序)。

    向量 = tokens() 集合, 簇心 = 成员并集; 按 token 数降序遍历保证确定性。
    """
    toks = [tokens(p) for p in prompts]
    order = sorted(range(len(prompts)), key=lambda i: (-len(toks[i]), prompts[i]))
    clusters = []  # [{"members": [i], "center": set}]
    for i in order:
        for c in clusters:
            if cosine_sets(toks[i], c["center"]) >= threshold:
                c["members"].append(i)
                c["center"] |= toks[i]
                break
        else:
            clusters.append({"members": [i], "center": set(toks[i])})
    clusters.sort(key=lambda c: (-len(c["members"]), prompts[c["members"][0]]))
    return [c["members"] for c in clusters]


def scenarios_for(prompts):
    """≥3 条不同 prompt 才聚类; 返回 top3 场景簇摘要, 不足返回 None。

    top_terms = 簇内过半共有且全局不过半的 token(有区分度), 按簇内频次排序。
    """
    if len(prompts) < 3:
        return None
    toks = [tokens(p) for p in prompts]
    global_counts = Counter()
    for t in toks:
        global_counts.update(t)
    n = len(prompts)
    out = []
    for members in cluster_prompts(prompts):
        cnt = Counter()
        for i in members:
            cnt.update(toks[i])
        terms = [t for t, c in cnt.items()
                 if c * 2 > len(members) and global_counts[t] * 2 <= n]
        terms.sort(key=lambda t: (-cnt[t], t))
        center = set().union(*(toks[i] for i in members))
        rep = max(members, key=lambda i: (cosine_sets(toks[i], center), -i))
        out.append({
            "count": len(members),
            "representative": prompts[rep][:60],
            "top_terms": terms[:5],
        })
        if len(out) == 3:
            break
    return out


def lint_one(skill, all_skills):
    """对单个 skill 做机械检查, 返回 verdict 供模型渲染报告。"""
    desc = skill.get("description", "")
    n = skill.get("name", "")
    r = {"skill": n, "dir": skill.get("dir", "")}

    # R1 长度
    ln = len(desc)
    r["R1_len"] = ln
    r["R1"] = "ok" if 50 <= ln <= 500 else ("short" if ln < 50 else "over")

    # R2 场景信号粗检(语义强弱仍需模型判断)
    r["R2_scene_signal"] = bool(SCENE_SIGNAL.search(desc))

    # R4 竞争: 与其他 skill 的 description 重叠率
    comps = []
    for other in all_skills:
        if other is skill:
            continue
        ov = overlap_rate(desc, other.get("description", ""))
        if ov > 0.4:
            comps.append({"skill": other.get("name", ""), "overlap": ov})
    comps.sort(key=lambda x: -x["overlap"])
    r["R4_competitors"] = comps[:5]

    # R5 name 规范
    dir_name = Path(skill.get("dir", "")).name
    kebab = bool(re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', n))
    r["R5"] = "ok" if (kebab and n == dir_name) else (
        "not_kebab" if not kebab else "mismatch_dir")

    # R7 模型可见性: 模型看不到的 skill 触发率恒为 0, description 调优前先查这里
    if not skill.get("frontmatter_ok", True):
        r["R7"] = "no_frontmatter"
    elif not skill.get("model_invocable", True):
        r["R7"] = "disabled_model_invocation"
    else:
        r["R7"] = "ok"
    return r


def cmd_lint(args):
    skills, _ = scan_skills(args.platform)
    if args.skill:
        targets = [s for s in skills if args.skill.lower() in s.get("name", "").lower()
                   or args.skill.lower() in Path(s.get("dir", "")).name.lower()]
    else:
        targets = skills
    results = []
    for s in targets:
        if "error" in s:  # 无 SKILL.md/读不了的目录: R7 直接报, 不进逐项检查
            results.append({"skill": Path(s["dir"]).name, "dir": s["dir"],
                            "R7": "no_skill_md" if s["error"] == "no SKILL.md"
                            else "unreadable",
                            "error": s["error"]})
        else:
            results.append(lint_one(s, skills))
    # .get 短路: error 条目无 R1/R5 键, 靠 R7!=ok 先命中
    flagged = [r for r in results
               if r.get("R7", "ok") != "ok" or r.get("R1", "ok") != "ok"
               or r.get("R5", "ok") != "ok" or not r.get("R2_scene_signal")
               or bool(r.get("R4_competitors"))]
    print(json.dumps({
        "platform": args.platform,
        "checked": len(results),
        "flagged": len(flagged),
        "results": results,
    }, ensure_ascii=False, indent=2))


def is_target_skill(called, target):
    """plugin skill 名形如 plugin:name, 取尾段比对。"""
    return called == target or called.split(":")[-1] == target


def case_role(tool_called, slash_called, target):
    """会话在测试集里的角色: pos=Skill 工具自动触发(有 NL 语境) /
    neg=路由到其他 skill / None=跳过(目标仅斜杠直展——用户显式点名,
    其前最近用户消息与触发无关, 是采样噪声)。"""
    if any(is_target_skill(n, target) for n in tool_called):
        return "pos"
    if any(is_target_skill(n, target) for n in slash_called):
        return None
    return "neg" if (set(tool_called) | set(slash_called)) else None


def run_claude_headless(prompt, max_turns=2, timeout=180, cwd=None):
    """跑一次性 claude 会话, 返回 stream-json 文本。找不到 CLI 或超时返回 ""。"""
    import os
    import shutil
    import subprocess
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        return ""
    # 剥 CLAUDECODE: 嵌套守卫只防交互终端冲突, 子进程程序化调用须放行
    # (本会话内 spawn 的 trigger 测试会因此挂死)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        p = subprocess.run(
            [exe, "-p", prompt, "--output-format", "stream-json", "--verbose",
             "--max-turns", str(max_turns)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, cwd=cwd)
        return p.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def collect_session_ids(stream):
    """从 stream-json 事件行收集 session_id, 供 usage 黑名单剔除测试会话。"""
    ids = set()
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        sid = ev.get("session_id")
        if isinstance(sid, str) and sid:
            ids.add(sid)
    return ids


def first_user_prompt(line_text):
    """该行若为真实用户文本消息则返回其文本, 否则 None。

    剔除命令直展(<command-name>)/工具结果/系统注入/Caveat 形态。
    """
    try:
        obj = json.loads(line_text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "user" or obj.get("isMeta"):
        return None
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text")
    else:
        return None
    text = text.strip()
    if not text or text.startswith("<") or text.startswith("Caveat:"):
        return None
    return text


def cmd_cases(args):
    """从 usage 历史采样生成 cases.json(数据驱动测试集)。

    正例: 目标 skill 调用时刻前的最近一条用户消息(真实触发语境;
          斜杠直展会话无此前消息, 兜底取会话首条)
    反例: 路由到其他 skill 的会话 prompt, 按 description 重叠度(竞争度)排序,
          竞品会话优先——反例天然测"抢触发"
    """
    skills = scan_skills(args.platform)[0]
    desc_by_name = {s.get("name", ""): s.get("description", "") for s in skills}
    target_desc = next((s.get("description", "") for s in skills
                        if is_target_skill(s.get("name", ""), args.skill)), "")
    known = known_skill_names(args.platform)
    boundary = [b.strip() for b in args.boundary.split(",")] if args.boundary else []

    pos, neg = [], []
    seen = set()
    for f in iter_logs(args.platform, args.days):
        tool_called, slash_called = [], []
        hit_prompt, first_prompt, last_prompt = None, None, None
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"type":"user"' in line:
                    p = first_user_prompt(line)
                    if p:
                        last_prompt = p
                        if first_prompt is None:
                            first_prompt = p
                if '"Skill"' in line or '"skill"' in line:
                    tool_called += extract_skill_calls(line)
                slash_called += slash_calls_in_line(line, known)
                if hit_prompt is None and any(
                        is_target_skill(n, args.skill) for n in tool_called + slash_called):
                    hit_prompt = last_prompt  # 首次命中前的最近用户消息
        except OSError:
            continue
        prompt = hit_prompt or first_prompt
        if not prompt or prompt in seen:
            continue
        seen.add(prompt)
        role = case_role(tool_called, slash_called, args.skill)
        called = set(tool_called) | set(slash_called)
        item = {"prompt": prompt, "source_session": f.stem}
        if role == "pos":
            item["expect"] = True
            pos.append(item)
        elif role == "neg":
            others = sorted(n for n in called if not is_target_skill(n, args.skill))
            if boundary and not any(b in prompt for b in boundary):
                continue
            item["expect"] = False
            item["routed_to"] = others[:3]
            neg.append(item)

    def rivalry(item):
        # 反例竞争度: routed skill 与目标的 description 重叠率;
        # prompt 点名目标 skill(却路由去了别处)= 最强边界测试, 直接加权
        base = max((overlap_rate(target_desc, desc_by_name.get(r, ""))
                    for r in item.get("routed_to", [])), default=0.0)
        if args.skill.lower() in item["prompt"].lower():
            base += 1.0
        return base

    pos.sort(key=lambda x: x["source_session"])  # 稳定序, 输出可复现
    neg.sort(key=lambda x: (-rivalry(x), x["source_session"]))
    cases = pos[:args.per] + neg[:args.per]
    out = {
        "skill": args.skill,
        "note": "正例=目标调用前最近用户消息(兜底会话首条); "
                "反例=路由到其他 skill 的 prompt, 按竞争度降序(竞品优先)",
        "cases": cases,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"# wrote {len(cases)} cases to {args.out} "
              f"(pos={min(len(pos), args.per)}, neg={min(len(neg), args.per)})",
              file=sys.stderr)
    else:
        print(text)


def wilson_ci(p, n, z=1.96):
    """Wilson 置信区间 [lo, hi]。n<=0 或 p 越界返回 None。"""
    if n <= 0 or not 0 <= p <= 1:
        return None
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(center - half, 3), round(center + half, 3)]


LINE_MODEL_RE = re.compile(r'"model"\s*:\s*"([^"]+)"')


def line_model(line_text):
    """stream-json 行里的 message.model(模型标识), 无则 None。"""
    m = LINE_MODEL_RE.search(line_text)
    return m.group(1) if m else None


def claude_version():
    """claude CLI 版本串, 供 trigger 结果可复现(拿不到返回 None)。"""
    import shutil
    import subprocess
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return (p.stdout.strip() or p.stderr.strip() or None)
    except (subprocess.TimeoutExpired, OSError):
        return None


def load_cases(path):
    """读 cases 文件, 兼容 cases 命令的 {skill,note,cases} 包装与裸列表两种形态。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases", [])
    return data


def cmd_trigger(args):
    cases = load_cases(args.cases)
    print(f"# 将执行 {len(cases)} case × {args.repeats} 次 = "
          f"{len(cases) * args.repeats} 次 claude -p 真实模型调用(花钱), "
          f"目标 skill: {args.skill}", file=sys.stderr)
    results = []
    test_sessions = set()
    models = set()
    import tempfile
    # 中性 cwd: 若源 skill 目录在 cwd, 模型会直接 Read 源文件绕过 Skill 工具, 触发测试失真
    neutral_cwd = tempfile.gettempdir()
    for c in cases:
        expect = bool(c.get("expect", True))
        hits = 0
        called_union = set()
        for _ in range(args.repeats):
            stream = run_claude_headless(c["prompt"], max_turns=args.max_turns,
                                         cwd=neutral_cwd)
            test_sessions |= collect_session_ids(stream)
            called = []
            for line in stream.splitlines():
                called += extract_skill_calls(line)
                m = line_model(line)
                if m:
                    models.add(m)
            called_union |= set(called)
            if any(is_target_skill(n, args.skill) for n in called):
                hits += 1
        rate = round(hits / args.repeats, 3)
        if expect:
            verdict = ("stable_hit" if hits == args.repeats
                       else "miss" if hits == 0 else "intermittent")
        else:
            verdict = "false_trigger" if hits else "pass_avoided"
        results.append({
            "prompt": c["prompt"][:80],
            "expect": expect,
            "hits": hits,
            "repeats": args.repeats,
            "hit_rate": rate,
            "skills_called": sorted(called_union),
            "verdict": verdict,
        })
    should_runs = sum(r["repeats"] for r in results if r["expect"])
    should_hits = sum(r["hits"] for r in results if r["expect"])
    shouldnt_runs = sum(r["repeats"] for r in results if not r["expect"])
    shouldnt_hits = sum(r["hits"] for r in results if not r["expect"])
    if test_sessions:  # 测试会话进黑名单, usage/cost 不再计入
        save_trigger_blocklist(load_trigger_blocklist() | test_sessions)
    trig = round(should_hits / should_runs, 3) if should_runs else None
    false = round(shouldnt_hits / shouldnt_runs, 3) if shouldnt_runs else None
    print(json.dumps({
        "platform": "claude-code",
        "skill": args.skill,
        "cases": len(results),
        "repeats": args.repeats,
        "trigger_rate": trig,
        "trigger_rate_ci": wilson_ci(trig, should_runs) if trig is not None else None,
        "false_trigger_rate": false,
        "false_trigger_rate_ci": wilson_ci(false, shouldnt_runs) if false is not None else None,
        # 环境快照: 触发率跨时间可比的前提
        "env": {
            "claude_version": claude_version(),
            "models": sorted(models),
            "installed_skills_count": len(scan_skills("claude-code")[0]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "test_sessions_excluded": len(test_sessions),
        "results": results,
    }, ensure_ascii=False, indent=2))


def cmd_ablate(args):
    """description 逐句消融: 删掉句 i 跑正例, 触发率掉幅 = 该句边际贡献。

    因果证据(非直觉): 哪句保命、哪句白占 token。SKILL.md 改写后 finally 还原
    并校验 sha256, 防中断留脏文件。
    """
    import hashlib
    import tempfile
    skills = scan_skills(args.platform)[0]
    target = next((s for s in skills
                   if is_target_skill(s.get("name", ""), args.skill)), None)
    if not target or "error" in target:
        print(json.dumps({"error": f"skill not found: {args.skill}"},
                         ensure_ascii=False, indent=2))
        return
    cases = load_cases(args.cases)
    pos = [c["prompt"] for c in cases if c.get("expect", True)][:args.per]
    sents = split_sentences(target.get("description", ""))
    if not pos:
        print(json.dumps({"error": "cases.json 无正例"}, ensure_ascii=False, indent=2))
        return
    if len(sents) < 2:
        print(json.dumps({"error": f"description 仅 {len(sents)} 句, 无从消融"},
                         ensure_ascii=False, indent=2))
        return

    skill_md = Path(target["dir"]) / "SKILL.md"
    original = skill_md.read_text(encoding="utf-8")
    orig_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
    runs_per_group = len(pos) * args.repeats
    groups = len(sents) + 1  # baseline + 每句一组
    print(f"# 将执行 {groups} 组 × {runs_per_group} 次 = "
          f"{groups * runs_per_group} 次 claude -p(花钱), 目标 skill: {args.skill}",
          file=sys.stderr)

    test_sessions = set()
    neutral_cwd = tempfile.gettempdir()

    def run_group():
        hits = 0
        for _ in range(args.repeats):
            for p in pos:
                stream = run_claude_headless(p, max_turns=args.max_turns,
                                             cwd=neutral_cwd)
                test_sessions.update(collect_session_ids(stream))
                called = []
                for line in stream.splitlines():
                    called += extract_skill_calls(line)
                if any(is_target_skill(n, args.skill) for n in called):
                    hits += 1
        return hits / runs_per_group

    rows = []
    try:
        baseline = run_group()
        rows.append({"index": None, "removed": "(基线, 原样)",
                     "rate": round(baseline, 3), "drop": 0.0})
        for idx, s in enumerate(sents):
            ablated_desc = " ".join(x for j, x in enumerate(sents) if j != idx)
            skill_md.write_text(rewrite_description(original, ablated_desc),
                                encoding="utf-8")
            rate = run_group()
            rows.append({"index": idx, "removed": s[:50],
                         "rate": round(rate, 3),
                         "drop": round(rate - baseline, 3)})
    finally:  # 无论中途发生什么, SKILL.md 必须还原
        skill_md.write_text(original, encoding="utf-8")
    restored = hashlib.sha256(
        skill_md.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    if test_sessions:
        save_trigger_blocklist(load_trigger_blocklist() | test_sessions)
    rows.sort(key=lambda r: (r["drop"], r["index"] or 0))
    variance = len({r["rate"] for r in rows}) > 1
    print(json.dumps({
        "platform": args.platform,
        "skill": args.skill,
        "sentences": len(sents),
        "cases_per_group": len(pos),
        "repeats": args.repeats,
        "baseline_rate": round(baseline, 3),
        "rows": rows,
        "restored_ok": restored == orig_hash,
        "note": "drop=消融后-基线, 负得越深=该句越保命; "
                + ("" if variance else
                   "全组零方差: 改写可能未生效(skill 列表缓存?), 结论不可用"),
    }, ensure_ascii=False, indent=2))


def route_windows(lines, known):
    """(prompt, [被调 skill 规范名]) 窗口: 每条 NL 用户 prompt 到下一条 prompt 间的全部调用。

    无 NL prompt 的窗口(斜杠直展/纯工具会话首段)整体丢弃——无语境无从判路由。
    """
    windows = []
    cur_prompt, cur_calls = None, []
    for line in lines:
        if '"type":"user"' in line:
            p = first_user_prompt(line)
            if p:
                if cur_prompt is not None:
                    windows.append((cur_prompt, cur_calls))
                cur_prompt, cur_calls = p, []
        if '"skill"' in line or '"Skill"' in line:
            cur_calls += extract_skill_calls(line)
        cur_calls += slash_calls_in_line(line, known)
    if cur_prompt is not None:
        windows.append((cur_prompt, cur_calls))
    return windows


def cmd_steal(args):
    """抢触发实证: prompt 命中目标 description 却路由别处的真实历史统计。

    R4(lint) 只给嫌疑(desc 重叠率), 这里给判决——路由结果是谁赢谁输。
    """
    skills = scan_skills(args.platform)[0]
    target = next((s for s in skills
                   if is_target_skill(s.get("name", ""), args.skill)), None)
    if not target or "error" in target or not target.get("description"):
        print(json.dumps({"error": f"skill not found or no description: {args.skill}"},
                         ensure_ascii=False, indent=2))
        return
    tdesc = target["description"]
    known = known_skill_names(args.platform)
    won = stolen = missed = 0
    stolen_by = Counter()
    evidence = []
    for f in iter_logs(args.platform, args.days):
        try:
            lines = f.open(encoding="utf-8", errors="replace").readlines()
        except OSError:
            continue
        for prompt, calls in route_windows(lines, known):
            if any(is_target_skill(n, args.skill) for n in calls):
                won += 1
                continue
            ov = overlap_rate(prompt, tdesc)
            if ov < args.overlap:  # prompt 与目标 desc 无语义命中, 不算被抢
                continue
            rivals = sorted({n for n in calls
                             if not is_target_skill(n, args.skill)})
            if rivals:
                stolen += 1
                for r in rivals:
                    stolen_by[r] += 1
            else:
                missed += 1  # 高重叠却零调用: 漏触发线索
            evidence.append({"prompt": prompt[:80], "routed_to": rivals[:3],
                             "overlap": ov})
    evidence.sort(key=lambda e: -e["overlap"])
    total = won + stolen
    print(json.dumps({
        "platform": args.platform,
        "skill": args.skill,
        "window_days": args.days,
        "overlap_threshold": args.overlap,
        "won": won,
        "stolen": stolen,
        "missed": missed,
        "steal_rate": round(stolen / total, 3) if total else None,
        "stolen_by": [{"skill": s, "count": c}
                      for s, c in stolen_by.most_common(5)],
        "evidence": evidence[:10],
        "note": "重叠率是机械粗筛, evidence 逐条由模型复核真伪; "
                "missed=高重叠但零调用(漏触发线索)",
    }, ensure_ascii=False, indent=2))


def est_tokens(text):
    """粗估 token: CJK ~1.1 字/token, 其余 ~2.8 字符/token (2026-08 转录实测校准)。估算口径, 勿折算金额。"""
    cjk = len(re.findall(r'[一-鿿]', text))
    return int(cjk / 1.1 + (len(text) - cjk) / 2.8)


def extract_calls_with_usage(line_text):
    """返回 [(skill名, output_tokens|None)]。usage 兼容 message.usage 与顶层 usage 两种位置。"""
    try:
        obj = json.loads(line_text)
    except (json.JSONDecodeError, ValueError):
        return []
    msg = obj.get("message") if isinstance(obj, dict) else None
    usage = None
    for holder in (msg, obj):
        if isinstance(holder, dict) and isinstance(holder.get("usage"), dict):
            usage = holder["usage"]
            break
    out_toks = None
    if usage:
        for k in ("output_tokens", "outputTokens", "completion_tokens"):
            if isinstance(usage.get(k), int):
                out_toks = usage[k]
                break
    return [(n, out_toks) for n in extract_skill_calls(line_text)]


def parse_usage(line_text):
    """行里的 usage dict(message.usage 或顶层), 无则 None。"""
    try:
        obj = json.loads(line_text)
    except (json.JSONDecodeError, ValueError):
        return None
    msg = obj.get("message") if isinstance(obj, dict) else None
    for holder in (msg, obj):
        if isinstance(holder, dict) and isinstance(holder.get("usage"), dict):
            return holder["usage"]
    return None


def effective_input(usage):
    """有效输入 token: input + cache 读/写(缓存命中也占上下文, 差分须算全量)。"""
    total = 0
    for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = usage.get(k)
        if isinstance(v, int):
            total += v
    return total


class InputDeltaTracker:
    """逐行配对 skill 调用与下一轮 input, 产出注入成本实测样本。

    原理: Skill 调用(tool_use / 斜杠直展)后, 下一个带 usage 的 assistant 事件
    的 input 增量 = skill 正文 + tool_result 信封进上下文的真实成本。
    调用所在行自身的 usage 只刷新基线不产样本(注入体现在下一轮)。
    """

    def __init__(self):
        self.prev = None
        self.pending = False

    def note_line(self, called_target, usage):
        """喂一行: called_target=该行含目标调用, usage=该行 usage(可 None)。
        配对完成返回差分样本, 否则 None。"""
        if usage is None:
            if called_target:  # 斜杠直展行(用户消息, 无 usage)
                self.pending = True
            return None
        cur = effective_input(usage)
        sample = None
        if called_target:
            self.pending = True  # 刷新基线, 注入在下一轮才可见
        elif self.pending and self.prev is not None and cur > self.prev:
            sample = cur - self.prev
            self.pending = False
        self.prev = cur
        return sample


def cmd_cost(args):
    skills, _ = scan_skills(args.platform)
    target = next((s for s in skills
                   if is_target_skill(s.get("name", ""), args.skill)), None)

    out = {"platform": args.platform, "skill": args.skill,
           "note": "token 为估算/实测混合口径, 不折算金额"}

    if target:
        out["description_tokens_est"] = est_tokens(target.get("description", ""))
        tdir = Path(target["dir"])
        files, bundled = [], []
        for f in sorted(tdir.rglob("*")):
            if not f.is_file() or "__pycache__" in f.relative_to(tdir).parts:
                continue
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = f.relative_to(tdir).as_posix()
            if f.suffix.lower() == ".md":
                body = re.sub(r"^---\s*\n.*?\n---", "", raw, flags=re.S)
                files.append({"file": f.name, "tokens_est": est_tokens(body)})
            else:  # 第三笔账: 按需读取的随身文件(脚本/参考资料), 二进制为上界估算
                bundled.append({"file": rel, "tokens_est": est_tokens(raw)})
        out["body_files_tokens_est"] = files
        out["bundled_files_tokens_est"] = bundled
    else:
        out["dir_found"] = False
        out["hint"] = "skill 目录不在当前扫描范围(可能装在别的项目), 仅输出调用统计"

    # 历史调用 + 调用轮 output_tokens 实测 + 注入成本 input 差分实测
    log_platform = args.platform if args.platform != "all" else "claude-code"
    known = known_skill_names(log_platform)
    counter = Counter()
    slash_count = 0
    out_samples = []
    in_samples = []
    tracker = InputDeltaTracker()
    for f in iter_logs(log_platform, args.days):
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                # 差分需要 usage 行做基线链, 斜杠直展行也触发注入, 都不能跳过
                if ('"usage"' not in line and '"skill"' not in line
                        and "<command-name>" not in line):
                    continue
                called_here = False
                if '"skill"' in line or '"Skill"' in line:
                    for n, t in extract_calls_with_usage(line):
                        if is_target_skill(n, args.skill):
                            called_here = True
                            counter[n] += 1
                            if t is not None:
                                out_samples.append(t)
                for name in slash_calls_in_line(line, known):
                    if is_target_skill(name, args.skill):
                        called_here = True
                        slash_count += 1
                sample = tracker.note_line(called_here, parse_usage(line))
                if sample is not None:
                    in_samples.append(sample)
        except OSError:
            continue
    out["invocations"] = sum(counter.values())  # Skill 工具调用
    out["slash_invocations"] = slash_count      # 斜杠直展(output_tokens 不可归因, 只测注入)
    if out_samples:
        avg = int(sum(out_samples) / len(out_samples))
        out["invocation_output_tokens"] = {
            "samples": len(out_samples),
            "avg": avg,
            "max": max(out_samples),
            # 总账: 窗口内全部调用按样本均值折算(实测样本覆盖不足时为估)
            "total_est": out["invocations"] * avg,
        }
    if in_samples:
        out["injection_input_tokens"] = {
            "samples": len(in_samples),
            "avg": int(sum(in_samples) / len(in_samples)),
            "max": max(in_samples),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))


SNAPSHOT_ROOT = Path.home() / ".skill-doctor" / "snapshots"


def snapshot_skill(skill_dir):
    """{相对路径: sha256} — skill 目录全文件指纹。"""
    import hashlib
    snap = {}
    for f in sorted(Path(skill_dir).rglob("*")):
        if f.is_file():
            rel = f.relative_to(skill_dir).as_posix()
            snap[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return snap


def cmd_drift(args):
    skills, _ = scan_skills(args.platform)
    if args.skill:
        skills = [s for s in skills if args.skill.lower() in s.get("name", "").lower()]
    store = SNAPSHOT_ROOT / args.platform
    store.mkdir(parents=True, exist_ok=True)
    results = []
    for s in skills:
        if "error" in s or "dir" not in s:
            continue
        name = s.get("name", Path(s["dir"]).name)
        snap_file = store / f"{name}.json"
        current = snapshot_skill(s["dir"])
        if args.reset or not snap_file.exists():
            snap_file.write_text(json.dumps(
                {"taken_at": datetime.now(timezone.utc).isoformat(), "files": current},
                ensure_ascii=False), encoding="utf-8")
            results.append({"skill": name, "status": "baseline_created",
                            "files": len(current)})
            continue
        old = json.loads(snap_file.read_text(encoding="utf-8"))
        old_files = old.get("files", {})
        changed = sorted(k for k in current if old_files.get(k) != current[k])
        removed = sorted(k for k in old_files if k not in current)
        status = "changed" if (changed or removed) else "clean"
        results.append({"skill": name, "status": status,
                        "changed": changed, "removed": removed,
                        "last_snapshot": old.get("taken_at")})
        if status == "changed":  # 更新快照, 下次以新版本为基线
            snap_file.write_text(json.dumps(
                {"taken_at": datetime.now(timezone.utc).isoformat(), "files": current},
                ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"platform": args.platform, "results": results},
                     ensure_ascii=False, indent=2))


def cmd_visibility(args):
    config_path = Path(args.config)
    if not config_path.is_file():
        print(json.dumps({"error": f"config not found: {config_path}",
                          "hint": "OpenClaw 未安装或配置在别处, 可用 --config 指定"},
                         ensure_ascii=False, indent=2))
        return
    cfg = json.loads(config_path.read_text(encoding="utf-8", errors="replace"))
    skills_dir = Path(args.skills_dir)
    installed = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md")) \
        if skills_dir.is_dir() else []

    # ponytail: 只认文档确认的三处: 顶层 skills / agents.defaults.skills / agents.entries.*.skills
    top = cfg.get("skills", {}) or {}
    defaults = ((cfg.get("agents") or {}).get("defaults") or {}).get("skills", {}) or {}
    entries = (cfg.get("agents") or {}).get("entries") or {}

    def visible_in(block, name):
        """返回 True/False(显式配置) / None(未提及)。兼容 list 与 {enable/disable} 形态。"""
        if isinstance(block, list):
            return name in block or None
        if isinstance(block, dict):
            for key, val in block.items():
                if name == key or (isinstance(val, dict) and name in val):
                    return bool(val is True or (isinstance(val, dict) and val.get("enabled", True)))
            # enable/disable 列表形态
            if isinstance(block.get("enable"), list) or isinstance(block.get("disable"), list):
                en = name in (block.get("enable") or [])
                dis = name in (block.get("disable") or [])
                if en or dis:
                    return en and not dis
        return None

    results = []
    for name in installed:
        global_vis = visible_in(top, name) if isinstance(top, (list, dict)) else None
        default_vis = visible_in(defaults, name)
        per_agent = {}
        for agent_id, agent_cfg in entries.items():
            if isinstance(agent_cfg, dict):
                v = visible_in(agent_cfg.get("skills", {}) or {}, name)
                if v is not None:
                    per_agent[agent_id] = v
        results.append({
            "skill": name,
            "global": global_vis,                  # 顶层 skills 配置
            "default_agent": default_vis,          # True/False/None=未提及(通常=可见)
            "explicit_agents": per_agent,           # 显式配置过的具名 agent
            "configured": global_vis is not None or default_vis is not None
                          or bool(per_agent),
        })
    if args.skill:
        results = [r for r in results if args.skill.lower() in r["skill"].lower()]
    print(json.dumps({
        "config": str(config_path), "installed": len(installed), "results": results,
    }, ensure_ascii=False, indent=2))


def main():
    # Windows 管道下 stdout 默认 cp936, ensure_ascii=False 的中文 JSON 全乱码;
    # 3.7+ 可 reconfigure, 更老版本静默维持原状
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="skill-doctor v1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="枚举已装 skill")
    p_list.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])

    p_usage = sub.add_parser("usage", help="统计 skill 工具调用(claude-code/codex)")
    p_usage.add_argument("--platform", default="claude-code",
                         choices=[p for p in SESSION_LOG_DIRS if SESSION_LOG_DIRS[p]])
    p_usage.add_argument("--skill", default=None, help="按名称过滤")
    p_usage.add_argument("--days", type=int, default=30)

    p_lint = sub.add_parser("lint", help="机械体检 R1/R2粗检/R4/R5")
    p_lint.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])
    p_lint.add_argument("--skill", default=None, help="只体检匹配名称的 skill")

    p_trig = sub.add_parser("trigger", help="回放触发测试(跑 claude -p, 花真钱)")
    p_trig.add_argument("--skill", required=True, help="目标 skill 名")
    p_trig.add_argument("--cases", required=True, help="cases.json 路径")
    p_trig.add_argument("--max-turns", type=int, default=2,
                        help="单 case claude 会话轮数上限(默认 2)")
    p_trig.add_argument("--repeats", type=int, default=1,
                        help="每 case 重复次数(默认 1; ≥3 配合置信区间更有意义)")

    p_cases = sub.add_parser("cases", help="从 usage 历史采样生成 trigger 测试集")
    p_cases.add_argument("--skill", required=True, help="目标 skill 名")
    p_cases.add_argument("--platform", default="claude-code",
                         choices=[p for p in SESSION_LOG_DIRS if SESSION_LOG_DIRS[p]])
    p_cases.add_argument("--days", type=int, default=30)
    p_cases.add_argument("--per", type=int, default=5,
                         help="正/反例各采 N 条(默认 5)")
    p_cases.add_argument("--boundary", default=None,
                         help="逗号分隔边界词, 反例 prompt 须命中其一(如 仓库,RFID)")
    p_cases.add_argument("--out", default=None,
                         help="写出 cases.json 路径(缺省打印 stdout)")

    p_abl = sub.add_parser("ablate",
                           help="description 逐句消融(跑 claude -p, 花真钱)")
    p_abl.add_argument("--skill", required=True, help="目标 skill 名")
    p_abl.add_argument("--cases", required=True, help="cases.json 路径(取正例)")
    p_abl.add_argument("--per", type=int, default=3,
                       help="每组用前 N 条正例(默认 3)")
    p_abl.add_argument("--repeats", type=int, default=1)
    p_abl.add_argument("--max-turns", type=int, default=2)
    p_abl.add_argument("--platform", default="claude-code",
                       choices=list(PLATFORM_DIRS) + ["all"])

    p_steal = sub.add_parser("steal", help="抢触发实证(读历史, 不花钱)")
    p_steal.add_argument("--skill", required=True, help="目标 skill 名")
    p_steal.add_argument("--days", type=int, default=30)
    p_steal.add_argument("--overlap", type=float, default=0.3,
                         help="prompt 与目标 description 的重叠率阈值(默认 0.3)")
    p_steal.add_argument("--platform", default="claude-code",
                         choices=[p for p in SESSION_LOG_DIRS if SESSION_LOG_DIRS[p]])

    p_cost = sub.add_parser("cost", help="成本账单(估算+实测, 不出钱)")
    p_cost.add_argument("--skill", required=True, help="目标 skill 名")
    p_cost.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])
    p_cost.add_argument("--days", type=int, default=30)

    p_drift = sub.add_parser("drift", help="skill 目录漂移检测(快照 diff)")
    p_drift.add_argument("--platform", default="claude-code",
                         choices=list(PLATFORM_DIRS) + ["all"])
    p_drift.add_argument("--skill", default=None, help="只检测匹配名称的 skill")
    p_drift.add_argument("--reset", action="store_true",
                         help="丢弃旧快照重建基线")

    p_vis = sub.add_parser("visibility", help="OpenClaw 可见性审计")
    p_vis.add_argument("--config",
                       default=str(Path.home() / ".openclaw" / "openclaw.json"))
    p_vis.add_argument("--skills-dir",
                       default=str(Path.home() / ".openclaw" / "workspace" / "skills"))
    p_vis.add_argument("--skill", default=None, help="只看匹配名称的 skill")

    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "usage":
        cmd_usage(args)
    elif args.cmd == "lint":
        cmd_lint(args)
    elif args.cmd == "trigger":
        cmd_trigger(args)
    elif args.cmd == "cases":
        cmd_cases(args)
    elif args.cmd == "ablate":
        cmd_ablate(args)
    elif args.cmd == "steal":
        cmd_steal(args)
    elif args.cmd == "cost":
        cmd_cost(args)
    elif args.cmd == "drift":
        cmd_drift(args)
    elif args.cmd == "visibility":
        cmd_visibility(args)


if __name__ == "__main__":
    main()
