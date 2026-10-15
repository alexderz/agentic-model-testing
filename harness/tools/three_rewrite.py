"""Point the three.js URLs of a model-written page at the local copy of three 0.186.1 (./three/...).

Shared by tools/render_html.sh (the frames that are graded, tests 6 and 8) and the test 8 preview server
(sandbox/t8/preview.py), so the agent's browser shows a page the way the grader renders it.
  python3 -I tools/three_rewrite.py <page.html> <out.html> <rewrites.txt>
Covers any CDN path into build/, examples/jsm/ or addons/, and a bare package URL such as https://esm.sh/three@0.186.1
(to the module build). A page with a module script and no import map gets one for "three" and "three/addons/".
"""
import re
import sys

PAT = re.compile(r"""(?:https?:)?//[^\s"'`()]*?three(?:\.js)?(?:@[\w.\-]+)?/(?P<path>(?:build|examples/jsm|addons)/[^\s"'`()]*)""")
BARE = re.compile(r"""(?:https?:)?//[^\s"'`()]*?/three(?:@[\w.\-]+)?/?(?=["'`])""")
URL = re.compile(r"""(?:https?:)?//[^\s"'`()<>]+""")


def rewrite(s):
    """Return (rewritten page, list of the rewrites made)."""
    seen = []

    def sub(m):
        path = m.group("path")
        path = "examples/jsm/" + path[len("addons/"):] if path.startswith("addons/") else path
        seen.append(f"{m.group(0)} -> ./three/{path}")
        return "./three/" + path
    s = PAT.sub(sub, s)

    def bare(m):
        seen.append(f"{m.group(0)} -> ./three/build/three.module.js")
        return "./three/build/three.module.js"
    s = BARE.sub(bare, s)
    # a bare "three/addons/..." import-map target or specifier left as is resolves through the page's own import map.
    # The vendored addons import the bare specifier "three"; a page that loads them by URL without an import map gets one.
    if not re.search(r"type\s*=\s*[\"']importmap", s, re.I):
        m = re.search(r"<script\b[^>]*type\s*=\s*[\"']module", s, re.I)
        if m:
            s = (s[:m.start()] + '<script type="importmap">{"imports":{"three":"./three/build/three.module.js",'
                 '"three/addons/":"./three/examples/jsm/"}}</script>\n' + s[m.start():])
            seen.append("(no import map in the page: one added for three and three/addons/)")
    return s, seen


def others(s):
    """URLs left in the rewritten page; in the sealed renderer they load nothing."""
    return sorted(set(URL.findall(s)))


if __name__ == "__main__":
    src, dst, log = sys.argv[1:4]
    s, seen = rewrite(open(src, encoding="utf-8", errors="replace").read())
    open(dst, "w").write(s)
    open(log, "w").write("\n".join(seen) + "\n-- other URLs left in the page (they load nothing):\n" + "\n".join(others(s)) + "\n")
