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
| Daemon | `sudo ./tmux-node.sh l3 <id>` | `sudo ./tmux-node.sh arp <id>` |
| **Vídeo da aplicação** | **UDP** (`... udp`) | **TCP** (`... tcp`) |

## Como está montada

- **Os 3 nós correm em `tmux`**, cada um numa sessão chamada `mesh`, **em segundo
  plano**. Sobrevivem a quedas de SSH e a fechares o terminal. Arrancam-se com um
  comando por nó (`tmux-node.sh`), e só se "entra" na sessão para ver os logs.
- **2 terminais visíveis:** a **base station** (PC) e o **robô** (`alphabot_node.py`,
  por SSH ao N1).
- **Sem cortes nem bloqueios no guia:** são inseridos por ti, à mão.

| Terminal | Onde | O que corre |
|---|---|---|
| **A** | PC | arranca os 3 nós (3 comandos curtos) e depois fica a correr a **base station** |
| **B** | PC → N1 | o **robô** (`alphabot_node.py`) |

Ver um nó: `sudo tmux attach -t mesh` (no PC) ou `ssh -t pi@172.20.10.1 "sudo tmux attach -t mesh"`.
Sair sem o parar: **Ctrl+b e depois d**.

---

# A. Preparação (uma vez)

Se já está feita, passa à **B**.

## A1. Código, compilação e tmux

Na **pasta do repo do PC** (o `rsync` usa caminhos relativos):
```bash
cd ~/Documentos/RoutingMesh
rsync -av src include deploy Makefile run-node.sh tmux-node.sh alphabot_node.py pi@172.20.10.1:Documents/RoutingMesh/
rsync -av src include deploy Makefile run-node.sh tmux-node.sh alphabot_node.py pi@172.20.10.2:Documents/RoutingMesh/
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && chmod +x run-node.sh tmux-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && chmod +x run-node.sh tmux-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
chmod +x run-node.sh tmux-node.sh && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0
```
Cada `make both` gera `meshnode_ipforward` (L3) e `meshnode_arp` (ARP); procura
`Gerado: meshnode_ipforward e meshnode_arp`. Os avisos do `wifi_quality.c` são normais.

**Confirma os ficheiros e o tmux nas 3 máquinas:**
```bash
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && ls -l run-node.sh tmux-node.sh meshnode_ipforward meshnode_arp alphabot_node.py; which tmux"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && ls -l run-node.sh tmux-node.sh meshnode_ipforward meshnode_arp; which tmux"
ls -l run-node.sh tmux-node.sh meshnode_ipforward meshnode_arp base_station.py; which tmux
```
`run-node.sh` e `tmux-node.sh` têm de ter `x` (`-rwxr-xr-x`), e o `which tmux` tem de
imprimir um caminho. **Se faltar o tmux:** precisa de internet. No PC, `sudo apt install tmux`
**antes** de o pores em ad-hoc. Num Pi, dá-lhe internet (cabo Ethernet, ou desfaz o
ad-hoc como indicado em A2, "Efeito secundário") e `sudo apt install tmux`.

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

**1. Arrancar os 3 nós** (terminal **A**, no PC, na pasta do repo). Cada comando
regressa logo; o nó fica a correr numa sessão tmux:
```bash
cd ~/Documentos/RoutingMesh
sudo ./tmux-node.sh l3 3
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && sudo ./tmux-node.sh l3 1"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && sudo ./tmux-node.sh l3 2"
```
Cada um responde `[tmux-node] no <id> em l3 arrancado na sessao tmux 'mesh'`.
Se der erro (por exemplo `tmux nao esta instalado`), aparece logo no terminal.

**2. Espera a mesh convergir** (~10-20 s). Para ver o estado sem entrar nas sessões:
```bash
sudo tmux capture-pane -p -t mesh | grep -E "GATE|ERRO" | tail -3
```
Tem de aparecer `[GATE] Sync convergiu — trafego de dados ADMITIDO`. (Ou
`sudo tmux attach -t mesh` para veres tudo; sair com **Ctrl+b e d**.)

**3. Base station** (terminal **A**, o mesmo):
```bash
python3 base_station.py udp
```

**4. Robô** (terminal **B**):
```bash
ssh pi@172.20.10.1
cd Documents/RoutingMesh
sudo python3 alphabot_node.py udp
```
(o robô espera 10 s antes de começar o vídeo).

# D. Demonstração 2 — passar para o método ARP (vídeo TCP)

1. **Pára os dois programas de vídeo:** **Ctrl+C** na base (terminal A) e no robô
   (terminal B; o Ctrl+C no robô pára a stream e a câmara).
2. **Troca os 3 nós para ARP.** O `tmux-node.sh` termina a sessão anterior e o
   `run-node.sh` limpa a TUN, as rotas e as entradas ARP. No terminal **A**:
   ```bash
   sudo ./tmux-node.sh arp 3
   ssh pi@172.20.10.1 "cd Documents/RoutingMesh && sudo ./tmux-node.sh arp 1"
   ssh pi@172.20.10.2 "cd Documents/RoutingMesh && sudo ./tmux-node.sh arp 2"
   ```
3. Espera o `[GATE] ... ADMITIDO` (`sudo tmux capture-pane -p -t mesh | grep -E "GATE|ERRO" | tail -3`).
4. A base arranca **antes** do robô (em TCP é ela que escuta):
   - **A:** `python3 base_station.py tcp`
   - **B:** `sudo python3 alphabot_node.py tcp` (na sessão SSH ao N1, na pasta `Documents/RoutingMesh`)

**Voltar ao L3:** o mesmo com `l3` nos três `tmux-node.sh` e `udp` nos dois
programas de vídeo.

> **Cortes e bloqueios (por ti, à mão):** o corte de ligação apanha também o SSH
> direto ao N1. Os nós **continuam a correr** porque estão em tmux; o terminal B
> (robô) fica parado e retoma depois. Para falar com o N1 durante um corte, vai
> pelo N2: `ssh -J pi@172.20.10.2 pi@172.20.10.1`. Depois de uma corrida em ARP,
> limpa as entradas ARP permanentes (secção E).

---

# E. Parar tudo

**Programas de vídeo:** Ctrl+C na base (A) e no robô (B).

**Nós:** terminar as sessões tmux, nos 3 nós:
```bash
sudo tmux kill-session -t mesh
ssh pi@172.20.10.1 "sudo tmux kill-session -t mesh"
ssh pi@172.20.10.2 "sudo tmux kill-session -t mesh"
```
Se algum nó ficar vivo, ou o robô tiver ficado a prender a câmara:
```bash
sudo pkill -KILL -f '[m]eshnode_'
ssh pi@172.20.10.1 "sudo pkill -f '[a]lphabot_node.py'; sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'; sudo pkill -KILL -f '[m]eshnode_'"
ssh pi@172.20.10.2 "sudo pkill -KILL -f '[m]eshnode_'"
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

# F. Porque o L3 e o ARP fazem de maneira diferente

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

# G. Se algo falhar

- **`tmux-node.sh: Permission denied`:** `chmod +x tmux-node.sh run-node.sh` nessa máquina (A1).
- **`ERRO: o tmux nao esta instalado`:** ver A1 (precisa de internet para o instalar).
- **`ERRO: ... run-node.sh nao existe ou nao e executavel`:** falta enviar o código ou o `chmod +x` (A1).
- **Ver o que um nó escreveu, incluindo erros:** `sudo tmux capture-pane -p -t mesh | tail -30`
  (no PC) ou `ssh pi@172.20.10.1 "sudo tmux capture-pane -p -t mesh | tail -30"`. Se o
  nó terminou, a sessão fica aberta com `--- o no terminou (codigo N) ---`.
- **`no server running` / `can't find session: mesh`:** o nó não está a correr (ou foi
  parado). Arranca-o outra vez (secção C).
- **`rsync: link_stat ... failed`:** não estás na pasta do repo (`cd ~/Documentos/RoutingMesh`).
- **`Network is unreachable` / `No route to host`:** o PC perdeu o IP ou o ad-hoc
  (ver B). Confirma com `ping -c 3 172.20.10.1`.
- **O PC não pinga um Pi, mas os Pi pingam-se entre si; ou dois IPs com o mesmo MAC no
  `ip neigh`:** entradas ARP permanentes que o método ARP deixou. Limpa-as (secção E).
- **Vídeo não aparece:** a base tem de arrancar antes do robô (TCP), os dois usam
  o mesmo transporte, e o `[GATE]` já tem de ter aparecido.
- **Câmara ocupada ao reiniciar o robô:** `ssh pi@172.20.10.1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"`.
- **Blocos pretos no ARP:** hipótese de fragmentação dos pacotes de 1500 bytes.
  Testa `sudo ip link set tun<id> mtu 1400` nos três nós, reinicia o vídeo e compara.
