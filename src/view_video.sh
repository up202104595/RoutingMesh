#!/bin/bash

# IP da interface TUN deste nó (ex: 10.0.0.1 ou 10.0.0.2)
# Porta onde a Raspberry está a enviar o stream (ajusta se necessário)
PORT=5000

echo "Aguardando stream de vídeo na interface TUN..."
# O ffplay lê o stream UDP vindo da rede Mesh
ffplay -nodisp -f h264 -i udp://0.0.0.0:$PORT -fflags nobuffer -flags low_delay -framedrop