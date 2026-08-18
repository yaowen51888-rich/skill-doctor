#!/usr/bin/env python3
"""skill-doctor v1: 跨平台 skill 体检脚本。

子命令:
  list   枚举已装 skill + 解析 frontmatter(claude-code/codex/dsh/openclaw/hermes 目录探测,
         格式同为 SKILL.md)
  usage  扫 Claude Code 会话日志, 统计 Skill 工具调用(v1 仅 claude-code 实现, 其余平台见 PLATFORMS.md)
  lint   机械体检 R1/R2粗检/R4/R5(确定性部分脚本化, R2/R3 语义判断留给模型, 见 SKILL.md)
  trigger 回放触发测试: 用 cases.json 逐条跑 claude -p, 统计触发率/误触发(v2, 仅 claude-code)
  cost   成本账单: desc/body token 估算 + 调用轮 output_tokens 实测(不出钱, 仅 claude-code)
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


def is_target_skill(called, target):
    """plugin skill 名形如 plugin:name, 取尾段比对。"""
    return called == target or called.split(":")[-1] == target


def run_claude_headless(prompt, max_turns=2, timeout=180):
    """跑一次性 claude 会话, 返回 stream-json 文本。找不到 CLI 或超时返回 ""。"""
    import shutil
    import subprocess
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        return ""
    try:
        p = subprocess.run(
            [exe, "-p", prompt, "--output-format", "stream-json", "--verbose",
             "--max-turns", str(max_turns)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout)
        return p.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def cmd_trigger(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    print(f"# 将执行 {len(cases)} 次 claude -p 真实模型调用(花钱), 目标 skill: {args.skill}",
          file=sys.stderr)
    results = []
    for c in cases:
        stream = run_claude_headless(c["prompt"])
        called = []
        for line in stream.splitlines():
            called += extract_skill_calls(line)
        hit = any(is_target_skill(n, args.skill) for n in called)
        expect = bool(c.get("expect", True))
        if expect and hit:
            verdict = "pass"
        elif expect and not hit:
            verdict = "miss"
        elif not expect and hit:
            verdict = "false_trigger"
        else:
            verdict = "pass_avoided"
        results.append({
            "prompt": c["prompt"][:80],
            "expect": expect,
            "skills_called": called,
            "verdict": verdict,
        })
    should = [r for r in results if r["expect"]]
    shouldnt = [r for r in results if not r["expect"]]
    hits = sum(1 for r in should if r["verdict"] == "pass")
    falses = sum(1 for r in shouldnt if r["verdict"] == "false_trigger")
    print(json.dumps({
        "platform": "claude-code",
        "skill": args.skill,
        "cases": len(results),
        "trigger_rate": round(hits / len(should), 3) if should else None,
        "false_trigger_rate": round(falses / len(shouldnt), 3) if shouldnt else None,
        "results": results,
    }, ensure_ascii=False, indent=2))


def est_tokens(text):
    """粗估 token: CJK ~1.6 字/token, 其余 ~4 字符/token。估算口径, 勿折算金额。"""
    cjk = len(re.findall(r'[一-鿿]', text))
    return int(cjk / 1.6 + (len(text) - cjk) / 4)


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


def cmd_cost(args):
    skills, _ = scan_skills(args.platform)
    target = next((s for s in skills
                   if is_target_skill(s.get("name", ""), args.skill)), None)

    out = {"platform": args.platform, "skill": args.skill,
           "note": "token 为估算/实测混合口径, 不折算金额"}

    if target:
        out["description_tokens_est"] = est_tokens(target.get("description", ""))
        files = []
        for f in sorted(Path(target["dir"]).rglob("*.md")):
            try:
                body = re.sub(r"^---\s*\n.*?\n---", "",
                              f.read_text(encoding="utf-8", errors="replace"),
                              flags=re.S)
                files.append({"file": f.name, "tokens_est": est_tokens(body)})
            except OSError:
                continue
        out["body_files_tokens_est"] = files
    else:
        out["dir_found"] = False
        out["hint"] = "skill 目录不在当前扫描范围(可能装在别的项目), 仅输出调用统计"

    # 历史调用 + 调用轮 output_tokens 实测
    counter = Counter()
    out_samples = []
    for f in iter_cc_logs(args.days):
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                if '"Skill"' not in line and '"skill"' not in line:
                    continue
                for n, t in extract_calls_with_usage(line):
                    if is_target_skill(n, args.skill):
                        counter[n] += 1
                        if t is not None:
                            out_samples.append(t)
        except OSError:
            continue
    out["invocations"] = sum(counter.values())
    if out_samples:
        out["invocation_output_tokens"] = {
            "samples": len(out_samples),
            "avg": int(sum(out_samples) / len(out_samples)),
            "max": max(out_samples),
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

    p_trig = sub.add_parser("trigger", help="回放触发测试(跑 claude -p, 花真钱)")
    p_trig.add_argument("--skill", required=True, help="目标 skill 名")
    p_trig.add_argument("--cases", required=True, help="cases.json 路径")

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
    elif args.cmd == "cost":
        cmd_cost(args)
    elif args.cmd == "drift":
        cmd_drift(args)
    elif args.cmd == "visibility":
        cmd_visibility(args)


if __name__ == "__main__":
    main()
