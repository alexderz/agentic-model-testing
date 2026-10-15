# evalbox: the locked-down eval sandbox for highly untrusted code and models

A sandbox for model evals that need a real service to test against (operator, 2026-10-07). It will
run **highly untrusted code and models** (on Saturn), and other tests and future evals build on it,
so **the whole sandbox stays locked down**. Everything is declared in **`compose.yaml`**; this file
explains every lock, why it is there, and how to change it safely.

```
                 internal              internal                 internal
 [db] ──── <N>-db ──── [server] ──── <N>-api ──── [client] ──── <N>-edge ─┬─ [edge: Envoy] ── <N>-titan ── titan:8080
 trusted               UNTRUSTED                  UNTRUSTED               │   proxy, routed: titan only
 no route              (test subject)             no route                └─ [web: Squid] ─── <N>-out ──── public internet
                       no route                                               proxy, routed: public IPv4, allowlisted domains
```

**Trust model** (operator, 2026-10-07). The **db** is trusted (our image) and trusts the server,
which holds its credentials. The **server** is our code, but it is the test subject and may act in
untrusted ways, so it is untrusted from the outside; it does not trust the client by default (that
takes authentication, in the abstract). The **client** is untrusted by definition: it is where the
agent or test runs. The client never reaches the db directly. None of the three has a route
anywhere: being trusted gives the db nothing, and the launcher refuses a routed network, an outside
destination or a host mount for anything but the two proxies (`x-trusted: true` plus `x-role: proxy`). The only ways out are the two
proxies, which are established software configured only by config files (no custom proxy code):
**Envoy** for inference, **Squid** for the web. The host runs the launcher, the preflight and nothing
else of the sandbox.

| service | trust | can reach | cannot reach |
|---|---|---|---|
| `db` | trusted (trusts the server) | nothing (answers only the server, on 5432) | everything, including outside DNS and the server's other ports |
| `server` | untrusted (test subject) | the db on 5432 | internet, titan, the proxies, the client |
| `client` | untrusted | the server's address on **any port**; titan **only through Envoy**; allowlisted web **only through Squid** | the db (no packets, no credentials), any address directly, outside DNS, the LAN, the mesh, the host, other sandboxes |
| `edge` (Envoy) | trusted proxy | titan's inference port | everything else |
| `web` (Squid) | trusted proxy | public IPv4 on TCP 80/443 (kernel); Squid allows only listed domains | private ranges, titan, the LAN, any other port or protocol |

## Use

```
export ALLOW_MODELS=qwen3.8-27b-vllm                  # required: model id(s) Envoy lets through
sandbox/evalbox.py check [NAME]                       # validate compose.yaml, print each service's reach
sandbox/evalbox.py up NAME [--seed DIR]               # preflight, create, firewall, start; DIR -> the client's /work
sandbox/selftest.sh NAME                              # proves every lock; must end ALL PASS
podman exec -it NAME-client ...                       # run the agent / tests in the client
sandbox/evalbox.py collect NAME DEST                  # the client's /work + proxy logs + preflight report -> DEST
sandbox/evalbox.py down NAME                          # remove containers and networks
sandbox/evalbox.py preflight                          # the update / vulnerability check alone
```

Inside the client: `SERVER_URL` (`http://server:8000`), `INFERENCE_URL` (`http://edge:8080`, OpenAI-compatible:
llama-swap through Envoy), and `HTTP(S)_PROXY=http://web:3128` (so pip, cargo, npm, git and curl
reach the allowlisted web; anything that ignores the proxy simply has no route).

Variables: `ALLOW_MODELS` (required), `TITAN` (`host:port`), `EXTRA_DOMAINS` (comma-separated,
added to the web allowlist for one run), `SERVER_IMAGE`, `SERVER_CMD`, `SERVER_PORT`, `DB_IMAGE`,
`CLIENT_IMAGE`, `EVALBOX_USERNS_SIZE` (user ids per container, default 8192),
`EVALBOX_MAX_IMAGE_DAYS` (default 7). Run state (rendered proxy configs, logs, preflight report)
lives in `~/.local/share/evalbox/runs/<NAME>/`.

**Why not `docker compose up`:** compose cannot run a host step between creating a container and
starting it (the firewall must be in place before the first process runs), cannot run the
preflight, and does not refuse edits that weaken the lockdown. `evalbox.py` reads the same file.

## The locks

### 1. Networks
`db`, `api`, `edge` are `internal: true`: no gateway, no route, no NAT. Only the proxies sit on
routed networks (`titan`, `out`). The db, server and client therefore have **no route out at all**,
independent of any filter rule. Podman's DNS on internal networks answers container names only and
does not forward outside names, so there is no DNS tunnel out. IPv6 is off on every network.

### 2. Firewall (`x-firewall`)
Each service's `x-firewall` becomes an nftables table in that container's own network namespace,
**applied from the host** (`podman init`, then `podman unshare nsenter --net=<netns> nft -f -`)
**before the first process starts**; no container has `CAP_NET_ADMIN`. Output and input default to
drop; established traffic and loopback pass; each rule opens exactly one thing:

| rule | opens |
|---|---|
| `{net: db, port: 5432}` | a sandbox network's subnet (any port if `port` is left out) |
| `{service: edge, net: edge, port: 8080}` | one container's address on one network |
| `{host: 192.0.2.62, port: 8080}` | one outside address and port (proxies only) |
| `{dns: [api]}` | podman's resolver on those networks, port 53 |
| `{internet: true, ports: [80, 443]}` | rejects 0/8, 10/8, 100.64/10, 127/8, 169.254/16, 172.16/12, 192.0.0/24, 192.168/16, 198.18/15, 224/3, accepts other IPv4 on the listed TCP ports only (proxies only; `ports` required) |

### 3. Every container (`x-locked`, plus what the launcher adds)
- `cap_drop: [ALL]`, `no-new-privileges`, `read_only: true` root filesystem.
- **Strict seccomp** (`make-seccomp.py`, regenerated each start from the host's current podman
  default): additionally blocks new namespaces (`unshare`, `setns`, `clone3`, and `clone` with any
  `CLONE_NEW*` flag, `CLONE_NEWTIME` included; unprivileged user namespaces are the usual first step of a container escape),
  the mount API, `ptrace` and `process_vm_*`, kernel keyrings, file handles and `syslog`.
- **Own user range per container** (`--userns=auto`, 8192 ids each): root in a container is an
  unprivileged id that no other container and no host account shares, so an escape that stays
  inside the user namespace does not land as the user running podman. One that leaves it lands as
  `evalbox`, which owns the podman runtime, the image store and the run directories (see below).
- Limits: `mem_limit` (swap off), `cpus`, `pids_limit: 512`, `nofile 4096`, no core dumps, a
  `size=` on every tmpfs. No GPU or other device is ever passed in.

### 4. Host mounts
Only the proxies get host mounts; the db, server and client get **none**. The client's `/work` is a tmpfs: `--seed DIR` copies input in as a tar
stream; `collect` copies it out and unpacks it as untrusted data (Python `tarfile` `data` filter: no
absolute paths, no `..`, no links pointing out, no devices, no setuid bits). The proxies mount only
their rendered config (read-only) and their own log directory.

### 5. Inference proxy: Envoy (`envoy.yaml.tmpl`)
Official image, newest release line. Only `POST /v1/chat/completions`, `POST /v1/completions`,
`GET /v1/models`, `GET /health` reach titan; llama-swap's `/unload`, `/upstream/...`, `/logs`,
`/running`, `/ui` and every other path or method get a 403 from Envoy. Request bodies over 8 MiB are
refused; a POST must name a model in `ALLOW_MODELS` (built-in `json_to_metadata` + `rbac` filters),
so a client cannot make llama-swap swap models. Paths are normalised and escaped slashes rejected.
Limits: 32 connections, 4 concurrent upstream requests. `Authorization`, cookies and API keys are
stripped. **No admin interface.** Every exchange is recorded in full by the `tap` filter
(`logs/edge/tap/`, headers and bodies up to 64 MiB each way) and summarised in
`logs/edge/edge-access.jsonl`. Responses stream back as they arrive.

### 6. Web proxy: Squid (`squid.conf.tmpl`, `Containerfile.squid`)
Fedora's Squid package on a current Fedora base (the official Ubuntu image was a year old). Only
domains in `x-web-allow` (and their subdomains), HTTPS only via CONNECT to 443 (TLS end to end, no
interception), plain HTTP only to 80; destinations resolving to private, loopback, link-local,
CGNAT or multicast addresses are refused (Squid checks the address it connects to, so DNS
rebinding cannot slip one in); only clients from `<N>-edge`; no caching; no client details
forwarded. Log: `logs/web/web-access.log`. IPv6 is blocked in the kernel, not in Squid: the networks
are created with `--ipv6=false` and the proxy's nftables policy accepts only IPv4 out. (A Squid
`dst ipv6` rule matched any host with an AAAA record, which refused pypi.org and most of the
allowlist; removed 2026-10-07.) Squid 7 needs shared memory even with one worker, so this one
trusted container gets a 16 MB `/dev/shm` tmpfs; Envoy runs with `--disable-hot-restart` instead.

### 7. Update preflight (`preflight.py`, before every start)
Operator: "an update check of the sandbox components before it starts to get rid of bugs or vulns".
A problem refuses the start unless `--accept-risk "<reason>"` is given (recorded in
`preflight.json`):
- **host:** a pending update for any package the isolation depends on (podman, crun, conmon,
  netavark, aardvark-dns, passt, nftables, containers-common, kernel, glibc, libseccomp, shadow
  subid, fuse-overlayfs, systemd); a newer kernel installed than running (reboot); security
  advisories are listed;
- **images:** registry images are pulled when newer; our built images (db, server, squid, client) are
  rebuilt when missing or older than 7 days, and rebuilt from scratch when the vulnerability scan
  finds anything; Envoy must be on the newest release line;
- **vulnerabilities:** Trivy (official image, kept current) scans every image; any fixable
  CRITICAL or HIGH finding is a problem.

### 8. The launcher's guard (`evalbox.py`, `lock_violations()`)
`evalbox.py` refuses to start (and `check` lists) a compose file with: a service missing
`cap_drop: [ALL]`, `read_only`, `no-new-privileges`, the strict seccomp profile, `mem_limit`,
`cpus`, `pids_limit`, a tmpfs `size=`, an `x-firewall` or an explicit `networks` list; any of
`cap_add`, `privileged`, `network_mode`, `pid`, `ipc`, `userns_mode`, `devices`, `sysctls`,
`extra_hosts`, `ports`, `volumes_from`, `runtime`, `gpus`, `deploy`, `group_add`, `shm_size`, `tty`;
any other `security_opt`, or more than one `seccomp=` (a later one would win); a service that is not
a proxy (`x-trusted: true` plus `x-role: proxy`) on a routed network, with an outside destination or
with any host mount, whether it is trusted or not; a proxy mounting anything but its rendered config
(read-only) and its log dir; `x-role` other than `proxy`, or `x-role: proxy` without `x-trusted`; a routed network without an outside rule (or the reverse); an empty or odd
`ALLOW_MODELS`; a web allowlist entry that is not a plain domain name.

## What the locks do not stop (independent review, Grok, 2026-10-07)

- **The client reaches db data through the server.** The db trusts the server (fixed
  `server`/`server` superuser credentials, only in the server's `DATABASE_URL`), and the client may
  use any port on the server. What the client can get out of the db through the server is the
  server's behaviour under test (does it authenticate the client, does it leak), not a sandbox
  escape. No packet goes from the client to the db, the client holds no db credentials (self-test),
  and nothing gets out of the db.
- **The web allowlist is by name, in Squid.** The kernel limits the proxy to public IPv4 on TCP
  80/443; which domain is reached is Squid's decision, and CONNECT does not inspect TLS, so a site
  that shares a CDN address with an allowlisted one (domain fronting) may be reachable.
- **Host disk.** Envoy's tap writes every exchange (up to 64 MiB each way) to the run directory with
  no file count or rotation, and Squid's access log grows per request. Memory, CPU and task caps do
  not limit this. On Saturn the run directories and podman's store sit on a 100 GB XFS loop image
  at /home/evalbox/.local/share, so a runaway run fills that, not
  the root disk. Container stdout goes to journald, whose own size limits apply.
- **pasta and aardvark-dns** run as `evalbox` outside each container's cgroup; the account's 20 GB
  and 12-CPU caps still bound them.

## Running on Saturn (the target for untrusted runs)

- Run it as a **dedicated unprivileged user** with no sudo, no NAS write access and no SSH keys
  (for example `evalbox`), with its own large subordinate id range (`/etc/subuid`, at least
  6 × 8192 = 49,152 ids per concurrent sandbox). A full escape then lands in an account with no
  privileges on the host, the NAS or the LAN; it does own the sandbox runtime itself (podman, images,
  run logs), so the next run is only as clean as that account.
- Host packages current and rebooted into the newest kernel: the preflight refuses otherwise.
- `nft`, `nsenter` (util-linux) and `python3-pyyaml` on the host.
- On Saturn those changes go through the host's configuration management, not by hand.
- Later, worth considering: gVisor (`runsc`) as the runtime for the db, server and client, for a second kernel
  boundary. Its network stack bypasses the netns output hook, so the firewall would need
  `--network=host` mode in runsc (the container netns' kernel stack) and the self-test must prove it.

## Changing it (for test agents and future evals)

Edit `compose.yaml`; change the lock, not the test. After any change: `evalbox.py check`, `down`,
`up`, and `selftest.sh` must end ALL PASS. Add a check to `selftest.sh` for anything new you open,
and note the change and the reason in the eval's notes.

| need | change | keep |
|---|---|---|
| a different server | `server.image` + `build`, or `SERVER_IMAGE` / `SERVER_CMD` | the server's networks and firewall; build packages in, the server has no route |
| the server on another port | `SERVER_PORT` | no rule change: the client may use any port on the server |
| a different db (another database) | `db.image` / `build`, `environment`, `tmpfs`, the port in the db's `in` rule and the server's `out` rule | the db on network `db` only, answering only the server; never a host mount; no GPU. Untrusted code or models do not belong in the db: it is trusted |
| another backing service | add a service with `<<: *locked`, on an internal network shared with the server only, and an `x-firewall` like `db`'s | internal networks only |
| the server must call an outside API | not directly: add a trusted proxy service (`x-trusted` + `x-role: proxy`; established software, config only) on a new internal network shared with the server, with one `host` rule | the server keeps no route |
| the client needs another web domain | add it to `x-web-allow` (or `EXTRA_DOMAINS` for one run) | a domain, never a wildcard or IP |
| the client without the web for a test | remove `web` from `client.depends_on` and its `web` rule | the inference path still works |
| another model | `ALLOW_MODELS` | Envoy's path list |
| another model server | `TITAN=host:port` | Envoy still filters and records |
| more memory / CPU / processes | `mem_limit` / `cpus` / `pids_limit` on that service | everything in `x-locked` |
| a writable path | a `tmpfs` entry with `size=` | `read_only: true` |
| tools needing capabilities (ping, tcpdump, debuggers) | not possible by design; inspect from the host | `cap_drop: [ALL]`, seccomp |

Never: `cap_add`, `privileged`, `network_mode: host`, a `security_opt` other than
`no-new-privileges` and the strict seccomp, a routed network or host mount for the db, server or client, a device
or GPU, the podman socket, or a hand-written proxy. The launcher refuses all of these; do not work
around it.
