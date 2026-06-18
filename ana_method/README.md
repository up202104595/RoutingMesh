# RA-TDMAs+ — Método Ana Morais (recriação fiel)

Projeto **independente** que recria o algoritmo de routing da dissertação da
Ana Morais, para comparação direta com o método deste repositório (Miguel).
Não partilha código com o projeto principal — copia apenas os módulos do
framework que são agnósticos ao método (sincronização TDMA, fila TX, partilha
de matriz, interface TUN).

## Como compilar e correr

```bash
# build para a rede ad-hoc real (Raspberry Pi / AlphaBot)
make MESH_NET_PREFIX=192.168.2 MESH_PHY_IFACE=wlan0

# em cada nó (id = último octeto do IP):
sudo ./scripts/ana_setup.sh <node_id> wlan0     # sysctl + iptables (tese 3.2.2 / 3.4)
sudo ./meshnode_ana <node_id> <num_nodes>

# no fim:
sudo ./scripts/ana_teardown.sh
```

Para teste local em loopback: `make` (default `127.0.0` / `lo`).

## O que é fiel à tese (e onde está no código)

| Conceito da tese | Secção | Ficheiro |
|---|---|---|
| Prim sobre matriz **binária** (sem link quality) | 3.1.1 | `src/matrix.c` → `primAlgorithm_weighted()` (cost=1) |
| Routing matrix → **linked list** primária/secundária | 3.1.2 / 3.2.1 | `src/routing_list.c`, `routingList_t` (= Code Block 3.3) |
| Construção por **DFS** a partir do nó local | 3.2.4 | `dfs_collect()` |
| **qsort** + diff incremental (só toca ARP no que muda) | 3.2.4 | `routing_update()` |
| Routing à **Camada 2** via tabela **ARP** | 3.2 | `tun_arp_set()` (ioctl `SIOCSARP`) |
| ARP via **`ioctl()`** (não `popen`/`system`) | 3.2.4 | `src/tun.c` → `arp_set()` |
| **MAC partilhado no state packet** (6 bytes) | 3.2.3 | `node.c` trailer + `src/mac_table.c` (= Code Block 3.2) |
| Delete ARP só quando um nó **sai do grupo** | 3.2.4 | `routing_update()` (detecção `prev_active`) |
| **Tudo UDP** no framework; TCP só na aplicação | 3.2 | `node.c` (socket único `SOCK_DGRAM`) |
| **Sem separação MSG_DATA** — relay transparente | 3.2 | `node.c` DATA = `[tdma_header][IP raw]` |
| **iptables mangle** + `ip rule` (wlan0→tun) | Code Block 3.4 | `src/tun.c` `tun_open()` + `scripts/ana_setup.sh` |
| **raw socket** `IPPROTO_RAW` ligado ao destino | 3.2.5 | `src/tun.c` `tun_write()` |
| sysctl `ip_forward`, `accept_redirects`, etc. | 3.2.2 | `scripts/ana_setup.sh` |

## Diferenças face ao método Miguel (objeto da comparação)

| | Método Ana (este projeto) | Método Miguel (projeto principal) |
|---|---|---|
| MST | binária | ponderada por link quality (0–100) |
| Transporte de dados | UDP | TCP per-peer (`tcp_sockfd[]`) |
| Header de dados | nenhum (IP raw) | `msg_data_hdr_t` (src/dst/msg_id) |
| Relay | L2 / ARP (kernel) | overlay app-level + ip_forward/Netlink |
| Routing struct | linked list + ARP table | tabela plana + rotas /32 Netlink |
| Update | incremental (qsort diff) | rebuild total por ronda |

## Nota de arquitetura (importante para a defesa)

A tese descreve duas peças do relay: (1) **decisão** de next-hop via tabela ARP
e (2) **transmissão** em UDP no slot TDMA. No sistema dela, o kernel reencaminha
nos relays via ARP — o que ela própria identifica como limitação de
sincronização (um pacote enviado perto do fim do slot pode não completar o
relay a tempo; *future work* = atraso de transmissão adaptativo).

Para a recriação **funcionar dentro do slot TDMA**, o reenvio nos relays é feito
pelo framework em UDP no slot do nó (`node.c`: o relay reenfileira o IP raw e
transmite no seu próprio slot), mantendo a **decisão** de rota via routing matrix
/ ARP exatamente como na tese. O comportamento observável (RTT, throughput, PLR,
relay transparente com IP de origem preservado) é equivalente, e a disciplina de
slot fica respeitada — uma realização fiel e mais rigorosa da Secção 3.2.5.

Tudo o resto (MST binária, UDP, sem MSG_DATA, ARP via ioctl, MAC no state packet,
update incremental) é réplica direta da dissertação.
