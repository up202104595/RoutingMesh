# Demonstração: método L3 vs método ARP

Tudo se faz a partir do **PC (base station, N3)**, com **3 terminais** e SSH
para os dois Pi. N1 = Pi do AlphaBot (`172.20.10.1`), N2 = Pi do relay
(`172.20.10.2`), N3 = PC (`172.20.10.3`). Pastas: `~/Documentos/RoutingMesh`
no PC e `~/Documents/RoutingMesh` nos Pi.

| | Método L3 (o teu) | Método ARP (Ana Morais) |
|---|---|---|
| Daemon | `run-node.sh l3 <id> 3` | `run-node.sh arp <id> 3` |
| **Vídeo da aplicação** | **UDP** (`... udp`) | **TCP** (`... tcp`) |
| Porquê | a mesh já repõe perdas no 1.º salto (TCP entre vizinhos) | o relay é transparente e não repõe perdas, por isso é a aplicação que dá a fiabilidade |

(Dentro da mesh, o ARP leva os pacotes em datagramas UDP até ao destino final;
o que é TCP é o vídeo da aplicação.)

## Os 3 terminais, todos no PC

| Terminal | Para quê | Fica |
|---|---|---|
| **T1 — Mesh N3** | corre o daemon do N3 (vê aqui o `[GATE] Sync convergiu`) | aberto, em primeiro plano |
| **T2 — Controlo** | arranca/pára o N1, o N2 e o robô por SSH | comandos que regressam logo |
| **T3 — Base** | `base_station.py` (vídeo + comando do jogo) | aberto, em primeiro plano |

Em **T2**, uma vez por sessão, define estas variáveis (encurtam os comandos):
```bash
N1=pi@172.20.10.1; N2=pi@172.20.10.2; D='cd Documents/RoutingMesh'
```

## Preparação (uma vez)

1. **Código atualizado nos 3 sítios.** Os ficheiros mais recentes são
   `src/`, `include/`, `Makefile`, `run-node.sh`, `alphabot_node.py`,
   `base_station.py`. Do PC para os Pi:
   ```bash
   for ip in 172.20.10.1 172.20.10.2; do
     rsync -av src include Makefile run-node.sh alphabot_node.py pi@$ip:Documents/RoutingMesh/
   done
   ```
2. **Compilar** (cada comando compila os dois binários: `meshnode_ipforward` e `meshnode_arp`):
   ```bash
   ssh $N1 "$D && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
   ssh $N2 "$D && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
   cd ~/Documentos/RoutingMesh && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0
   ```
3. **Desligar os serviços antigos** (em cada Pi; no N1 inclui o `alphabot`):
   ```bash
   ssh $N1 "sudo systemctl disable --now meshnode meshnode-metrics alphabot"
   ssh $N2 "sudo systemctl disable --now meshnode meshnode-metrics"
   ```
4. **Ad-hoc e IPs** nos três nós (têm de se pingar). Perdem-se ao reiniciar.
   Nos Pi, no ecrã de cada um (`.1` no AlphaBot, `.2` no relay):
   ```bash
   sudo systemctl stop NetworkManager
   sudo ip link set wlan0 down
   sudo iwconfig wlan0 mode ad-hoc
   sudo iwconfig wlan0 essid manet-mesh
   sudo iwconfig wlan0 channel 6
   sudo ip link set wlan0 up
   sudo iwconfig wlan0 power off
   sudo ip addr add 172.20.10.1/28 dev wlan0      # ou 172.20.10.2/28
   ```
   No PC (fica sem internet):
   ```bash
   sudo systemctl stop NetworkManager; sudo systemctl stop wpa_supplicant
   sudo ip link set wlp5s0 down
   sudo iwconfig wlp5s0 mode ad-hoc
   sudo iwconfig wlp5s0 essid manet-mesh
   sudo iwconfig wlp5s0 channel 6
   sudo ip link set wlp5s0 up
   sudo iwconfig wlp5s0 power off
   sudo ip addr add 172.20.10.3/28 dev wlp5s0
   ```
5. **SSH por chave** (já feito): `ssh -o BatchMode=yes $N1 hostname` e `$N2`
   têm de responder sem pedir password.

## Demonstração 1 — método L3 (vídeo UDP)

1. **T1:** `cd ~/Documentos/RoutingMesh && sudo ./run-node.sh l3 3 3`
2. **T2:**
   ```bash
   ssh $N1 "$D && sudo nohup ./run-node.sh l3 1 3 >/dev/null 2>&1 </dev/null &"
   ssh $N2 "$D && sudo nohup ./run-node.sh l3 2 3 >/dev/null 2>&1 </dev/null &"
   ```
3. Espera (~10-20 s) até **T1** mostrar `[GATE] Sync convergiu — trafego de dados ADMITIDO`.
4. **T3:** `cd ~/Documentos/RoutingMesh && python3 base_station.py udp`
5. **T2:** `ssh $N1 "$D && sudo nohup python3 alphabot_node.py udp >/dev/null 2>&1 </dev/null &"`
   (o robô espera 10 s antes de começar o vídeo).

## Demonstração 2 — método ARP (vídeo TCP)

É a mesma sequência, com **`arp`** nos `run-node.sh` e **`tcp`** nos dois
programas de vídeo. A base tem de estar a correr antes do robô (em TCP é ela
que escuta).

1. **T1:** `cd ~/Documentos/RoutingMesh && sudo ./run-node.sh arp 3 3`
2. **T2:**
   ```bash
   ssh $N1 "$D && sudo nohup ./run-node.sh arp 1 3 >/dev/null 2>&1 </dev/null &"
   ssh $N2 "$D && sudo nohup ./run-node.sh arp 2 3 >/dev/null 2>&1 </dev/null &"
   ```
3. Espera pelo `[GATE] ... ADMITIDO` em **T1**.
4. **T3:** `cd ~/Documentos/RoutingMesh && python3 base_station.py tcp`
5. **T2:** `ssh $N1 "$D && sudo nohup python3 alphabot_node.py tcp >/dev/null 2>&1 </dev/null &"`

## Trocar de método a meio (ex.: L3 → ARP)

O `run-node.sh` já pára o daemon anterior e limpa o que ficou (inclui as
entradas ARP do método ARP), por isso basta arrancar o novo.

1. **T3:** Ctrl+C na base station.
2. **T2:** pára o robô: `ssh $N1 "sudo pkill -f '[a]lphabot_node.py'"`
3. **T1:** Ctrl+C no daemon (duas vezes se não sair) e arranca o do outro
   método: `sudo ./run-node.sh arp 3 3`
4. **T2:** `ssh $N1 ... run-node.sh arp 1 3` e `ssh $N2 ... run-node.sh arp 2 3`
   (os comandos da Demonstração 2).
5. Espera pelo `[GATE] ... ADMITIDO` e arranca a base e o robô com o
   transporte do novo método (`tcp` para ARP, `udp` para L3).

## Mostrar o relay a reagir a uma falha

Corta a ligação direta N1↔N3 **nos dois lados**, só a receção e por MAC
(o corte por IP também mataria o tráfego que passa pelo N2):
```bash
# T2 (N1 deixa de ouvir o N3):
ssh $N1 "sudo iptables -I INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP"
# PC (N3 deixa de ouvir o N1):
sudo iptables -I INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP
```
Em ~3 s a rota passa pelo N2 e o vídeo continua. Para confirmar, no N1:
- ARP: `ssh $N1 "arp -an | grep 172.20.10.3"` mostra o MAC do N2
  (`2c:cf:67:79:93:50`).
- L3: `ssh $N1 "ip route | grep 10.0.0.3"` mostra `via 10.0.0.2`.

Repor (só limpa a tabela INPUT, não mexe nas regras da mesh):
```bash
ssh $N1 "sudo iptables -F INPUT"
sudo iptables -F INPUT
```

## Parar tudo

```bash
# T3: Ctrl+C na base.      T1: Ctrl+C no daemon (ou o comando abaixo).
ssh $N1 "sudo pkill -f '[a]lphabot_node.py'; sudo pkill -INT -f '[m]eshnode_'; sleep 3; sudo pkill -KILL -f '[m]eshnode_'"
ssh $N2 "sudo pkill -INT -f '[m]eshnode_'; sleep 3; sudo pkill -KILL -f '[m]eshnode_'"
```
Se o daemon do PC não sair com Ctrl+C: `sudo pkill -KILL -f '[m]eshnode_'`.
O arranque seguinte (`run-node.sh`) limpa a TUN, as rotas e as entradas ARP.

## Opcional: trocar de método só escrevendo na base station

A base station também aceita `arp` / `l3` (ou Square / Circle no comando): reinicia a
mesh nos 3 nós por SSH com `run-node.sh` e muda o transporte do vídeo sozinha.
Precisa de `sudo -v` no terminal da base e de SSH por chave. Ainda **não foi
testado em hardware**; o procedimento manual acima é o testado.

## Se algo falhar

- **`Network is unreachable` / `No route to host`:** o PC ou o Pi perdeu o IP ou o
  ad-hoc (passo 4 da preparação). Confirma com `ping -c 3 172.20.10.1`.
- **Vídeo não aparece:** confirma que a base foi arrancada antes do robô
  (TCP), que os dois usam o mesmo transporte, e que o `[GATE]` já apareceu.
- **Câmara ocupada ao reiniciar o robô:** `ssh $N1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"`.
- **Blocos pretos no ARP:** hipótese de fragmentação dos pacotes de 1500 bytes.
  Testa `sudo ip link set tun<id> mtu 1400` nos três nós, reinicia o vídeo e compara.
