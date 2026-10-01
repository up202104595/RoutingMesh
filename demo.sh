#!/bin/bash
# demo.sh — arranca TUDO a partir do PC (base station).
#
# Uso:  ./demo.sh [l3|arp]        (default: l3)
#
#   1. poe o Wi-Fi do PC em ad-hoc com o IP 172.20.10.3 (se ainda nao estiver);
#   2. espera que os dois Pi respondam e descobre qual e o do AlphaBot (N1)
#      pelo MAC — assim nao importa qual dos dois tem o .1 ou o .2;
#   3. arranca a mesh nos 3 nos (switch-all.sh: N1 e N2 por SSH, N3 em background);
#   4. espera a mesh convergir (ping ao overlay 10.0.0.1);
#   5. arranca o robo (alphabot_node.py) no N1 por SSH, se nao estiver a correr;
#   6. abre a base station neste terminal.
# Depois: escrever "arp" / "l3" (ou Square / Circle) na base station.
#
# Pre-requisitos: Pi em ad-hoc com um IP 172.20.10.x (ver DEMO.md), SSH por
# chave para os Pi, repo em Documents/RoutingMesh nos Pi com os binarios
# compilados (make both).
#
# Env (opcional): MESH_IFACE (wlp5s0)  REMOTE_USER (pi)  REMOTE_DIR
#                 N1_MAC (MAC do wlan0 do Pi do AlphaBot)
#                 WAIT_PI / WAIT_MESH (segundos, 120)  DRY_RUN=1

set -u

METHOD=${1:-l3}
case "$METHOD" in
    l3|arp) ;;
    *) echo "Uso: $0 [l3|arp]"; exit 1 ;;
esac

DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=${DRY_RUN:-0}
REMOTE_USER=${REMOTE_USER:-pi}
REMOTE_DIR=${REMOTE_DIR:-Documents/RoutingMesh}
N1_MAC=${N1_MAC:-d8:3a:dd:33:f3:be}
WAIT_PI=${WAIT_PI:-120}
WAIT_MESH=${WAIT_MESH:-120}
if [ -n "${MESH_IFACE:-}" ]; then
    IFACE=$MESH_IFACE
elif [ -d /sys/class/net/wlp5s0 ]; then
    IFACE=wlp5s0
else
    IFACE=wlan0
fi

say()  { echo "[demo] $*"; }
fail() { echo "[demo] ERRO: $*"; exit 1; }
run()  { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi; }

SSH_BASE=(ssh -n -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new)

wait_ping() {   # $1 = host   $2 = segundos
    local i=0
    [ "$DRY_RUN" = "1" ] && return 0
    until ping -c1 -W1 "$1" >/dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -ge "$2" ] && return 1
        sleep 1
    done
}

mac_of() {      # MAC do wlan0 de um Pi
    "${SSH_BASE[@]}" "$REMOTE_USER@$1" cat /sys/class/net/wlan0/address 2>/dev/null
}

# ── 0. sudo (a password fica em cache neste terminal) ─────────────
say "sudo -v (password do PC)"
run sudo -v || fail "sudo falhou"

# ── 1. Wi-Fi do PC em ad-hoc ──────────────────────────────────────
if [ "$DRY_RUN" = "1" ] || ! iwconfig "$IFACE" 2>/dev/null | grep -q "Mode:Ad-Hoc"; then
    say "a por $IFACE em ad-hoc (o PC fica sem internet)"
    run sudo systemctl stop NetworkManager
    run sudo systemctl stop wpa_supplicant
    run sudo ip link set "$IFACE" down
    run sudo iwconfig "$IFACE" mode ad-hoc
    run sudo iwconfig "$IFACE" essid manet-mesh
    run sudo iwconfig "$IFACE" channel 6
    run sudo ip link set "$IFACE" up
fi
run sudo iwconfig "$IFACE" power off
run sudo ip addr replace 172.20.10.3/28 dev "$IFACE"

# ── 2. Pi ao alcance e qual e qual ────────────────────────────────
say "a esperar pelos Pi (ate ${WAIT_PI}s) ..."
for ip in 172.20.10.1 172.20.10.2; do
    wait_ping "$ip" "$WAIT_PI" || fail "o Pi $ip nao responde. Confirma o ad-hoc e o IP nele (DEMO.md)."
done

N1_IP=172.20.10.1
N2_IP=172.20.10.2
if [ "$DRY_RUN" != "1" ]; then
    m1=$(mac_of 172.20.10.1); m1=${m1,,}
    m2=$(mac_of 172.20.10.2); m2=${m2,,}
    if   [ "$m1" = "${N1_MAC,,}" ]; then
        :
    elif [ "$m2" = "${N1_MAC,,}" ]; then
        N1_IP=172.20.10.2; N2_IP=172.20.10.1
        say "AVISO: IPs dos Pi trocados — o AlphaBot (N1) esta em $N1_IP"
    else
        say "AVISO: nenhum Pi tem o MAC $N1_MAC; a assumir .1 = N1"
    fi
fi

# ── 3. Mesh nos 3 nos ─────────────────────────────────────────────
say "a arrancar a mesh em ${METHOD^^} ..."
env LOCAL_BG=1 N1_HOST="$N1_IP" N2_HOST="$N2_IP" "$DIR/switch-all.sh" "$METHOD" \
    || fail "switch-all.sh falhou"

# ── 4. Esperar a mesh convergir ───────────────────────────────────
say "a esperar que a mesh convirja (ate ${WAIT_MESH}s) ..."
wait_ping 10.0.0.1 "$WAIT_MESH" \
    || fail "a mesh nao convergiu (10.0.0.1 nao responde). Logs: /tmp/meshnode_<id>.log nos nos"

# ── 5. Robo no N1 ─────────────────────────────────────────────────
# '[a]lphabot_node.py': o padrao nao apanha a propria linha de comando do shell
say "a arrancar o robo no N1 ..."
started=0
for h in 10.0.0.1 "$N1_IP"; do
    if run "${SSH_BASE[@]}" "$REMOTE_USER@$h" \
        "cd $REMOTE_DIR && (pgrep -f '[a]lphabot_node.py' >/dev/null || setsid nohup sudo -n python3 alphabot_node.py </dev/null >/tmp/alphabot.log 2>&1 &)"; then
        started=1; break
    fi
done
[ "$started" = "1" ] || fail "nao consegui arrancar o robo por SSH (log no N1: /tmp/alphabot.log)"

# ── 6. Base station ───────────────────────────────────────────────
say "pronto. A abrir a base station: escreve 'arp' ou 'l3' (ou Square / Circle)."
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] exec python3 $DIR/base_station.py"
    exit 0
fi
cd "$DIR" || exit 1
exec python3 base_station.py
