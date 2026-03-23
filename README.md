# 🌐 RoutingMeshNet - Versão Diogo

## 📖 **BASEADO 100% NO TRABALHO DO DIOGO**

Este projeto segue **EXATAMENTE** a estrutura do RA-TDMAs do Diogo Almeida.

---

## 🎯 **DIFERENÇAS-CHAVE IMPLEMENTADAS:**

### **1. Round Increment NO FIM do Slot**
```c
// COMO O DIOGO FAZ:
void* heartbeat_loop() {
    while (running) {
        begin_of_slot_operations();
        
        wait_for_my_slot();
        
        send_heartbeat();  // ← Envia com round=0 na primeira iteração
        
        update_aging();
        
        end_of_slot_operations();
        round++;           // ← INCREMENTA NO FIM (como Diogo!)
    }
}
```

Comentário do Diogo:
```c
ts.slot_round_counter++;  
/* first round is #0 . set new round at the END of one. */
```

### **2. Estrutura Modular (como Diogo)**
```
RoutingMeshNet/
├── include/
│   ├── node.h      ← Header principal
│   └── matrix.h    ← Header da matriz
├── src/
│   ├── node.c      ← Implementação do nó
│   └── matrix.c    ← Implementação da matriz (separado!)
├── main.c          ← Entry point
└── Makefile
```

### **3. Operações de Slot Separadas**
```c
// Como o Diogo:
begin_of_slot_operations(node);  // Sincronização, requests
// ... transmissão ...
end_of_slot_operations(node);    // Estatísticas, round++
```

---

## 📊 **SEMÂNTICA DO ROUND:**

### **Diogo:**
- Round 0 = primeira iteração
- Round é incrementado **DEPOIS** de enviar
- Todos os heartbeats de um slot têm o **mesmo round number**

### **Exemplo:**
```
Slot 0 (Round 0):
  send_heartbeat()  → round=0
  send_heartbeat()  → round=0
  end_of_slot()
  round++           → agora round=1

Slot 1 (Round 1):
  send_heartbeat()  → round=1
  ...
```

---

## 🔬 **CONCEITOS IMPLEMENTADOS:**

### **1. TDMA Slots**
- Cada nó tem slot específico (33.333 ms)
- Frame = N × 33.333 ms
- `wait_for_my_slot()` coordena transmissões

### **2. Matriz de Adjacência**
- Cada nó mantém sua linha
- `adjacency_matrix[i] = 1` → consigo ouvir Node (i+1)
- Separada em `matrix.c` (como Diogo)

### **3. Aging Mechanism**
```c
// Quando RECEBO heartbeat:
node_age[sender] = 0;  // Reseta

// A cada round:
node_age[i]++;  // Incrementa

// Se timeout:
if (node_age[i] > 5) {
    adjacency_matrix[i] = 0;  // Desconecta
}
```

---

## 🚀 **COMPILAR E TESTAR:**

```bash
make

# Abrir 3 terminais:
./mesh_node 1 3
./mesh_node 2 3
./mesh_node 3 3
```

---

## 📈 **SAÍDA ESPERADA:**

```
[Node 1] 💓 Round 0 (slot 0, time 0.234 ms)
[Node 1] 💓 Round 10 (slot 0, time 0.187 ms)
[Node 1] 📥 Recebido de Node 2 (total: 10)

# A cada 20 segundos:
═══════════════════════════════════════════════════════════
  MATRIZ DE ADJACÊNCIA - Node 1 (Round 200)
═══════════════════════════════════════════════════════════
       N1  N2  N3  
  N1 |  -   ✓   ✓   ← Vê todos!

  📊 Node Age (rounds sem heartbeat):
     Node 2: 0 rounds
     Node 3: 1 rounds

  📈 Estatísticas:
     Slot round counter: 200  ← Igual ao Diogo!
     Vizinhos ativos: 2/2
═══════════════════════════════════════════════════════════
```

---

## 🔑 **DIFERENÇAS VS VERSÃO ANTERIOR:**

| Aspecto | Anterior | Agora (Diogo) |
|---------|----------|---------------|
| **Round increment** | ANTES de enviar | NO FIM do slot ✅ |
| **Primeiro round** | 1 | 0 ✅ |
| **Estrutura** | Tudo em node.c | matrix.c separado ✅ |
| **Operações slot** | Inline | begin/end functions ✅ |
| **slot_round_counter** | ❌ | ✅ Sim |

---

## 📚 **REFERÊNCIAS:**

Baseado em:
- `tdma.c` do Diogo → `node.c`
- `matrix.c` do Diogo → `matrix.c`
- `tdma_slot.c` do Diogo → funções de slot em `node.c`

---

## ✅ **STATUS:**

- ✅ Round incrementado como Diogo (no fim)
- ✅ Estrutura modular com matrix.c
- ✅ begin_of_slot / end_of_slot operations
- ✅ slot_round_counter implementado
- ✅ Aging mechanism
- ✅ TDMA slots coordenados

**Pronto para testar!** 🚀# RoutingMesh
