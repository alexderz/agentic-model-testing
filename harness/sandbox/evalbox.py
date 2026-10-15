#!/usr/bin/env python3
"""Run the locked-down eval sandbox declared in compose.yaml (README.md explains the design).

  evalbox.py check [NAME]                         validate compose.yaml, print what each container can reach
  evalbox.py preflight                            update and vulnerability checks only (preflight.py)
  evalbox.py up NAME [--seed DIR] [--accept-risk "why"]
                                                  preflight, create, firewall, start; DIR is copied into the client's /work
  evalbox.py collect NAME DEST                    copy the client's /work and the proxy logs out to DEST (new or empty dir)
  evalbox.py down NAME                            remove containers and networks
  evalbox.py -f other.yaml ...                    another compose file, same rules

Required for up and check: ALLOW_MODELS (comma-separated model ids the inference proxy lets through).
Optional: TITAN (host:port), EXTRA_DOMAINS (comma-separated, added to the web allowlist),
EVALBOX_USERNS_SIZE (user ids per container, default 8192), EVALBOX_MAX_IMAGE_DAYS (default 7).

Why not `docker compose up`: compose cannot run a host step between creating a container and
starting it, and the firewall must be in place before the first process runs. So this reads the
compose file, renders the proxies' config files, creates everything with podman, installs each
service's x-firewall from the host into the container's network namespace (no container has
CAP_NET_ADMIN), then starts in depends_on order. It refuses a compose file that weakens the lockdown
(lock_violations()) and refuses to start when the preflight finds pending updates or vulnerable
images, unless --accept-risk gives a reason (recorded with the run).
"""
import ipaddress, json, os, re, shlex, subprocess, sys, tarfile, time
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.expanduser("~"), ".local", "share", "evalbox")
PRIVATE = ("0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, "
           "192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/3")
FORBIDDEN_KEYS = ("cap_add", "privileged", "network_mode", "pid", "ipc", "userns_mode", "devices",
                  "device_cgroup_rules", "sysctls", "cgroup_parent", "extra_hosts", "ports", "volumes_from",
                  "runtime", "group_add", "shm_size", "stdin_open", "tty", "gpus", "deploy", "configs", "secrets")
USERNS_SIZE = os.environ.get("EVALBOX_USERNS_SIZE", "8192")
MODEL_ID = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def sh(*a, check=True, inp=None):
    r = subprocess.run(a, input=inp, text=True, capture_output=True)
    if check and r.returncode:
        sys.exit(f"failed: {' '.join(a)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def interpolate(obj, env):
    if isinstance(obj, str):
        def rep(m):
            v = env.get(m.group(1))
            return v if v not in (None, "") else (m.group(3) if m.group(3) is not None else "")
        return re.sub(r"\$\{(\w+)(:-([^}]*))?\}", rep, obj)
    if isinstance(obj, list): return [interpolate(x, env) for x in obj]
    if isinstance(obj, dict): return {k: interpolate(v, env) for k, v in obj.items()}
    return obj


def paths(name):
    run = os.path.join(STATE, "runs", name)
    return run, os.path.join(run, "logs"), os.path.join(run, "conf")


def load(path, name):
    run, logdir, conf = paths(name)
    titan = os.environ.get("TITAN", "192.0.2.62:8080")
    env = dict(os.environ, NAME=name, LOGDIR=logdir, CONF=conf, SECCOMP=os.path.join(STATE, "seccomp-evalbox.json"),
               TITAN_IP=titan.rsplit(":", 1)[0], TITAN_PORT=titan.rsplit(":", 1)[1])
    raw = yaml.safe_load(open(path))
    c = interpolate({k: v for k, v in raw.items() if not k.startswith("x-")}, env)
    c["x-web-allow"] = list(raw.get("x-web-allow") or []) + [d for d in os.environ.get("EXTRA_DOMAINS", "").split(",") if d.strip()]
    c["x-env"] = env
    return c


def models():
    return [m.strip() for m in os.environ.get("ALLOW_MODELS", "").split(",") if m.strip()]


def lock_violations(c):
    """The lockdown invariants (README lock 8). Any hit refuses to start."""
    bad, nets = [], c.get("networks") or {}
    run, logdir, conf = paths(c["x-env"]["NAME"])
    for s, d in c["services"].items():
        trusted = d.get("x-trusted") is True
        # Reach (a route out, outside rules, config/log binds) is for the proxies only. A trusted
        # service that is not a proxy (the db) is held to exactly the untrusted locks.
        proxy = trusted and d.get("x-role") == "proxy"
        if d.get("x-role") not in (None, "proxy"): bad.append(f"{s}: x-role must be proxy or absent")
        if d.get("x-role") == "proxy" and not trusted: bad.append(f"{s}: x-role proxy needs x-trusted: true")
        for k in FORBIDDEN_KEYS:
            if k in d: bad.append(f"{s}: `{k}` is not allowed")
        if "ALL" not in (d.get("cap_drop") or []): bad.append(f"{s}: needs cap_drop: [ALL]")
        if d.get("read_only") is not True: bad.append(f"{s}: needs read_only: true")
        so = [str(o) for o in d.get("security_opt") or []]
        if "no-new-privileges" not in so: bad.append(f"{s}: needs security_opt no-new-privileges")
        if f"seccomp={c['x-env']['SECCOMP']}" not in so:
            bad.append(f"{s}: needs security_opt seccomp=${{SECCOMP}} (the generated strict profile)")
        for o in so:
            if o not in ("no-new-privileges", f"seccomp={c['x-env']['SECCOMP']}"): bad.append(f"{s}: security_opt {o} is not allowed")
        if sum(o.startswith("seccomp=") for o in so) != 1: bad.append(f"{s}: exactly one seccomp= option (a later one would win)")
        for k in ("mem_limit", "cpus", "pids_limit"):
            if not d.get(k): bad.append(f"{s}: needs {k}")
        for t in d.get("tmpfs") or []:
            if "size=" not in t: bad.append(f"{s}: tmpfs {t.split(':')[0]} needs a size= limit")
        if "x-firewall" not in d: bad.append(f"{s}: needs an x-firewall block (default drop)")
        if not d.get("networks"): bad.append(f"{s}: must list its networks (no default network)")
        for n in d.get("networks") or {}:
            if n not in nets: bad.append(f"{s}: network {n} is not declared")
        routed = [n for n in d.get("networks") or {} if not (nets.get(n) or {}).get("internal")]
        fw = d.get("x-firewall") or {}
        outside = [r for r in fw.get("out") or [] if r.get("internet") or "host" in r]
        for r in fw.get("out") or []:
            if r.get("internet") and not (isinstance(r.get("ports"), list) and r["ports"]
                                          and all(str(p).isdigit() for p in r["ports"])):
                bad.append(f"{s}: an internet rule needs a ports list (the kernel allows only those TCP ports)")
        if not proxy and (routed or outside):
            bad.append(f"{s}: only the proxies may have a routed network or an outside destination "
                       f"(routed={routed}); reach the outside through a trusted proxy")
        if routed and not outside: bad.append(f"{s}: on routed network(s) {routed} but allows nothing outside")
        if outside and not routed: bad.append(f"{s}: allows outside destinations but has no routed network")
        for v in d.get("volumes") or []:
            parts = v.split(":"); src, opts = parts[0], (parts[2] if len(parts) > 2 else "")
            if not src.startswith("/"): bad.append(f"{s}: volume {src}: only ${{CONF}} and ${{LOGDIR}} binds; use tmpfs"); continue
            p = os.path.realpath(src)
            if not proxy: bad.append(f"{s}: only the proxies get host mounts ({src}); use --seed / collect")
            elif p.startswith(os.path.realpath(conf) + "/"):
                if "ro" not in opts.split(","): bad.append(f"{s}: {src} must be mounted read-only")
            elif not (p == os.path.realpath(logdir) or p.startswith(os.path.realpath(logdir) + "/")):
                bad.append(f"{s}: bind mount {src} is outside ${{CONF}} and ${{LOGDIR}}")
        for r in fw.get("in") or []:
            if set(r) - {"net", "port", "service"}: bad.append(f"{s}: inbound rule {r}: only net/service/port")
    if "edge" in c["services"]:
        if not models(): bad.append("edge: set ALLOW_MODELS to the model id(s) under eval")
        for m in models():
            if not MODEL_ID.match(m): bad.append(f"edge: model id {m!r} has unexpected characters")
    for dom in c["x-web-allow"]:
        if not DOMAIN.match(dom.strip().lower()): bad.append(f"web: allowlist entry {dom!r} is not a plain domain name")
    return bad


def reach(c):
    nets = c.get("networks") or {}
    for s, d in c["services"].items():
        routed = [n for n in d["networks"] if not (nets.get(n) or {}).get("internal")]
        outs = []
        for r in ((d.get("x-firewall") or {}).get("out") or []):
            if "dns" in r: outs.append("dns")
            elif r.get("internet"): outs.append(f"public IPv4 on TCP {r.get('ports')} (proxy allowlists apply)")
            elif "host" in r: outs.append(f"{r['host']}:{r.get('port', '*')}")
            elif "service" in r: outs.append(f"{r['service']}:{r.get('port', '*')}")
            elif "net" in r: outs.append(f"net {r['net']}:{r.get('port', '*')}")
        print(f"  {s:7} {('proxy    ' if d.get('x-role') == 'proxy' else 'trusted  ') if d.get('x-trusted') else 'UNTRUSTED'} route out: "
              f"{'yes via ' + ','.join(routed) if routed else 'none'}; may reach: {', '.join(outs) or 'nothing'}")
    print(f"  models allowed through edge: {', '.join(models()) or '(none set)'}")
    print(f"  web allowlist: {', '.join(c['x-web-allow'])}")


def render(c, info):
    """The proxies' config files, from the templates (no custom proxy code)."""
    run, logdir, conf = paths(c["x-env"]["NAME"])
    os.makedirs(conf, exist_ok=True)
    e = c["x-env"]
    env_tmpl = open(os.path.join(HERE, "envoy.yaml.tmpl")).read()
    env_tmpl = (env_tmpl.replace("{{UPSTREAM_IP}}", str(ipaddress.ip_address(e["TITAN_IP"])))
                .replace("{{UPSTREAM_PORT}}", str(int(e["TITAN_PORT"])))
                .replace("{{PATHS_REGEX}}", "^/(v1/chat/completions|v1/completions|v1/models|health)$")
                .replace("{{MODELS_REGEX}}", "^(" + "|".join(re.escape(m) for m in models()) + ")$"))
    open(os.path.join(conf, "envoy.yaml"), "w").write(env_tmpl)
    sq = open(os.path.join(HERE, "squid.conf.tmpl")).read()
    sq = (sq.replace("{{DOMAINS}}", " ".join("." + d.strip().lower() for d in c["x-web-allow"]))
            .replace("{{CLIENT_NET}}", info["subnet"]["edge"]))
    open(os.path.join(conf, "squid.conf"), "w").write(sq)
    for f in os.listdir(conf): os.chmod(os.path.join(conf, f), 0o644)


def nft(c, svc, info):
    fw = c["services"][svc]["x-firewall"]
    def addr(r):
        if "host" in r: return str(ipaddress.ip_address(r["host"]))
        if "service" in r: return info["ip"][(r["service"], r["net"])]
        return info["subnet"][r["net"]]
    def port(r):
        return f" tcp dport {int(r['port'])}" if r.get("port") not in (None, "") else ""
    out, inn = [], []
    for r in fw.get("out") or []:
        if "dns" in r:
            for n in r["dns"]:
                g = info["gateway"][n]
                out += [f"ip daddr {g} udp dport 53 accept", f"ip daddr {g} tcp dport 53 accept"]
        elif r.get("internet"):
            ports = ", ".join(str(int(p)) for p in r.get("ports") or [])
            out += [f"ip daddr {{ {PRIVATE} }} reject with icmpx admin-prohibited",
                    f"meta nfproto ipv4 tcp dport {{ {ports} }} accept"]
        else:
            out.append(f"ip daddr {addr(r)}{port(r)} accept")
    for r in fw.get("in") or []:
        inn.append(f"ip saddr {addr(r)}{port(r)} accept")
    j = "\n    ".join
    return f"""table inet evalbox {{
  chain output {{
    type filter hook output priority 0; policy drop;
    ct state established,related accept
    oif "lo" accept
    {j(out)}
    reject with icmpx admin-prohibited
  }}
  chain input {{
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif "lo" accept
    {j(inn)}
  }}
}}
"""


def create_args(name, svc, d):
    a = ["podman", "create", "--name", f"{name}-{svc}", "--label", f"evalbox={name}",
         f"--userns=auto:size={USERNS_SIZE}", "--hostname", d.get("hostname") or svc]
    for n, o in d["networks"].items():
        al = (o or {}).get("aliases") or []
        a += ["--network", f"{name}-{n}" + "".join(f":alias={x}" for x in al)]
    if d.get("user"): a += ["--user", str(d["user"])]
    if d.get("working_dir"): a += ["--workdir", d["working_dir"]]
    a += ["--memory", str(d["mem_limit"]), "--memory-swap", str(d["mem_limit"]),   # no swap
          "--cpus", str(d["cpus"]), "--pids-limit", str(d["pids_limit"])]
    for k, v in (d.get("ulimits") or {}).items(): a += ["--ulimit", f"{k}={v}:{v}"]
    for x in d.get("cap_drop") or []: a += ["--cap-drop", x]
    if d.get("read_only"): a += ["--read-only", "--read-only-tmpfs=false"]
    for x in d.get("security_opt") or []: a += ["--security-opt", x]
    for x in d.get("tmpfs") or []: a += ["--tmpfs", x]
    for v in d.get("volumes") or []: a += ["-v", v]
    env = d.get("environment") or {}
    if isinstance(env, list): env = dict(e.split("=", 1) for e in env)
    for k, v in env.items(): a += ["-e", f"{k}={v}"]
    ep = d.get("entrypoint")
    if ep: a += ["--entrypoint", json.dumps(ep if isinstance(ep, list) else shlex.split(ep))]
    a.append(d["image"])
    cmd = d.get("command")
    if isinstance(cmd, str) and cmd.strip(): a += shlex.split(cmd)
    elif isinstance(cmd, list): a += [str(x) for x in cmd]
    return a


def order(c):
    done, out = set(), []
    def visit(s, stack=()):
        if s in done: return
        if s in stack: sys.exit(f"depends_on cycle at {s}")
        for p in c["services"][s].get("depends_on") or []: visit(p, stack + (s,))
        done.add(s); out.append(s)
    for s in c["services"]: visit(s)
    return out


def down(name):
    for cid in sh("podman", "ps", "-aq", "--filter", f"label=evalbox={name}").split():
        sh("podman", "rm", "-f", "-t", "5", cid, check=False)
    for n in sh("podman", "network", "ls", "-q", "--filter", f"label=evalbox={name}").split():
        sh("podman", "network", "rm", n, check=False)
    print(f"evalbox {name} removed (logs stay in {paths(name)[1]} until collected)")


def seed(name, src):
    run = paths(name)[0]; tmp = os.path.join(run, "seed.tar")
    with tarfile.open(tmp, "w") as t: t.add(src, arcname=".")
    with open(tmp, "rb") as f:
        r = subprocess.run(["podman", "exec", "-i", f"{name}-client", "tar", "-x", "--no-same-owner",
                            "--no-same-permissions", "-C", "/work"], stdin=f)
    os.remove(tmp)
    if r.returncode: sys.exit("seeding /work failed")


def collect(name, dest):
    """Copy out the client's /work (as untrusted data: no links out, no devices, no setuid) and the proxy logs."""
    if os.path.exists(dest) and os.listdir(dest): sys.exit(f"{dest} exists and is not empty")
    os.makedirs(os.path.join(dest, "work"), exist_ok=True)
    tmp = os.path.join(dest, ".work.tar")
    with open(tmp, "wb") as f:
        r = subprocess.run(["podman", "exec", f"{name}-client", "tar", "-c", "-C", "/work", "."], stdout=f)
    if r.returncode == 0:
        with tarfile.open(tmp) as t: t.extractall(os.path.join(dest, "work"), filter="data")
    os.remove(tmp)
    logdir = paths(name)[1]
    if os.path.isdir(logdir):   # owned by the proxies' user ranges: read through the user namespace
        out = os.path.join(dest, "logs")
        sh("podman", "unshare", "sh", "-c", f"cp -r --no-preserve=ownership,mode {shlex.quote(logdir)} {shlex.quote(out)}"
           f" && chown -R 0:0 {shlex.quote(out)} && chmod -R u+rwX {shlex.quote(out)}")
        pf = os.path.join(paths(name)[0], "preflight.json")
        if os.path.exists(pf): sh("cp", pf, out)
    print(f"collected into {dest}: work/ (the client's /work) and logs/ (edge: access + tap/, web: access, preflight.json)")


def up(path, name, seed_dir, accept_risk):
    run, logdir, conf = paths(name)
    if sh("podman", "ps", "-aq", "--filter", f"label=evalbox={name}"): sys.exit(f"evalbox {name} exists; run down first")
    if os.path.isdir(logdir) and os.listdir(logdir): sys.exit(f"{logdir} holds an earlier run's logs; collect them, then remove {run}")
    os.makedirs(STATE, exist_ok=True)
    sh(sys.executable, os.path.join(HERE, "make-seccomp.py"), c_secc := os.path.join(STATE, "seccomp-evalbox.json"))
    c = load(path, name)
    bad = lock_violations(c)
    if bad: sys.exit("refusing to start, the compose file weakens the lockdown:\n  " + "\n  ".join(bad))
    sys.path.insert(0, HERE); import preflight
    ok, report = preflight.run(c["services"], HERE)
    os.makedirs(run, exist_ok=True)
    if not ok:
        if not accept_risk:
            json.dump(report, open(os.path.join(run, "preflight.json"), "w"), indent=1)
            sys.exit("refusing to start: the preflight found problems (above); fix them, or pass "
                     "--accept-risk \"<reason>\" (recorded in the run's preflight.json)")
        report["accepted_risk"] = {"reason": accept_risk, "by": os.environ.get("USER"), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
        print(f"!! starting despite preflight problems: {accept_risk}")
    json.dump(report, open(os.path.join(run, "preflight.json"), "w"), indent=1)
    for sub in ("edge/tap", "web"): os.makedirs(os.path.join(logdir, sub), exist_ok=True)
    for n, o in (c.get("networks") or {}).items():
        a = ["podman", "network", "create", "--label", f"evalbox={name}", "--ipv6=false"]
        if (o or {}).get("internal"): a.append("--internal")
        sh(*a, f"{name}-{n}")
    info = {"subnet": {}, "gateway": {}, "ip": {}}
    for n in c.get("networks") or {}:
        sub = json.loads(sh("podman", "network", "inspect", f"{name}-{n}"))[0]["subnets"][0]
        info["subnet"][n], info["gateway"][n] = sub["subnet"], sub["gateway"]
    render(c, info)
    for s, d in c["services"].items():
        sh(*create_args(name, s, d))
        sh("podman", "init", f"{name}-{s}")
    for s, d in c["services"].items():
        nets = json.loads(sh("podman", "inspect", f"{name}-{s}"))[0]["NetworkSettings"]["Networks"]
        for n in d["networks"]: info["ip"][(s, n)] = nets[f"{name}-{n}"]["IPAddress"]
    for s in c["services"]:
        ns = sh("podman", "inspect", f"{name}-{s}", "--format", "{{.NetworkSettings.SandboxKey}}")
        sh("podman", "unshare", "nsenter", f"--net={ns}", "nft", "-f", "-", inp=nft(c, s, info))
    for s in order(c):
        sh("podman", "start", f"{name}-{s}")
    if seed_dir: seed(name, seed_dir)
    print(f"evalbox {name} up; run dir {run}")
    reach(c)
    print(f"  run in the client: podman exec -it {name}-client <cmd>    self-test: sandbox/selftest.sh {name}")


def main():
    a = sys.argv[1:]; path = os.path.join(HERE, "compose.yaml")
    if a[:1] == ["-f"]: path, a = os.path.abspath(a[1]), a[2:]
    if not a or a[0] not in ("check", "preflight", "up", "down", "collect"): sys.exit(__doc__)
    name = a[1] if len(a) > 1 and a[0] != "preflight" else "check"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name): sys.exit("NAME: lowercase letters, digits, dashes")
    if a[0] == "down": return down(name)
    if a[0] == "collect": return collect(name, os.path.abspath(a[2]))
    if a[0] == "preflight":
        sys.path.insert(0, HERE); import preflight
        ok, _ = preflight.run(load(path, name)["services"], HERE); sys.exit(0 if ok else 1)
    if a[0] == "check":
        c = load(path, name); bad = lock_violations(c)
        print("lockdown: " + ("OK" if not bad else "VIOLATIONS\n  " + "\n  ".join(bad))); reach(c)
        sys.exit(1 if bad else 0)
    opts = a[2:]; seed_dir = accept = None
    while opts:
        if opts[0] == "--seed": seed_dir, opts = os.path.abspath(opts[1]), opts[2:]
        elif opts[0] == "--accept-risk": accept, opts = opts[1], opts[2:]
        else: sys.exit(f"unknown option {opts[0]}")
    up(path, name, seed_dir, accept)


if __name__ == "__main__":
    main()
