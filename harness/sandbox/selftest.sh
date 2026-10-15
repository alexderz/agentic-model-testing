#!/bin/bash
# Prove an eval sandbox's lockdown. Every line must say PASS; the last line must be ALL PASS.
#   sandbox/selftest.sh NAME
# Network probes run from the host inside each container's network namespace (nsenter), so they
# test the firewall itself and do not depend on tools in the images. Behaviour probes (DNS, the
# proxies, seccomp, user ranges) run inside the containers.
# Sends no inference request to titan: the edge checks are a GET /health (llama-swap's own status
# page, loads nothing) and requests Envoy refuses before they reach titan. SELFTEST_INFERENCE=1
# adds one real chat completion with the first model in ALLOW_MODELS.
N=${1:?usage: selftest.sh NAME}; TITAN=${TITAN:-192.0.2.62:8080}; SERVER_PORT=${SERVER_PORT:-8000}
PASTA_ADDR=${PASTA_ADDR:?set to the host address pasta maps into containers (169.254.x.y, see passt(1))}
RUN=$HOME/.local/share/evalbox/runs/$N; fail=0
CL=$N-client; SV=$N-server; DB=$N-db; E=$N-edge; W=$N-web
pass() { echo "PASS  $*"; }; bad() { echo "FAIL  $*"; fail=1; }
ns() { podman inspect "$1" --format '{{.NetworkSettings.SandboxKey}}'; }
probe() {   # container host port open|closed label  -- TCP connect from inside the container's netns
  local r; r=$(podman unshare nsenter --net="$(ns "$1")" python3 -c "
import socket
try: socket.create_connection(('$2',$3),timeout=5); print('open')
except Exception: print('closed')" 2>&1 | tail -1)
  [ "$r" = "$4" ] && pass "$1: $5 ($2:$3 $r)" || bad "$1: $5 ($2:$3 $r, want $4)"
}
ip_of() { podman inspect "$1" --format "{{(index .NetworkSettings.Networks \"$N-$2\").IPAddress}}"; }
gw_of() { podman network inspect "$N-$1" --format '{{range .Subnets}}{{.Gateway}}{{end}}'; }
in_c() { podman exec "$CL" sh -c "$1" 2>&1; }
sleep 3

# --- the client (untrusted) --------------------------------------------------------------------------
r=$(in_c "curl -s -m 10 \$SERVER_URL/health"); case "$r" in *'"ok": true'*) pass "$CL: reaches the server's API, the server reaches the db";; *) bad "$CL: the server's API: $r";; esac
podman exec -d "$SV" python3 -c "import socket;s=socket.socket();s.bind(('0.0.0.0',47123));s.listen();[s.accept() for _ in range(3)]" >/dev/null
sleep 1
probe $CL "$(ip_of $SV api)" 47123 open "reaches any port on the server"
probe $CL "$(ip_of $DB db)" 5432 closed "cannot reach the db"
probe $CL "$(ip_of $W out)" 3128 closed "cannot reach the web proxy's outside address"
probe $CL ${TITAN%:*} ${TITAN#*:} closed "cannot reach titan directly"
probe $CL 1.1.1.1 443 closed "no direct internet"
probe $CL 192.0.2.1 53 closed "cannot reach the LAN router"
probe $CL "$(gw_of api)" 22 closed "cannot reach the host through a network gateway"
probe $CL $PASTA_ADDR 22 closed "cannot reach the host through pasta's address"
r=$(in_c "getent hosts pypi.org || echo no-resolve"); [ "${r##*$'\n'}" = no-resolve ] && pass "$CL: no outside DNS" || bad "$CL: resolves outside names: $r"
r=$(podman exec "$CL" env 2>&1 | grep -c -i -E 'DATABASE_URL|POSTGRES|PGPASS|server:server')
[ "$r" = 0 ] && pass "$CL: holds no db credentials (only the server does)" || bad "$CL: $r db credential variables in its environment"
r=$(in_c "nft flush ruleset 2>&1; ip link set lo down 2>&1" | head -1)
case "$r" in *ermission*|*"not permitted"*|*"not found"*) pass "$CL: cannot change its firewall";; *) bad "$CL: firewall change attempt said: $r";; esac
r=$(in_c "unshare -U -r true 2>&1 || echo blocked" | tail -1); case "$r" in *blocked*|*"not implemented"*|*"not permitted"*) pass "$CL: cannot create user namespaces (seccomp)";; *) bad "$CL: unshare -U worked: $r";; esac
r=$(in_c "python3 -c 'import ctypes,os; l=ctypes.CDLL(None,use_errno=True); r=l.syscall(56,0x80|17,0,0,0,0); os._exit(0) if r==0 else print(r, ctypes.get_errno())'" | tail -1)
case "$r" in "-1 1"|"-1 38") pass "$CL: cannot clone into a new time namespace (seccomp, $r)";; *) bad "$CL: clone(CLONE_NEWTIME) gave: $r";; esac
# inference proxy (Envoy)
code() { in_c "curl -s -o /dev/null -w '%{http_code}' -m 15 $1"; }
[ "$(code http://edge:8080/health)" = 200 ] && pass "$CL: titan's /health through Envoy" || bad "$CL: titan /health through Envoy: $(code http://edge:8080/health)"
for p in /unload /running /logs /upstream/x/metrics /ui /v1/../unload; do
  c=$(code "--path-as-is http://edge:8080$p"); [ "$c" = 403 ] || [ "$c" = 400 ] && pass "$CL: Envoy refuses $p ($c)" || bad "$CL: Envoy let $p through ($c)"
done
c=$(code "-X DELETE http://edge:8080/v1/models"); [ "$c" = 403 ] && pass "$CL: Envoy refuses other methods ($c)" || bad "$CL: DELETE /v1/models gave $c"
c=$(code "-X POST -H 'Content-Type: application/json' -d '{\"model\":\"not-allowed\",\"messages\":[]}' http://edge:8080/v1/chat/completions")
[ "$c" = 403 ] && pass "$CL: Envoy refuses a model outside ALLOW_MODELS ($c)" || bad "$CL: other model gave $c"
# a bounded 9 MB body (over Envoy's 8 MiB cap); @/dev/zero made curl buffer forever and get OOM-killed
c=$(in_c "head -c 9000000 /dev/zero | curl -s -o /dev/null -w '%{http_code}' -m 30 -X POST -H 'Content-Type: application/json' --data-binary @- http://edge:8080/v1/chat/completions")
case "$c" in 413|400|000) pass "$CL: Envoy refuses an oversized body ($c)";; *) bad "$CL: oversized body gave $c";; esac
if [ "${SELFTEST_INFERENCE:-0}" = 1 ]; then
  m=${ALLOW_MODELS%%,*}
  r=$(in_c "curl -s -m 600 -H 'Content-Type: application/json' -d '{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"max_tokens\":8}' http://edge:8080/v1/chat/completions")
  case "$r" in *choices*) pass "$CL: a chat completion through Envoy";; *) bad "$CL: chat completion: ${r:0:150}";; esac
fi
# web proxy (Squid)
c=$(code "https://pypi.org/simple/pip/"); [ "$c" = 200 ] && pass "$CL: allowlisted site through Squid (pypi.org $c)" || bad "$CL: pypi.org through Squid gave $c"
c=$(code "https://example.com/"); [ "$c" = 000 ] || [ "$c" = 403 ] && pass "$CL: Squid refuses a site off the allowlist (example.com $c)" || bad "$CL: example.com gave $c"
c=$(code "http://$TITAN/health"); [ "$c" = 403 ] && pass "$CL: Squid refuses titan by address ($c)" || bad "$CL: titan via Squid gave $c"
c=$(code "--proxytunnel -x http://web:3128 http://github.com:22/"); [ "$c" = 000 ] || [ "$c" = 403 ] && pass "$CL: Squid refuses CONNECT to a port other than 443 ($c)" || bad "$CL: CONNECT :22 gave $c"

# --- the server (untrusted; the test subject) ------------------------------------------------------
probe $SV "$(ip_of $DB db)" 5432 open "reaches the db's Postgres"
probe $SV 1.1.1.1 443 closed "no internet"
probe $SV ${TITAN%:*} ${TITAN#*:} closed "cannot reach titan"
probe $SV "$(ip_of $E edge)" 8080 closed "cannot reach the inference proxy"
probe $SV "$(ip_of $W edge)" 3128 closed "cannot reach the web proxy"
podman exec -d "$CL" python3 -c "import socket;s=socket.socket();s.bind(('0.0.0.0',47124));s.listen();s.accept()" >/dev/null
sleep 1
probe $SV "$(ip_of $CL api)" 47124 closed "cannot open connections to the client"
r=$(podman exec $SV python3 -c "
import socket
try: socket.gethostbyname('pypi.org'); print('resolves')
except Exception: print('no-resolve')"); [ "$r" = no-resolve ] && pass "$SV: no outside DNS" || bad "$SV: resolves outside names"

# --- the db (trusted; answers only the server) -----------------------------------------------------
probe $DB 1.1.1.1 443 closed "no internet"
probe $DB ${TITAN%:*} ${TITAN#*:} closed "cannot reach titan"
probe $DB "$(ip_of $SV api)" 8000 closed "cannot open connections to the server"
podman exec $DB getent hosts pypi.org >/dev/null 2>&1 && bad "$DB: resolves outside names" || pass "$DB: no outside DNS"

# --- the proxies (trusted) -------------------------------------------------------------------------
probe $E 1.1.1.1 443 closed "inference proxy: no internet"
probe $E ${TITAN%:*} ${TITAN#*:} open "inference proxy: reaches titan"
probe $W 192.0.2.1 53 closed "web proxy: no LAN"
probe $W ${TITAN%:*} ${TITAN#*:} closed "web proxy: cannot reach titan"
GH=$(getent ahostsv4 github.com | awk 'NR==1{print $1}')   # github.com listens on 22 and 443: a closed 22 is the firewall
probe $W "$GH" 443 open "web proxy: reaches public TCP 443"
probe $W "$GH" 22 closed "web proxy: no public TCP port outside 80/443"
sleep 2
podman unshare sh -c "grep -q '\"path\":\"/health\"' $RUN/logs/edge/edge-access.jsonl" && pass "edge access log records requests" || bad "edge access log has no /health line"
ok200=cat; [ "${SELFTEST_INFERENCE:-}" = 1 ] && ok200="grep -v '\"status\":200'"   # the one real completion goes upstream
r=$(podman unshare sh -c "grep -v '\"path\":\"/health\"' $RUN/logs/edge/edge-access.jsonl | $ok200 | grep -c via_upstream" 2>/dev/null)
[ "${r:-x}" = 0 ] && pass "edge: every refused request was answered by Envoy, none reached titan" || bad "edge: $r non-/health requests went upstream"
podman unshare sh -c "ls $RUN/logs/edge/tap | grep -q ." && pass "edge tap records full exchanges ($RUN/logs/edge/tap)" || bad "edge tap dir is empty"
podman unshare sh -c "grep -q 'pypi.org' $RUN/logs/web/web-access.log" && pass "web access log records requests" || bad "web access log has no pypi.org line"

# --- every container -------------------------------------------------------------------------------
maps=""
for c in $DB $SV $E $W $CL; do
  e=$(podman inspect $c --format '{{.EffectiveCaps}}'); ro=$(podman inspect $c --format '{{.HostConfig.ReadonlyRootfs}}')
  so=$(podman inspect $c --format '{{.HostConfig.SecurityOpt}}')
  m=$(podman exec $c cat /proc/self/uid_map 2>/dev/null | awk 'NR==1{print $2}'); [ -n "$m" ] || m=$(podman inspect $c --format '{{.State.Pid}}' | xargs -I{} awk 'NR==1{print $2}' /proc/{}/uid_map)
  [ "$e" = "[]" ] && [ "$ro" = true ] && [[ "$so" == *no-new-privileges* ]] && [[ "$so" == *seccomp* ]] \
    && pass "$c: no capabilities, read-only root, no-new-privileges, strict seccomp" || bad "$c: caps=$e readonly=$ro secopt=$so"
  [[ "$m" =~ ^[0-9]+$ ]] && [ "$m" != "$(id -u)" ] && [ "$m" != 0 ] && pass "$c: own user range (container root = host uid $m, not $(id -un))" || bad "$c: uid_map starts at $m"
  maps="$maps $m"
done
[ "$(echo $maps | tr ' ' '\n' | sort -u | wc -l)" = 5 ] && pass "every container has a different user range" || bad "user ranges overlap: $maps"
[ $fail = 0 ] && echo "ALL PASS" || { echo "SOME CHECKS FAILED"; exit 1; }
