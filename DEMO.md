# Demonstração: trocar de método na base station

Na demonstração só se mexe na base station (PC, N3): escreve-se `arp` ou `l3`
(ou carrega-se Square / Circle no comando) e os três nós trocam de método.

| Método | Como o relay funciona | Vídeo |
|---|---|---|
| `l3`  | TCP ao next-hop; o relay reinjeta na TUN e o kernel encaminha por rota `/32` | UDP |
| `arp` | UDP ao destino final; o kernel dos relays encaminha por entradas ARP (método da Ana) | TCP |

## Preparação (uma vez)

1. **Compilar em cada nó** (PC e os dois Pi), na pasta do repo:
   ```bash
   make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0     # Pi
   make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0    # PC
   ```
2. **Desligar os serviços antigos** em cada nó:
   `sudo systemctl disable --now meshnode meshnode-metrics`
3. **Ad-hoc configurado** nos três nós (NetworkManager parado), como no guia.
4. **SSH por chave** do PC para os Pi (com os nós ao alcance uns dos outros):
   ```bash
   ssh-copy-id pi@172.20.10.1
   ssh-copy-id pi@172.20.10.2
   ```
   Os Pi precisam de `sudo` sem password (o utilizador `pi` já tem). Se o
   utilizador ou a pasta forem outros: `REMOTE_USER=... REMOTE_DIR=...`
   antes de `./switch-all.sh` (ou editar as duas linhas no topo do script).
5. **Ensaio sem rede:** `DRY_RUN=1 ./switch-all.sh arp` mostra o que faria.

## Arranque (tudo a partir do PC)

Com os Pi ligados, em ad-hoc e com um IP `172.20.10.x` (ver abaixo), no PC,
na pasta do repo:

```bash
./demo.sh          # arranca em L3;  ./demo.sh arp  arranca em ARP
```

Faz, por esta ordem: põe o Wi-Fi do PC em ad-hoc (`172.20.10.3`); espera pelos
Pi e descobre qual é o do AlphaBot pelo MAC (não importa qual tem o `.1` ou o
`.2`); arranca a mesh nos 3 nós; espera que convirja; arranca o robô
(`alphabot_node.py`) no N1 por SSH; e abre a base station neste terminal.
Pede a password do `sudo` do PC no início. Os logs ficam em
`/tmp/meshnode_<id>.log` e `/tmp/alphabot.log` nos nós.

`DRY_RUN=1 ./demo.sh` mostra o que faria, sem executar.

**Depois de reiniciar um Pi**, o ad-hoc e o IP perdem-se e o PC deixa de o
alcançar. Repõe-nos nesse Pi (uma vez por arranque):
```bash
sudo systemctl stop NetworkManager
sudo ip link set wlan0 down
sudo iwconfig wlan0 mode ad-hoc
sudo iwconfig wlan0 essid manet-mesh
sudo iwconfig wlan0 channel 6
sudo ip link set wlan0 up
sudo iwconfig wlan0 power off
sudo ip addr add 172.20.10.1/28 dev wlan0      # .1 ou .2 (tanto faz qual)
```
Se o MAC do Pi do AlphaBot não for `d8:3a:dd:33:f3:be`, define
`N1_MAC=<mac>` ao correr o `demo.sh`.

## Durante a demonstração

| Ação na base | Efeito |
|---|---|
| escrever `arp` + Enter, ou **Square** | troca para ARP (vídeo passa a TCP) |
| escrever `l3` + Enter, ou **Circle** | troca para L3 (vídeo passa a UDP) |
| escrever `status` | mostra o método e o transporte do vídeo |

Depois de cada troca espera **10 a 20 s**: a mesh reconverge e o vídeo volta
(em TCP só reconecta quando o watchdog do robô volta a tentar).

Para mostrar o relay a reagir a uma falha, corta o link N1↔N3 por MAC nos dois
lados (`sudo iptables -I INPUT -m mac --mac-source <MAC do outro> -j DROP`) e
confirma no N1 com `arp -an | grep 172.20.10.3`. Repõe com
`sudo iptables -F INPUT` nos dois.

## Se algo falhar

- **`[SWITCH] ERRO: o sudo pede password`**: corre `sudo -v` no terminal da base.
- **`SSH para Nx falhou`**: confirma `ssh pi@10.0.0.x` à mão e a chave (passo 4).
- **Logs:** `/tmp/meshnode_<id>.log` em cada nó (no Pi: `tail -f`).
- **Vídeo não volta:** `status` na base; confirma que `alphabot_node.py` está a
  correr no robô.
- **Blocos pretos no ARP:** ainda por validar a hipótese de fragmentação; testa
  `sudo ip link set tun<id> mtu 1400` nos três nós, reinicia o vídeo e compara.
