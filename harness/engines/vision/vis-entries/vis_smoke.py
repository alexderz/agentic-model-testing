#!/usr/bin/env python3
"""Helpers for queue-new.d/20-vision-entries.sh: load an entry, ask the vision probe, count what one
screenshot costs.

  vis_smoke.py warm <base-url> <model> <timeout-s>
      load with a tiny text request; prints "secs<TAB>status<TAB>retries<TAB>err". secs is wall time from the first
      request to the answer, so it includes the 30 s sleeps between retries (llama-swap answers 5xx while an
      upstream starts); retries says how many there were.
  vis_smoke.py probe <base-url> <model> <out.json> <timeout-s>
      test 8's swap probe (tools/t8_tools.py png_red_blue: A left half red, B the halves swapped) with test 8's
      question, but max_tokens 1024 (test 8: 4000) and thinking off in the request (vLLM: thinking_token_budget
      256). Prints "verdict<TAB>statusA/statusB<TAB>finishA/finishB<TAB>t8_old_rule<TAB>answerA | answerB": verdict
      is yes / no / unclear,
      from test 8's own rule (tools/t8_tools.py vision_verdict: 1 / 0 / None), the same function test 8 uses since
      2026-10-15; t8_old_rule is what test 8's rule before that ("red and no blue anywhere") says, for comparison
      with the pilot cases. The whole message (content, reasoning excerpt, usage) goes to <out.json>. Exit 3 when no
      HTTP answer came to A or B (timeout, dropped connection): the server may still be working on it.
  vis_smoke.py tokens <base-url> <model> <out.json> <timeout-s>
      one 1280x720 PNG (stdlib zlib/struct) with a short prompt, the same prompt without it, and two DIFFERENT PNGs
      (the second has its red and blue panels swapped, so a cache or dedupe cannot answer for it). max_tokens 1, so
      image_req_s is the image's encode + prefill + one decoded token. Prints "text_pt<TAB>image_pt<TAB>image_tokens
      <TAB>image_req_s<TAB>two_image_status<TAB>two_image_pt<TAB>two_image_tokens<TAB>prompt_tokens_details<TAB>err"
      (prompt_tokens_details: the image request's usage.prompt_tokens_details as compact JSON, or -). Stops at the
      first request that gets no HTTP answer (timeout): the requests after it are not sent (status "not_sent"), the
      fields are still printed, and it exits 3, so the step unloads the server (it may still be prefilling) first.
  vis_smoke.py png <out.png> [swap]                          write the screenshot, for a look

Stdlib only; talks to llama-swap's OpenAI routes (/v1/chat/completions) and nothing else. A model error never makes
it exit non-zero (probe and tokens: only "no answer at all" does, exit 3): the step records it and goes on.
"""
import base64, json, os, re, struct, sys, time, urllib.error, urllib.request, zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from t8_tools import png_red_blue, text_of, vision_verdict  # noqa: E402  (test 8's probe image and its rule)


def verdict(a, b):
    """yes / no / unclear: test 8's rule, tools/t8_tools.py vision_verdict (1 / 0 / None) over the swap pair."""
    return {1: "yes", 0: "no"}.get(vision_verdict(a, b), "unclear")


def t8_old_rule(answer):
    """test 8's rule before 2026-10-15 (red and no blue anywhere; the pilot cases used it), for comparison only."""
    return int(bool(re.search(r"\bred\b", answer, re.I)) and not re.search(r"\bblue\b", answer, re.I))


def png_screenshot(w=1280, h=720, swap=False):
    """A screenshot-like RGB PNG: title bar, sidebar, text-like stripes, two coloured panels (swap: blue, red)."""
    white, bar, side, ink = b"\xf4\xf4\xf4", b"\x2b\x2f\x3a", b"\xdd\xe1\xe8", b"\x40\x40\x48"
    red, blue = b"\xd0\x30\x30", b"\x30\x60\xd0"
    if swap:
        red, blue = blue, red
    rows = []
    for y in range(h):
        if y < 40:
            row = bar * w
        else:
            row = side * 200
            if 80 <= y < 360:
                row += white * 40 + red * 440 + white * 40 + blue * 440 + white * (w - 200 - 960)
            elif 400 <= y < 690 and (y - 400) % 24 < 10:
                n = 300 + ((y * 37) % 600)
                row += white * 40 + ink * n + white * (w - 240 - n)
            else:
                row += white * (w - 200)
        rows.append(b"\x00" + row)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def post(base, body, timeout):
    """(status or None, json or None, error text, seconds)."""
    t0 = time.time()
    try:
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r), "", time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, None, e.read()[:300].decode("utf-8", "replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return None, None, repr(e)[:300], time.time() - t0


def clean(s, n=300):
    return " ".join(str(s).split())[:n]


def dash(v):
    return "-" if v is None or v == "" else str(v)


def is_vllm(model):
    return model.endswith("-vllm") or "-vllm-" in model


def warm(base, model, timeout):
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
    t0, tries = time.time(), 0
    while True:
        st, js, err, _ = post(base, body, max(30, timeout - (time.time() - t0)))
        # llama-swap answers 5xx while the upstream starts (lib.sh warm); retry like it does
        if st in (500, 502, 503) and tries < 10 and time.time() - t0 + 30 < timeout:
            tries += 1; time.sleep(30); continue
        break
    ok = st == 200 and js and js.get("choices")
    print(f"{time.time() - t0:.0f}\t{dash(st)}\t{tries}\t{'' if ok else clean(err or 'no choices')}")


def probe(base, model, out, timeout):
    def one(png, budget):
        url = "data:image/png;base64," + base64.b64encode(png).decode()
        body = {"model": model, "max_tokens": 1024, "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "What colour fills the left half of this image? Answer with one word."},
                    {"type": "image_url", "image_url": {"url": url}}]}]}
        if is_vllm(model):
            body["thinking_token_budget"] = 256
        st, js, err, secs = post(base, body, budget)
        rec = {"status": st, "seconds": round(secs, 1)}
        answer, finish = "", None
        if st == 200 and js:
            ch = (js.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = text_of(msg.get("content"))
            answer = re.sub(r"(?s)<think>.*?</think>", "", content).strip()
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            m = re.search(r"(?s)<think>(.*?)</think>", content)
            if m and not reasoning:
                reasoning = m.group(1)
            finish = ch.get("finish_reason")
            rec.update(answer=answer[:1000], content_raw=content[:2000], reasoning_excerpt=clean(reasoning, 1000),
                       finish_reason=finish, usage=js.get("usage"))
        else:
            rec["error"] = clean(err, 500)
        return (st, answer, err), finish, rec

    t0 = time.time()
    a, fin_a, rec_a = one(png_red_blue(), timeout)
    if a[0] is None:   # no answer: do not stack a second request on a server that may still be working
        b, fin_b, rec_b = (None, "", "not sent"), None, {"status": None, "error": "not sent"}
    else:
        b, fin_b, rec_b = one(png_red_blue(swap=True), max(30, timeout - (time.time() - t0)))
    rec = {"model": model, "max_tokens": 1024, "a_left_red": rec_a, "b_left_blue": rec_b,
           "verdict": verdict(a, b), "t8_old_rule": t8_old_rule(a[1])}
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1)
    st = f"{a[0] or 'no_answer'}/{b[0] or 'no_answer'}"
    ans = f"{a[1] or (f'ERROR {a[2]}' if a[2] else '')} | {b[1] or (f'ERROR {b[2]}' if b[2] else '')}"
    print("\t".join([rec["verdict"], st, f"{dash(fin_a)}/{dash(fin_b)}", str(rec["t8_old_rule"]), dash(clean(ans, 200))]))
    if a[0] is None or b[0] is None:
        sys.exit(3)

def tokens(base, model, out, timeout):
    def img(png):
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}
    text = {"type": "text", "text": "Reply with the single word OK."}
    img1, img2 = img(png_screenshot()), img(png_screenshot(swap=True))

    def body(content):
        b = {"model": model, "max_tokens": 1, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
             "messages": [{"role": "user", "content": content}]}
        return b
    rec, errs = {"model": model, "image": "1280x720 PNG; two_images: it and a red/blue-swapped copy"}, []
    res, hung = {}, None
    for name, content in (("text", [text]), ("image", [text, img1]), ("two_images", [text, img1, img2])):
        if hung:   # the server may still be working on the timed-out request: send nothing more
            res[name] = ("not_sent", None, 0.0, None)
            rec[name] = {"status": "not_sent", "error": f"not sent: {hung} got no answer"}
            continue
        st, js, err, secs = post(base, body(content), timeout)
        usage = (js or {}).get("usage") or {}
        pt = usage.get("prompt_tokens")
        res[name] = (st, pt, secs, usage.get("prompt_tokens_details"))
        rec[name] = {"status": st, "prompt_tokens": pt, "completion_tokens": usage.get("completion_tokens"),
                     "prompt_tokens_details": usage.get("prompt_tokens_details"), "seconds": round(secs, 1),
                     "error": err or None}
        if st is None:
            hung = name
            errs.append(f"{name}: no answer ({clean(err)}); later requests not sent, unload first")
        elif st != 200 or pt is None:
            errs.append(f"{name}: {st} {clean(err) or 'no usage.prompt_tokens'}")
    tp = res["text"][1]
    d = res["image"][1] - tp if res["image"][1] is not None and tp is not None else None
    d2 = res["two_images"][1] - tp if res["two_images"][1] is not None and tp is not None else None
    rec["image_tokens"], rec["two_image_tokens"], rec["hung"] = d, d2, hung
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1)
    det = res["image"][3]
    det = clean(json.dumps(det, separators=(",", ":")), 200) if det else None
    isec = "-" if res["image"][0] in (None, "not_sent") else f"{res['image'][2]:.1f}"
    print("\t".join([dash(tp), dash(res["image"][1]), dash(d), isec, dash(res["two_images"][0]),
                     dash(res["two_images"][1]), dash(d2), dash(det), clean("; ".join(errs))]), flush=True)
    if hung:
        sys.exit(3)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    if cmd == "warm":
        warm(a[0], a[1], float(a[2]))
    elif cmd == "probe":
        probe(a[0], a[1], a[2], float(a[3]))
    elif cmd == "tokens":
        tokens(a[0], a[1], a[2], float(a[3]))
    elif cmd == "png":   # write the test image, for a look
        open(a[0], "wb").write(png_screenshot(swap=len(a) > 1 and a[1] == "swap"))
    else:
        sys.exit(__doc__)
