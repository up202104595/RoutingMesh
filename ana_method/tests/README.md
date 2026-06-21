# Testes — Método Ana (`meshnode_ana`)

Recriação dos mesmos testes do método Miguel (`tests/` na raiz), adaptados ao
`meshnode_ana`, para **comparação directa lado-a-lado**. Mede as duas coisas
pedidas:

1. **Tempo de convergência** do relay (o que está no `sudo run_all.sh`).
2. **Colocação dos pacotes por slot** (de-rotada), como feito no método Miguel.

Os dois métodos usam, por defeito, o **mesmo endereçamento** (`172.20.10.x`
físico / `10.0.0.x` mesh), as **mesmas portas de STATE** (7001–7003) e o **mesmo
frame** (150 ms / 3×50 ms), pelo que os testes e os gráficos são directamente
comparáveis. Se compilares o `meshnode_ana` com outro prefixo
(`make MESH_NET_PREFIX=192.168.2`), passa esse prefixo aos scripts.

## Pré-requisitos (no testbed)

- Mesh ana ativa nos 3 nós: `sudo ./scripts/ana_setup.sh <id> wlan0` e
  `sudo ./meshnode_ana <id> 3`.
- Vídeo a fluir N1 → `10.0.0.3:5000` (a mesma app de teste do método Miguel:
  `alphabot_node.py` / `base_station.py`).

## 1. Suite completa (convergência + captura de slots)

```bash
sudo bash tests/run_all.sh --runs 3 --node1-phy 172.20.10.1 --iface wlan0
```

Faz: captura `state.pcap` (STATE packets, 60 s) + N runs de convergência, e
imprime a mediana. Tudo vai para `tests/results_ana_<timestamp>/`.

## 2. Convergência isolada

```bash
sudo python3 tests/convergence_test.py --label conv_r1 --node1-phy 172.20.10.1
```

Bloqueia o link directo (iptables no físico do N1), mede o gap no vídeo até o
relay retomar, e grava `convergence_conv_r1.json`. Como no método Miguel, a
convergência é dominada pelo *node-aging* (`MAX_AGE`) antes de o link ser dado
como morto.

## 3. Colocação por slot (de-rotada)

Captura os STATE packets e exporta para CSV (Wireshark:
`File → Export Packet Dissections → As CSV`, colunas No./Time/Source/
Destination/Protocol/Length/Info), depois:

```bash
python3 tests/slot_occupancy.py state.csv --out figs/ana_slots --phy-prefix 172.20.10
```

Gera:
- `figs/ana_slots_scatter.png` — cru, mostra a deriva comum (~18 ms/s);
- `figs/ana_slots_derot.png` — de-rotado, cada nó fixo no seu slot.

e imprime, por nó, o centro, o desvio circular σ (ms) e a **% de pacotes dentro
do slot atribuído**. Cada nó deve ficar em `[(n-1)·50, n·50]` ms, em ordem
cíclica N1→N2→N3 — a prova de que o método da Ana também respeita os slots.

## Comparar com o método Miguel

Corre a suite equivalente da raiz (`sudo bash tests/run_all.sh`) e a análise de
slots do método Miguel sobre a mesma topologia, e compara:

| Métrica | Onde |
|---|---|
| Convergência (mediana, ms) | `convergence_*.json` de cada método |
| σ por nó / % no slot | output do `slot_occupancy.py` de cada método |
| Gráfico de-rotado | `*_derot.png` de cada método |
