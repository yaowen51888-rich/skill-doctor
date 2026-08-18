#!/usr/bin/env python3
"""skill-doctor v1: 跨平台 skill 体检脚本。

子命令:
  list   枚举已装 skill + 解析 frontmatter(claude-code/codex/dsh/openclaw/hermes 目录探测,
         格式同为 SKILL.md)
  usage  扫 Claude Code 会话日志, 统计 Skill 工具调用(v1 仅 claude-code 实现, 其余平台见 PLATFORMS.md)
  lint   机械体检 R1/R2粗检/R4/R5(确定性部分脚本化, R2/R3 语义判断留给模型, 见 SKILL.md)

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
    """简易 frontmatter 解析, 只取 name/description, 不引 yaml 依赖。"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        kv = re.match(r'^(name|description):\s*(.+)$', line.strip())
        if kv:
            out[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return out


def scan_skills(platform):
    bases = PROJECT_DIRS.get(platform, []) + PLATFORM_DIRS[platform]
    skills, missing = [], []
    for base in bases:
        if not base.is_dir():
            missing.append(str(base))
            continue
        for md in sorted(base.glob("*/SKILL.md")):
            try:
                fm = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                skills.append({"dir": str(md.parent), "error": str(e)})
                continue
            desc = fm.get("description", "")
            skills.append({
                "dir": str(md.parent),
                "name": fm.get("name") or md.parent.name,
                "description": desc,
                "description_chars": len(desc),
            })
    return skills, missing


def cmd_list(args):
    result = {}
    platforms = [args.platform] if args.platform != "all" else list(PLATFORM_DIRS)
    for p in platforms:
        skills, missing = scan_skills(p)
        result[p] = {"found": len(skills), "skills": skills, "dirs_not_found": missing}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def iter_cc_logs(days):
    """产出 ~/.claude/projects 下 N 天内修改过的 jsonl 文件。"""
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return
    cutoff = datetime.now().timestamp() - days * 86400
    for f in root.rglob("*.jsonl"):
        try:
            if f.stat().st_mtime >= cutoff:
                yield f
        except OSError:
            continue


def extract_skill_calls(line_text):
    """从一行转录 JSON 提取 Skill 工具调用名。找不到返回空列表。

    兼容: content 为数组, 元素 type==tool_use 且 name 含 Skill;
    参数名可能是 skill / skill_name / name, 取第一个字符串值。
    """
    calls = []
    try:
        obj = json.loads(line_text)
    except (json.JSONDecodeError, ValueError):
        return calls
    msg = obj.get("message") or obj
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return calls
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and "Skill" in str(block.get("name", "")):
            inp = block.get("input") or {}
            for key in ("skill", "skill_name", "name", "command"):
                v = inp.get(key)
                if isinstance(v, str) and v:
                    calls.append(v.lstrip("/").split()[0] if v.startswith("/") else v)
                    break
    return calls


def cmd_usage(args):
    counter = Counter()
    sessions = {}
    total_lines = 0
    for f in iter_cc_logs(args.days):
        used_here = set()
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"Skill"' not in line and '"skill"' not in line:
                    continue  # 快速预过滤, 跳过无关行
                total_lines += 1
                for name in extract_skill_calls(line):
                    counter[name] += 1
                    used_here.add(name)
        except OSError:
            continue
        for n in used_here:
            sessions[n] = sessions.get(n, 0) + 1

    result = {
        "platform": "claude-code",
        "window_days": args.days,
        "files_scanned_hint_lines": total_lines,
        "skill_calls": [
            {"skill": n, "calls": c, "sessions": sessions.get(n, 0)}
            for n, c in counter.most_common()
        ],
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

    # 已知局限提示: 多行 YAML 折叠被截断
    if desc[:1] in (">", "|"):
        r["yaml_multiline_truncated"] = True
    return r


def cmd_lint(args):
    skills, _ = scan_skills(args.platform)
    if args.skill:
        targets = [s for s in skills if args.skill.lower() in s.get("name", "").lower()]
    else:
        targets = skills
    results = [lint_one(s, skills) for s in targets if "error" not in s]
    flagged = [r for r in results if r["R1"] != "ok" or r["R4_competitors"]
               or r["R5"] != "ok" or not r["R2_scene_signal"]
               or r.get("yaml_multiline_truncated")]
    print(json.dumps({
        "platform": args.platform,
        "checked": len(results),
        "flagged": len(flagged),
        "results": results,
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="skill-doctor v1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="枚举已装 skill")
    p_list.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])

    p_usage = sub.add_parser("usage", help="统计 Skill 工具调用(仅 claude-code)")
    p_usage.add_argument("--skill", default=None, help="按名称过滤")
    p_usage.add_argument("--days", type=int, default=30)

    p_lint = sub.add_parser("lint", help="机械体检 R1/R2粗检/R4/R5")
    p_lint.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])
    p_lint.add_argument("--skill", default=None, help="只体检匹配名称的 skill")

    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "usage":
        cmd_usage(args)
    elif args.cmd == "lint":
        cmd_lint(args)


if __name__ == "__main__":
    main()
