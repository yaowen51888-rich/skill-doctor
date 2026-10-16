#!/usr/bin/env python3
"""doctor.py 零框架自测: py test_doctor.py, 全过打印 ALL PASS。

fixture 覆盖三平台 skill 调用事件同构形态(dsh/codex 为文档推断形态,
真机首跑若失败优先怀疑这里)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from doctor import (  # noqa: E402
    InputDeltaTracker, case_role, cluster_prompts, collect_session_ids,
    effective_input, est_tokens, extract_skill_calls, extract_slash_commands,
    first_user_prompt, is_target_skill, lint_one, overlap_rate,
    parse_frontmatter, parse_usage, scenarios_for, wilson_ci,
)

# --- 三平台提取形态 ---
CC_LINE = ('{"message":{"content":[{"type":"tool_use","name":"Skill",'
           '"input":{"skill":"aihot"}}]}}')
DSH_LINE = ('{"type":"tool/call","seq":12,"time":1755400000000,'
            '"data":{"name":"skill","arguments":{"name":"aihot"}}}')
CODEX_LINE = ('{"type":"function_call","name":"skill",'
              '"arguments":"{\\"name\\": \\"aihot\\"}"}')
SLASH_LINE = ('{"message":{"content":[{"type":"tool_use","name":"Skill",'
              '"input":{"command":"/aihot AI日报"}}]}}')
NOISE_LINE = '{"message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}'

assert extract_skill_calls(CC_LINE) == ["aihot"], "cc tool_use 形态"
assert extract_skill_calls(DSH_LINE) == ["aihot"], "dsh 事件信封形态"
assert extract_skill_calls(CODEX_LINE) == ["aihot"], "codex arguments 字符串形态"
assert extract_skill_calls(SLASH_LINE) == ["aihot"], "斜杠命令取首词"
assert extract_skill_calls(NOISE_LINE) == [], "非 skill 工具不误报"
assert extract_skill_calls("not json at all") == [], "坏行不崩"

# --- 斜杠直展形态(transcript 用户消息含 command-name 标签, 不走 Skill 工具) ---
SLASH_DIRECT = ('{"message":{"content":"<command-name>/aihot</command-name>'
                '<command-message>aihot</command-message>"}}')
SLASH_WITH_ARG = ('{"message":{"content":"<command-name>/caveman lite</command-name>"}}')
assert extract_slash_commands(SLASH_DIRECT) == ["aihot"], "斜杠直展取名"
assert extract_slash_commands(SLASH_WITH_ARG) == ["caveman"], "带参数斜杠取首词"
assert extract_slash_commands(NOISE_LINE) == [], "无 command-name 不误报"

# --- trigger 测试会话收集 ---
STREAM = ('{"type":"system","session_id":"abc-1"}\n'
          '{"type":"assistant","session_id":"abc-1","message":{}}\n'
          '{"type":"user","session_id":"def-2"}\n'
          "not json\n")
assert collect_session_ids(STREAM) == {"abc-1", "def-2"}, "session_id 去重收集"
assert collect_session_ids("") == set(), "空流不崩"

# --- cases 采样: 首条用户 prompt 提取 ---
USER_STR = '{"type":"user","message":{"content":"今天有什么AI新闻"}}'
USER_LIST = ('{"type":"user","message":{"content":[{"type":"text","text":"帮我查RFID"}]}}')
TOOL_RESULT = ('{"type":"user","message":{"content":'
               '[{"type":"tool_result","content":"ok"}]}}')
CMD_LINE2 = ('{"type":"user","message":{"content":'
             '"<command-name>/aihot</command-name>"}}')
META = '{"type":"user","isMeta":true,"message":{"content":"meta行"}}'
ASSISTANT = '{"type":"assistant","message":{"content":"模型输出"}}'
assert first_user_prompt(USER_STR) == "今天有什么AI新闻", "字符串 content"
assert first_user_prompt(USER_LIST) == "帮我查RFID", "数组 content 取 text 段"
assert first_user_prompt(TOOL_RESULT) is None, "纯 tool_result 行不算 prompt"
assert first_user_prompt(CMD_LINE2) is None, "命令直展剔除"
assert first_user_prompt(META) is None, "meta 行剔除"
assert first_user_prompt(ASSISTANT) is None, "assistant 行剔除"

# --- name / token 估算 ---
assert is_target_skill("aihot", "aihot")
assert is_target_skill("superpowers:brainstorming", "brainstorming")
assert not is_target_skill("skill-doctor", "doctor")  # 尾段精确, 非子串

cjk, other = est_tokens("中文内容"), est_tokens("abcdefgh")  # 4/1.1≈3, 8/2.8≈2
assert cjk == 3 and other == 2, f"est_tokens 失准: {cjk},{other}"

# --- frontmatter 多行折叠 ---
FOLD = "---\nname: fold-skill\ndescription: >-\n  第一行内容\n  第二行内容\n---\nbody"
LIT = "---\nname: lit-skill\ndescription: |\n  行A\n  行B\n---\n"
QUOTED = '---\nname: q\ndescription: "单行带引号"\n---\n'
assert parse_frontmatter(FOLD)["description"] == "第一行内容 第二行内容", "折叠块空格连接"
assert parse_frontmatter(LIT)["description"] == "行A\n行B", "字面块保留换行"
assert parse_frontmatter(QUOTED)["description"] == "单行带引号", "引号剥离"

# --- R7 模型可见性: disable-model-invocation / frontmatter 缺失 ---
FM_DISABLE = ('---\nname: d\ndescription: "x"\n'
              'disable-model-invocation: true\n---\n')
assert parse_frontmatter(FM_DISABLE)["disable-model-invocation"] == "true"
BASE = {"name": "x", "description": "a" * 60, "dir": "x"}
assert lint_one(dict(BASE), [])["R7"] == "ok", "默认模型可见"
assert lint_one({**BASE, "model_invocable": False}, [])["R7"] == \
    "disabled_model_invocation", "disable-model-invocation=true 报 R7"
assert lint_one({**BASE, "frontmatter_ok": False}, [])["R7"] == \
    "no_frontmatter", "frontmatter 缺失报 R7"

# --- wilson 置信区间 ---
ci = wilson_ci(0.8, 10)
assert ci and abs(ci[0] - 0.490) < 0.002 and abs(ci[1] - 0.943) < 0.002, ci
assert wilson_ci(0, 0) is None, "n=0 无区间"
assert wilson_ci(1, 8) == [1.0, 1.0] or wilson_ci(1, 8)[0] > 0.6, wilson_ci(1, 8)

# --- 实测注入: effective_input + 差分配对 ---
U_FULL = {"input_tokens": 100, "cache_read_input_tokens": 50,
          "cache_creation_input_tokens": 10}
assert effective_input(U_FULL) == 160
assert effective_input({}) == 0
assert parse_usage('{"message":{"usage":{"input_tokens":100}}}') == \
    {"input_tokens": 100}
assert parse_usage(NOISE_LINE) is None

tr = InputDeltaTracker()
assert tr.note_line(True, {"input_tokens": 100}) is None, "调用行只设基线"
assert tr.note_line(False, {"input_tokens": 260}) == 160, "下一轮差分=注入成本"
assert tr.note_line(False, {"input_tokens": 270}) is None, "pending 已清"
tr2 = InputDeltaTracker()
tr2.note_line(True, {"input_tokens": 100})
assert tr2.note_line(True, {"input_tokens": 120}) is None, "连续调用刷新基线"
assert tr2.note_line(False, {"input_tokens": 300}) == 180
tr3 = InputDeltaTracker()
tr3.note_line(True, None)  # 斜杠直展: 用户行无 usage
assert tr3.note_line(False, {"input_tokens": 200}) is None, "无前值(首轮)跳过"
tr4 = InputDeltaTracker()
tr4.note_line(False, {"input_tokens": 150})
tr4.note_line(True, None)
assert tr4.note_line(False, {"input_tokens": 330}) == 180, "斜杠直展后差分"

# --- 场景聚类 ---
A = ["帮我查今天的AI新闻", "查一下今天的AI新闻有什么", "看看今天的AI新闻动态"]
B = ["extract pdf tables", "extract pdf tables from file", "merge pdf tables"]
clusters = cluster_prompts(A + B)
assert sorted(len(c) for c in clusters) == [3, 3], f"两簇分离失败: {clusters}"
assert scenarios_for(["a", "b"]) is None, "不足 3 条不聚类"
sc = scenarios_for(A + B)
assert sc and sc[0]["count"] >= 3 and len(sc[0]["top_terms"]) >= 1, sc

# --- 竞争重叠率 ---
assert overlap_rate("", "x") == 0.0
hi = overlap_rate("pdf extract tables forms merge", "extract pdf forms tables fill")
assert hi > 0.5, f"高重叠未检出: {hi}"

# --- cases 采样角色判定: 斜杠直展无 NL 语境, 不作正例 ---
assert case_role(["skill-doctor"], [], "skill-doctor") == "pos", "工具触发=正例"
assert case_role(["skill-doctor"], ["skill-doctor"], "skill-doctor") == "pos", "工具+斜杠以工具为准"
assert case_role([], ["skill-doctor"], "skill-doctor") is None, "仅斜杠=跳过"
assert case_role([], ["aihot"], "skill-doctor") == "neg", "路由别处=反例"
assert case_role(["aihot"], [], "skill-doctor") == "neg", "工具路由别处=反例"
assert case_role([], [], "skill-doctor") is None, "空会话=跳过"

print("ALL PASS")
