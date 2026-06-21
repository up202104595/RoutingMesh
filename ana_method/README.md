# RA-TDMAs+ — Método Ana Morais (recriação literal)

Projeto **independente** que recria o algoritmo de routing da dissertação da
Ana Morais, para comparação directa com o método deste repositório (Miguel).
Não partilha código com o projeto principal — copia apenas os módulos do
framework agnósticos ao método (sincronização TDMA, partilha de matriz).

## Filosofia (igual à tese)

O framework é **apenas plano de controlo**: partilha a topologia em slots TDMA,
calcula a MST binária e **mantém a tabela ARP**. O **data plane é o próprio
kernel Linux** (`ip_forward` + ARP estática): o reencaminhamento é feito pelo
kernel à Camada 2 sobre `wlan0`, **não pelo framework e não gated pelo slot** —
os nós intermédios reencaminham imediatamente, com a limitação de slot que a
própria tese assume (3.2.6). É a "routing without modifying the system" da
dissertação (Secções 3.2 e 4.4).

As aplicações comunicam **directamente pelos IPs físicos** (ex.: `ping`/`iperf`
para `172.20.10.X`); o kernel resolve o destino para o MAC do next-hop via ARP
e reencaminha hop a hop. Os IPs origem/destino ficam intactos → comunicação
peer-to-peer transparente.

## Como compilar e correr

```bash
# build para a rede ad-hoc real (Raspberry Pi / AlphaBot)
make MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0

# em cada nó (id = último octeto do IP):
sudo ./meshnode_ana <node_id> <num_nodes>     # configura wlan0 + ip_forward + ARP

# (o binário já aplica ad-hoc + sysctl; ana_setup.sh é opcional/documentação)
```

Para teste local: `make` (default `127.0.0` / `lo`, só valida o plano de controlo).

## O que é fiel à tese (e onde está no código)

| Conceito da tese | Secção | Ficheiro |
|---|---|---|
| Prim sobre matriz **binária** (sem link quality) | 3.1.1 | `src/matrix.c` → `primAlgorithm_weighted()` (cost=1) |
| Routing matrix → **linked list** primária/secundária | 3.1.2 / 3.2.1 | `src/routing_list.c`, `routingList_t` (= Code Block 3.3) |
| Construção por **DFS** a partir do nó local | 3.2.4 | `dfs_collect()` |
| **qsort** + diff incremental (só toca ARP no que muda) | 3.2.4 | `routing_update()` |
| Relay à **Camada 2 pelo KERNEL** via ARP + `ip_forward` | 3.2 / 4.4 | `src/net_ana.c` + kernel |
| Reenvio **não gated pelo slot** (imediato nos relays) | 3.2.6 | data plane = kernel |
| ARP via **`ioctl()` SIOCSARP** (não popen/system) | 3.2.4 | `src/net_ana.c` → `net_ana_arp_set()` |
| **MAC partilhado no state packet** (6 bytes) + `macInfo_t` | 3.2.3 | `node.c` trailer + `src/mac_table.c` (= Code Block 3.2) |
| **Tudo UDP** no framework; TCP só na aplicação | 3.2 | `node.c` (socket único `SOCK_DGRAM`, só STATE) |
| **Sem separação MSG_DATA** (o framework não transporta dados) | 3.2 | `node.c` |
| sysctl `ip_forward`, `accept_redirects`, `send_redirects` | 3.2.2 | `src/net_ana.c` `net_ana_setup()` |
| Delete ARP só quando um nó **sai do grupo** | 3.2.4 | `routing_update()` (detecção `prev_active`) |

## Diferenças face ao método Miguel (objeto da comparação)

| | Método Ana (este projeto) | Método Miguel (projeto principal) |
|---|---|---|
| MST | binária | ponderada por link quality (0–100) |
| Data plane | **kernel** (`ip_forward` + ARP) | overlay no framework |
| Transporte de dados | nenhum no framework (kernel L2) | TCP per-peer (`tcp_sockfd[]`) |
| Header de dados | nenhum (IP intacto) | `msg_data_hdr_t` (src/dst/msg_id) |
| Relay | Camada 2 / ARP, **não gated pelo slot** | app-level, gated pelo slot |
| Routing struct | linked list + tabela ARP | tabela plana + rotas /32 Netlink |
| Update | incremental (qsort diff) | rebuild total por ronda |

## Nota sobre os slots

Como na tese, o relay **não respeita o slot TDMA**: o kernel reencaminha o pacote
no momento em que o recebe (dentro do slot da origem), pelo que um pacote enviado
perto do fim do slot pode não completar o multi-hop a tempo — exactamente a
limitação descrita em 3.2.6 e proposta como *future work* (atraso de transmissão
adaptativo). Os pacotes de **estado/sincronização** do framework continuam em
slots; os de **dados** fluem pelo kernel. A análise de colocação de pacotes por
slot mostra precisamente esta distinção.
