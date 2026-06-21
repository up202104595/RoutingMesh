# RA-TDMAs+ — Método Ana Morais (recriação literal)

Projeto **independente** que recria o algoritmo de routing da dissertação da
Ana Morais, para comparação directa com o método deste repositório (Miguel).
Copia apenas os módulos do framework agnósticos ao método (sincronização TDMA,
partilha de matriz) e reimplementa o resto fiel à tese.

## Filosofia (igual à tese)

Desenho de **2 subredes**, como na dissertação (3.2.5):

- **wlan0** (ad-hoc, real L2) → prefixo **físico** `172.20.10.x`: é onde vivem
  os MACs e onde o kernel faz o relay ARP (papel do `192.168.2.x` dela).
- **tunN** (virtual) → prefixo **mesh** `10.0.0.x`: o IP que as aplicações
  endereçam, peer-to-peer, com o IP intacto (papel do `192.168.3.x` dela).

As **aplicações endereçam o IP de wlan0** (`172.20.10.x`), não a tun — é o que a
tese diz explicitamente (3.2.5). Por estarem na subrede de wlan0, o destino fica
on-link e a mudança de rota é **só a tabela ARP, via `ioctl` (SIOCSARP) — sem
qualquer comando de linux/rota**. A tun (`10.0.0.x`) é a interface interna do
framework (papel do `192.168.3.x` dela).

O framework é **apenas plano de controlo**: partilha a topologia em slots TDMA,
calcula a MST binária e **mantém a tabela ARP** (ioctl). O **data plane é o
próprio kernel Linux**:

- `ip_forward=1` → o nó reencaminha o que não é para si;
- por destino: ARP estática `172.20.10.dst → MAC do next-hop` (ioctl SIOCSARP),
  forçando o frame a sair para o next-hop (não para o destino real, mesmo
  estando em alcance) — o truque ARP da tese (3.2.4);
- o kernel envia o frame L2 ao next-hop sobre wlan0 e **relaya hop a hop,
  imediatamente, NÃO gated pelo slot TDMA** — com a limitação de slot que a
  própria tese assume (3.2.6).

## Como compilar e correr

```bash
# build para a rede ad-hoc real (Raspberry Pi / AlphaBot)
make MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0

# em cada nó (id = último octeto do IP):
sudo ./meshnode_ana <node_id> <num_nodes>   # configura wlan0 + tun + ip_forward + ARP
```

As aplicações comunicam pelos IPs de **wlan0** (`ping`/`iperf` para
`172.20.10.X`); o kernel resolve para o MAC do next-hop (ARP estática) e relaya.
Para teste local: `make` (default `127.0.0`/`lo`, valida só o plano de controlo).

## O que é fiel à tese (e onde está no código)

| Conceito da tese | Secção | Ficheiro |
|---|---|---|
| Prim sobre matriz **binária** (sem link quality) | 3.1.1 | `src/matrix.c` → `primAlgorithm_weighted()` (cost=1) |
| Routing matrix → **linked list** primária/secundária | 3.1.2 / 3.2.1 | `src/routing_list.c`, `routingList_t` (= Code Block 3.3) |
| Construção por **DFS** + **qsort** (diff incremental) | 3.2.4 | `routing_update()` / `dfs_collect()` |
| Relay à **Camada 2 pelo KERNEL** via ARP + `ip_forward` | 3.2 / 4.4 | `src/net_ana.c` + kernel |
| Reenvio **não gated pelo slot** (imediato nos relays) | 3.2.6 | data plane = kernel |
| ARP via **`ioctl()` SIOCSARP** (não popen/system) | 3.2.4 | `src/net_ana.c` → `arp_set()` |
| **2 subredes** (tun mesh + wlan0 físico) | 3.2.5 | `src/net_ana.c` `net_ana_setup()` |
| **MAC partilhado no state packet** (6 bytes) + `macInfo_t` | 3.2.3 | `node.c` trailer + `src/mac_table.c` (= Code Block 3.2) |
| **Tudo UDP** no framework; TCP só na aplicação | 3.2 | `node.c` (socket único `SOCK_DGRAM`, só STATE) |
| **Sem separação MSG_DATA** (o framework não transporta dados) | 3.2 | `node.c` |
| sysctl `ip_forward`, `accept_redirects`, `send_redirects` | 3.2.2 | `src/net_ana.c` |
| Delete ARP só quando um nó **sai do grupo** | 3.2.4 | `routing_update()` (`prev_active`) |

## Diferenças face ao método Miguel (objeto da comparação)

| | Método Ana (este projeto) | Método Miguel (projeto principal) |
|---|---|---|
| MST | binária | ponderada por link quality (0–100) |
| Data plane | **kernel** (`ip_forward` + ARP estática, ioctl) | overlay no framework |
| Transporte de dados | nenhum no framework (kernel L2) | TCP per-peer (`tcp_sockfd[]`) |
| Header de dados | nenhum (IP intacto) | `msg_data_hdr_t` (src/dst/msg_id) |
| Relay | Camada 2 / ARP, **não gated pelo slot** | app-level, gated pelo slot |
| Routing | linked list + rota/ARP por destino | tabela plana + rotas /32 Netlink |

## Testes

Ver `tests/` (suite de convergência + colocação por slot) e `Guia.txt`.
A análise de slots mostra os **STATE packets** confinados aos slots, enquanto os
**dados** (relayed pelo kernel) fluem fora dos slots — precisamente a limitação
de 3.2.6.
