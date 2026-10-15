"""Test 8 preview server, inside the sealed browser container (no network): http://127.0.0.1:8000/

Shows the agent's files the way the grader renders them, and nothing else:
  /<name>.html        the page with its three.js URLs pointed at the local three 0.186.1 (tools/three_rewrite.py,
                      the same code tools/render_html.sh uses)
  /<name>.svg         the SVG file itself
  /view/<name>.svg    the SVG as the grader shows it (tools/render_svg.sh): the fitted file on its own in an
                      iframe sandboxed without scripts, filling the window, so scripts in the SVG do not run and
                      SMIL and CSS animation do (the grader also seeks the clock; here it simply runs)
  /fit/<name>.svg     the SVG after tools/svg_fit.py, the copy the grader's frame loads
  .../three/build/... and .../three/examples/jsm/...   the local three.js copy
Any other file gets 404: the grader receives only the one file. The agent's shell reaches this server too (browser-entry.sh offers it on /sock/preview.sock,
preview-bridge.py puts it on the agent's 127.0.0.1:8000). The site folder is the agent's /work, mounted
read-only; paths that leave it (.., symlinks) are refused.
  python3 -I preview.py <site> <three-package> [port]
"""
import html
import os
import stat
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from three_rewrite import rewrite  # noqa: E402

SITE, THREE = os.path.realpath(sys.argv[1]), os.path.realpath(sys.argv[2])
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".wasm": "application/wasm",
         ".png": "image/png", ".jpg": "image/jpeg", ".hdr": "application/octet-stream", ".glb": "model/gltf-binary"}
# render_svg.sh's wrapper (without its clock seek), pointed at the fitted copy
SVG_VIEW = ('<!doctype html><html><body style="margin:0;background:#888;overflow:hidden">'
            '<iframe sandbox="allow-same-origin" src="{src}" '
            'style="display:block;border:0;width:100vw;height:100vh"></iframe></body></html>')
SVG_FIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "svg_fit.py")
FIT_LOCK = threading.BoundedSemaphore(2)   # the agent's shell can reach /fit too: do not let it starve the browser
NOT_SERVED = ("Not served. The preview shows only .html and .svg files from /work, and three.js from the local copy: "
              "the grader gets only your one file, so other files would not load there either.\n")


def inside(root, rel):
    """The real path of rel under root, or None when it leaves root or is missing."""
    p = os.path.realpath(os.path.join(root, rel))
    return p if (p == root or p.startswith(root + os.sep)) and os.path.isfile(p) else None


def read_site(rel):
    """The bytes of the regular file rel in /work, or None. The file itself must not be a symlink (the grader skips
    those too), and the opened file is checked to be inside /work, so a link swapped in after inside() changes nothing.
    Over 64 MB is not served at all, like the grader, which takes no file over 32 MB."""
    try:
        fd = os.open(os.path.join(SITE, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 64 << 20:
            return None
        if not os.readlink(f"/proc/self/fd/{fd}").startswith(SITE + os.sep):
            return None
        return fh.read(64 << 20)


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("preview: " + (fmt % a) + "\n")

    def send(self, code, body, ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        parts = [p for p in path.split("/") if p]
        if ".." in parts:
            return self.send(404, NOT_SERVED)
        rel = "/".join(parts)
        if not parts:
            return self.index()
        if "three" in parts:   # .../three/build/... or .../three/examples/...
            i = len(parts) - 1 - parts[::-1].index("three")
            sub = parts[i + 1:]
            p = inside(THREE, "/".join(sub)) if sub and sub[0] in ("build", "examples") else None
            if p:
                return self.send(200, open(p, "rb").read(), TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))
            return self.send(404, "three.js 0.186.1 has no such file: /" + rel + "\n")
        if parts[0] == "view" and rel.endswith(".svg"):
            target = "/".join(parts[1:])
            if not inside(SITE, target):
                return self.send(404, "no such SVG in /work: " + target + "\n")
            return self.send(200, SVG_VIEW.format(src=html.escape("/fit/" + urllib.parse.quote(target))), "text/html; charset=utf-8")
        if parts[0] == "fit" and rel.endswith(".svg"):
            target = "/".join(parts[1:])
            data = read_site(target) if inside(SITE, target) else None
            if data is None:
                return self.send(404, "no such SVG in /work: " + target + "\n")
            # stdin to stdout, no temp files: the pilot orrery's /fit failed for good after 16 minutes and the reason
            # was not recorded (suspects: the 1 GB /tmp tmpfs, which Chromium's shared memory (--disable-dev-shm-usage)
            # and Playwright's outputDir also use, and the container's 3 GB memory cap, which tmpfs pages count
            # against). A subprocess, not an import, so a regex that runs long cannot hold the server; failures now go
            # to browser.log with exit code, stderr, /tmp free space and the cgroup's oom counters at that moment.
            with FIT_LOCK:
                try:
                    r = subprocess.run([sys.executable, "-I", SVG_FIT, "-", "-"], input=data,
                                       capture_output=True, timeout=60)
                except subprocess.TimeoutExpired:
                    return self.fit_fail(target, "svg_fit took over 60 s")
                except OSError as e:
                    return self.fit_fail(target, "svg_fit did not start: %s" % e)
            if r.returncode != 0 or len(r.stdout) > 64 << 20:   # an empty file fits to an empty file, as before
                err = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
                return self.fit_fail(target, "svg_fit failed: exit %d, %d bytes out%s" % (
                    r.returncode, len(r.stdout), (", " + err[-1][:300]) if err else ""))
            return self.send(200, r.stdout, "image/svg+xml")
        p = inside(SITE, rel)
        data = read_site(rel) if p and rel.endswith((".html", ".svg")) else None
        if data is not None and rel.endswith(".html"):
            page, _ = rewrite(data.decode("utf-8", errors="replace"))
            return self.send(200, page, "text/html; charset=utf-8")
        if data is not None:
            return self.send(200, data, "image/svg+xml")
        return self.send(404, NOT_SERVED if p else "no such file in /work: " + rel + "\n")

    def fit_fail(self, target, why):
        try:
            v = os.statvfs("/tmp")
            room = "/tmp free %d KiB" % (v.f_bavail * v.f_frsize // 1024)
        except OSError as e:
            room = "/tmp statvfs: %s" % e
        try:
            ev = " ".join(l.strip() for l in open("/sys/fs/cgroup/memory.events") if l.startswith(("oom ", "oom_kill ")))
        except OSError:
            ev = "memory.events unreadable"
        sys.stderr.write("preview: /fit/%s: %s [%s; %s]\n" % (target, why, room, ev))
        return self.send(500, why + "\n")

    def index(self):
        rows = []
        for d, _, files in os.walk(SITE):
            for f in sorted(files):
                r = os.path.relpath(os.path.join(d, f), SITE)
                if r.endswith(".html"):
                    rows.append(f'<li><a href="/{html.escape(r)}">{html.escape(r)}</a></li>')
                elif r.endswith(".svg"):
                    rows.append(f'<li><a href="/view/{html.escape(r)}">{html.escape(r)}</a> (as the grader shows it) '
                                f'<a href="/{html.escape(r)}">raw</a></li>')
        self.send(200, "<!doctype html><title>/work</title><ul>" + "".join(rows) + "</ul>", "text/html; charset=utf-8")


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
