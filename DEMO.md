# Demonstração: método L3 vs método ARP

Máquinas (todas em ad-hoc, rede `172.20.10.0/28`):

| | Máquina | IP | Utilizador |
|---|---|---|---|
| **N1** | Pi do AlphaBot (robô) | `172.20.10.1` | `pi` |
| **N2** | Pi do relay | `172.20.10.2` | `pi` |
| **N3** | PC (base station) | `172.20.10.3` | `miguel` |

Pastas: `~/Documentos/RoutingMesh` no PC e `~/Documents/RoutingMesh` nos Pi.

> **Em que máquina corro isto?** Os comandos das secções **A** e **B** correm **no
> PC** (prompt `miguel@miguel-Bravo-...`). Os `ssh pi@172.20.10.x` levam-te aos Pi.
> Se o prompt for `pi@raspberrypi` estás **dentro de um Pi** (sem internet e sem
> chave SSH para o outro Pi): sai com `exit` e volta ao PC. Nunca corras no Pi os
> comandos do PC (`wlp5s0`, `rsync`, `make both ... wlp5s0`).

| | Método L3 (o teu) | Método ARP (Ana Morais) |
|---|---|---|
| Daemon | `sudo ./run-node.sh l3 <id> 3` | `sudo ./run-node.sh arp <id> 3` |
| **Vídeo da aplicação** | **UDP** (`... udp`) | **TCP** (`... tcp`) |

## Os 5 terminais

Cada processo corre **num terminal próprio, em primeiro plano**, para veres os
logs e os erros. Para parar: **Ctrl+C** nesse terminal.

| Terminal | Onde | O que correr |
|---|---|---|
| **T1** | PC | `cd ~/Documentos/RoutingMesh` e `sudo ./run-node.sh l3 3 3` |
| **T2** | N1 | `ssh pi@172.20.10.1`, depois `cd Documents/RoutingMesh` e `sudo ./run-node.sh l3 1 3` |
| **T3** | N2 | `ssh pi@172.20.10.2`, depois `cd Documents/RoutingMesh` e `sudo ./run-node.sh l3 2 3` |
| **T4** | N1 (2.ª sessão) | `ssh pi@172.20.10.1`, depois `cd Documents/RoutingMesh` e `sudo python3 alphabot_node.py udp` |
| **T5** | PC | `cd ~/Documentos/RoutingMesh` e `python3 base_station.py udp` |

Ordem: **T1, T2, T3** (qualquer ordem) → espera o `[GATE] Sync convergiu` em T1 →
**T5** (base) → **T4** (robô). Para ARP troca `l3` por `arp` e `udp` por `tcp`.
Um 6.º terminal do PC serve para os comandos soltos do teste de quebra.

---

# A. Preparação (uma vez)

Se já está feita, passa à **B**.

## A1. Código e compilação

Na **pasta do repo do PC** (o `rsync` usa caminhos relativos):
```bash
cd ~/Documentos/RoutingMesh
rsync -av src include deploy Makefile run-node.sh alphabot_node.py pi@172.20.10.1:Documents/RoutingMesh/
rsync -av src include deploy Makefile run-node.sh alphabot_node.py pi@172.20.10.2:Documents/RoutingMesh/
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
chmod +x run-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0
```
Cada `make both` gera `meshnode_ipforward` (L3) e `meshnode_arp` (ARP); procura
`Gerado: meshnode_ipforward e meshnode_arp`. Os avisos do `wifi_quality.c` são normais.

Confirma que cada máquina tem o que precisa:
```bash
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && ls -l run-node.sh meshnode_ipforward meshnode_arp alphabot_node.py"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && ls -l run-node.sh meshnode_ipforward meshnode_arp"
ls -l run-node.sh meshnode_ipforward meshnode_arp base_station.py
```
O `run-node.sh` tem de ter `x` nas permissões (`-rwxr-xr-x`).

## A2. Serviço de ad-hoc nos Pi (para arrancarem sempre em ad-hoc)

Sem isto, ao ligar o Pi fica em Wi-Fi normal e o PC não o alcança. O serviço
`adhoc` põe cada Pi em ad-hoc com o IP do seu `NODE_ID`, ativa o SSH e desliga os
serviços antigos (`meshnode`, `meshnode-metrics`, `alphabot`).

Na pasta do repo do PC, com os Pi alcançáveis:
```bash
cd ~/Documentos/RoutingMesh
# 1. o ID fica gravado no Pi: confirma qual é qual
ssh pi@172.20.10.1 "cat /sys/class/net/wlan0/address"     # d8:3a:dd:33:f3:be (AlphaBot)
ssh pi@172.20.10.2 "cat /sys/class/net/wlan0/address"     # 2c:cf:67:79:93:50 (relay)
# 2. envia o deploy/
rsync -av deploy pi@172.20.10.1:Documents/RoutingMesh/
rsync -av deploy pi@172.20.10.2:Documents/RoutingMesh/
# 3. instala (1 e 2 são o NODE_ID) — cada um acaba com "Feito. Reinicia o Pi"
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && sudo bash deploy/install-adhoc.sh 1"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && sudo bash deploy/install-adhoc.sh 2"
# 4. confirma e reinicia
ssh pi@172.20.10.1 "cat /etc/routingmesh/node.conf; systemctl is-enabled adhoc meshnode"
ssh pi@172.20.10.2 "cat /etc/routingmesh/node.conf; systemctl is-enabled adhoc meshnode"
ssh pi@172.20.10.1 "sudo reboot"
ssh pi@172.20.10.2 "sudo reboot"
```
Esperado em cada Pi: `NODE_ID=<id>`, `adhoc` **enabled**, `meshnode` **disabled**.

Efeito secundário: o Pi deixa de ligar ao Wi-Fi normal. Para lhe dar internet
(ex.: `git pull`): `ssh pi@172.20.10.1 "sudo systemctl disable adhoc; sudo rm -f /etc/NetworkManager/conf.d/90-manet-unmanaged.conf; sudo reboot"`.

## A3. SSH por chave

```bash
ssh -o BatchMode=yes pi@172.20.10.1 hostname      # tem de responder sem pedir password
ssh -o BatchMode=yes pi@172.20.10.2 hostname
```
Se não, `ssh-copy-id pi@172.20.10.1` e `.2`. Se avisar `HOST IDENTIFICATION HAS CHANGED`:
`ssh-keygen -f ~/.ssh/known_hosts -R 172.20.10.1` (e `.2`).

---

# B. Todos os dias: ligar a rede

**Pi (N1 e N2):** basta ligá-los. Com o serviço da A2 arrancam sozinhos em
ad-hoc, com o IP certo e o SSH ativo (~1 minuto).

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
ping -c 3 172.20.10.1
ping -c 3 172.20.10.2
ssh pi@172.20.10.1 "systemctl is-active adhoc; ip -4 addr show wlan0 | grep inet"
ssh pi@172.20.10.2 "systemctl is-active adhoc; ip -4 addr show wlan0 | grep inet"
```
Esperado: os `ping` respondem e cada Pi mostra `active` e o seu IP. Se não
respondem ao fim de 2 minutos, vê os `Cell:` do `iwconfig` nos três nós: têm de
ser iguais.

**No fim do dia, voltar o PC ao Wi-Fi normal:**
```bash
sudo ip addr flush dev wlp5s0; sudo ip link set wlp5s0 down
sudo iwconfig wlp5s0 mode managed; sudo ip link set wlp5s0 up
sudo systemctl start NetworkManager
```

---

# C. Demonstração 1 — método L3 (vídeo UDP)

Abre 5 terminais e corre, **por esta ordem**:

1. **T1 (PC):**
   ```bash
   cd ~/Documentos/RoutingMesh
   sudo ./run-node.sh l3 3 3
   ```
2. **T2 (N1):**
   ```bash
   ssh pi@172.20.10.1
   cd Documents/RoutingMesh
   sudo ./run-node.sh l3 1 3
   ```
3. **T3 (N2):**
   ```bash
   ssh pi@172.20.10.2
   cd Documents/RoutingMesh
   sudo ./run-node.sh l3 2 3
   ```
4. Espera (~10-20 s) até **T1** mostrar `[GATE] Sync convergiu — trafego de dados ADMITIDO`.
5. **T5 (PC):**
   ```bash
   cd ~/Documentos/RoutingMesh
   python3 base_station.py udp
   ```
6. **T4 (N1):**
   ```bash
   ssh pi@172.20.10.1
   cd Documents/RoutingMesh
   sudo python3 alphabot_node.py udp
   ```
   (o robô espera 10 s antes de começar o vídeo).

# D. Demonstração 2 — passar para o método ARP (vídeo TCP)

1. **Pára tudo:** Ctrl+C em **T5, T4, T1, T2, T3** (duas vezes no daemon se não
   sair). O Ctrl+C no robô (T4) pára a stream e a câmara.
2. **Arranca de novo, igual à Demonstração 1, mas com `arp` e `tcp`:**
   - **T1 (PC):** `cd ~/Documentos/RoutingMesh` e `sudo ./run-node.sh arp 3 3`
   - **T2 (N1):** `ssh pi@172.20.10.1`, `cd Documents/RoutingMesh` e `sudo ./run-node.sh arp 1 3`
   - **T3 (N2):** `ssh pi@172.20.10.2`, `cd Documents/RoutingMesh` e `sudo ./run-node.sh arp 2 3`
3. Espera o `[GATE] ... ADMITIDO` em **T1**. A base arranca **antes** do robô (em
   TCP é ela que escuta):
   - **T5 (PC):** `python3 base_station.py tcp`
   - **T4 (N1):** `sudo python3 alphabot_node.py tcp`

O `run-node.sh` pára o daemon anterior e limpa a TUN, as rotas e as entradas ARP,
por isso não precisas de limpar nada à mão. **Voltar ao L3:** o mesmo, com `l3` e `udp`.

---

# E. Testar a quebra de ligação (o relay a assumir)

Com o vídeo a correr nos dois sentidos, corta-se a ligação direta N1↔N3 e
vê-se a mesh passar a encaminhar pelo N2. **O mesmo comando serve para os dois
métodos.**

MACs: N1 `d8:3a:dd:33:f3:be`, N2 `2c:cf:67:79:93:50`, N3 `f0:9e:4a:a2:20:38`.

**1. Antes de cortar** (a "foto" da rota direta):
```bash
ssh pi@172.20.10.1 "ip route | grep '^10.0.0.3'; arp -an | grep 172.20.10.3"
```
- L3: `10.0.0.3 via 10.0.0.3 dev tun1` (direto).
- ARP: `172.20.10.3 ... at f0:9e:4a:a2:20:38 ... PERM` (MAC do N3).

**2. Cortar**, só a receção, **por MAC, nos dois lados**. As regras repõem-se
**sozinhas ao fim de 60 s**, porque com o link cortado o PC já não chega ao N1 por
`172.20.10.1` e não conseguia repô-las por SSH:
```bash
sudo -v
ssh pi@172.20.10.1 "sudo nohup sh -c 'iptables -I INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP; sleep 60; iptables -D INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP' >/dev/null 2>&1 &"
sudo nohup sh -c 'iptables -I INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP; sleep 60; iptables -D INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP' >/dev/null 2>&1 &
```
Durante os 60 s, **o `ssh pi@172.20.10.1` direto deixa de funcionar** (o corte apanha
também o SSH), e os terminais T2 e T4, que são SSH direto ao N1, **ficam parados**:
os processos continuam a correr no N1 e os terminais retomam quando a regra se repuser.
Espera ~3 s: o nó só é dado como perdido ao fim de `MAX_AGE = 2 s`, depois a árvore
é recalculada. O vídeo pára um instante e volta.

**3. Confirmar que passou pelo N2** (dentro dos 60 s). Ao N1 vai-se **pelo N2**
(`-J`), porque o caminho direto está cortado:
```bash
ssh -J pi@172.20.10.2 pi@172.20.10.1 "ip route | grep '^10.0.0.3'; arp -an | grep 172.20.10.3"
# relay a trabalhar: o contador da regra com pacotes tem de subir entre as duas leituras
ssh pi@172.20.10.2 "sudo iptables -vnxL FORWARD | sed -n 3,5p; sleep 3; sudo iptables -vnxL FORWARD | sed -n 3,5p"
```
- L3: `10.0.0.3 via 10.0.0.2 dev tun1`. No N2 sobe a regra `tun2 → wlan0`
  (o daemon reinjeta o pacote na TUN e o kernel envia-o por `wlan0`).
- ARP: o MAC de `172.20.10.3` passa a ser o do N2. No N2 sobe a regra
  `wlan0 → wlan0` (o kernel reencaminha o datagrama; o daemon do N2 não vê nada).
- Nos dois: o vídeo continua no ecrã da base.

**4. Repor a ligação.** Repõe-se sozinha aos 60 s. Para repor antes:
```bash
sudo iptables -F INPUT                                                  # PC
ssh -J pi@172.20.10.2 pi@172.20.10.1 "sudo iptables -F INPUT"           # N1, pelo N2
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

**Ctrl+C em cada um dos 5 terminais** (duas vezes no daemon se não sair).

Se algum ficar preso, de um 6.º terminal do PC:
```bash
ssh pi@172.20.10.1 "sudo pkill -f '[a]lphabot_node.py'; sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'; sudo pkill -KILL -f '[m]eshnode_'"
ssh pi@172.20.10.2 "sudo pkill -KILL -f '[m]eshnode_'"
sudo pkill -KILL -f '[m]eshnode_'
```
O `rpicam-vid` e o `ffmpeg` têm de morrer também: se ficarem, prendem a câmara e
continuam a enviar com o transporte antigo.

**Depois de uma corrida em ARP, limpa as entradas ARP permanentes.** O método ARP
associa o IP de cada destino ao MAC do vizinho que faz de next-hop (por isso dois
IPs podem aparecer com o **mesmo MAC**), e o `meshnode` **não as apaga ao sair**.
Se ficarem, o `ping` e o SSH entre os nós falham ou vão pelo caminho errado:
```bash
for a in 172.20.10.1 172.20.10.2; do sudo ip neigh del $a dev wlp5s0 2>/dev/null; done
ssh pi@172.20.10.1 'for a in 172.20.10.1 172.20.10.2 172.20.10.3; do sudo ip neigh del $a dev wlan0 2>/dev/null; done'
ssh pi@172.20.10.2 'for a in 172.20.10.1 172.20.10.2 172.20.10.3; do sudo ip neigh del $a dev wlan0 2>/dev/null; done'
```
O `run-node.sh` também as limpa, mas só quando o nó arranca. Para ver o estado:
`ip neigh show dev wlp5s0` (nos Pi, `wlan0`); `PERMANENT` com o MAC errado é lixo.

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

Como cada processo corre em primeiro plano, a mensagem de erro aparece no
próprio terminal. As mais comuns:

- **O PC não pinga um Pi, mas os Pi pingam-se entre si; ou dois IPs com o mesmo MAC no
  `ip neigh`:** entradas ARP permanentes que o método ARP deixou. Limpa-as (secção F).
- **`Connection timed out` ao N1 durante o corte de ligação:** é o corte a funcionar
  (apanha o SSH direto). Vai pelo N2: `ssh -J pi@172.20.10.2 pi@172.20.10.1 ...`.
- **`Permission denied` ao correr `./run-node.sh`:** `chmod +x run-node.sh` nessa máquina.
- **`No such file ... meshnode_ipforward` / `meshnode_arp`:** falta compilar
  (A1, `make both ...`) nessa máquina.
- **`No such file ... run-node.sh`:** falta enviar o código (A1, `rsync`).
- **`rsync: link_stat ... failed`:** não estás na pasta do repo (`cd ~/Documentos/RoutingMesh`).
- **`Network is unreachable` / `No route to host`:** o PC perdeu o IP ou o
  ad-hoc (ver B). Confirma com `ping -c 3 172.20.10.1`.
- **Vídeo não aparece:** a base tem de arrancar antes do robô (TCP), os dois usam
  o mesmo transporte, e o `[GATE]` já tem de ter aparecido em T1.
- **Câmara ocupada ao reiniciar o robô:** `ssh pi@172.20.10.1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"`.
- **Blocos pretos no ARP:** hipótese de fragmentação dos pacotes de 1500 bytes.
  Testa `sudo ip link set tun<id> mtu 1400` nos três nós, reinicia o vídeo e compara.
