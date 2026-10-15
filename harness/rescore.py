#!/usr/bin/env python3
"""Recompute python file/LOC counts for finished cases.

The first metric counted only *.py, so qwen3-coder's `ha-api` -- a complete
8.6KB tool with a #!/usr/bin/env python3 shebang and no extension -- scored
0 LOC. Detect by shebang as well as extension. Reads the files already on
disk, so no case needs re-running.
"""
import json, os, sys, glob, ast

# Round 2 lets models install packages, so a work dir can contain a venv,
# pip's own source, caches and build artifacts. Counting those reported 816,923
# LOC for a ~300 line tool. Only count what the model actually authored.
_SKIP_DIRS = {"venv", ".venv", "env", ".env", "site-packages", "__pycache__",
              ".pytest_cache", ".git", "node_modules", "build", "dist",
              ".mypy_cache", ".ruff_cache", ".tox", "lib", "lib64", "bin",
              "include", "share", "wheels"}
def _authored(path, root):
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if any(p in _SKIP_DIRS for p in parts[:-1]):
        return False
    if any(p.endswith(".egg-info") or p.endswith(".dist-info") for p in parts):
        return False
    return not path.endswith((".pyc", ".pyo", ".so", ".whl"))

def is_python(path):
    if path.endswith(".py"):
        return True
    try:
        with open(path, "rb") as fh:
            first = fh.readline(200).decode("utf-8", "replace")
        if first.startswith("#!") and "python" in first:
            return True
    except Exception:
        pass
    return False

def parses(path):
    try:
        ast.parse(open(path, encoding="utf-8", errors="replace").read())
        return True
    except Exception:
        return False

RESULTS_DIR = sys.argv[1] if len(sys.argv) > 1 else "results"
for meta_path in sorted(glob.glob(f"{RESULTS_DIR}/*/meta.json")):
    out = os.path.dirname(meta_path)
    meta = json.load(open(meta_path))
    root = os.path.join(out, "work")
    files = [f for f in glob.glob(os.path.join(root, "**", "*"), recursive=True)
             if os.path.isfile(f) and _authored(f, root)]
    py = [f for f in files if is_python(f)]
    loc = 0
    for f in py:
        try:
            loc += sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except Exception:
            pass
    # duplicate detection: identical sizes across python files is a smell
    sizes = {}
    for f in py:
        sizes.setdefault(os.path.getsize(f), []).append(os.path.basename(f))
    dupes = [v for v in sizes.values() if len(v) > 1]

    meta["files_created"] = len(files)
    meta["py_files"] = len(py)
    meta["py_loc"] = loc
    meta["py_names"] = [os.path.basename(f) for f in py]
    meta["py_syntax_ok"] = sum(1 for f in py if parses(f))
    meta["duplicate_groups"] = dupes
    json.dump(meta, open(meta_path, "w"), indent=2)
    print(f"{meta['case']:<16} files={len(files)} py={len(py)} loc={loc} "
          f"ok={meta['py_syntax_ok']} dupes={dupes if dupes else '-'}")
