CC = gcc
CFLAGS = -Wall -Wextra -pthread -g -Iinclude
LDFLAGS = -pthread -lm

SRC_DIR = src
OBJ_DIR = obj
TARGET = meshnode

SRCS = $(SRC_DIR)/main.c $(SRC_DIR)/node.c $(SRC_DIR)/matrix.c \
       $(SRC_DIR)/routing.c $(SRC_DIR)/event_handler.c

OBJS = $(SRCS:$(SRC_DIR)/%.c=$(OBJ_DIR)/%.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $(TARGET) $(LDFLAGS)
	@echo "✅ Compilado com routing!"

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
