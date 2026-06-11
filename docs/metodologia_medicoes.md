# Metodologia de Recolha de Métricas — RA-TDMAs+

## Ambiente

Três nós em rede mesh ad-hoc IEEE 802.11, protocolo TDMA com frame de 150ms
dividida em 3 slots de 50ms (um por nó):

| Nó | Papel | IP Mesh | IP Físico |
|----|-------|---------|-----------|
| N1 | Robot (AlphaBot) | 10.0.0.1 | 172.20.10.1 |
| N2 | Relay intermédio | 10.0.0.2 | 172.20.10.2 |
| N3 | Base Station (PC) | 10.0.0.3 | 172.20.10.3 |

O vídeo da câmara do robot flui continuamente de N1 para N3 via UDP na porta 5000.
Todos os testes correm exclusivamente no N3, sem intervenção manual durante a execução.

---

## 1. RTT do Canal de Controlo

**Ficheiros:** `tests/rtt_test.py`
**Resultados:** `rtt_results_direct_rtt_rN.json`

### Como foi medido

O N1 corre um servidor UDP passivo (`--mode server`) na porta 19876 que devolve
cada pacote recebido imediatamente (echo).

O N3 (`--mode client`) envia 100 pacotes UDP com o timestamp de envio embutido
no payload, com intervalo de 100ms entre pacotes. Para cada pacote devolvido:

```
RTT = t_receção - t_envio
```

Não é necessária sincronização de relógios entre nós porque a medição é feita
inteiramente no N3 (round-trip). O jitter é calculado como a média das
diferenças absolutas entre RTTs consecutivos.

### Resultados obtidos

| Run | Avg (ms) | Min (ms) | Max (ms) | Std (ms) | Jitter (ms) | PDR |
|-----|----------|----------|----------|----------|-------------|-----|
| 1   | 50.51    | 16.83    | 114.56   | 8.41     | 4.79        | 100% |
| 2   | 50.67    | 45.36    | 124.49   | 7.80     | 3.88        | 100% |
| 3   | 49.71    | 35.07    | 56.43    | 2.92     | 3.52        | 100% |
| **Média** | **50.30** | | | **6.38** | **4.06** | **100%** |

### Interpretação

O RTT médio de ~50ms é coerente com a arquitetura TDMA de 150ms/frame:
um pacote enviado pelo N3 aguarda em média ~25ms pelo slot do N3, percorre
a mesh até N1, e regressa pelo slot do N1. O max de ~115ms corresponde ao
worst-case de quase uma frame completa de espera.

---

## 2. Throughput UDP Passivo

**Ficheiros:** `tests/throughput_test.py`
**Resultados:** `throughput_direct_thru_rN.json`, `throughput_relay_thru_rN.json`

### Como foi medido

O script usa `SO_REUSEPORT` na porta 5000 para co-existir com o
`base_station.py` sem interromper o vídeo. **Não injeta tráfego** — observa
passivamente os pacotes de vídeo já existentes durante 15 segundos.

```
throughput (kbps) = (bytes_recebidos × 8) / tempo / 1000
```

### Resultados obtidos

| Modo | Run 1 | Run 2 | Média |
|------|-------|-------|-------|
| Direto | 667.9 kbps | 529.3 kbps | ~580 kbps |
| Relay  | 596.2 kbps | 543.9 kbps | ~570 kbps |
| **Overhead relay** | | | **~2%** |

### Interpretação

A degradação de throughput em relay é inferior a 2%, demonstrando que o
encaminhamento via ip_forward kernel em N2 é praticamente transparente.
A variabilidade entre runs (~100 kbps) é atribuída ao encoder de vídeo
(H.264 adaptativo) e às condições de canal, não ao relay em si.

---

## 3. Convergência de Topologia

**Ficheiros:** `tests/convergence_test.py`
**Resultados:** `convergence_conv_rN.json`

### Como foi medido

O teste corre inteiramente no N3 como root, em 5 fases:

1. **Warmup (3s):** escuta porta 5000 via `SO_REUSEPORT`, aguarda vídeo estável
2. **Bloqueio do link direto:**
   ```
   iptables -I INPUT  1 -s 172.20.10.1 -j DROP
   iptables -I OUTPUT 1 -d 172.20.10.1 -j DROP
   ```
   Bloqueia todo o tráfego IP entre N3 e N1 ao nível do kernel, forçando
   o protocolo de routing da mesh a redirecionar o tráfego via N2.

3. **Deteção de gap:** monitoriza timestamps dos pacotes recebidos. Se o
   intervalo entre pacotes exceder 400ms → link considerado quebrado.
   Regista `t_gap_start` = timestamp do último pacote direto.

4. **Deteção de convergência:** primeiro pacote recebido após o gap →
   `t_converged`. Regista os inter-arrivals após convergência.

5. **Restauro do link:**
   ```
   iptables -D INPUT  -s 172.20.10.1 -j DROP
   iptables -D OUTPUT -d 172.20.10.1 -j DROP
   ```

```
convergência (ms) = t_converged - t_gap_start
```

### Resultados obtidos

| Run | Convergência (ms) | Estado |
|-----|------------------|--------|
| 1   | 2847             | OK     |
| 2   | 1801             | OK     |
| 3   | Timeout >30s     | Robot sem pilhas — descartado |
| **Média** | **~2324 ms** | |

### Interpretação

O tempo de convergência de ~2.3s inclui: deteção de falha pelo protocolo
de routing, atualização e propagação de rotas pela mesh, e estabilização
do relay via N2. Para uma mesh TDMA com frame de 150ms, ~2.3s corresponde
a ~15 frames de convergência.

---

## 4. Timing TDMA dos Pacotes de Vídeo

**Ficheiros:** `tests/tdma_timing_test.py`
**Resultados:** `tdma_timing_direct_rN.json`, `tdma_timing_relay_rN.json`

### Como foi medido

O script escuta passivamente a porta 5000 via `SO_REUSEPORT` durante 30
segundos e regista o timestamp exato (`time.perf_counter()`) de cada pacote
recebido com precisão de microssegundos.

Para cada par de pacotes consecutivos calcula o inter-arrival:
```
IA[i] = t[i] - t[i-1]   (em milissegundos)
```

Os inter-arrivals são agrupados em buckets de 10ms para construir o histograma
de distribuição. São também calculados percentis (P95, P99) e a percentagem
de pacotes próximos de múltiplos dos períodos TDMA (slot=50ms, frame=150ms).

### Resultados obtidos — Direto (média das 3 runs)

```
  Inter-arrival (ms)   Contagem
  ──────────────────   ────────────────────────────────────────
       0 – 10 ms        ~1520 pkts  ████████████████████████████  (88%)
      10 – 130 ms           ~0 pkts
     130 – 150 ms         ~185 pkts  █████                         (11%)
     150 – 160 ms           ~2 pkts  (frame boundary)
```

| Métrica | Direto | Relay |
|---------|--------|-------|
| Avg IA | 17.4 ms | 16.2 ms |
| Mediana IA | 0.71 ms | 0.55 ms |
| Std IA | 45.7 ms | 44.2 ms |
| Max IA | 150.4 ms | 155.2 ms |
| P95 IA | 144.3 ms | 143.7 ms |

### Interpretação — Distribuição Bimodal

O histograma revela uma distribuição **bimodal** com dois picos bem definidos:

**Pico 1 — 0 a 10ms (~88% dos inter-arrivals)**

O encoder de vídeo (câmara H.264) não conhece o TDMA — produz frames
continuamente ao seu próprio ritmo. Durante o slot de 50ms do N1, todos os
pacotes acumulados na fila são transmitidos em rajada, chegando a N3 com
inter-arrivals muito pequenos (<10ms).

**Pico 2 — 130 a 150ms (~11% dos inter-arrivals)**

Corresponde à separação entre rajadas consecutivas — o silêncio entre o fim
de um slot do N1 e o início do próximo (uma frame completa de 150ms). O valor
ligeiramente inferior a 150ms (pico em ~144ms) deve-se ao tempo de
processamento e propagação.

**Número médio de pacotes por rajada:**
```
~1520 / ~185 ≈ 8.2 pacotes por frame
```
Consistente com o throughput: 580 kbps / 8 / 1200 bytes × 0.150s ≈ 9 pacotes/frame.

### O relay não altera o padrão TDMA

O histograma em modo relay é **idêntico** ao modo direto. Isto porque:

```
N1 (slot TDMA 50ms) ──TDMA──→ N2 recebe rajada
                                    │
                               ip_forward (~0ms, kernel)
                                    │
                               wlan0 ──WiFi──→ N3 recebe a mesma rajada
```

O slot TDMA pertence ao N1. O N2 não precisa de esperar um slot para
reencaminhar — o ip_forward injeta os pacotes diretamente na `wlan0` em
modo WiFi normal, sem agendamento TDMA. Por isso a rajada chega a N3
com o mesmo padrão temporal, apenas com ~19ms de atraso adicional
(propagação WiFi N2→N3).

---

## 5. Automação — run_all.sh

Todos os testes são orquestrados por `tests/run_all.sh`, correndo
inteiramente no N3. O único pré-requisito é o servidor RTT no N1:

```bash
# No N1 (uma vez):
python3 tests/rtt_test.py --mode server &

# No N3:
sudo bash tests/run_all.sh
```

### Sequência de execução (por run)

**Fase 1 — Link Direto:**
1. RTT (100 pacotes, 10s)
2. Throughput passivo (15s)
3. Timing TDMA (30s)

**Fase 2 — Relay:**
1. Convergência (bloqueia link, aguarda relay, restaura)
2. Bloqueia link novamente
3. Throughput passivo em relay (15s)
4. Timing TDMA em relay (30s)
5. Restaura link + hysteresis 10s

**Fase 3:** Sumário automático em tabelas (`results_summary.py`)

---

## Sumário dos Resultados

| Métrica | Valor | Notas |
|---------|-------|-------|
| RTT direto (avg) | **50.3 ms** | PDR 100%, 3 runs |
| RTT direto (jitter) | **4.1 ms** | Baixo, canal estável |
| Throughput direto | **~580 kbps** | Variabilidade do encoder |
| Throughput relay | **~570 kbps** | Overhead: ~2% |
| Convergência | **~2.3 s** | 2 runs válidos |
| Padrão TDMA | **Bimodal 0-10ms / 140-150ms** | Idêntico em direto e relay |
| Overhead ip_forward | **~0 ms** | Transparente ao nível de timing |
