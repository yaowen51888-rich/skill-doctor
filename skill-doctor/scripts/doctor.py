#!/usr/bin/env python3
"""skill-doctor v1: 跨平台 skill 体检脚本。

子命令:
  list   枚举已装 skill + 解析 frontmatter(claude-code/codex/dsh/openclaw/hermes 目录探测,
         其中 claude-code、codex、dsh、openclaw、hermes 均为目录扫描, 格式同为 SKILL.md)
  usage  扫 Claude Code 会话日志, 统计 Skill 工具调用(v1 仅 claude-code 实现, 其余平台见 PLATFORMS.md)

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


def main():
    ap = argparse.ArgumentParser(description="skill-doctor v1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="枚举已装 skill")
    p_list.add_argument("--platform", default="claude-code",
                        choices=list(PLATFORM_DIRS) + ["all"])

    p_usage = sub.add_parser("usage", help="统计 Skill 工具调用(仅 claude-code)")
    p_usage.add_argument("--skill", default=None, help="按名称过滤")
    p_usage.add_argument("--days", type=int, default=30)

    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "usage":
        cmd_usage(args)


if __name__ == "__main__":
    main()
