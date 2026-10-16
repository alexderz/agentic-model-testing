#!/usr/bin/env python3
"""Offline integrity check for the existing TASKS harness; never runs inference."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shlex


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(root, package):
    candidates = [root / "harness/tools/bench_tasks.py", root / "tools/bench_tasks.py"]
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        raise ValueError("existing bench_tasks.py not found under root")
    raw = source.read_bytes()
    code = raw.decode("utf-8")
    tree = ast.parse(code)
    nodes = [n.value for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "TASKS" for t in n.targets)]
    if len(nodes) != 1:
        raise ValueError("expected exactly one literal TASKS assignment")
    tasks = ast.literal_eval(nodes[0])
    fixtures_raw = (package / "fixtures.json").read_bytes()
    fixtures = json.loads(fixtures_raw)
    manifest = json.loads((package / "fixture-sha256.json").read_bytes())
    if list(tasks) != ["code", "prose", "structured"] or list(fixtures) != list(tasks):
        raise ValueError("category order mismatch")
    rows = []
    for task, prompts in tasks.items():
        if not isinstance(prompts, list) or len(prompts) != 5:
            raise ValueError("expected five prompts per category")
        if fixtures[task] != prompts or not all(isinstance(p, str) for p in prompts):
            raise ValueError("fixture text/order mismatch")
        for index, prompt in enumerate(prompts, 1):
            rows.append({"task": task, "index": index, "sha256": sha(prompt.encode("utf-8"))})
    if len(rows) != 15 or manifest["prompts"] != rows:
        raise ValueError("prompt count/order/hash mismatch")
    if manifest["source_harness_sha256"] != sha(raw):
        raise ValueError("source harness hash mismatch")
    span = ast.get_source_segment(code, nodes[0]).encode("utf-8")
    if manifest["tasks_literal_sha256"] != sha(span):
        raise ValueError("TASKS literal hash mismatch")
    if manifest["fixtures_json_sha256"] != sha(fixtures_raw):
        raise ValueError("JSON hash mismatch")
    relative_patch = Path("engines/tensorfold/patches/0001-sm86-floor-and-fp8-stub.patch")
    patch = root / (Path("harness") / relative_patch if source == candidates[0] else relative_patch)
    if sha(patch.read_bytes()) != manifest["patch_sha256"]:
        raise ValueError("missing public build patch hash mismatch")
    return source.relative_to(root)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    ap.add_argument("--print-command", action="store_true", help="print, never execute, the existing runner command")
    args = ap.parse_args()
    package = Path(__file__).resolve().parent
    try:
        runner = verify(args.root.resolve(), package)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        ap.exit(1, "FAIL: " + str(exc) + chr(10))
    print("PASS: 15 prompts, order/text/hashes, source harness, TASKS literal, JSON and patch")
    if args.print_command:
        print(shlex.join(["python3", runner.as_posix(), "http://127.0.0.1:18080", "bench",
                          "--tasks", "code,prose,structured", "--tokens", "400", "--temperature", "0",
                          "--label", "tf-dflash2-r1", "--output", "tf-dflash2-r1.json"]))


if __name__ == "__main__":
    main()
