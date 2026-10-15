#!/usr/bin/env python3
"""Derive evalbox's seccomp profile from the host's current podman default (so host updates to the
default carry over) and remove what hostile code in a container could use against the kernel:

  - new namespaces: unshare, setns, clone3 (ENOSYS so libc falls back to clone), and clone with
    any CLONE_NEW* flag. Unprivileged user namespaces are the usual first step of a container
    escape (they hand out full capabilities over a fresh namespace).
  - mount APIs: mount, umount2, pivot_root, fsopen, fsmount, fspick, move_mount, open_tree,
    mount_setattr.
  - cross-process access: ptrace, process_vm_readv, process_vm_writev, kcmp.
  - kernel keyrings: keyctl, add_key, request_key. File handles: name_to_handle_at,
    open_by_handle_at. syslog.
  io_uring, bpf, perf_event_open, userfaultfd are already denied by the default.

  python3 make-seccomp.py [SRC] OUT      (SRC default /usr/share/containers/seccomp.json)
"""
import json, sys

DENY = {"unshare", "setns", "mount", "umount", "umount2", "pivot_root", "fsopen", "fsmount", "fspick",
        "move_mount", "open_tree", "mount_setattr", "ptrace", "process_vm_readv", "process_vm_writev",
        "kcmp", "keyctl", "add_key", "request_key", "name_to_handle_at", "open_by_handle_at", "syslog",
        "clone", "clone3"}
CLONE_NEW = 0x7E020080   # NEWNS|NEWCGROUP|NEWUTS|NEWIPC|NEWUSER|NEWPID|NEWNET|NEWTIME (Grok review 2026-10-07)

a = sys.argv[1:]
src, out = (a[0], a[1]) if len(a) == 2 else ("/usr/share/containers/seccomp.json", a[0])
d = json.load(open(src))
rules = []
for s in d["syscalls"]:
    names = [n for n in s["names"] if n not in DENY]
    if names: rules.append(dict(s, names=names))
rules.append({"names": ["clone"], "action": "SCMP_ACT_ALLOW",
              "args": [{"index": 0, "value": CLONE_NEW, "valueTwo": 0, "op": "SCMP_CMP_MASKED_EQ"}],
              "comment": "evalbox: clone only without namespace flags"})
rules.append({"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38,
              "comment": "evalbox: ENOSYS so libc falls back to the filtered clone"})
d["syscalls"] = rules
json.dump(d, open(out, "w"), indent=1)
print(f"{out}: {len(rules)} rules, removed {sorted(DENY)}")
