# RA-TDMAs+ — RoutingMesh

Rede mesh sem fios de 3 nós com controlo de acesso ao meio TDMA (RA-TDMA),
encaminhamento dinâmico multi-hop baseado em Árvore de Expansão Mínima (MST)
e relay transparente ao nível 3 (IP) via `ip_forward` do kernel Linux.

Desenvolvido como dissertação de mestrado (MEEC, FEUP) — "Encaminhamento em
Malhas Dinâmicas de Agentes Autónomos". Caso de uso de demonstração:
teleoperação de um robot (AlphaBot2) com vídeo em tempo real, em que o
encaminhamento se adapta automaticamente à topologia (ligação direta ou via
relay) sem qualquer intervenção da aplicação.

> **Nota:** o método alternativo de relay por manipulação ARP (usado por
> outro trabalho relacionado) não faz parte deste repositório — este projeto
> usa exclusivamente `ip_forward` + rotas Netlink.

---

## 1. Arquitetura

```
N1 (Robot / AlphaBot)   ←──── TDMA ────→   N2 (Relay)
        ↑                                        ↑
        └────────────── TDMA ───────────────────→ N3 (Base Station / PC)
```

| Nó | Papel | IP Mesh (TUN) | IP Físico (wlan0) |
|----|-------|---------------|--------------------|
| N1 | Robot, fonte de vídeo | 10.0.0.1 | 172.20.10.1 |
| N2 | Relay intermédio | 10.0.0.2 | 172.20.10.2 |
| N3 | Base Station, operador | 10.0.0.3 | 172.20.10.3 |

Cada nó corre um único processo, `meshnode`, que arranca as seguintes
threads:

| Thread | Função |
|--------|--------|
| RX UDP | Recebe beacons MATRIX e atualiza a topologia conhecida |
| TX | Controla os slots TDMA; envia MATRIX (beacon) + MSG_DATA (dados) |
| TUN Reader | Lê pacotes IP da interface TUN e insere-os na `tx_queue` |
| TCP Accept | Aceita ligações TCP de peers |
| TCP Keepalive | Mantém ligações TCP vivas, deteta peers mortos |
| TCP RX (uma por peer) | Recebe MSG_DATA via TCP e entrega/reencaminha |
| Event Handler | Reage a `EVENT_TOPOLOGY_CHANGED` e recalcula o routing |
| Video Feedback (só N1) | Escuta feedback de qualidade de vídeo vindo do N3 |

A rede vive em dois planos:
- **Plano virtual (`tunN`, rede `10.0.0.0/24`)** — onde a aplicação (vídeo,
  comandos) envia e recebe pacotes IP normalmente.
- **Plano físico (`wlan0`, rede `172.20.10.0/28`, modo ad-hoc)** — por onde
  os pacotes TDMA/TCP e o relay `ip_forward` realmente circulam.

### 1.1 Protocolo TDMA

O tempo é dividido em frames de **150 ms**, com 3 slots de **50 ms** (um por
nó). Cada nó só transmite no seu slot, eliminando colisões ao nível da
aplicação. Em cada slot o nó:

1. Envia um beacon **MATRIX** via UDP broadcast — a sua matriz de adjacência
   e a link quality de cada ligação conhecida.
2. Drena a `tx_queue` e envia pacotes **MSG_DATA** (vídeo, comandos,
   telemetria) via TCP para o next-hop calculado pelo routing.

Os nós mantêm a sincronização de slots através do timestamp incluído em cada
beacon recebido dos vizinhos.

### 1.2 Descoberta de topologia e Link Quality

Cada nó mantém uma matriz de adjacência distribuída, propagada por *gossip*
nos beacons MATRIX. Cada ligação tem uma qualidade (0–100) que evolui
dinamicamente: **+3** por beacon recebido, **−40** por slot perdido — a
degradação assimétrica garante que uma ligação fraca é rapidamente
preterida, mas a recuperação é conservadora para evitar oscilação.

Uma entrada expira (`MAX_AGE = 2.0 s`) se não houver observação **direta**
do nó — reportar um nó através de um vizinho não o mantém "vivo" na vista de
quem não o ouve diretamente.

A MST é recalculada com o algoritmo de **Prim ponderado**
(`cost = 100 − link_quality`), com penalização de arestas confirmadas apenas
numa direção. Sempre que a MST muda, o sistema recalcula e instala as rotas
no kernel automaticamente.

### 1.3 Encaminhamento e relay (`ip_forward` + Netlink)

Para cada destino são instaladas duas rotas no kernel:

- **Tabela `main`** — tráfego gerado localmente (`10.0.0.X via 10.0.0.nhop
  dev tunY`). Os pacotes entram na TUN e a Thread TUN Reader envia-os por
  TCP no slot TDMA correto.
- **Tabela `200`** — tráfego de relay (`10.0.0.X via 172.20.10.nhop dev
  wlan0`), selecionada por uma regra `ip rule iif tunY lookup 200`. Um nó
  intermédio recebe o pacote via TCP, escreve-o na sua própria TUN e o
  **kernel** reencaminha-o diretamente para `wlan0` — sem passar pela
  aplicação.

O relay é **completamente transparente**: o destino final recebe o pacote
como se viesse diretamente da origem (mesmo IP de origem/destino).

O routing (listas ligadas construídas por DFS sobre a MST, com lista de
vizinhos diretos + lista de nós alcançáveis por cada vizinho) segue o
método desenvolvido por Ana Morais; a contribuição desta dissertação é o
mecanismo de relay por `ip_forward`/Netlink com link quality (0–100) e
sincronização de rotas com o kernel, em substituição do relay anterior por
manipulação de tabela ARP.

---

## 2. Estrutura do repositório

```
RoutingMesh/
├── Makefile                 Compilação do daemon meshnode
├── include/                 Headers C (node, matrix, routing, tun, ...)
├── src/                     Implementação C do daemon meshnode
├── deploy/                  Scripts + unidades systemd para deployment nas Raspberry Pi
├── tests/                   Scripts de medição de métricas (RTT, throughput, convergência, timing TDMA)
├── alphabot_node.py         Aplicação do Nó 1 — controlo do robot + stream de vídeo
├── base_station.py          Aplicação do Nó 3 — comando (DS4) + receção de vídeo
├── metrics_collector.py     Extrai métricas dos logs do meshnode (journald) para JSONL
├── metrics_show.py          Visualização em tempo real / resumo das métricas recolhidas
└── servo_debug.py           Utilitário de diagnóstico dos servos do AlphaBot2 (I2C)
```

---

## 3. Compilar

Requisitos: Linux, `gcc`, `make`. Testado em Raspberry Pi OS / Debian.

```bash
make
```

Variáveis de compilação (opcionais, com valores por omissão):

```bash
make MESH_NET_PREFIX="172.20.10" MESH_PHY_IFACE="wlan0"
```

- `MESH_NET_PREFIX` — prefixo /28 da rede física ad-hoc (default `127.0.0`,
  usar `172.20.10` em deployment real).
- `MESH_PHY_IFACE` — interface WiFi física a colocar em modo ad-hoc (default
  `enp0s3`, usar `wlan0` numa Raspberry Pi).

Isto produz o binário `meshnode` na raiz do projeto.

```bash
make clean   # remove obj/ e o binário
```

---

## 4. Correr manualmente (teste local / desenvolvimento)

Cada nó precisa de root (cria a interface TUN, manipula rotas e iptables).

```bash
sudo ./meshnode <node_id> <num_nodes>

# ex., rede de 3 nós:
sudo ./meshnode 1 3     # Nó 1
sudo ./meshnode 2 3     # Nó 2
sudo ./meshnode 3 3     # Nó 3
```

Atalhos no Makefile para uma rede local de 3 nós (`num_nodes=10`, útil para
testar em máquinas virtuais na mesma rede):

```bash
make run8    # sudo ./meshnode 8 10
make run9    # sudo ./meshnode 9 10
make run10   # sudo ./meshnode 10 10
```

Ao arrancar, cada nó configura automaticamente a interface física em modo
ad-hoc (essid `manet-mesh`, canal 6) e cria a interface `tunN`
correspondente. Consulte o output — o daemon regista cada passo (`[TUN]`,
`[ROUTING]`, `[SYNC]`, ...).

---

## 5. Deployment em produção (Raspberry Pi)

O diretório `deploy/` contém tudo o necessário para correr o sistema como
serviços `systemd`, com arranque automático no boot.

### 5.1 Instalação

Em cada Raspberry Pi (com o repositório clonado):

```bash
sudo bash deploy/install.sh <node_id>
```

Isto:
1. Compila o `meshnode` (`MESH_NET_PREFIX=172.20.10`, `MESH_PHY_IFACE=wlan0`)
   e instala-o em `/usr/local/bin/meshnode`.
2. Cria `/etc/routingmesh/node.conf` com `NODE_ID`/`NUM_NODES`.
3. Instala e ativa os serviços `adhoc`, `meshnode` e `meshnode-metrics`
   (e também `alphabot` se `node_id == 1`).
4. Desativa `wpa_supplicant` no arranque (a interface fica dedicada ao modo
   ad-hoc da mesh).
5. Cria `/var/log/routingmesh/` para os logs de métricas.

### 5.2 Serviços systemd

| Serviço | Função |
|---------|--------|
| `adhoc.service` | Configura `wlan0` em modo ad-hoc antes do `meshnode` arrancar (`deploy/adhoc-start.sh`/`adhoc-stop.sh`) |
| `meshnode.service` | Corre o daemon `meshnode` |
| `meshnode-metrics.service` | Faz parsing do log do `meshnode` (via `journalctl`) e alimenta `metrics_collector.py` |
| `alphabot.service` | (só Nó 1) Corre `alphabot_node.py`; espera 180 s após o `meshnode` arrancar para a sincronização TDMA estabilizar antes de ligar o vídeo |

Arrancar/parar manualmente:

```bash
sudo systemctl start adhoc meshnode meshnode-metrics       # Nós 2 e 3
sudo systemctl start adhoc meshnode meshnode-metrics alphabot  # Nó 1
```

Ver logs em tempo real:

```bash
journalctl -u meshnode -f
journalctl -u meshnode-metrics -f
```

Ver métricas recolhidas:

```bash
tail -f /var/log/routingmesh/metrics.jsonl
python3 metrics_show.py            # visualização ao vivo
python3 metrics_show.py --summary  # resumo do ficheiro completo
```

### 5.3 Aplicações por nó

- **Nó 1 (Robot / AlphaBot2)** — `alphabot_node.py` controla o hardware do
  robot (motores, servos da câmara via I2C) e inicia o stream de vídeo
  (`rpicam-vid | ffmpeg`) através da interface TUN; o relay/transporte é
  tratado de forma transparente pelo TDMA. Diagnóstico dos servos:
  `sudo python3 servo_debug.py`.
- **Nó 3 (Base Station / PC)** — `base_station.py` lê um comando DS4 (USB) e
  envia comandos de movimento/câmara ao Nó 1, além de receber e mostrar o
  vídeo. Para visualizar apenas o vídeo sem o cliente de comando completo:
  `bash deploy/view_video.sh`.
- **Nó 2** — relay puro, não corre aplicação própria (apenas os serviços
  `adhoc`/`meshnode`/`meshnode-metrics`).

### 5.4 Configuração de vídeo (Nó 1)

```bash
rpicam-vid -t 0 --width 640 --height 480 --framerate 15 \
           --codec yuv420 -o - | \
ffmpeg -f rawvideo -pix_fmt yuv420p -s 640x480 -r 15 -i - \
       -c:v libx264 -preset ultrafast -tune zerolatency \
       -g 1 -b:v 500000 \
       -f mpegts "udp://10.0.0.3:5000?pkt_size=1316"
```

VGA (640×480) @15fps, H.264 (`ultrafast`+`zerolatency`, GOP=1 para minimizar
latência), 500 kbps configurados, encapsulado em MPEG-TS. O throughput real
medido (~580 kbps) fica ligeiramente acima do configurado devido ao
overhead do MPEG-TS e ao keyframe em todos os frames.

---

## 6. Testes e medição de métricas

Todos os scripts de teste estão em `tests/` e correm inteiramente no Nó 3
(base station), sem interromper a aplicação em curso.

| Script | Mede |
|--------|------|
| `rtt_test.py` | RTT/jitter/PDR do canal de controlo (requer servidor echo no Nó 1: `python3 tests/rtt_test.py --mode server`) |
| `throughput_test.py` | Throughput passivo do vídeo (direto vs. relay), via sniffer raw — não ocupa a porta do vídeo |
| `convergence_test.py` | Tempo de convergência do routing após falha do link direto (bloqueia com `iptables -I`, mede o gap no vídeo) |
| `tdma_timing_test.py` | Inter-arrival dos pacotes de vídeo, para verificar alinhamento com os slots TDMA |
| `tdma_sync_plot.py`, `tdma_slot_occupancy.py` | Visualização da sincronização/ocupação de slots a partir de capturas Wireshark (CSV) |
| `fwd_monitor.py` | Conta pacotes reencaminhados pelo `ip_forward` do kernel (via `/proc/net/snmp`) |
| `compare_captures.py`, `tdma_relay_analysis.py`, `video_sniff.py` | Ferramentas de apoio à análise de capturas Wireshark |
| `results_summary.py`, `rtt_plot.py`, `throughput_plot.py`, `timing_plot.py` | Agregação e geração de gráficos a partir dos JSON produzidos pelos testes acima |

Suite completa (recomendado):

```bash
# No Nó 1, antes de começar:
python3 tests/rtt_test.py --mode server &

# No Nó 3:
sudo bash tests/run_all.sh
```

Testes individuais / rápidos:

```bash
bash tests/run_tests.sh direct   # só fase de link direto
bash tests/run_tests.sh relay    # só medições em modo relay (já ativo)
bash tests/run_tests.sh both     # direto + relay (pede confirmação)
```

### 6.1 Resultados de referência

Medidos em ambiente controlado (2 corridas completas, 3 repetições por
métrica):

| Métrica | Valor |
|---------|-------|
| RTT canal de controlo (médio) | ~50.3 ms |
| Jitter | ~4.0 ms |
| PDR canal de controlo | 100% |
| Throughput vídeo — direto | ~580 kbps |
| Throughput vídeo — relay | ~568 kbps |
| Overhead do relay (throughput) | ~2.1% |
| Convergência de topologia após falha de link | ~2.76 s ± 110 ms |
| Padrão de inter-arrival do vídeo | Bimodal (0–10 ms rajada / ~140–150 ms entre frames), idêntico em direto e relay |

O padrão bimodal reflete o encoder H.264 a produzir frames continuamente:
dentro do slot de 50 ms do Nó 1 os pacotes acumulados são enviados em
rajada; entre slots há silêncio até ao frame seguinte (150 ms). O relay via
`ip_forward` não altera este padrão — a operação no kernel é praticamente
instantânea.

---

## 7. Limitações conhecidas / trabalho futuro

- **Deteção de nó morto baseada apenas em beacons UDP:** o `creationTime`
  que controla a expiração de um nó (`MAX_AGE`) é atualizado pelos beacons
  MATRIX (UDP, pequenos, toleram sinal fraco), não pelos dados MSG_DATA
  (TCP). Em condições de sinal marginal, os beacons podem continuar a
  chegar ocasionalmente enquanto o TCP de dados já não consegue entregar,
  atrasando ou impedindo a ativação do relay. Ver `pdr.c`, que já calcula o
  PDR real dos dados mas ainda não controla diretamente a expiração do nó.
  Alternativas propostas: usar o PDR para gatear a atualização do
  `creationTime`; manter um timeout separado para dados (`t_last_data`)
  independente dos beacons; ou degradar a link quality apenas com base em
  dados entregues, não em beacons recebidos.
- O feedback de qualidade de vídeo (`{"cmd": "video_poor"}`, porta 9002) já
  força a degradação da link quality direta quando o vídeo falha no Nó 3,
  mas cobre apenas esse sintoma específico, não o caso geral acima.

---

## 8. Licença / autoria

Miguel Almeida — FEUP, 2025/2026. Encaminhamento MST (DFS sobre listas
ligadas) baseado no trabalho de Ana Morais; contribuição desta dissertação:
relay `ip_forward` + Netlink com link quality dinâmica (0–100) e
sincronização de rotas com o kernel.
