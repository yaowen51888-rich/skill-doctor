#!/usr/bin/env python3
"""doctor.py 零框架自测: py test_doctor.py, 全过打印 ALL PASS。

fixture 覆盖三平台 skill 调用事件同构形态(dsh/codex 为文档推断形态,
真机首跑若失败优先怀疑这里)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from doctor import (  # noqa: E402
    est_tokens, extract_skill_calls, is_target_skill, overlap_rate,
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

# --- name / token 估算 ---
assert is_target_skill("aihot", "aihot")
assert is_target_skill("superpowers:brainstorming", "brainstorming")
assert not is_target_skill("skill-doctor", "doctor")  # 尾段精确, 非子串

cjk, other = est_tokens("中文内容"), est_tokens("abcdefgh")  # 4字/1.6≈2, 8/4=2
assert cjk == 2 and other == 2, f"est_tokens 失准: {cjk},{other}"

# --- 竞争重叠率 ---
assert overlap_rate("", "x") == 0.0
hi = overlap_rate("pdf extract tables forms merge", "extract pdf forms tables fill")
assert hi > 0.5, f"高重叠未检出: {hi}"

print("ALL PASS")
