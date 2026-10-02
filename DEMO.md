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

| Passo | T1 (daemon N3) | T2 (controlo) | T3 (base) |
|---|---|---|---|
| 1 | `sudo ./run-node.sh <l3\|arp> 3 3` | `run-node.sh <l3\|arp> 1 3` no N1 e `... 2 3` no N2, por SSH | |
| 2 | esperar `[GATE] ... ADMITIDO` | | |
| 3 | | | `python3 base_station.py <udp\|tcp>` |
| 4 | | `alphabot_node.py <udp\|tcp>` no N1, por SSH | |

`l3` com `udp`; `arp` com `tcp`.

---

# A. Preparação (uma vez)

Se já está feita, passa à **B**.

## A1. Variáveis dos comandos (em todos os terminais)

Os comandos usam `$N1`, `$N2` e `$D`. Se estiverem vazias, o `ssh` dá
`hostname contains invalid characters` (trata o comando como nome da máquina).
Torna-as permanentes, uma vez:
```bash
cat >> ~/.bashrc <<'EOF'
export N1=pi@172.20.10.1 N2=pi@172.20.10.2 D='cd Documents/RoutingMesh'
EOF
source ~/.bashrc          # nos terminais que já estavam abertos
echo "$N1 $N2 $D"         # tem de imprimir os 3 valores
```

## A2. Código e compilação

Na **pasta do repo do PC** (o `rsync` usa caminhos relativos):
```bash
cd ~/Documentos/RoutingMesh
for ip in 172.20.10.1 172.20.10.2; do
  rsync -av src include deploy Makefile run-node.sh alphabot_node.py pi@$ip:Documents/RoutingMesh/
done
ssh $N1 "$D && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
ssh $N2 "$D && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0
```
Cada `make both` gera `meshnode_ipforward` (L3) e `meshnode_arp` (ARP); procura
`Gerado: meshnode_ipforward e meshnode_arp`. Os avisos do `wifi_quality.c` são normais.

## A3. Serviço de ad-hoc nos Pi (para arrancarem sempre em ad-hoc)

Sem isto, ao ligar o Pi fica em Wi-Fi normal e o PC não o alcança. O serviço
`adhoc` põe cada Pi em ad-hoc com o IP do seu `NODE_ID` (`.1` no AlphaBot, `.2`
no relay), ativa o SSH e desliga os serviços antigos (`meshnode`,
`meshnode-metrics`, `alphabot`). O daemon e o robô continuam a arrancar-se à mão.

Na pasta do repo do PC, com os Pi alcançáveis:
```bash
cd ~/Documentos/RoutingMesh
# 1. o ID fica gravado no Pi: confirma qual é qual
ssh $N1 "cat /sys/class/net/wlan0/address"     # d8:3a:dd:33:f3:be (AlphaBot)
ssh $N2 "cat /sys/class/net/wlan0/address"     # 2c:cf:67:79:93:50 (relay)
# 2. envia o deploy/ (já vai no rsync da A2)
rsync -av deploy pi@172.20.10.1:Documents/RoutingMesh/
rsync -av deploy pi@172.20.10.2:Documents/RoutingMesh/
# 3. instala (1 e 2 são o NODE_ID) — cada um acaba com "Feito. Reinicia o Pi"
ssh $N1 "$D && sudo bash deploy/install-adhoc.sh 1"
ssh $N2 "$D && sudo bash deploy/install-adhoc.sh 2"
# 4. confirma e reinicia
ssh $N1 "cat /etc/routingmesh/node.conf; systemctl is-enabled adhoc meshnode"
ssh $N2 "cat /etc/routingmesh/node.conf; systemctl is-enabled adhoc meshnode"
ssh $N1 "sudo reboot"; ssh $N2 "sudo reboot"
```
Esperado em cada Pi: `NODE_ID=<id>`, `adhoc` **enabled**, `meshnode` **disabled**
(no N2 o `alphabot` aparece `masked`, o que está certo).

Efeito secundário: o Pi deixa de ligar ao Wi-Fi normal. Para lhe dar internet
(ex.: `git pull`): `ssh $N1 "sudo systemctl disable adhoc; sudo rm -f /etc/NetworkManager/conf.d/90-manet-unmanaged.conf; sudo reboot"`.

## A4. SSH por chave

```bash
ssh -o BatchMode=yes $N1 hostname      # tem de responder sem pedir password
ssh -o BatchMode=yes $N2 hostname
```
Se não, `ssh-copy-id pi@172.20.10.1` e `.2`. Se avisar `HOST IDENTIFICATION HAS CHANGED`:
`ssh-keygen -f ~/.ssh/known_hosts -R 172.20.10.1` (e `.2`).

---

# B. Todos os dias: ligar a rede

**Pi (N1 e N2):** basta ligá-los. Com o serviço da A3 arrancam sozinhos em
ad-hoc, com o IP certo e com o SSH ativo (~1 minuto).

**PC (N3):** nunca arranca em ad-hoc sozinho (perdia a internet). Põe-no à mão:
```bash
sudo systemctl stop NetworkManager; sudo systemctl stop wpa_supplicant
sudo ip link set wlp5s0 down
sudo iwconfig wlp5s0 mode ad-hoc
sudo iwconfig wlp5s0 essid manet-mesh
sudo iwconfig wlp5s0 channel 6
sudo ip link set wlp5s0 up
sudo iwconfig wlp5s0 power off
sudo ip addr replace 172.20.10.3/28 dev wlp5s0
```

**Confirma antes de começar:**
```bash
ping -c 3 172.20.10.1; ping -c 3 172.20.10.2
for n in $N1 $N2; do ssh -o BatchMode=yes $n "hostname; systemctl is-active adhoc; ip -4 addr show wlan0 | grep inet"; done
```
Esperado: os dois `ping` respondem e cada Pi mostra `active` e o seu IP. Se os
`ping` não respondem ao fim de 2 minutos, vê os `Cell:` do `iwconfig` nos três
nós: têm de ser iguais.

**No fim do dia, voltar o PC ao Wi-Fi normal:**
```bash
sudo ip addr flush dev wlp5s0; sudo ip link set wlp5s0 down
sudo iwconfig wlp5s0 mode managed; sudo ip link set wlp5s0 up
sudo systemctl start NetworkManager
```

---

# C. Demonstração 1 — método L3 (vídeo UDP)

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

# D. Demonstração 2 — passar para o método ARP (vídeo TCP)

O `run-node.sh` já pára o daemon anterior e limpa o que ficou (inclui as
entradas ARP), por isso basta arrancar o novo. Com o L3 a correr:

1. **T3:** Ctrl+C na base station.
2. **T2:** pára o robô e a stream (têm de morrer os três, senão a câmara fica presa
   e continua a enviar com o transporte antigo):
   ```bash
   ssh $N1 "sudo pkill -f '[a]lphabot_node.py'; sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"
   ```
3. **T1:** Ctrl+C no daemon (duas vezes se não sair) e `sudo ./run-node.sh arp 3 3`
4. **T2:**
   ```bash
   ssh $N1 "$D && sudo nohup ./run-node.sh arp 1 3 >/dev/null 2>&1 </dev/null &"
   ssh $N2 "$D && sudo nohup ./run-node.sh arp 2 3 >/dev/null 2>&1 </dev/null &"
   ```
5. Espera pelo `[GATE] ... ADMITIDO` em **T1**. A base tem de arrancar **antes**
   do robô (em TCP é ela que escuta):
   - **T3:** `python3 base_station.py tcp`
   - **T2:** `ssh $N1 "$D && sudo nohup python3 alphabot_node.py tcp >/dev/null 2>&1 </dev/null &"`

**Voltar ao L3:** os mesmos passos com `l3` nos `run-node.sh` e `udp` nos dois
programas de vídeo. **Começar do zero em ARP:** a Demonstração 1 com `arp` e `tcp`.

# E. Testar a quebra de ligação (o relay a assumir)

Com o vídeo a correr nos dois sentidos, corta-se a ligação direta N1↔N3 e
vê-se a mesh passar a encaminhar pelo N2. **O mesmo comando serve para os dois
métodos.**

MACs: N1 `d8:3a:dd:33:f3:be`, N2 `2c:cf:67:79:93:50`, N3 `f0:9e:4a:a2:20:38`.

**1. Antes de cortar** (a "foto" da rota direta):
```bash
ssh $N1 "ip route | grep '^10.0.0.3'; arp -an | grep 172.20.10.3"
```
- L3: `10.0.0.3 via 10.0.0.3 dev tun1` (direto).
- ARP: `172.20.10.3 ... at f0:9e:4a:a2:20:38 ... PERM` (MAC do N3).

**2. Cortar**, só a receção, **por MAC, nos dois lados**:
```bash
ssh $N1 "sudo iptables -I INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP"   # N1 deixa de ouvir o N3
sudo iptables -I INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP              # N3 deixa de ouvir o N1
```
Espera ~3 s: o nó só é dado como perdido ao fim de `MAX_AGE = 2 s`, depois a
árvore é recalculada. O vídeo pára um instante e volta.

**3. Confirmar que passou pelo N2:**
```bash
ssh $N1 "ip route | grep '^10.0.0.3'; arp -an | grep 172.20.10.3"
# relay a trabalhar: o contador da regra com pacotes tem de subir entre as duas leituras
ssh $N2 "sudo iptables -vnxL FORWARD | sed -n 3,5p; sleep 3; sudo iptables -vnxL FORWARD | sed -n 3,5p"
```
- L3: `10.0.0.3 via 10.0.0.2 dev tun1`. No N2 sobe a regra `tun2 → wlan0`
  (o daemon reinjeta o pacote na TUN e o kernel envia-o por `wlan0`).
- ARP: o MAC de `172.20.10.3` passa a ser o do N2. No N2 sobe a regra
  `wlan0 → wlan0` (o kernel reencaminha o datagrama; o daemon do N2 não vê nada).
- Nos dois: o vídeo continua no ecrã da base.

**4. Repor a ligação** (limpa só a tabela INPUT, não mexe nas regras da mesh):
```bash
ssh $N1 "sudo iptables -F INPUT"
sudo iptables -F INPUT
```
Em alguns segundos a rota volta a ser direta (repete o passo 1 para ver).

**Porque se corta por MAC:** no ARP o pacote vai sempre endereçado ao destino
final (`172.20.10.3`), mesmo quando passa pelo N2; só o MAC muda a cada salto.
Cortar por IP deitava fora também o que vem via N2 e o vídeo morria em vez de
reencaminhar. O corte por MAC funciona igualmente no L3.

**O que esperar:** o L3 (vídeo UDP) retoma assim que a rota muda. O ARP (vídeo
TCP) retoma quando o TCP da aplicação voltar a enviar, que pode demorar mais. Se
no ARP o MAC de `172.20.10.3` ficar a **alternar** entre o do N3 e o do N2, é
suspeita de beacons reencaminhados a manterem a ligação direta "viva" (hipótese
ainda não confirmada). A reposição em L3 também não foi testada em hardware;
regista o que vires.

# F. Parar tudo

```bash
# T3: Ctrl+C na base.      T1: Ctrl+C no daemon (ou o último comando abaixo).
ssh $N1 "sudo pkill -f '[a]lphabot_node.py'; sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'; sudo pkill -INT -f '[m]eshnode_'; sleep 3; sudo pkill -KILL -f '[m]eshnode_'"
ssh $N2 "sudo pkill -INT -f '[m]eshnode_'; sleep 3; sudo pkill -KILL -f '[m]eshnode_'"
sudo pkill -KILL -f '[m]eshnode_'      # PC, se o Ctrl+C não chegar
```
O arranque seguinte (`run-node.sh`) limpa a TUN, as rotas e as entradas ARP.

---

# G. Porque o L3 e o ARP fazem de maneira diferente

**O que é igual nos dois** (e é por isso que a comparação é justa): a mesma
sincronização TDMA, os mesmos beacons e a mesma árvore de caminhos; a fonte lê
os pacotes da aplicação numa TUN e só transmite no **seu slot**, com o mesmo
orçamento de bytes por slot; e o relay **reencaminha logo** quando recebe, sem
esperar pelo slot dele. O pacote da aplicação só volta à aplicação no destino.

**O que é diferente é como o pacote chega ao nó seguinte e como o relay o
reencaminha:**

| | Método ARP (Ana Morais) | Método L3 (o teu) |
|---|---|---|
| Pacote enviado pela fonte | UDP, **endereçado ao destino final** | TCP, **endereçado ao next-hop** |
| O que escolhe o salto | o **MAC**: entrada ARP `IP do destino → MAC do next-hop` | o **IP**: rota de host `/32` com gateway = next-hop |
| Quem a instala | o routing, por `ioctl` na tabela ARP | o routing, por `netlink` (tabela main e tabela 200) |
| Relay | só o **kernel** (`ip_forward`); o daemon do relay não vê o pacote | o **daemon** recebe o TCP e faz `tun_write`; o kernel encaminha pela rota `/32` |
| Fiabilidade na mesh | nenhuma | no 1.º salto (TCP) |
| Vídeo da aplicação | **TCP** (a fiabilidade tem de vir da aplicação) | **UDP** (evita TCP dentro de TCP) |

**ARP, porque assim:** é o método da Ana, reproduzido como descrito na tese
dela (secções 3.2 e 3.3): o routing mantém a tabela ARP de modo a que o IP do
destino aponte para o MAC do vizinho que é o next-hop; a fonte envia um só
pacote endereçado ao destino; o kernel de cada relay encaminha-o sem a
aplicação. A comparação só é justa se o ARP for este método e não uma variante.

**L3, porque assim:** o encaminhamento é por **IP**: o routing instala rotas de
host `/32` por netlink (~50 µs por rota) e o pacote vai para o IP do next-hop,
sem depender de endereços MAC nem de manter a tabela ARP. O pacote exterior é
TCP para o next-hop, o que dá entrega fiável no 1.º salto. Como o TCP **termina**
no relay, o kernel do relay nunca vê o pacote interior; por isso o daemon faz
`tun_write` para o entregar ao kernel, e a regra `ip rule iif tunN lookup 200`
com a rota `/32` da tabela 200 manda-o logo para o `wlan0`.

**Custos de cada um** (para não ficarem por dizer): o L3 tem o daemon no
caminho do relay e teria TCP-sobre-TCP com vídeo TCP, daí o vídeo UDP; o ARP não
dá fiabilidade na mesh (daí o vídeo TCP), o datagrama de 1524 bytes é
fragmentado (hipótese dos blocos pretos) e as entradas ARP têm de ser limpas ao
trocar de método (o `run-node.sh` faz isso).

> Estas são as razões que o **código** sustenta. O que motivou cada escolha na
> altura confirma-o no capítulo 3 da tese antes de o afirmares ao professor.

# H. Opcional: trocar de método só escrevendo na base station

A base station também aceita `arp` / `l3` (ou Square / Circle no comando):
reinicia a mesh nos 3 nós por SSH com `run-node.sh` e muda o transporte do vídeo
sozinha. Precisa de `sudo -v` no terminal da base e de SSH por chave. Ainda
**não foi testado em hardware**; o procedimento manual acima é o testado.

# I. Se algo falhar

- **`hostname contains invalid characters`:** `$N1`/`$N2`/`$D` estão vazias neste
  terminal. Faz `source ~/.bashrc` (ver A1).
- **`Network is unreachable` / `No route to host`:** o PC perdeu o IP ou o
  ad-hoc (ver B). Confirma com `ping -c 3 172.20.10.1`.
- **`rsync: link_stat ... deploy failed`:** não estás na pasta do repo
  (`cd ~/Documentos/RoutingMesh`).
- **Vídeo não aparece:** a base tem de arrancar antes do robô (TCP), os dois usam
  o mesmo transporte, e o `[GATE]` já tem de ter aparecido.
- **Câmara ocupada ao reiniciar o robô:** `ssh $N1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"`.
- **Blocos pretos no ARP:** hipótese de fragmentação dos pacotes de 1500 bytes.
  Testa `sudo ip link set tun<id> mtu 1400` nos três nós, reinicia o vídeo e compara.
