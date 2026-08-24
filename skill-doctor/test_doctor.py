#!/usr/bin/env python3
"""doctor.py 零框架自测: py test_doctor.py, 全过打印 ALL PASS。

fixture 覆盖三平台 skill 调用事件同构形态(dsh/codex 为文档推断形态,
真机首跑若失败优先怀疑这里)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from doctor import (  # noqa: E402
    case_role, collect_session_ids, est_tokens, extract_skill_calls,
    extract_slash_commands, first_user_prompt, is_target_skill,
    overlap_rate, parse_frontmatter,
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
