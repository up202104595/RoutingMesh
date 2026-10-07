# Guião da demonstração: Layer 3 → mudar de método → Layer 2 (ARP) com bloqueio

Este guião é a sequência ao vivo. A preparação única (compilar, serviço de ad-hoc, SSH
por chave) está no `DEMO.md`, secção **A**.

## 0. Disposição

| Onde | O que tem |
|---|---|
| **PC, monitor 1** | terminal em ecrã inteiro com o **tmux** (os 5 painéis visíveis) |
| **PC, monitor 2** | o **vídeo** (a janela do `ffplay`, que a base abre sozinha: arrasta-a para este monitor) |
| **Pi do AlphaBot (N1)**, com monitor e teclado | um terminal para os comandos do bloqueio |
| **Pi do relay (N2)** | ligado, sem ecrã |
| Robô + comando **DS4** | o DS4 ligado ao PC |

| Nó | IP | MAC |
|---|---|---|
| N1 (AlphaBot) | `172.20.10.1` | `d8:3a:dd:33:f3:be` |
| N2 (relay) | `172.20.10.2` | `2c:cf:67:79:93:50` |
| N3 (PC) | `172.20.10.3` | `f0:9e:4a:a2:20:38` |

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
5. **No monitor do N1**, abre um terminal e deixa-o pronto: `cd ~/Documents/RoutingMesh`.

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
2. Os três painéis dos nós enchem-se de logs. Em ~10-20 s aparece `[GATE] Sync convergiu — trafego de dados ADMITIDO`.
3. **A base e o robô arrancam sozinhos**: esperam que a mesh responda (`[a esperar que a mesh convirja ...]`, depois `[mesh pronta]`). A base abre o `ffplay`; o robô começa o vídeo ~10 s depois.
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

**Arranca o outro método:**
```bash
./demo-tmux.sh arp
```

## 4. Parte 2 — método Layer 2 (ARP) com bloqueio

**Arranque:** igual à Parte 1 (palavra-passe no painel N3, `[GATE]`, base e robô sozinhos). O
vídeo agora vai em **TCP**, porque o ARP é um relay transparente que não repõe perdas: é a
aplicação que dá a fiabilidade.

### 4.1 Antes do bloqueio: confirma que o N1 e o N3 se veem diretamente

No terminal do **N1** (monitor):
```bash
arp -an | grep 172.20.10.3
```
Tem de mostrar o **MAC do N3** (`f0:9e:4a:a2:20:38`, `PERM`). Se já mostrar o do N2
(`2c:cf:67:79:93:50`), o N1 e o N3 **já não se ouvem** e o bloqueio não mostra nada: aproxima os nós.

### 4.2 O bloqueio (dois lados, por MAC, só a receção)

**No terminal do N1** (monitor do N1):
```bash
sudo iptables -I INPUT -m mac --mac-source f0:9e:4a:a2:20:38 -j DROP
```
**No PC**, janela `controlo` (`Ctrl+b` `n`):
```bash
sudo iptables -I INPUT -m mac --mac-source d8:3a:dd:33:f3:be -j DROP
```
Escreve os dois seguidos. Espera ~3 s.

### 4.3 O que vês

- No terminal do **N1**: `arp -an | grep 172.20.10.3` passa a mostrar o **MAC do N2** (`2c:cf:67:79:93:50`).
- **O vídeo continua** (pode parar um instante).
- Prova de que o N2 está a reencaminhar, na janela `controlo` do PC:
  ```bash
  ssh pi@172.20.10.2 "sudo iptables -vnxL FORWARD | sed -n 3,5p; sleep 3; sudo iptables -vnxL FORWARD | sed -n 3,5p"
  ```
  O contador da regra `wlan0 → wlan0` **sobe** entre as duas leituras.
- Os painéis SSH do N1 e do robô: no ARP o PC passa a mandar para o N1 pelo MAC do N2, por isso
  é esperado que **continuem a responder**. Se congelarem, retomam quando repuseres a ligação.
  Não deixes o corte muito tempo ligado (alguns minutos), para o SSH não cair.

### 4.4 Repor

No terminal do N1 e na janela `controlo` do PC:
```bash
sudo iptables -F INPUT
```
Em alguns segundos o `arp -an | grep 172.20.10.3` do N1 volta ao MAC do N3.

### 4.5 Este bloqueio basta?

**Sim, para esta demonstração**, e foi o que testaste (a entrada ARP do N1 passou para o MAC do
N2 e o vídeo chegou). Basta se cumprires **três condições**:

| Condição | Porquê |
|---|---|
| **Nos dois lados** (N1 e N3) | A topologia usa uma aresta se **um** dos sentidos está confirmado (com uma penalização pequena). Se bloqueares só um lado, a aresta N1–N3 continua na árvore e **não há desvio**: o vídeo pára e não volta. |
| **Por MAC, não por IP** | No ARP o cabeçalho IP é de ponta a ponta: um pacote que vem **via N2** continua a ter o IP do N1 como origem. Só o **MAC de origem** distingue "veio direto do N1" de "veio pelo N2". Cortar por IP deitava fora também o que vem pelo relay. |
| **Só a receção (INPUT)** | Basta descartar o que se recebe do outro: para os beacons e para os dados é como se o link tivesse caído. |

Esperar ~3 s: a ligação só é dada como perdida ao fim de `MAX_AGE = 2 s` sem beacons, e só então a árvore é recalculada.

**O que o bloqueio não faz:** não desliga o rádio (os nós continuam a transmitir um ao outro, e o outro deita fora o que recebe) e não afeta o N2.

**Risco por confirmar:** depois do desvio, os beacons do N3 para o N1 também passam pelo N2 (a entrada
ARP muda), e chegam ao N1 com o MAC do **N2**, que o filtro deixa passar. Podem manter a ligação
direta "viva" na matriz e fazer a rota alternar. Se vires o `arp -an | grep 172.20.10.3` a
**alternar** entre o MAC do N3 e o do N2, é isso. No teste que fizeste o desvio ficou estável.

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
# Ctrl+b d   e depois:
tmux kill-session -t demo
sudo iptables -F INPUT                                  # PC, por garantia
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
| Não aparece o `[GATE]` | Os nós não se ouvem: `ping` entre eles; vê se os três painéis estão a correr. |
| A base/robô dizem `[aviso] a mesh nao respondeu em 180 s` | A mesh não convergiu. Arrancaram mesmo assim: pára, resolve e monta outra vez. |
| Vídeo não aparece | A base tem de arrancar antes do robô (já acontece), com o mesmo transporte. Confirma o DS4 ligado. |
| Câmara ocupada ao reiniciar o robô | `ssh pi@172.20.10.1 "sudo pkill -f '[r]picam-vid'; sudo pkill -f '[f]fmpeg'"` |
| O PC não pinga um Pi, mas os Pi pingam-se | Entradas ARP permanentes velhas: os comandos do passo 5. |
| `./demo-tmux.sh: nao corras com sudo` | Corre-o como utilizador normal. |
| `ERRO: estas dentro da sessao 'demo'` | Sai com `Ctrl+b d` e corre-o de fora. |
