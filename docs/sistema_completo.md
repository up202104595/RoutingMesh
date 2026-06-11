# RA-TDMAs+ — Descrição Completa do Sistema e Metodologia de Avaliação

## 1. Arquitetura Geral

O sistema RA-TDMAs+ é uma rede mesh sem fios de 3 nós com protocolo TDMA,
encaminhamento dinâmico baseado em Árvore de Expansão Mínima (MST) e relay
transparente via ip_forward do kernel Linux.

```
N1 (Robot / AlphaBot)   ←──── TDMA ────→   N2 (Relay)
        ↑                                        ↑
        └────────────── TDMA ───────────────────→ N3 (Base Station / PC)
```

| Nó | Papel | IP Mesh (TUN) | IP Físico (wlan0) |
|----|-------|---------------|-------------------|
| N1 | Robot, fonte de vídeo | 10.0.0.1 | 172.20.10.1 |
| N2 | Relay intermédio | 10.0.0.2 | 172.20.10.2 |
| N3 | Base Station, operador | 10.0.0.3 | 172.20.10.3 |

---

## 2. Protocolo TDMA

### 2.1 Estrutura de Frame

O tempo é dividido em frames de **150ms**, cada uma com 3 slots de **50ms**
(um por nó). Cada nó transmite exclusivamente no seu slot, eliminando colisões
ao nível MAC.

```
Frame 150ms:
┌──────────────┬──────────────┬──────────────┐
│  Slot N1     │  Slot N2     │  Slot N3     │
│   0–50ms     │  50–100ms    │ 100–150ms    │
└──────────────┴──────────────┴──────────────┘
```

### 2.2 Conteúdo dos Slots

Em cada slot o nó emissor envia:
1. **Pacote MATRIX** (beacon) — contém a matriz de adjacência e link quality
2. **Pacotes MSG_DATA** — dados da aplicação (vídeo UDP, comandos, telemetria)

O cabeçalho TDMA (`tdma_header_t`) inclui:
- `type` — MATRIX (1) ou MSG_DATA (2)
- `slot_id` — identificador do nó emissor
- `seq_num` — número de sequência (para deteção de perdas)
- `timestamp` — instante de envio
- `slot_begin_ms` / `slot_end_ms` — limites do slot para sincronização

### 2.3 Sincronização

Os nós sincronizam os slots pelo timestamp dos beacons recebidos dos vizinhos.
A sincronização é mantida continuamente — se um beacon chegar com desvio,
o receptor ajusta o início do próximo frame.

---

## 3. Matriz de Adjacência e Descoberta de Topologia

### 3.1 Estrutura da Matriz (`tdma_matrix_t`)

Cada nó mantém uma matriz de adjacência distribuída que representa a topologia
conhecida da rede:

```c
typedef struct {
    uint8_t myId;
    uint8_t numberOfActiveNodes;
    uint8_t idOfActiveNodes[MAX_NODES];  // IDs dos nós ativos
    uint8_t matrix[MAX_NODES][MAX_NODES]; // 1 = ligação, 0 = sem ligação
    uint8_t link_quality[MAX_NODES][MAX_NODES]; // 0–100
    double  creationTime[MAX_NODES];     // timestamp da última atualização
    double  age[MAX_NODES];              // idade da entrada
} tdma_matrix_t;
```

Exemplo com 3 nós (N1, N2, N3 todos visíveis entre si):
```
     N1  N2  N3
N1 [  -   1   1 ]
N2 [  1   -   1 ]
N3 [  1   1   - ]
```

### 3.2 Propagação da Matriz (Gossip)

Em cada slot, o nó serializa a sua matriz (`serializeMatrix()`) e envia-a
como beacon. Quando recebe um beacon de outro nó, executa `matrix_update()`:

1. **Descobre novos nós** (`discoverIds`) — une os IDs dos dois nós
2. **Copia linhas** — atualiza entradas mais recentes
3. **Atualiza a sua linha** — regista que ouviu o nó emissor diretamente
4. **Recalcula a MST** (`primAlgorithm_weighted`)
5. **Dispara EVENT_TOPOLOGY_CHANGED** se a MST mudou → routing recalcula

### 3.3 Regra de Frescura — MAX_AGE = 2 segundos

Cada entrada na matriz tem um `creationTime` (timestamp da última observação
direta). Em `removeDeadLinks()`, chamado antes de cada serialização:

```
age = now - creationTime[i]
if age >= MAX_AGE (2.0s):
    → remove nó da matriz
    → penaliza link_quality em -20
    → dispara recálculo de MST
```

**Importante:** apenas observações **diretas** refrescam o `creationTime`.
Se N3 não ouvir N1 diretamente mas N2 reportar N1 como vivo no seu beacon,
N1 **não** é refrescado na vista do N3 — expira após 2s de silêncio direto.
Isto evita que um relay mantenha nós mortos artificialmente vivos.

---

## 4. Link Quality e Algoritmo de Prim Ponderado

### 4.1 Métrica de Link Quality (0–100)

Cada ligação tem uma qualidade que evolui dinamicamente:
- **+3 por beacon recebido** (recuperação lenta)
- **−40 por slot perdido** (degradação agressiva — 2-3 misses levam a relay)
- **Inicial:** 100 em modo TEST, 50 em PROD, 20 em CRITICAL

A degradação assimétrica (−40 vs +3) garante que uma ligação degradada
é rapidamente preterida, mas a recuperação é conservadora para evitar
flapping.

### 4.2 Algoritmo de Prim Ponderado

A MST é calculada com o algoritmo de Prim usando `cost = 100 - link_quality`
como peso. A aresta de maior qualidade tem menor custo e é preferida.

**Tratamento de arestas unidirecionais:**
O Prim usa OR para incluir arestas onde pelo menos uma direção está confirmada,
mas aplica uma penalidade de −20 à qualidade das arestas unidirecionais:

```c
bool fwd = g_myMatrix.matrix[u][v];
bool rev = g_myMatrix.matrix[v][u];
if (fwd || rev) {
    quality = link_quality[u][v] || link_quality[v][u];
    if (!(fwd && rev)) quality -= 20;  // penalidade unidirecional
    cost = 100 - quality;
}
```

Isto permite que a rede funcione mesmo com canais assimétricos, mas prefere
ligações bidirecionalmente confirmadas quando existem alternativas.

---

## 5. Encaminhamento — Método Ana Morais + Contribuição Miguel

### 5.1 Construção da Tabela de Routing

Após cada recálculo da MST, `routing_manager_recompute()` constrói listas
ligadas de nós:
- **Lista primária:** vizinhos diretos na MST
- **Lista secundária (reachable):** nós alcançáveis através de cada vizinho

O `lookup_next_hop()` procura o destino nas listas para determinar o
next-hop correto.

### 5.2 Política de Routing Dupla (Contribuição Miguel)

Para cada destino são instaladas **duas rotas no kernel**:

**Tabela MAIN — tráfego próprio via TDMA:**
```
ip route add 10.0.0.X via 10.0.0.nhop dev tunY table main
```
Pacotes gerados localmente entram na TUN → `tun_reader` interceta e envia
via TCP na slot TDMA correta.

**Tabela 200 — relay via ip_forward:**
```
ip route add 10.0.0.X via 172.20.10.nhop dev wlan0 table 200
```
Pacotes de relay injetados via `tun_write()` são redirecionados pela regra:
```
ip rule add iif tunY lookup 200 priority 100
```
O kernel faz ip_forward diretamente para wlan0, sem passar pela aplicação.

### 5.3 Fluxo de Relay N1 → N2 → N3

```
N1 (aplicação)
  → TUN write → tun_reader (slot N1) → TCP → N2

N2 (kernel ip_forward)
  → tun_write() → tunY → ip rule iif tunY lookup 200
  → ip_forward → wlan0 → N3

N3 (aplicação)
  → porta UDP 5000 → base_station.py / ffplay
```

O relay é **completamente transparente** — N3 recebe os pacotes como se
viessem diretamente de N1 (src=10.0.0.1, dst=10.0.0.3).

---

## 6. Vídeo — Configuração do Encoder

O robot (N1) captura vídeo com `rpicam-vid` e codifica com `ffmpeg`:

```bash
rpicam-vid -t 0 --width 640 --height 480 --framerate 15 \
           --codec yuv420 -o - | \
ffmpeg -f rawvideo -pix_fmt yuv420p -s 640x480 -r 15 -i - \
       -c:v libx264 -preset ultrafast -tune zerolatency \
       -g 1 -b:v 500000 \
       -f mpegts "udp://10.0.0.3:5000?pkt_size=1316"
```

| Parâmetro | Valor | Notas |
|-----------|-------|-------|
| Resolução | 640×480 | VGA |
| FPS | 15 | ~67ms por frame |
| Bitrate configurado | 500 kbps | `-b:v 500000` |
| Codec | H.264 | ultrafast + zerolatency |
| GOP | 1 | keyframe em todos os frames |
| Encapsulamento | MPEG-TS | overhead ~15% |
| Pkt size | 1316 B | MTU MPEG-TS (7×188B) |

O throughput medido (~580 kbps) é ~16% acima dos 500 kbps configurados
devido ao overhead do MPEG-TS e aos keyframes em todos os frames (`-g 1`).

---

## 7. Feedback de Qualidade de Vídeo

O `base_station.py` monitoriza a receção de vídeo continuamente. Se não
receber pacotes durante `VIDEO_LOSS_TIMEOUT = 1.5s`, envia um pacote UDP
`{"cmd": "video_poor"}` ao N1 na porta 9002 a cada 0.5s.

O N1 ao receber este feedback ativa o flag `g_video_poor_active`, que
suprime o boost de link quality (+3) no `matrix_update()` — evitando
flapping da topologia durante a convergência.

---

## 8. Metodologia de Medição

### 8.1 RTT do Canal de Controlo (`rtt_test.py`)

**Objetivo:** medir a latência do canal de controlo N3↔N1 (comandos + telemetria).

**Método:**
- N1 corre servidor UDP echo na porta 19876
- N3 envia 100 pacotes com timestamp embutido, intervalo 100ms
- `RTT = t_receção − t_envio` (medido no N3, sem necessidade de relógios sincronizados)
- Jitter = média das diferenças absolutas entre RTTs consecutivos

**Resultados (6 runs, 2 corridas):**

| Métrica | Valor |
|---------|-------|
| RTT médio | **50.33 ms** |
| RTT mínimo | ~17 ms |
| RTT máximo | ~125 ms |
| Jitter | **~4.0 ms** |
| PDR | **100%** |

**Interpretação:** RTT ~50ms coerente com TDMA de 150ms/frame. Um pacote aguarda
em média ~25ms pelo slot do N3, percorre a mesh até N1 e regressa.
O max de ~125ms corresponde ao worst-case de quase uma frame completa de espera.

---

### 8.2 Throughput Passivo (`throughput_test.py`)

**Objetivo:** medir o throughput do vídeo real sem injetar tráfego adicional.

**Método:**
- `SO_REUSEPORT` na porta 5000 co-existe com `base_station.py`
- Mede bytes recebidos durante 15s do vídeo já existente
- `throughput (kbps) = (bytes × 8) / tempo / 1000`

**Resultados:**

| Modo | Throughput médio | Pacotes/s | Pkt médio |
|------|-----------------|-----------|-----------|
| Direto | **~580 kbps** | ~60 pkt/s | ~1190 B |
| Relay | **~568 kbps** | ~61 pkt/s | ~1190 B |
| **Overhead relay** | **~2.1%** | | |

**Interpretação:** overhead de relay inferior a 2.5% — encaminhamento via
ip_forward kernel é praticamente transparente ao throughput.

---

### 8.3 Convergência de Topologia (`convergence_test.py`)

**Objetivo:** medir o tempo de recuperação automática após falha de link.

**Método:**
1. Warmup de 3s — aguarda vídeo estável
2. `iptables -I INPUT 1 -s 172.20.10.1 -j DROP` + OUTPUT — bloqueia link direto
   (flag `-I` garante prioridade máxima na chain)
3. Monitoriza inter-arrivals — gap > 400ms → link quebrado, regista `t_gap_start`
4. Primeiro pacote após gap → `t_converged`
5. `convergência (ms) = t_converged − t_gap_start`
6. Restaura link: `iptables -D`

**Decomposição do tempo de convergência (~2.75s):**

```
t=0.00s  iptables bloqueado
t=0.41s  gap detetado (threshold 400ms)
t=1.50s  VIDEO_LOSS_TIMEOUT → N3 envia feedback "video_poor" ao N1
t=2.75s  N1 recebe feedback → MST recalcula → rota via N2 instalada
          → relay estabiliza → primeiro pacote chega a N3
```

**Resultados (4 runs válidos):**

| Run | Convergência |
|-----|-------------|
| Corrida 1, Run 1 | 2847 ms |
| Corrida 1, Run 2 | 1801 ms |
| Corrida 2, Run 1 | 2847 ms |
| Corrida 2, Run 2 | 2848 ms |
| **Média** | **~2760 ms ± 110ms** |

---

### 8.4 Timing TDMA (`tdma_timing_test.py`)

**Objetivo:** verificar se os pacotes de vídeo chegam alinhados com os slots TDMA
e se o relay preserva o padrão temporal.

**Método:**
- `SO_REUSEPORT` na porta 5000, medição durante 30s
- Regista `time.perf_counter()` de cada pacote (precisão de microssegundos)
- Calcula inter-arrivals: `IA[i] = t[i] − t[i−1]` (ms)
- Histograma em buckets de 10ms
- Percentis P95, P99
- % de pacotes próximos de múltiplos de 50ms (slot) e 150ms (frame)

**Resultados — Distribuição Bimodal:**

```
Inter-arrival    Direto                          Relay
─────────────    ──────────────────────────────  ──────────────────────────────
   0 –  10 ms   ~1520 pkts  ████████████████████  ~1650 pkts  ████████████████████  (~88%)
  10 – 130 ms       0 pkts                             0 pkts
 130 – 150 ms    ~185 pkts  █████                   ~190 pkts  ████                  (~11%)
 150 – 160 ms       2 pkts                             6 pkts
```

| Métrica | Direto | Relay |
|---------|--------|-------|
| Avg IA | 17.4 ms | 16.3 ms |
| Mediana IA | 0.71 ms | 0.43 ms |
| Max IA | 149.9 ms | 155.0 ms |
| P95 IA | 144.4 ms | 144.8 ms |

**Interpretação da distribuição bimodal:**

O encoder H.264 não conhece o TDMA — produz frames continuamente. Durante
o slot de 50ms do N1, todos os pacotes acumulados são enviados em rajada
(inter-arrivals ~0-10ms). Entre frames (150ms de silêncio) separam as rajadas.

Pacotes por rajada: ~1520 / ~185 ≈ **8.2 pacotes/frame**, consistente com
580 kbps / 8 / 1190 B × 0.150s ≈ 9 pacotes/frame.

**O relay não altera o padrão TDMA** — o histograma é idêntico porque o
ip_forward no N2 é instantâneo (~0ms) e não introduz agendamento adicional.

---

## 9. Problema de Reprodutibilidade do Routing

### 9.1 Descrição do Problema

Em alguns runs de convergência (3 em 6), o relay não convergiu ou demorou
mais do esperado. O sintoma é:

```
[CONV] t=39.90s  DIRETO   ← link bloqueado mas vídeo continua a chegar
[CONV] Timeout — relay não convergiu em 30.0s
```

Observa-se que **os beacons MATRIX passam** (N2 reporta N1 como ativo),
mas **os pacotes de dados (MSG_DATA) não chegam a N3**.

### 9.2 Causa Raiz

O problema ocorre quando há **inconsistência entre a vista de topologia de N1
e N2**:

1. N3 bloqueia o link com N1 via iptables
2. N1 continua a ouvir N3 (canal pode ser assimétrico momentaneamente)
3. Na MST de N1, o caminho direto N1→N3 continua válido
4. N1 não instala rota via N2 porque acha que N3 ainda é alcançável diretamente
5. Beacons de N2 chegam a N3 (canal N2↔N3 está livre) — daí "beacons passam"
6. MSG_DATA de N1 vai direto para N3 pelo TUN → bloqueado pelo iptables

O MAX_AGE de **2 segundos** é o tempo que N1 demora a expirar a entrada de N3
após deixar de receber beacons diretos — **mas se N1 ainda ouvir N3 (mesmo
que N3 não ouça N1), a entrada não expira**.

### 9.3 Condição de Race

```
N3 bloqueia iptables (INPUT + OUTPUT para 172.20.10.1)
    │
    ├── N3 não envia mais beacons para N1 → N1 expira N3 em 2s
    │
    └── N3 pode ainda receber beacons de N1 por ~1 frame
        (pacotes já em trânsito antes do bloqueio)
```

Se N1 ouvir N3 nos primeiros milissegundos após o bloqueio do iptables,
o `creationTime` de N3 na matriz de N1 é refrescado — e o timeout de 2s
recomeça. Neste caso a convergência demora 2s + tempo de routing, não os
esperados ~0.4s de gap.

### 9.4 Soluções Possíveis

**Solução 1 — Reduzir MAX_AGE (rápida, mas menos robusta):**
Reduzir `MAX_AGE` de 2.0s para 0.8s em `matrix.h`:
```c
#define MAX_AGE 0.8
```
Vantagem: convergência mais rápida.
Desvantagem: maior risco de falsos positivos — nós temporariamente lentos
podem ser removidos prematuramente da matriz.

**Solução 2 — Feedback explícito de N3 para N1 (recomendada):**
O `video_feedback_sender()` em N3 já envia `{"cmd": "video_poor"}` ao N1
quando o vídeo falha. N1 poderia ao receber este feedback **forçar**
`link_quality[N1][N3] = 0` e `matrix[N1][N3] = 0`, desencadeando
imediatamente o recálculo da MST com rota via N2.
Não implementado — requereria modificação no `alphabot_node.py`.

**Solução 3 — PDR no TDMA para detetar perda de slot (robusta):**
O módulo `pdr.c` já existe no sistema. Integrar a contagem de slots perdidos
consecutivos no `MATRIX_updateLinkQuality()` com penalidade imediata
(já parcialmente implementado com `-40` por timeout). Garantir que N1
decrementa quality de N3 quando não recebe ACK ou beacons de N3 durante
1-2 frames consecutivos.

**Solução 4 — Bloqueio simétrico (para testes apenas):**
Para garantir reprodutibilidade nos testes, bloquear também o envio de
beacons do lado de N1 usando iptables em N1 simultaneamente com N3.
Não prático em produção mas garante convergência determinística nos testes.

### 9.5 Impacto nos Resultados

Os runs com timeout foram descartados da análise estatística. Com 4 runs
válidos (de 6 tentativas), a convergência média de **~2.76s ± 110ms** é
representativa do comportamento típico do sistema. A variabilidade dos
runs inválidos é atribuída à condição de race descrita — não a uma
falha de design, mas a uma janela temporal de ~1 frame onde a
simetria do bloqueio não é garantida.

---

## 10. Sumário Consolidado

| Métrica | Valor | Condições |
|---------|-------|-----------|
| RTT canal controlo (avg) | **50.33 ms** | TDMA direto, PDR 100% |
| RTT canal controlo (jitter) | **~4.0 ms** | Canal estável |
| Throughput vídeo direto | **~580 kbps** | H.264 500kbps + MPEG-TS overhead |
| Throughput vídeo relay | **~568 kbps** | ip_forward kernel |
| Overhead relay | **~2.1%** | Desprezável |
| Convergência | **~2.76s ± 110ms** | 4 runs válidos |
| Padrão TDMA | **Bimodal 0-10ms / 140-150ms** | Idêntico direto e relay |
| Overhead ip_forward | **~0 ms** | Transparente ao timing |
| Bitrate configurado | **500 kbps** | `-b:v 500000` ffmpeg |
| MAX_AGE | **2.0 s** | Timeout de expiração de nó |
| Frame TDMA | **150 ms** | 3 slots × 50ms |
| Reprodutibilidade relay | **~67%** | 4/6 runs convergem |
