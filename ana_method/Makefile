# ═══════════════════════════════════════════════════════════════
# Makefile — RA-TDMAs+  MÉTODO ANA MORAIS (projeto independente)
#
#   make                         → build local (loopback de teste)
#   make MESH_NET_PREFIX=192.168.2 MESH_PHY_IFACE=wlan0
#                                → build para a rede ad-hoc real
#
# O método Ana implica SEMPRE: relay L2 via ARP (ioctl), transporte
# UDP, MST binária. Por isso RELAY_METHOD_ARP está sempre definido.
# ═══════════════════════════════════════════════════════════════

CC      = gcc
CFLAGS  = -Wall -Wextra -pthread -g -Iinclude
LDFLAGS = -pthread -lm

MESH_NET_PREFIX ?= 127.0.0
CFLAGS += -DMESH_NET_PREFIX=\"$(MESH_NET_PREFIX)\"

MESH_PHY_IFACE ?= lo
CFLAGS += -DMESH_PHY_IFACE=\"$(MESH_PHY_IFACE)\"

$(info [BUILD-ANA] phy_prefix=$(MESH_NET_PREFIX)  iface=$(MESH_PHY_IFACE)  relay=kernel/ARP (não-slot)  MST=binária)

SRC_DIR = src
OBJ_DIR = obj
TARGET  = meshnode_ana

SRCS = $(SRC_DIR)/main.c         \
       $(SRC_DIR)/node.c         \
       $(SRC_DIR)/matrix.c       \
       $(SRC_DIR)/net_ana.c      \
       $(SRC_DIR)/sync.c         \
       $(SRC_DIR)/mac_table.c    \
       $(SRC_DIR)/routing_list.c

OBJS = $(SRCS:$(SRC_DIR)/%.c=$(OBJ_DIR)/%.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $(TARGET) $(LDFLAGS)
	@echo "Compilado: $(TARGET) [método Ana Morais]"

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -rf $(OBJ_DIR) $(TARGET)

run1:
	sudo ./$(TARGET) 1 3
run2:
	sudo ./$(TARGET) 2 3
run3:
	sudo ./$(TARGET) 3 3

.PHONY: all clean run1 run2 run3
