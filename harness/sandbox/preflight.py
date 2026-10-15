#!/usr/bin/env python3
"""evalbox update preflight: run before every start (evalbox.py up), or alone (evalbox.py preflight).

Operator 2026-10-07: "Add an update check of the sandbox components before it starts to get rid of
bugs or vulns that could affect it." A problem refuses the start unless --accept-risk gives a reason.

Host (the isolation lives here):
  - pending updates for the packages the isolation depends on (HOST_PACKAGES): any is a problem,
    because Fedora ships container-runtime and kernel CVE fixes as ordinary updates;
  - security advisories for them (listed, for the record);
  - a newer kernel installed than the one running (reboot pending): a problem.
Images (every service's image):
  - registry images: `podman pull --policy=newer` (updates in place when the registry has newer);
  - images built here (compose `build:`; all of ours): rebuilt when missing or older than
    MAX_IMAGE_DAYS, and rebuilt from scratch (fresh base, every package upgraded) when the scan finds
    a fixable vulnerability, then scanned again;
  - other local images (the client): older than MAX_IMAGE_DAYS is a problem (rebuild it);
  - Envoy: a newer release line than the configured tag is a problem;
  - vulnerability scan with Trivy (official image, itself kept current): any CRITICAL or HIGH
    vulnerability that has a fix is a problem. Results are cached per image ID for a day.
"""
import json, os, re, subprocess, sys, time

HOST_PACKAGES = ["podman", "crun", "conmon", "netavark", "aardvark-dns", "passt", "nftables",
                 "containers-common", "containers-common-extra", "kernel", "kernel-core", "glibc",
                 "libseccomp", "shadow-utils-subid", "fuse-overlayfs", "systemd"]
MAX_IMAGE_DAYS = int(os.environ.get("EVALBOX_MAX_IMAGE_DAYS", "7"))
TRIVY = "docker.io/aquasec/trivy:latest"
CACHE = os.path.join(os.path.expanduser("~"), ".local", "share", "evalbox", "trivy")


def run(services, here):
    """services: {name: compose service dict}. Returns (ok, report)."""
    rep = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "problems": [], "notes": []}
    host(rep)
    for name, d in services.items():
        image(rep, name, d, here)
    ok = not rep["problems"]
    for p in rep["problems"]: print(f"  PROBLEM  {p}")
    for n in rep["notes"]: print(f"  note     {n}")
    print(f"preflight: {'OK' if ok else str(len(rep['problems'])) + ' problem(s)'}")
    return ok, rep


def sh(*a, timeout=900):
    r = subprocess.run(a, text=True, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def host(rep):
    rc, out, err = sh("dnf", "-q", "--assumeno", "check-update", *HOST_PACKAGES)
    pend = [l.split()[0] + " " + l.split()[1] for l in out.splitlines() if len(l.split()) == 3 and "." in l.split()[0]]
    if rc not in (0, 100): rep["problems"].append(f"host: could not check for updates (dnf rc {rc}: {err.strip()[:200]})")
    for p in pend: rep["problems"].append(f"host: update pending for {p} (apply it, then reboot if it is the kernel)")
    rc, out, _ = sh("dnf", "-q", "--assumeno", "advisory", "list", "--security", "--updates")
    adv = [l for l in out.splitlines() if any(re.search(rf"\b{re.escape(p)}-\d", l) for p in HOST_PACKAGES)]
    for a in adv: rep["notes"].append(f"host security advisory: {' '.join(a.split()[:4])}")
    running = os.uname().release
    rc, out, _ = sh("rpm", "-q", "kernel-core", "--qf", "%{VERSION}-%{RELEASE}.%{ARCH}\n")
    installed = sorted(out.split(), key=lambda v: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", v)])
    if installed and installed[-1] != running:
        rep["problems"].append(f"host: kernel {installed[-1]} is installed but {running} is running (reboot)")
    rep["host"] = {"kernel": running, "pending": pend}


def created_days(img):
    rc, out, _ = sh("podman", "image", "inspect", img, "--format", "{{.Created.Unix}}")
    return (time.time() - int(out.strip())) / 86400 if rc == 0 and out.strip() else None


def build(rep, svc, d, here, why, fresh=False):
    img = d["image"]; b = d["build"]; ctx = os.path.join(here, b.get("context", "."))
    print(f"  rebuilding {img} for {svc} ({why}) ...", flush=True)
    a = ["podman", "build", "-q", "-t", img, "-f", os.path.join(ctx, b.get("dockerfile", "Containerfile"))]
    a += ["--pull=always", "--no-cache"] if fresh else ["--pull=newer"]
    rc, _, err = sh(*a, ctx, timeout=3600)
    if rc: rep["problems"].append(f"{svc}: rebuild of {img} failed: {err.strip()[-300:]}"); return False
    rep["notes"].append(f"{svc}: rebuilt {img} ({why})"); return True


def image(rep, svc, d, here):
    img = d.get("image", "")
    if d.get("build"):
        age = created_days(img)
        if age is None or age > MAX_IMAGE_DAYS:
            build(rep, svc, d, here, "missing" if age is None else f"{age:.0f} days old")
    elif img.startswith("localhost/"):
        age = created_days(img)
        if age is None: rep["problems"].append(f"{svc}: image {img} is missing")
        elif age > MAX_IMAGE_DAYS: rep["problems"].append(f"{svc}: {img} is {age:.0f} days old; rebuild it (pulls fixes)")
    else:
        before = sh("podman", "image", "inspect", img, "--format", "{{.Id}}")[1].strip()
        rc, _, err = sh("podman", "pull", "-q", "--policy=newer", img)
        if rc: rep["problems"].append(f"{svc}: could not check {img} for updates: {err.strip()[:200]}")
        elif sh("podman", "image", "inspect", img, "--format", "{{.Id}}")[1].strip() != before:
            rep["notes"].append(f"{svc}: pulled a newer {img}")
    m = re.match(r".*envoyproxy/envoy:v1\.(\d+)", img)
    if m:
        rc, out, _ = sh("curl", "-sf", "-m", "20", "https://api.github.com/repos/envoyproxy/envoy/releases/latest")
        try:
            latest = int(re.match(r"v1\.(\d+)", json.loads(out)["tag_name"]).group(1))
            if latest > int(m.group(1)): rep["problems"].append(f"{svc}: Envoy v1.{latest} is out; move {img} to v1.{latest}-latest")
        except (ValueError, KeyError, AttributeError, TypeError):
            rep["notes"].append(f"{svc}: could not check the latest Envoy release")
    vulns = scan(rep, svc, img)
    if vulns and d.get("build"):   # built here: rebuild from scratch on fresh packages, then look again
        if build(rep, svc, d, here, f"{len(vulns)} fixable vulnerabilities", fresh=True):
            vulns = scan(rep, svc, img)
    if vulns:
        top = ", ".join(f"{i} {p} ({sv}, fixed in {f})" for i, p, sv, f in vulns[:5])
        rep["problems"].append(f"{svc}: {img} has {len(vulns)} fixable CRITICAL/HIGH vulnerabilities: {top}"
                               + (" ..." if len(vulns) > 5 else ""))


def scan(rep, svc, img):
    iid = sh("podman", "image", "inspect", img, "--format", "{{.Id}}")[1].strip()
    if not iid: return []
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, iid[:24] + ".json")
    if not (os.path.exists(cached) and time.time() - os.path.getmtime(cached) < 86400):
        sh("podman", "pull", "-q", "--policy=newer", TRIVY)
        tar = os.path.join(CACHE, "image.tar")
        print(f"  scanning {img} for vulnerabilities ...", flush=True)
        rc, _, err = sh("podman", "save", "-q", "-o", tar, img, timeout=1800)
        if rc: rep["problems"].append(f"{svc}: could not export {img} for scanning: {err.strip()[:200]}"); return []
        rc, out, err = sh("podman", "run", "--rm", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                          "-v", f"{CACHE}:/cache:Z", TRIVY, "image", "--quiet", "--cache-dir", "/cache/db",
                          "--input", "/cache/image.tar", "--severity", "CRITICAL,HIGH", "--ignore-unfixed",
                          "--scanners", "vuln", "--format", "json", timeout=3600)
        os.remove(tar)
        if rc: rep["problems"].append(f"{svc}: vulnerability scan of {img} failed: {err.strip()[-200:]}"); return []
        open(cached, "w").write(out)
    res = json.load(open(cached))
    return [(v["VulnerabilityID"], v.get("PkgName"), v.get("Severity"), v.get("FixedVersion"))
            for r in res.get("Results") or [] for v in r.get("Vulnerabilities") or []]


if __name__ == "__main__":
    sys.exit("run through evalbox.py preflight")
