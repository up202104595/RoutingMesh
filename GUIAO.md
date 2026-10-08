# Guião da demonstração: Layer 3 → mudar de método → Layer 2 (ARP) com bloqueio

Este guião é a sequência ao vivo. A preparação única (compilar, serviço de ad-hoc, SSH
por chave) está no `DEMO.md`, secção **A**.

## 0. Disposição

| Onde | O que tem |
|---|---|
| **PC, monitor 1** | terminal em ecrã inteiro com o **tmux**: no L3 os 5 painéis; no ARP só N3, N2 e BASE |
| **PC, monitor 2** | o **vídeo** (a janela do `ffplay`, que a base abre sozinha: arrasta-a para este monitor) |
| **Pi do AlphaBot (N1)**, com monitor e teclado | **no ARP corre aqui o N1 e o robô**, e daqui escreves o bloqueio: 3 terminais (nó N1, robô, bloqueio) |
| **Pi do relay (N2)** | ligado, sem ecrã |
| Robô + comando **DS4** | o DS4 ligado ao PC |

No **ARP** o N1 e o robô **não** vão no tmux: correm no monitor do Pi. Assim o bloqueio não corta
nenhuma ligação SSH que os esteja a controlar.

| Nó | IP | MAC |
|---|---|---|
| N1 (AlphaBot) | `172.20.10.1` | `d8:3a:dd:33:f3:be` |
| N2 (relay) | `172.20.10.2` | `2c:cf:67:79:93:50` |
| N3 (PC) | `172.20.10.3` | `f0:9e:4a:a2:20:38` |

Estes MACs estão no ficheiro **`macs.conf`**, que o `meshnode` lê ao arrancar (tem de estar na pasta do repo
em cada nó). Se mudares uma placa, atualiza-o.

## Enviar e compilar nos nós (quando o código mudou)

Faz isto **sempre que o código mudou** (`src/`, `include/` ou `Makefile`). Para trocar de método
não é preciso (os dois binários já existem em cada nó); o `demo-tmux.sh`, a `base_station.py` e
este guião só contam no PC. Os três nós têm de ficar com o **mesmo código**. O `rsync` só copia os ficheiros: **o `make` é que compila**, nos três.

```bash
# 0. descarregar o codigo mais recente (PC COM internet, antes de o pores em ad-hoc)
#    No browser, com a conta GitHub aberta, guarda o ZIP deste endereco:
#    https://github.com/up202104595/RoutingMesh/archive/refs/heads/claude/youthful-tesla-a6e0g8.zip
cd ~/Documentos
mv RoutingMesh RoutingMesh-antigo
unzip ~/Transferências/RoutingMesh-claude-youthful-tesla-a6e0g8.zip
mv RoutingMesh-claude-youthful-tesla-a6e0g8 RoutingMesh
cd ~/Documentos/RoutingMesh && ls            # tem de mostrar src include Makefile run-node.sh macs.conf ...
# se o ZIP ou a pasta tiverem outro nome, ajusta (ls ~/Transferências  e  ls ~/Documentos)

# (poe o PC em ad-hoc: os Pi estao em ad-hoc e so assim lhes chega)
# 1. enviar (na pasta do repo do PC; tem de mostrar os ficheiros, nao erros)
cd ~/Documentos/RoutingMesh
rsync -av src include Makefile run-node.sh alphabot_node.py macs.conf pi@172.20.10.1:Documents/RoutingMesh/
rsync -av src include Makefile run-node.sh alphabot_node.py macs.conf pi@172.20.10.2:Documents/RoutingMesh/

# 2. compilar nos três (procura "Gerado: meshnode_ipforward e meshnode_arp")
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && chmod +x run-node.sh && make clean && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && chmod +x run-node.sh && make clean && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlan0"
chmod +x run-node.sh demo-tmux.sh && make clean && make both MESH_NET_PREFIX=172.20.10 MESH_PHY_IFACE=wlp5s0
```
No PC, se o `make` der `Ficheiro de texto ocupado`, ainda há um `meshnode` a correr:
`tmux kill-session -t demo; sudo pkill -KILL -f '[m]eshnode_'`.

```bash
# 3. confirmar que o código é igual nas três máquinas (os 3 valores têm de ser iguais)
H='(find src include -type f \( -name "*.c" -o -name "*.h" \) | LC_ALL=C sort | xargs cat; cat Makefile) | md5sum'
cd ~/Documentos/RoutingMesh && bash -c "$H"
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && bash -c '$H'"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && bash -c '$H'"

# scripts: run-node.sh e macs.conf iguais nas três; alphabot_node.py do N1 igual ao do PC
md5sum run-node.sh alphabot_node.py macs.conf
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && md5sum run-node.sh alphabot_node.py macs.conf"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && md5sum run-node.sh macs.conf"

# 4. permissões e binários (x em run-node.sh e demo-tmux.sh; binários com a data de agora)
ls -l run-node.sh demo-tmux.sh meshnode_ipforward meshnode_arp base_station.py
ssh pi@172.20.10.1 "cd Documents/RoutingMesh && ls -l run-node.sh meshnode_ipforward meshnode_arp alphabot_node.py"
ssh pi@172.20.10.2 "cd Documents/RoutingMesh && ls -l run-node.sh meshnode_ipforward meshnode_arp"
```

## 1. Antes de começar (sem público, ~5 min)

1. **Liga os dois Pi** (arrancam sozinhos em ad-hoc com o IP certo, ~1 min).
2. **Põe o PC em ad-hoc** (fica sem internet):
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
3. **Confirma:**
   ```bash
   ping -c 2 172.20.10.1; ping -c 2 172.20.10.2
   ssh -o BatchMode=yes pi@172.20.10.1 hostname; ssh -o BatchMode=yes pi@172.20.10.2 hostname
   which tmux
   ```
   Os dois `ping` respondem, os dois `ssh` dizem o nome sem pedir password, e o `which tmux` imprime um caminho.
4. **Liga o DS4 ao PC** (a base station sai se não houver comando).
5. **No monitor do N1**, abre **três terminais** e em cada um faz `cd ~/Documents/RoutingMesh` (nó N1, robô, bloqueio). No L3 só vais precisar deles no ARP.

## 2. Parte 1 — método Layer 3 (vídeo UDP)

**Arranque**, num terminal do PC, **sem sudo**:
```bash
cd ~/Documentos/RoutingMesh
./demo-tmux.sh l3
```
Entras numa sessão tmux com **5 painéis visíveis** ao mesmo tempo:
```
┌───────────────┬───────────────┬───────────────┐
│ N3 · PC       │ N1 · AlphaBot │ N2 · relay    │   <- os 3 nós (N1 e N2 por SSH)
├───────────────┴───────┬───────┴───────────────┤
│ BASE STATION          │ ROBO N1               │   <- arrancam sozinhos
└───────────────────────┴───────────────────────┘
```
(há ainda uma janela `controlo`, com uma shell livre no PC: `Ctrl+b` `n`.)

**O que fazes e o que vês:**
1. O painel **N3** pede a **palavra-passe do `sudo`**: clica nele e escreve-a. N1 e N2 entram nos Pi sem pedir nada.
2. Os três painéis dos nós enchem-se de logs. Quando a base e o robô arrancarem, no painel N1 começam a aparecer linhas `[TUN] Pacote: ... dst=3`: são os pacotes de vídeo a entrar na mesh.
3. **A base e o robô arrancam sozinhos**, sem esperar por nada: a base 5 s depois de lançares o script e o robô 2 s depois da base. A base abre o `ffplay`.
4. O vídeo aparece no monitor 2.

**O que dizer:** é uma rede ad-hoc mesh multi-hop de robôs; os nós sincronizam o acesso ao meio
(TDMA), trocam a topologia por beacons, e o routing instala rotas de host no kernel por netlink;
o vídeo do robô chega à base mesmo sem ligação direta, saltando pelo nó do meio. Aqui o vídeo vai
em UDP porque o método Layer 3 já repõe perdas no primeiro salto (TCP entre vizinhos).

Dicas: `Ctrl+b` `z` amplia o painel onde estás (outra vez volta); o rato também muda de painel.

## 3. Mudar de método (L3 → ARP)

**Tens de fechar tudo, sim.** Os 5 processos têm de parar, porque:
- o método está **compilado dentro de cada binário** e os 3 nós têm de usar o mesmo;
- o **vídeo muda de transporte** (UDP → TCP), por isso a base e o robô reiniciam;
- o ARP deixa entradas permanentes e o L3 deixa regras: o `run-node.sh` limpa-as ao arrancar.

**Opção A, à vista (~10 s):** **Ctrl+C** em cada um dos 5 painéis (base e robô primeiro, depois os nós). Vês cada um a parar.
**Opção B, rápida:**
```bash
# Ctrl+b e depois d   (sai do tmux sem parar nada)
tmux kill-session -t demo
```
Fecha os 5 painéis e as ligações SSH, e os processos nos Pi terminam com elas. Não corras isto
**dentro** da sessão: o script recusa.

**Confirma que não ficou nada vivo** (os três têm de vir vazios):
```bash
pgrep -af '[m]eshnode_'
ssh pi@172.20.10.1 "pgrep -af '[m]eshnode_|[a]lphabot_node|[r]picam-vid|[f]fmpeg'"
ssh pi@172.20.10.2 "pgrep -af '[m]eshnode_'"
```
Se algum mostrar processos: `sudo pkill -KILL -f '[m]eshnode_'` (e, no N1,
`sudo pkill -f '[a]lphabot_node.py'; sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'`, por SSH).

**Arranca o outro método:** segue a **Parte 2** (4.0): `N1_LOCAL=1 ./demo-tmux.sh arp` no PC, e o N1 e o robô à mão no monitor do Pi.

## 4. Parte 2 — método Layer 2 (ARP) com bloqueio

O vídeo agora vai em **TCP**, porque o ARP é um relay transparente que não repõe perdas: é a
aplicação que dá a fiabilidade. **Aqui o N1 e o robô correm no monitor do Pi, não no tmux.**

### 4.0 Arranque (ordem importa)

**a) No PC, terminal normal, sem sudo** (N3, N2 e a base ficam no tmux):
```bash
cd ~/Documentos/RoutingMesh
N1_LOCAL=1 ./demo-tmux.sh arp
```
Entras no tmux com **3 painéis**: N3 e N2 em cima, BASE STATION em baixo. Escreve as palavras-passe
(`sudo` no N3; SSH e `sudo` no N2, se as pedir). A base arranca sozinha aos 5 s com `tcp` e fica à escuta:
o banner tem de dizer **`Video:  tcp://0.0.0.0:5000`** e depois `Proxy TCP a escutar em :5000`.

**b) No monitor do N1, terminal 1: o nó N1**
```bash
cd ~/Documents/RoutingMesh
sudo ./run-node.sh arp 1 3
```
Nas primeiras linhas tem de aparecer `[MAC] Node 1 -> ... [macs.conf]` (e 2 e 3). Se não, o `macs.conf` não está nesta pasta.

**c) Espera ~20 s** com os três nós a correr e a base à escuta.

**d) No monitor do N1, terminal 2: o robô**
```bash
cd ~/Documents/RoutingMesh
sudo python3 alphabot_node.py tcp
```
O banner tem de dizer **`Stream: tcp://10.0.0.3:5000`** e depois `[VIDEO] Stream iniciado (TCP)`. O robô espera
10 s antes da câmara. Na base tem de aparecer `[VIDEO] Robo ligado ... a receber stream TCP`.

Se passados ~15 s do `Stream iniciado` a base ainda não disse `Robo ligado` (o *handshake* TCP demora a
atravessar a mesh): **Ctrl+C no robô e lança-o outra vez**. A base não precisa de reiniciar, aceita reconexões.

> A janela do `ffplay` e a linha `ffplay iniciado — udp://127.0.0.1:5001` dizem `udp` e **isso está certo**: é só o salto
> local, dentro do PC, entre a base e o `ffplay`. Pela mesh o vídeo vai em TCP.

### 4.1 Antes do bloqueio: confirma que o N1 e o N3 se veem diretamente

No **terminal 3** do N1:
```bash
ip neigh show
```
`172.20.10.3` tem de ter o **MAC do N3** (`f0:9e:4a:a2:20:38`, `PERMANENT`). Se já tiver o do N2
(`2c:cf:67:79:93:50`), o N1 e o N3 já não se ouvem e o bloqueio não mostra nada: aproxima os nós.
No PC (janela `controlo`, `Ctrl+b` `n`): `ip neigh show` tem de dar `172.20.10.1` com o MAC do N1.

### 4.2 O bloqueio (dois lados, por MAC, só a receção)

**No terminal 3 do N1** (monitor do N1):
```bash
sudo iptables -I INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP
```
**No PC**, janela `controlo` (`Ctrl+b` `n`):
```bash
sudo iptables -I INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP
```
Escreve os dois seguidos. Espera **~5 s**. Nada no N2.

### 4.3 O que vês

- No **terminal 3 do N1**: `ip neigh show` passa a ter `172.20.10.3` com o **MAC do N2** (`2c:cf:67:79:93:50`).
- No **PC**: `ip neigh show` passa a ter `172.20.10.1` com o **MAC do N2**.
- **O vídeo pára uns segundos e depois continua.** É o TCP: sem os ACKs retransmite com esperas crescentes (0,2 s, 0,4 s, 0,8 s...);
  assim que a rota passa pelo N2, a mesma ligação continua (os IPs são ponta a ponta) e o vídeo recupera o atraso.
- Prova de que o N2 está a reencaminhar, na janela `controlo` do PC:
  ```bash
  ssh pi@172.20.10.2 "sudo iptables -vnxL FORWARD | sed -n 3,5p; sleep 3; sudo iptables -vnxL FORWARD | sed -n 3,5p"
  ```
  O contador da regra `wlan0 → wlan0` **sobe** entre as duas leituras.
- No painel **N3** e no terminal do N1 procura: `[MATRIX] TIMEOUT: No ... expirou`, `[MATRIX] MST mudou!` e `[ROUTING]   arp set ... [relay via 2 ...]`.

Se o vídeo não voltar em ~15 s: **Ctrl+C no robô e relança-o** (`sudo python3 alphabot_node.py tcp`); a base aceita a nova ligação, já pelo N2.

### 4.4 Repor

No terminal 3 do N1 e na janela `controlo` do PC:
```bash
sudo iptables -F INPUT
```
Só mexe na cadeia `INPUT`, onde estão os bloqueios (não apaga as regras de `FORWARD` do relay). Em alguns segundos
`ip neigh show` volta aos MACs diretos. Para tirar só a regra: `sudo iptables -D INPUT -m mac --mac-source <MAC> -j DROP`.

### 4.5 Este bloqueio basta?

**Sim, para esta demonstração**, se cumprires **três condições** (a recuperação em hardware com o `macs.conf`
confirma-se no ensaio):

| Condição | Porquê |
|---|---|
| **Nos dois lados** (N1 e N3) | A topologia usa uma aresta se **um** dos sentidos está confirmado (com uma penalização pequena). Se bloqueares só um lado, a aresta N1–N3 pode continuar na árvore e **não há desvio**: o TCP precisa dos ACKs de volta e o vídeo pára. |
| **Por MAC, não por IP** | No ARP o cabeçalho IP é de ponta a ponta: um pacote que vem **via N2** continua a ter o IP do N1 como origem. Só o **MAC de origem** distingue "veio direto do N1" de "veio pelo N2". Cortar por IP deitava fora também o que vem pelo relay. |
| **Só a receção (INPUT)** | Basta descartar o que se recebe do outro: para os beacons e para os dados é como se o link tivesse caído. |

Esperar ~5 s: a ligação só é dada como perdida ao fim de `MAX_AGE = 2 s` sem beacons, e só então a árvore é recalculada.

**Porque a ligação TCP não morre:** o TCP só conhece IPs, portas e números de sequência, não o caminho. O corte perde
segmentos e ACKs; o TCP retransmite os mesmos segmentos; o ARP passa a mandá-los pelo N2; o N3 aceita-os porque o IP,
as portas e os números de sequência batem, e a ligação continua.

**Por que o `macs.conf`:** o roteamento escreve na tabela ARP `IP do destino -> MAC do próximo salto`. Se o MAC de cada
nó fosse aprendido dessa tabela, o de um nó atrás de um relay ficava com o MAC do relay, e depois do corte o ARP era
reescrito com o MAC errado. O ficheiro fixa os três MACs.

**O que o bloqueio não faz:** não desliga o rádio (os nós continuam a transmitir um ao outro, e o outro deita fora o que recebe) e não afeta o N2.

**Risco por confirmar:** depois do desvio, os beacons do N3 para o N1 também passam pelo N2 e chegam ao N1 com o
MAC do **N2**, que o filtro deixa passar. Podem manter a ligação direta "viva" na matriz e fazer a rota alternar.
Se vires `ip neigh show` a alternar entre o MAC do N3 e o do N2, é isso.

### 4.6 Como explicar (podes dizer isto)

> "Num espaço com três nós não consigo pôr dois nós fora de alcance quando quero, por isso simulo a
> falha de um link por software: o N1 e o N3 passam a descartar tudo o que recebem um do outro, o que
> para a rede é igual a o rádio ter caído. A rede deteta a falha porque deixa de receber os beacons
> desse vizinho: ao fim de dois segundos a ligação sai da matriz de topologia e a árvore é recalculada,
> e o único caminho passa a ser pelo nó do meio.
>
> No método da Ana, o que muda é só a tabela ARP: o routing reescreve a entrada do IP do destino para
> apontar para o MAC do novo vizinho, e o kernel passa a enviar as tramas ao N2, que as reencaminha
> também pelo kernel, sem a aplicação saber. Por isso o vídeo continua.
>
> Corto **por MAC** porque no ARP o IP é de ponta a ponta e só o MAC identifica de que vizinho veio a
> trama; e corto **nos dois lados** porque a topologia só tira uma ligação quando nenhum dos sentidos
> a confirma."

Se perguntarem **porque o L3 e o ARP diferem**: ver `DEMO.md`, secção **F**.

## 5. Fim

```bash
# No monitor do N1 (ARP): Ctrl+C no robô e depois no nó N1.
# No PC:  Ctrl+b d   e depois:
tmux kill-session -t demo
sudo iptables -F INPUT                                  # PC e N1, por garantia
# limpar as entradas ARP permanentes que o método ARP deixou (os 3 nós):
for a in 172.20.10.1 172.20.10.2; do sudo ip neigh del $a dev wlp5s0 2>/dev/null; done
ssh pi@172.20.10.1 'for a in 172.20.10.1 172.20.10.2 172.20.10.3; do sudo ip neigh del $a dev wlan0 2>/dev/null; done'
ssh pi@172.20.10.2 'for a in 172.20.10.1 172.20.10.2 172.20.10.3; do sudo ip neigh del $a dev wlan0 2>/dev/null; done'
```
Se o PC deve voltar ao Wi-Fi normal: `DEMO.md`, secção **B**, "No fim do dia".

## 6. Se algo correr mal

| Sintoma | O que fazer |
|---|---|
| Um painel mostra `--- terminou (codigo N) ---` | Lê as linhas acima desse aviso (é o erro). `Enter` fecha o painel. Corrige e monta outra vez: `Ctrl+b d`, `tmux kill-session -t demo`, `./demo-tmux.sh <método>`. |
| Os painéis N1/N2 dão `Permission denied`, `Connection refused` ou `timed out` | O SSH não chega ao Pi: `ping` ao Pi; se não responde, o PC perdeu o ad-hoc (passo 1.2) ou o Pi não arrancou em ad-hoc. |
| Não aparecem linhas `[TUN] Pacote` no painel N1 | O robô só lança a câmara 10 s depois de arrancar. Se nunca aparecerem: `ssh pi@172.20.10.1 'pgrep -a rpicam-vid; pgrep -a ffmpeg; ip route get 10.0.0.3'`. |
| O vídeo não aparece | Se o robô já terminou, na janela **controlo** (`Ctrl+b n`): `ssh -t pi@172.20.10.1 'cd Documents/RoutingMesh && sudo python3 alphabot_node.py udp'` (`tcp` no ARP). |
| O vídeo está parado no ARP e a base diz `Video: udp://...` | A base foi lançada sem o argumento. Para e relança com `python3 base_station.py tcp` (ou `N1_LOCAL=1 ./demo-tmux.sh arp`). O `ffplay` mostra `udp://127.0.0.1:5001` sempre: é só o salto local. |
| A base não diz `Robo ligado` | O *handshake* TCP demora a atravessar a mesh: `Ctrl+C` no robô e relança-o (`sudo python3 alphabot_node.py tcp`). A base fica a correr. |
| Depois do bloqueio o `ip neigh show` não muda | A rota não mudou: bloqueaste os **dois** lados, por MAC? Esperaste ~5 s? Vê os `[MATRIX] TIMEOUT` e `MST mudou!` nos painéis. |
| Não aparece `[MAC] Node ... [macs.conf]` ao arrancar um nó | O `macs.conf` não está na pasta de onde corres o `run-node.sh`. Reenvia-o com o `rsync` do início. |
| Vídeo não aparece | Confirma o DS4 ligado ao PC (a base sai sem comando) e que a base arrancou **antes** do robô. |
| Câmara ocupada ao reiniciar o robô | `ssh pi@172.20.10.1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"` |
| O PC não pinga um Pi, mas os Pi pingam-se | Entradas ARP permanentes velhas: os comandos do passo 5. |
| `./demo-tmux.sh: nao corras com sudo` | Corre-o como utilizador normal. |
| `ERRO: estas dentro da sessao 'demo'` | Sai com `Ctrl+b d` e corre-o de fora. |
