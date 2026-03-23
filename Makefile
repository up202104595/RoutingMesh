CC      = gcc
CFLAGS  = -Wall -Wextra -pthread -g -Iinclude
LDFLAGS = -pthread -lm

# Prefixo da rede física mesh.
# Testes locais (default): 127.0.0
# Produção WiFi/Raspberry:  make MESH_NET_PREFIX=192.168.2
MESH_NET_PREFIX ?= 127.0.0
CFLAGS += -DMESH_NET_PREFIX=\"$(MESH_NET_PREFIX)\"

SRC_DIR = src
OBJ_DIR = obj
TARGET  = meshnode

SRCS = $(SRC_DIR)/main.c            \
       $(SRC_DIR)/node.c            \
       $(SRC_DIR)/matrix.c          \
       $(SRC_DIR)/routing.c         \
       $(SRC_DIR)/event_handler.c   \
       $(SRC_DIR)/ip_route_netlink.c \
       $(SRC_DIR)/tun.c             \
       $(SRC_DIR)/tx_queue.c

OBJS = $(SRCS:$(SRC_DIR)/%.c=$(OBJ_DIR)/%.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $(TARGET) $(LDFLAGS)
	@echo "Compilado: Layer3 + Netlink + TUN + tx_queue"

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(OBJ_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -rf $(OBJ_DIR) $(TARGET)

run1:
	./$(TARGET) 1 3
run2:
	./$(TARGET) 2 3
run3:
	./$(TARGET) 3 3

.PHONY: all clean run1 run2 run3