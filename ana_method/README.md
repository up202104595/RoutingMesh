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

**Fluxo de dados (Figura 3.13 da tese):**

1. A aplicação endereça a **tun** (`10.0.0.dst`). O pacote vai para a tun
   (directamente, ou desviado de wlan0 pelo `iptables mangle`), onde o
   **framework o lê**.
2. O framework envia-o por **UDP, no seu slot**, para o IP de **wlan0** do
   destino final (`172.20.10.dst:7000+dst`).
3. Os **relays são feitos pelo KERNEL** via `ip_forward` + ARP estática
   (`172.20.10.dst → MAC do next-hop`, ioctl SIOCSARP), imediatos, dentro do
   slot da origem — **NÃO gated pelo slot** (limitação que a tese assume, 3.2.6).
4. No **destino**, o framework recebe a UDP e **escreve o IP raw na tun** → o
   kernel entrega à app local, com o IP de origem intacto (transparente).

Resumo: `app → TUN → UDP(slot) → [kernel ARP relay] → TUN → app`.

O framework partilha a topologia em slots TDMA, calcula a **MST binária**,
mantém a **tabela ARP** (ioctl) e transporta os dados da app pela tun. O
**reencaminhamento multi-hop é do kernel** (ip_forward + ARP), não do framework.
A mudança de rota é **só a tabela ARP, via `ioctl` SIOCSARP — sem comandos de
linux/rota** (o setup único — ad-hoc, sysctl, iptables mangle — usa shell, como
a Ana em 3.2.2/3.2.5).

## Como compilar e correr

```bash
# build para a rede ad-hoc real (Raspberry Pi / AlphaBot)
make MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0

# em cada nó (id = último octeto do IP):
sudo ./meshnode_ana <node_id> <num_nodes>   # configura wlan0 + tun + ip_forward + ARP
```

As aplicações comunicam pelos IPs da **tun** (`ping`/`iperf`/vídeo para
`10.0.0.X`); o framework lê a tun, envia por UDP no slot e o kernel relaya via
ARP. Para teste local: `make` (default `127.0.0`/`lo`, valida o plano de controlo).

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
| **Tudo UDP** no framework; TCP só na aplicação | 3.2 | `node.c` (socket único `SOCK_DGRAM`) |
| Dados pela **tun → UDP no slot → tun** (Figura 3.13) | 3.2.5 | `node.c` (tun reader + DATA) + `iptables mangle` |
| sysctl `ip_forward`, `accept_redirects`, `send_redirects` | 3.2.2 | `src/net_ana.c` |
| Delete ARP só quando um nó **sai do grupo** | 3.2.4 | `routing_update()` (`prev_active`) |

## Diferenças face ao método Miguel (objeto da comparação)

| | Método Ana (este projeto) | Método Miguel (projeto principal) |
|---|---|---|
| MST | binária | ponderada por link quality (0–100) |
| Captura de dados | tun + `iptables mangle` (app→tun→framework) | TCP per-peer / TUN |
| Transporte (origem) | UDP no slot p/ IP wlan0 do destino | TCP per-peer (`tcp_sockfd[]`) |
| Relay (intermédios) | **kernel** ARP/ip_forward, **não gated pelo slot** | app-level, gated pelo slot |
| Header de dados | nenhum (IP intacto, só `tdma_header`) | `msg_data_hdr_t` (src/dst/msg_id) |
| Routing | linked list + rota/ARP por destino | tabela plana + rotas /32 Netlink |

## Testes

Ver `tests/` (suite de convergência + colocação por slot) e `Guia.txt`.
A análise de slots mostra os **STATE packets** confinados aos slots, enquanto os
**dados** (relayed pelo kernel) fluem fora dos slots — precisamente a limitação
de 3.2.6.
