#!/usr/bin/env python3
"""Test 8 helpers for run-case-test8.sh (suites/test8/README.md).

  t8_tools.py vision <base-url> <model> <out.json>      does the served model see images? prints 1 or 0, or exit 3
  t8_tools.py prompt <task> <cap-s> <vision> <out.txt>  the agent's prompt: suites/test8/preamble.txt + the task
  t8_tools.py stats <case-dir>                          writes t8-stats.json from events.jsonl and browser.log

vision: two requests with the same question and two 64 x 32 PNGs, A (left half red, right half blue) and B (the same
with the halves swapped), thinking off where the template allows. The answers (not their reasoning) are scored by
vision_verdict(), which vis_smoke.py uses too. A model that does not see the image gets the same prompt
twice, so it gives the same answer twice; a model that sees it names different colours. So the rule compares the two
answers instead of trying to read one free-text answer exactly:
  1 (prints 1): the left-half colours read from A and B are red and blue, in either order, and differ, with no refusal.
  0 (prints 0): a refusal in either answer, a server that says it takes no images, or the same colour read from both.
  anything else exits 3 with nothing printed (no HTTP answer, 408/429/5xx, a 4xx that is not about images, an empty
  answer, no colour, two different colours other than red and blue): run-case-test8.sh retries once, then stops the
  case as a harness failure (rerunnable).
The answers and the verdict are kept in <out.json>. History: before 2026-10-15 "red and no blue anywhere" (called
"Red on the left, blue on the right" blind); 2026-10-15 a one-image left-half parser (Grok review 3); since the swap
probe (Grok review 4), a parser quirk reads both answers the same way, so it no longer decides the verdict, and a
blind guess of "red" is 0 instead of 1. Known, accepted (Grok review 5): the earliest left colour wins ("The left is red.
No, the left is blue." reads as red), and a nondeterministic server could say Red then Blue blind.
"""
import base64
import collections
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS = {"pagoda": ("suites/prompt-test6-pagoda.txt", "page.html"), "orrery": ("suites/prompt-test5-orrery.txt", "orrery.svg")}


def png_red_blue(w=64, h=32, swap=False):
    left, right = (b"\x00\x00\xff", b"\xff\x00\x00") if swap else (b"\xff\x00\x00", b"\x00\x00\xff")
    row = b"\x00" + b"".join(left if x < w // 2 else right for x in range(w))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


COLOURS = ("red", "blue", "green", "yellow", "white", "black", "grey", "gray", "orange", "purple", "pink", "brown",
           "cyan", "magenta", "violet", "teal", "maroon", "navy", "beige")
# a refusal names what it cannot do AND an image-like object: "I don't see a problem" is not one
REFUSAL = re.compile(
    r"\b(?:can ?not|can't|cannot|unable to|not able to|don't|do not|doesn't|does not|am not able to|won't)\s+"
    r"(?:\w+\s+){0,2}?(?:see|view|access|process|display|read|open|interpret|analy[sz]e|perceive|look at)\s+"
    r"(?:\w+\s+){0,2}?(?:images?|pictures?|attachments?|photos?|uploads?)\b"
    r"|\b(?:don't|do not|doesn't|does not)\s+have\s+(?:the\s+)?(?:ability|access|vision|visual|eyes)"
    r"|\bno\s+(?:image|picture|attachment|photo)s?\b"
    r"|\btext[- ](?:only|based)\b"
    r"|\b(?:image|picture)s?\s+(?:is|are|was|were)?\s*not\s+(?:attached|provided|included|visible|shown|available)", re.I)
# an HTTP error body that says the server takes no images (llama.cpp without --mmproj answers 500 "image input is not
# supported - hint: ... mmproj", seen on the tiel pilot cases; vLLM --language-model-only and others similar)
NO_IMAGES = re.compile(r"image input is not supported|\bmmproj\b|not a multimodal model|at most 0 image"
                       r"|(?:does not|doesn't|do not|don't|cannot|can't) (?:support|accept|handle)\s+(?:\w+\s+){0,2}?"
                       r"(?:image|images|image_url|multimodal|multi-modal|vision)\b"
                       r"|\b(?:image|images|image_url|multimodal|multi-modal)\b[^\n]{0,40}\bnot\s+(?:be\s+)?supported",
                       re.I)
_NEG = {"not", "no", "never", "isn't", "aren't", "wasn't", "nor", "neither", "without"}
_AFTER = {"on", "in", "at", "to", "towards", "toward"}          # "red ON THE left"
_AFTER_FILL = _AFTER | {"the", "its", "hand", "side", "half", "part", "portion", "of", "image", "picture", "-"}
_BEFORE_FILL = {"the", "half", "side", "hand", "part", "portion", "of", "image", "picture", "is", "it's", "its", "was",
                "colour", "color", "appears", "looks", "seems", "to", "be", "filled", "fills", "with", "coloured",
                "colored", "shows", "contains", "a", "solid", "bright", "pure", "plain", ":", "-", "in"}
_BREAK = {".", ";", ",", "!", "?", "\n", "and", "but", "while", "whereas", "however", "although", "though", "yet"}


def http_class(status, answer, error=""):
    """'ok' for a 200, 0 for an error that says the server takes no images (NO_IMAGES, any status), None for anything
    else: a 400 from a request field we sent, an echoed image_url, "invalid image", 408, 429 and 5xx are not evidence."""
    if status is None:
        return None
    if status == 200:
        return "ok"
    body = (error or "") + " " + (answer or "")
    if NO_IMAGES.search(body):
        return 0
    return None


def refused(answer):
    return bool(REFUSAL.search(" ".join((answer or "").split()).lower()))


def left_colour(answer):
    """The colour one answer gives for the left half, or None. Colours tied to "left" first, else the colours that are
    neither negated nor tied to "right"; of those, the first in the text. Quirks are fine: vision_verdict reads both
    swap answers with this same function, so a blind model's identical answers read identically."""
    a = " ".join((answer or "").split()).lower()
    if not a:
        return None
    toks = [(m.group(0), m.start()) for m in re.finditer(r"[a-z]+(?:'[a-z]+)?|[.;,!?:\n-]", a)]
    words = [t for t, _ in toks]

    def side_of(i):
        """'left' / 'right' / None: the side word the colour at token i is tied to (same clause, only filler between)."""
        j, fill = i + 1, []
        while j < len(words) and j <= i + 5 and words[j] not in ("left", "right"):
            if words[j] in _BREAK or words[j] not in _AFTER_FILL:
                break
            fill.append(words[j]); j += 1
        else:
            if j < len(words) and words[j] in ("left", "right") and _AFTER & set(fill):
                return words[j]
        j = i - 1
        while j >= 0 and j >= i - 8 and words[j] not in ("left", "right"):
            if words[j] in _BREAK or words[j] not in _BEFORE_FILL:
                return None
            j -= 1
        return words[j] if j >= 0 and j >= i - 8 and words[j] in ("left", "right") else None

    def negated(i):
        j = i - 1
        while j >= 0 and j >= i - 3 and words[j] not in _BREAK:
            if words[j] in _NEG or words[j].endswith("n't"):
                return True
            j -= 1
        return False

    tied_left, free = [], []
    for i, w in enumerate(words):
        if w not in COLOURS or negated(i):
            continue
        s = side_of(i)
        if s == "left":
            tied_left.append((w, toks[i][1]))
        elif s is None:
            free.append((w, toks[i][1]))
    left = tied_left or free
    return min(left, key=lambda wp: wp[1])[0] if left else None


def vision_verdict(a, b):
    """test 8's vision rule (tools/t8_tools.py vision) and vis_smoke.py's: 1 sighted, 0 blind, None unclear.
    a, b: (status, answer, error) for image A (left red) and image B (left blue). status None: no HTTP answer;
    answer: the reply text with <think> blocks removed; error: an HTTP error body."""
    ha, hb = http_class(*a), http_class(*b)
    if 0 in (ha, hb):
        return 0
    if ha is None or hb is None:
        return None
    if refused(a[1]) or refused(b[1]):
        return 0
    ca, cb = left_colour(a[1]), left_colour(b[1])
    if ca is None or cb is None:
        return None
    if ca == cb:
        return 0
    return 1 if {ca, cb} == {"red", "blue"} else None

def text_of(content):
    """message.content as text: a string, or the text parts of a list of content parts."""
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content or ""


def ask(base, model, png, timeout):
    """(status, answer, error, record) for one probe request."""
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {"model": model, "max_tokens": 4000, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "What colour fills the left half of this image? Answer with one word."},
                {"type": "image_url", "image_url": {"url": url}}]}]}
    if model.endswith("-vllm") or "-vllm-" in model:
        body["thinking_token_budget"] = 512
    answer, err, st = "", "", None
    try:
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            msg = json.load(r)["choices"][0]["message"]
        answer = re.sub(r"(?s)<think>.*?</think>", "", text_of(msg.get("content"))).strip()
        st = 200
        rec = dict(status=200, answer=answer[:300])
    except urllib.error.HTTPError as e:
        err = e.read()[:500].decode("utf-8", "replace")
        st = e.code
        rec = dict(status=e.code, error=err)
    except Exception as e:  # noqa: BLE001  (a timeout, a dropped connection, a reply without choices: no verdict)
        err = repr(e)[:500]
        rec = dict(status=None, error=err)
    return st, answer, err, rec


def vision(base, model, out):
    timeout = float(os.environ.get("T8_PROBE_TIMEOUT_S", "900"))
    a = ask(base, model, png_red_blue(), timeout)
    # no HTTP answer to A: do not stack a second request on a server that may still be working on the first
    b = ask(base, model, png_red_blue(swap=True), timeout) if a[0] is not None else (None, "", "not sent", {"status": None, "error": "not sent"})
    rec = {"model": model, "rule": "vision_verdict swap 2026-10-15",
           "status": a[3]["status"], "answer": a[3].get("answer", ""), "error": a[3].get("error", ""),
           "b": b[3], "left_a": left_colour(a[1]) if a[0] == 200 else None,
           "left_b": left_colour(b[1]) if b[0] == 200 else None}
    v = vision_verdict(a[:3], b[:3])
    rec["vision"] = v   # null: unclear
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1)
    if v is None:   # the run must not quietly blind (or sight) a model: the runner retries, then stops the case
        sys.exit(3)
    print(v)

def prompt(task, cap_s, vis, out):
    src, art = TASKS[task]
    pre = open(os.path.join(HERE, "suites/test8/preamble.txt")).read()
    view = open(os.path.join(HERE, f"suites/test8/view-{task}.txt")).read().strip()
    eyes = open(os.path.join(HERE, f"suites/test8/eyes-{'on' if vis == '1' else 'off'}.txt")).read().strip()
    text = (pre.replace("{ARTIFACT}", art).replace("{MINUTES}", str(int(cap_s) // 60))
            .replace("{VIEW}", view).replace("{EYES}", eyes))
    assert not re.search(r"\{[A-Z]+\}", text), "a placeholder is left in the preamble"
    with open(out, "w") as fh:
        fh.write(text.rstrip() + "\n\n" + open(os.path.join(HERE, src)).read().strip() + "\n\n"
                 + f"(In this session the file you leave at /work/{art} is your answer; you need not paste it.)\n")


def stats(d):
    tools, sessions, compactions = collections.Counter(), set(), 0
    for line in open(os.path.join(d, "events.jsonl"), encoding="utf-8", errors="replace"):
        if "compaction_continue" in line:
            compactions += 1
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("sessionID"):
            sessions.add(e["sessionID"])
        p = e.get("part") or {}
        if e.get("type") == "tool_use":
            tools[p.get("tool") or "?"] += 1
    hits = collections.Counter()
    try:
        for line in open(os.path.join(d, "browser.log"), encoding="utf-8", errors="replace"):
            m = re.match(r'preview: "GET (\S+) HTTP/[\d.]+" (\d+)', line)
            if m and "/three/" not in m.group(1):
                hits[f"{m.group(1)} {m.group(2)}"] += 1
    except OSError:
        pass
    browser = {k: v for k, v in tools.items() if k.startswith("browser_")}
    s = {"tool_calls": dict(tools.most_common()), "browser_calls": sum(browser.values()),
         "screenshots": sum(v for k, v in browser.items() if k.endswith("take_screenshot")),
         "task_calls": tools.get("task", 0), "sessions_in_events": len(sessions), "compactions": compactions,
         "preview_requests": dict(hits.most_common(40))}
    with open(os.path.join(d, "t8-stats.json"), "w") as fh:
        json.dump(s, fh, indent=1)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    {"vision": vision, "prompt": prompt, "stats": stats}[cmd](*a)
