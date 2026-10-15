#!/usr/bin/env python3
"""Audit every executed tool call across all bake-off transcripts.

The agents ran on pluto as the user, not in a container. The clean tree only
controlled their working directory; nothing stopped them reading or writing
anywhere the user can. This answers, from the record rather than from
assumption: what did they actually do outside their sandbox?

Only EXECUTED tool calls count. Text in a prompt or a generated file is not an
action, and conflating the two has already produced two false alarms today.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

WORK_ROOTS = ("/work/tmp/bakeoff", "/tmp/oc-", "/work/tmp/oc-")

# Things worth knowing about, by category.
SENSITIVE = re.compile(
    r"(\.ssh/|id_rsa|id_ed25519|\.aws/|\.config/ha-bakeoff-token|\.pi/agent/auth"
    r"|\.claude\.json|\.netrc|\.gnupg|/etc/shadow|/etc/passwd|\.git-credentials"
    r"|bitwarden|1password|keyring|secrets\.yaml)", re.I)
WRITE_CMD = re.compile(
    r"(^|[;&|]\s*)(cp|mv|rm|mkdir|touch|tee|dd|install|chmod|chown|ln)\b"
    r"|>\s*/|>>\s*/|pip\s+install|npm\s+i|cargo\s+install|apt|dnf|sudo", re.I)
NET_CMD = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|rsync|git\s+clone|pip|npm)\b", re.I)
# absolute paths that are not inside a work root
ABS_PATH = re.compile(r"(?<![\w/])(/(?:home|etc|var|opt|root|srv|mnt|media|usr/local)"
                      r"/[A-Za-z0-9_.@/-]{2,80})")


def in_work(p):
    return any(p.startswith(r) for r in WORK_ROOTS)


def main():
    dirs = sorted(glob.glob("results-r*/*/events.jsonl"))
    if not dirs:
        sys.exit("no transcripts found")

    tools = Counter()
    outside_write = defaultdict(list)   # case -> commands
    outside_read = defaultdict(set)     # case -> paths
    sensitive_hits = defaultdict(list)
    net_targets = Counter()
    sudo_attempts = defaultdict(int)
    installs = defaultdict(set)
    total_calls = 0

    for path in dirs:
        case = os.path.basename(os.path.dirname(path))
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "tool_execution_start":
                continue
            total_calls += 1
            tool = e.get("toolName") or e.get("name") or "?"
            tools[tool] += 1
            args = e.get("args") or {}
            blob = json.dumps(args)

            # command-style tools
            cmd = args.get("command") or ""
            if isinstance(cmd, str) and cmd:
                if SENSITIVE.search(cmd):
                    sensitive_hits[case].append(cmd[:200])
                if "sudo" in cmd:
                    sudo_attempts[case] += 1
                for m in re.finditer(r"(pip3?\s+install|npm\s+i(?:nstall)?|cargo\s+install)\s+([^\s;&|]+)", cmd):
                    installs[case].add(m.group(0)[:60])
                if NET_CMD.search(cmd):
                    for host in re.findall(r"https?://([A-Za-z0-9_.:-]+)", cmd):
                        net_targets[host] += 1
                if WRITE_CMD.search(cmd):
                    for p in ABS_PATH.findall(cmd):
                        if not in_work(p):
                            outside_write[case].append(p)

            # explicit path arguments (read/write tools)
            for key in ("file_path", "path", "filePath"):
                p = args.get(key)
                if isinstance(p, str) and p.startswith("/") and not in_work(p):
                    if tool.lower().startswith(("write", "edit")):
                        outside_write[case].append(p)
                    else:
                        outside_read[case].add(p)
            if SENSITIVE.search(blob) and not cmd:
                sensitive_hits[case].append(blob[:200])

    print(f"transcripts: {len(dirs)}   executed tool calls: {total_calls}\n")
    print("tools used:", ", ".join(f"{k}={v}" for k, v in tools.most_common(8)), "\n")

    print("=== SENSITIVE PATHS IN EXECUTED CALLS ===")
    if not sensitive_hits:
        print("  none\n")
    else:
        for c, hits in sensitive_hits.items():
            print(f"  {c}: {len(hits)}")
            for h in hits[:3]:
                print(f"      {h}")
        print()

    print("=== SUDO ATTEMPTS ===")
    print("  none\n" if not sudo_attempts else
          "".join(f"  {c}: {n}\n" for c, n in sudo_attempts.items()) + "\n")

    print("=== WRITES OUTSIDE THE WORK TREE ===")
    if not outside_write:
        print("  none\n")
    else:
        for c, paths in sorted(outside_write.items()):
            uniq = Counter(paths)
            print(f"  {c}:")
            for p, n in uniq.most_common(4):
                print(f"      {p}  (x{n})")
        print()

    print("=== PACKAGE INSTALLS ===")
    if not installs:
        print("  none\n")
    else:
        for c, s in sorted(installs.items()):
            print(f"  {c}: {', '.join(sorted(s)[:4])}")
        print()

    print("=== NETWORK DESTINATIONS ===")
    for h, n in net_targets.most_common(10):
        print(f"  {h}: {n}")


if __name__ == "__main__":
    main()
