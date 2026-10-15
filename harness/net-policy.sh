#!/usr/bin/env bash
# Install the sandbox egress policy, drop the capability, then exec the agent.
#
# Policy: the public internet is reachable; the house LAN and the WireGuard mesh
# are not, except the two endpoints this harness needs. Enforced with nftables
# in the container's own network namespace, so it applies to every process and
# every protocol -- not just clients that happen to honour HTTP_PROXY.
set -euo pipefail
TITAN_IP="${TITAN_IP:-192.0.2.62}"
# The replay fixture is reached via the podman host gateway, which is NOT the
# default route (that is the LAN router). Resolve the name podman injects.
HOSTGW="$(getent hosts host.containers.internal | awk '{print $1; exit}')"
# DNS servers come from resolv.conf, not from a guess at the gateway.
RESOLVERS="$(awk '/^nameserver/{print $2}' /etc/resolv.conf | head -3)"
# NET_PUBLIC=0 (test 8): no public internet, no DNS and no HA fixture; only llama-swap on Titan stays open.
NET_PUBLIC="${NET_PUBLIC:-1}"
FIXTURE='    ip daddr '"${HOSTGW}"' tcp dport 8126 accept comment "HA replay fixture"'
if [ "$NET_PUBLIC" = 0 ]; then
  RESOLVERS=""
  FIXTURE='    # NET_PUBLIC=0: no HA replay fixture either'
  TAIL='    reject with icmpx type admin-prohibited comment "NET_PUBLIC=0: nothing else"'
else
  TAIL='    # anything left is the public internet: allowed on purpose'
fi

nft -f - <<NFT
table inet sandbox {
  chain output {
    type filter hook output priority 0; policy accept;

    ct state established,related accept
    oif "lo" accept

    # the two endpoints the harness legitimately needs
    ip daddr ${TITAN_IP} tcp dport 8080 accept comment "llama-swap inference"
${FIXTURE}

    # DNS to the configured resolvers only
$(for r in $RESOLVERS; do printf '    ip daddr %s udp dport 53 accept\n    ip daddr %s tcp dport 53 accept\n' "$r" "$r"; done)

    # everything else private is refused: LAN, WireGuard mesh, CGNAT, link-local
    ip daddr 10.0.0.0/8 reject with icmp type admin-prohibited
    ip daddr 172.16.0.0/12 reject with icmp type admin-prohibited
    ip daddr 192.168.0.0/16 reject with icmp type admin-prohibited
    ip daddr 100.64.0.0/10 reject with icmp type admin-prohibited
    ip daddr 169.254.0.0/16 reject with icmp type admin-prohibited
    ip6 daddr fc00::/7 reject
    ip6 daddr fe80::/10 reject

${TAIL}
  }
}
NFT
echo "net-policy: installed; public=${NET_PUBLIC} hostgw=${HOSTGW} titan=${TITAN_IP} resolvers=$(echo $RESOLVERS | tr '\n' ' ')" >&2

# Drop CAP_NET_ADMIN from every set before handing control to the agent, so the
# policy cannot be edited by anything the model runs.
exec setpriv --inh-caps=-all --bounding-set=-all --ambient-caps=-all -- "$@"
