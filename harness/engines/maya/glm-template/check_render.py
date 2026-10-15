"""Render GLM-5.3-Flash chat templates the way Maya does and compare them (bakeoff, 2026-10-15).

Run inside Maya's own image, offline, so the Jinja version and settings are Maya's:
  podman run --rm --network none --entrypoint /opt/venv/bin/python3 -v "$PWD:/t:ro,Z" <maya image> \
    -I /t/check_render.py /t/pack-03eb5366.chat_template.jinja /t/chat_template-46a050be.jinja

Part 1 sends OpenAI and Anthropic requests through Maya's converters (openai_to_messages, anthropic_to_messages), as
OpenCode's traffic does, and requires byte-identical prompts. Part 2 renders raw template messages that carry tool-call
ids (Maya's converters drop them), to show what the upstream change does for an engine that keeps them: both templates
must give the same output and the stated tool-result order (call order when the ids pair up, the given order for a
duplicate or unknown id), and for a none content the new output must be the old one minus its single "None" (the
2026-09-04 fix).
Exit 0 when every check passes."""
import copy
import json
import sys

sys.path.insert(0, "/opt/maya")
from serve.frontend import ChatTemplate, anthropic_to_messages, openai_to_messages  # noqa: E402

OLD, NEW = ChatTemplate(sys.argv[1]), ChatTemplate(sys.argv[2])
TOOLS = [{"type": "function", "function": {"name": "read", "description": "Read a file", "parameters": {
             "type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
             "required": ["path"]}}},
         {"type": "function", "function": {"name": "bash", "description": "Run a command", "parameters": {
             "type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]


def call(i, name, args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def tres(i, text):
    return {"role": "tool", "tool_call_id": f"call_{i}", "content": text}


SYS = {"role": "system", "content": "You are a coding agent."}
U = {"role": "user", "content": "Fix the failing test."}
OPENAI = {
    "plain": [SYS, U],
    "one_call": [SYS, U, {"role": "assistant", "content": "", "tool_calls": [call(1, "read", {"path": "a.py"})]},
                 tres(1, "print(1)")],
    "parallel_in_order": [SYS, U, {"role": "assistant", "content": None, "reasoning_content": "Look at three files.",
                                   "tool_calls": [call(1, "read", {"path": "a.py"}),
                                                  call(2, "read", {"path": "b.py", "limit": 5}),
                                                  call(3, "bash", {"command": "pytest -q"})]},
                          tres(1, "A"), tres(2, "B"), tres(3, "3 passed")],
    "parallel_shuffled": [SYS, U, {"role": "assistant", "content": "",
                                   "tool_calls": [call(1, "read", {"path": "a.py"}), call(2, "read", {"path": "b.py"}),
                                                  call(3, "bash", {"command": "ls"})]},
                          tres(3, "ls out"), tres(1, "A"), tres(2, "B"),
                          {"role": "assistant", "content": "Done.", "reasoning_content": "ok"},
                          {"role": "user", "content": "thanks"}],
    "late_system_and_image": [SYS, {"role": "user", "content": [
                                  {"type": "text", "text": "what is this"},
                                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
                              {"role": "system", "content": "hook context"},
                              {"role": "assistant", "content": "A square."}],
}
fails = 0


def check(label, a, b, expect_same=True):
    global fails
    same = a == b
    ok = same == expect_same
    fails += not ok
    print("ok  " if ok else "FAIL", label, "identical" if same else "differs", len(a), len(b))


def both(m, t, kw):
    return OLD.render(copy.deepcopy(m), t, **dict(kw)), NEW.render(copy.deepcopy(m), t, **dict(kw))


# Part 1: through Maya's converters, as OpenCode's requests go
for name, msgs in OPENAI.items():
    for effort in (None, "low", "medium", "high"):
        for tools in (TOOLS, None):
            req = {"messages": copy.deepcopy(msgs), "tools": tools}
            if effort:
                req["reasoning_effort"] = effort
            check(f"openai {name} effort={effort} tools={bool(tools)}", *both(*openai_to_messages(req)))
    req = {"messages": copy.deepcopy(msgs), "tools": TOOLS, "chat_template_kwargs": {"enable_thinking": False}}
    check(f"openai {name} thinking off", *both(*openai_to_messages(req)))
ANTH = {"system": "You are a coding agent.",
        "tools": [{"name": "read", "description": "Read", "input_schema": TOOLS[0]["function"]["parameters"]}],
        "messages": [{"role": "user", "content": "go"},
                     {"role": "assistant", "content": [
                         {"type": "thinking", "thinking": "hm"},
                         {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "a"}},
                         {"type": "tool_use", "id": "t2", "name": "read", "input": {"path": "b"}}]},
                     {"role": "user", "content": [
                         {"type": "tool_result", "tool_use_id": "t2", "content": "B"},
                         {"type": "tool_result", "tool_use_id": "t1", "content": "A"}]}]}
check("anthropic parallel shuffled", *both(*anthropic_to_messages(copy.deepcopy(ANTH))))


# Part 2: raw template messages with ids (not what Maya sends)
def raw(msgs):
    out = []
    for x in copy.deepcopy(msgs):
        if x.get("tool_calls"):
            x["tool_calls"] = [{"id": c["id"], "function": {"name": c["function"]["name"],
                                                            "arguments": json.loads(c["function"]["arguments"])}}
                               for c in x["tool_calls"]]
        out.append(x)
    return out


def expect_order(label, text, results):
    """The tool results must appear in `results` order, each exactly once."""
    global fails
    tags = [f"<tool_response>{r}<" for r in results]
    pos = [text.index(t) if text.count(t) == 1 else -1 for t in tags]
    ok = -1 not in pos and pos == sorted(pos)
    fails += not ok
    print("ok  " if ok else "FAIL", label, "->", " ".join(results), pos)


for name in ("one_call", "parallel_shuffled"):
    check(f"raw-ids {name}", *both(raw(OPENAI[name]), TOOLS, {}))
for t, o in zip(("old", "new"), both(raw(OPENAI["parallel_shuffled"]), TOOLS, {})):
    expect_order(f"raw-ids shuffled, {t} template reorders to call order", o, ("A", "B", "ls out"))
dup = raw(OPENAI["parallel_shuffled"])
dup[4]["tool_call_id"] = "call_3"       # duplicate result id: both must keep the order given
unk = raw(OPENAI["parallel_shuffled"])
unk[4]["tool_call_id"] = "call_9"       # a result without a call: both must keep the order given
for label, msgs in (("duplicate result id", dup), ("unknown result id", unk)):
    a, b = both(msgs, TOOLS, {})
    check(f"raw-ids {label}", a, b)
    for t, o in (("old", a), ("new", b)):
        expect_order(f"raw-ids {label}, {t} template keeps the given order", o, ("ls out", "A", "B"))
# Assistant content None, kept as None: the old template prints the text "None" once, the new one prints nothing
# there, and nothing else differs.
a, b = both(raw(OPENAI["parallel_in_order"]), TOOLS, {})
ok = a.count("None") == 1 and b == a.replace("None", "", 1)
fails += not ok
print("ok  " if ok else "FAIL", "raw-ids none content: new == old without its one \"None\"", len(a), len(b))
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
