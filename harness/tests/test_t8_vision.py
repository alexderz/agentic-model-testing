#!/usr/bin/env python3
"""Test 8's vision rule (tools/t8_tools.py vision_verdict, swap probe 2026-10-15) and the probes' exit codes, test 8's
(t8_tools.py vision) and vis_smoke.py's. Offline: the probes talk to a mock on 127.0.0.1. Run by tests/test_test8.sh;
every line must be PASS.

  tests/test_t8_vision.py                       the unit tests; exit status = number of failures
  tests/test_t8_vision.py --serve <port-file>   the probe mock for tests/test_test8.sh (writes its port, runs until
                                                killed): /unclear/v1 always answers "", /retry/v1 answers "" to the
                                                first probe (two requests), then sighted: "Red on the left, blue on
                                                the right." to image A and "Blue on the left, red on the right." to B.
"""
import base64, collections, json, os, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from t8_tools import png_red_blue, vision_verdict  # noqa: E402

NO_MMPROJ = ('{"error":{"code":500,"message":"image input is not supported - hint: if this is unexpected, you may need '
             'to provide the mmproj","type":"server_error"}}')   # llama.cpp without --mmproj (the tiel pilot cases)


def ok(answer):
    return (200, answer, "")


def err(status, body):
    return (status, "", body)


CASES = [   # (reply to A = left red, reply to B = left blue, expected: 1 sighted / 0 blind / None unclear)
    # sighted: the colour named follows the image
    (ok("Red on the left, blue on the right"), ok("Blue on the left, red on the right"), 1),
    (ok("blue on the right, red on the left"), ok("red on the right, blue on the left"), 1),
    (ok("Red"), ok("Blue"), 1), (ok("**Red**"), ok("blue."), 1), (ok("  RED\n"), ok("BLUE"), 1),
    (ok("Not blue, it is red"), ok("Not red, it is blue"), 1),
    (ok("I don't see a problem, the left is red"), ok("I don't see a problem, the left is blue"), 1),
    (ok("The left half of the image is filled with red."), ok("The left half of the image is filled with blue."), 1),
    (ok("Left: red. Right: blue."), ok("Left: blue. Right: red."), 1),
    (ok("I can't see it clearly, but the left is red"), ok("The left is blue"), 1),   # "it" is no refusal
    (ok("Blue"), ok("Red"), 1),   # mirrored, but it follows the image: sighted
    (ok("I can't see the visual boundary well, the left is red"), ok("The left is blue"), 1),   # "visual" is no image
    # Grok review 4's blockers: the per-answer parser is wrong, but it reads both answers the same way
    (ok("red left blue right"), ok("blue left red right"), 1),
    (ok("red (left) blue (right)"), ok("blue (left) red (right)"), 1),
    (ok("the left is red and blue"), ok("the left is red and blue"), 0),
    (ok("the left is red or blue"), ok("the left is red or blue"), 0),
    (ok("Red. I cannot view images."), ok("Red. I cannot view images."), 0),
    # blind: the same colour for opposite images (a guess), or a refusal or no-image error on either side
    (ok("Red"), ok("Red"), 0), (ok("blue"), ok("blue"), 0), (ok("Green"), ok("Green"), 0),
    (ok("Red on the left, blue on the right"), ok("Red on the left, blue on the right"), 0),
    (ok("red or blue"), ok("red or blue"), 0),
    (ok("I can't see images"), ok("I can't see images"), 0),
    (ok("I cannot see the image, but it is probably red"), ok("Blue"), 0),
    (ok("Red"), ok("I'm sorry, I can't view images. Red is a guess."), 0),
    (ok("There is no image attached."), ok("There is no image attached."), 0),
    (ok("As a text-only model I cannot tell."), ok("Blue"), 0),
    (err(500, NO_MMPROJ), err(500, NO_MMPROJ), 0),
    (ok("Red"), err(500, NO_MMPROJ), 0),
    (err(400, "At most 0 image(s) may be provided in one prompt."), ok("Blue"), 0),
    (err(400, '{"error":"image_url is not supported by this model"}'), ok("Blue"), 0),
    (err(400, '{"error":"model does not support vision"}'), ok("Blue"), 0),
    # unclear: no evidence either way
    (err(400, '{"error":"bad request"}'), ok("Blue"), None),   # a 4xx not about images is not evidence
    (err(400, '{"error":"invalid image_url: could not decode"}'), ok("Blue"), None),   # about the image, not "no images"
    (err(400, '{"error":"unknown field chat_template_kwargs"}'), ok("Blue"), None),
    (err(408, "request timeout while decoding image"), ok("Blue"), None),
    (err(429, "too many requests"), ok("Blue"), None),
    (err(502, "upstream died"), ok("Blue"), None),
    (err(503, "loading model"), err(503, "loading model"), None),
    (err(500, "CUDA error: out of memory in the vision encoder"), ok("Blue"), None),
    ((None, "", "TimeoutError('timed out')"), (None, "", "not sent"), None),
    (ok("Red"), (None, "", "TimeoutError('timed out')"), None),
    (ok(""), ok(""), None), (ok("Red"), ok(""), None),
    (ok("Crimson"), ok("Blue"), None),
    (ok("Green"), ok("Blue"), None),   # different, but not red and blue
    (ok("The image has two halves."), ok("The image has two halves."), None),
]

URL_A = "data:image/png;base64," + base64.b64encode(png_red_blue()).decode()
URL_B = "data:image/png;base64," + base64.b64encode(png_red_blue(swap=True)).decode()
SIGHTED = {"A": "Red on the left, blue on the right.", "B": "Blue on the left, red on the right."}


class Mock(BaseHTTPRequestHandler):
    """POST <base>/chat/completions; <base> picks the behaviour (see the module doc and the probe tests below). The
    image sent decides the sighted answers: A (left red) or B (left blue)."""
    seen = collections.Counter()

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        urls = [c.get("image_url", {}).get("url") for m in body.get("messages", []) if isinstance(m.get("content"), list)
                for c in m["content"] if c.get("type") == "image_url"]
        img = "A" if urls == [URL_A] else "B" if urls == [URL_B] else "?"
        mode = self.path.split("/")[1]
        Mock.seen[mode] += 1
        n = Mock.seen[mode]
        if mode == "hang":
            time.sleep(5)
        if mode == "nommproj":
            return self.reply(500, NO_MMPROJ)
        if mode == "crash":
            return self.reply(502, "upstream died")
        if img == "?":
            return self.reply(400, '{"error":"mock: unknown image"}')
        ans = {"sighted": SIGHTED[img], "parts": "", "mirror": SIGHTED["B" if img == "A" else "A"],
               "blind": "I can't see images.", "guess": "Red", "unclear": "",
               "retry": "" if n <= 2 else SIGHTED[img], "hang": "Red"}[mode]
        content = "<think>blue?</think>" + ans
        if mode == "parts":
            content = [{"type": "text", "text": "<think>blue?</think>"}, {"type": "text", "text": SIGHTED[img]}]
        self.reply(200, json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}))

    def reply(self, code, body):
        d = body.encode()
        try:
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(port_file):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    with open(port_file + ".tmp", "w") as fh:
        fh.write(str(srv.server_address[1]))
    os.replace(port_file + ".tmp", port_file)
    srv.serve_forever()


def main():
    fails = 0

    def check(good, what):
        nonlocal fails
        print(("PASS  " if good else "FAIL  ") + what)
        fails += (not good)

    def short(r):
        return f"{r[0]} {(r[1] or r[2])[:28]!r}"

    print("--- vision_verdict (tools/t8_tools.py, test 8 and vis_smoke.py): replies to A (left red) and B (left blue)")
    for a, b, want in CASES:
        got = vision_verdict(a, b)
        check(got == want, f"verdict {short(a)} | {short(b)} -> {got} (want {want})")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    tools = os.path.join(HERE, "tools", "t8_tools.py")
    smoke = os.path.join(HERE, "engines", "vision", "vis-entries", "vis_smoke.py")
    modes = (("sighted", "1", 0), ("parts", "1", 0), ("mirror", "1", 0), ("blind", "0", 0), ("guess", "0", 0), ("nommproj", "0", 0),
             ("unclear", "", 3), ("crash", "", 3), ("hang", "", 3))
    with tempfile.TemporaryDirectory() as d:
        print("--- t8_tools.py vision: output and exit code")
        for mode, out_want, rc_want in modes:
            Mock.seen.clear()
            js = os.path.join(d, mode + ".json")
            r = subprocess.run([sys.executable, "-I", tools, "vision", f"http://127.0.0.1:{port}/{mode}/v1", "m", js],
                               capture_output=True, text=True, env={**os.environ, "T8_PROBE_TIMEOUT_S": "1"},
                               stdin=subprocess.DEVNULL)
            rec = json.load(open(js)) if os.path.exists(js) else {}
            want_v = {"1": 1, "0": 0}.get(out_want)
            check(r.returncode == rc_want and r.stdout.strip() == out_want and rec.get("vision") == want_v,
                  f"probe {mode}: prints {r.stdout.strip()!r}, exit {r.returncode}, json vision {rec.get('vision')}"
                  f" (want {out_want!r}, exit {rc_want})")
            if mode == "sighted":
                check(rec.get("answer", "").startswith("Red on the left") and
                      rec.get("b", {}).get("answer", "").startswith("Blue on the left") and
                      (rec.get("left_a"), rec.get("left_b")) == ("red", "blue"),
                      f"probe sighted: json keeps both answers and colours ({rec.get('left_a')}, {rec.get('left_b')})")
            if mode == "hang":
                time.sleep(4.5)   # let the mock's sleeping handler finish counting
                check(Mock.seen["hang"] == 1, f"probe hang: B not sent after A got no answer ({Mock.seen['hang']} sent)")
        js = os.path.join(d, "refused.json")
        r = subprocess.run([sys.executable, "-I", tools, "vision", "http://127.0.0.1:9/v1", "m", js],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        check(r.returncode == 3 and r.stdout.strip() == "", f"probe, connection refused: exit {r.returncode} (want 3)")

        print("--- vis_smoke.py probe: verdict column and exit code")
        for mode, out_want, rc_want in modes:
            js = os.path.join(d, "smoke-" + mode + ".json")
            r = subprocess.run([sys.executable, "-I", smoke, "probe", f"http://127.0.0.1:{port}/{mode}/v1", "m", js,
                                "1"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            f = r.stdout.rstrip("\n").split("\t")
            v = f[0].strip()
            # vis_smoke exits 3 only when A or B got no HTTP answer; an unclear 200 or 5xx prints "unclear", exit 0
            want_word = {"1": "yes", "0": "no"}.get(out_want, "unclear")
            want_rc = 3 if mode == "hang" else 0
            want_st = {"nommproj": "500/500", "crash": "502/502", "hang": "no_answer/no_answer"}.get(mode, "200/200")
            check(r.returncode == want_rc and v == want_word and len(f) == 5 and f[1] == want_st,
                  f"vis_smoke probe {mode}: {v!r}, {len(f)} fields, status {f[1] if len(f) > 1 else None}, exit "
                  f"{r.returncode} (want {want_word!r}, 5 fields, {want_st}, exit {want_rc})")
    srv.shutdown()
    print(f"vision rule: {fails} failed" if fails else "vision rule: all pass")
    return fails


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        serve(sys.argv[2])
    else:
        sys.exit(min(main(), 100))
