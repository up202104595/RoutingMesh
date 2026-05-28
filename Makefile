CC      = gcc
CFLAGS  = -Wall -Wextra -pthread -g -Iinclude
LDFLAGS = -pthread -lm

MESH_NET_PREFIX ?= 127.0.0
CFLAGS += -DMESH_NET_PREFIX=\"$(MESH_NET_PREFIX)\"

MESH_PHY_IFACE ?= enp0s3
CFLAGS += -DMESH_PHY_IFACE=\"$(MESH_PHY_IFACE)\"

# ── Metodo de relay ──────────────────────────────────────────
# make RELAY_METHOD=arp       → ARP trick (metodo Ana Morais 2024)
# make                        → ip_forward (metodo Miguel, default)
ifdef RELAY_METHOD
ifeq ($(RELAY_METHOD),arp)
CFLAGS += -DRELAY_METHOD_ARP
$(info [BUILD] Relay method: ARP trick (Ana Morais 2024))
else
$(info [BUILD] Relay method: ip_forward (Miguel 2025))
endif
else
$(info [BUILD] Relay method: ip_forward (Miguel 2025) [default])
endif

SRC_DIR = src
OBJ_DIR = obj
TARGET  = meshnode

SRCS = $(SRC_DIR)/main.c             \
       $(SRC_DIR)/node.c             \
       $(SRC_DIR)/matrix.c           \
       $(SRC_DIR)/routing.c          \
       $(SRC_DIR)/event_handler.c    \
       $(SRC_DIR)/ip_route_netlink.c \
       $(SRC_DIR)/tun.c              \
       $(SRC_DIR)/tx_queue.c         \
       $(SRC_DIR)/sync.c             \
       $(SRC_DIR)/wifi_quality.c     \
       $(SRC_DIR)/pdr.c

ifdef RELAY_METHOD
ifeq ($(RELAY_METHOD),arp)
SRCS += $(SRC_DIR)/mac_table.c
endif
endif

OBJS = $(SRCS:$(SRC_DIR)/%.c=$(OBJ_DIR)/%.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $(TARGET) $(LDFLAGS)
	@echo "Compilado: $(TARGET) [relay=$(or $(RELAY_METHOD),ipforward)]"

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -rf $(OBJ_DIR) $(TARGET)

# ── Targets de conveniencia ──────────────────────────────────
run8:
	sudo ./$(TARGET) 8 10
run9:
	sudo ./$(TARGET) 9 10
run10:
	sudo ./$(TARGET) 10 10

# ── Compilar ambos os metodos ────────────────────────────────
both:
	$(MAKE) clean && $(MAKE) MESH_NET_PREFIX=$(MESH_NET_PREFIX) MESH_PHY_IFACE=$(MESH_PHY_IFACE)
	cp $(TARGET) meshnode_ipforward
	$(MAKE) clean && $(MAKE) MESH_NET_PREFIX=$(MESH_NET_PREFIX) MESH_PHY_IFACE=$(MESH_PHY_IFACE) RELAY_METHOD=arp
	cp $(TARGET) meshnode_arp
	@echo "Gerado: meshnode_ipforward e meshnode_arp"

.PHONY: all clean run8 run9 run10 both