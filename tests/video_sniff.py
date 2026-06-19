#!/usr/bin/env python3
"""
video_sniff.py — Captura PASSIVA do vídeo UDP sem ocupar a porta 5000.

Problema que resolve:
  Os testes passivos (throughput_test.py, tdma_timing_test.py) precisam de
  OBSERVAR o vídeo que já flui para a porta 5000, ao mesmo tempo que o ffplay /
  base_station.py também a escuta. Fazer bind à porta 5000 (mesmo com
  SO_REUSEPORT) é frágil:
    - se o outro processo (ffplay) não usar SO_REUSEPORT → "Address already in
      use" (Errno 98);
    - mesmo com SO_REUSEPORT, o kernel DIVIDE os datagramas UDP por hash da
      4-tupla; como o vídeo tem uma só origem, um socket fica com tudo e o
      outro com nada — a medição rouba pacotes ao vídeo e fica errada.

Solução:
  Um socket AF_PACKET (raw) observa as tramas no fio e filtra só o UDP destinado
  à porta de vídeo. NÃO faz bind à porta 5000 → nunca colide e NÃO rouba pacotes
  ao ffplay. Requer root (CAP_NET_RAW); sem root cai automaticamente para o
  método antigo de SO_REUSEPORT.

Uso (no chamador):
    tap = VideoTap(5000, iface="wlp5s0")   # iface opcional (None = todas)
    print(tap.mode)                         # 'raw' ou 'reuseport'
    while ...:
        r = tap.recv()
        if r is None:        # timeout do socket
            continue
        if r is False:       # trama capturada mas não é vídeo (só modo raw)
            continue
        ts, payload_len = r
    tap.close()
"""

import socket
import struct
import time

ETH_P_ALL = 0x0003
ETH_P_IP  = 0x0800

# timeout por leitura do socket (segundos) — igual ao usado antes nos testes
_RECV_TIMEOUT = 0.1


class PermissionFallback(Exception):
    """AF_PACKET indisponível (sem root ou SO não-Linux) → usar SO_REUSEPORT."""
    pass


class VideoTapError(Exception):
    """Não foi possível abrir a captura (nem raw nem reuseport)."""
    pass


def _open_raw(iface=None):
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    except PermissionError as e:
        raise PermissionFallback(f"sem permissão para AF_PACKET ({e}) — corre com sudo")
    except AttributeError:
        raise PermissionFallback("AF_PACKET indisponível (não-Linux)")
    if iface:
        s.bind((iface, 0))
    s.settimeout(_RECV_TIMEOUT)
    return s


def _open_reuseport(port, bind_ip="0.0.0.0"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    try:
        s.bind((bind_ip, port))
    except OSError as e:
        s.close()
        raise VideoTapError(
            f"não foi possível abrir a captura na porta {port} ({e}).\n"
            f"         → corre o teste com 'sudo' (usa o sniffer raw, sem ocupar "
            f"a porta).\n"
            f"         O fallback sem root falha porque o ffplay já segura a "
            f"porta {port}.")
    s.settimeout(_RECV_TIMEOUT)
    return s


def _udp_payload_len_to_port(frame, want_dport):
    """
    Recebe uma trama Ethernet crua e devolve o tamanho do PAYLOAD UDP (bytes de
    aplicação, = len que o recvfrom devolveria) se for UDP destinado a
    `want_dport`. Caso contrário devolve None.
    """
    n = len(frame)
    if n < 14:
        return None
    eth_proto = struct.unpack("!H", frame[12:14])[0]
    off = 14
    if eth_proto == 0x8100:           # tag VLAN 802.1Q
        if n < 18:
            return None
        eth_proto = struct.unpack("!H", frame[16:18])[0]
        off = 18
    if eth_proto != ETH_P_IP:
        return None
    if n < off + 20:
        return None
    ihl = (frame[off] & 0x0F) * 4
    if frame[off + 9] != 17:          # protocolo != UDP
        return None
    udp_off = off + ihl
    if n < udp_off + 8:
        return None
    dport = struct.unpack("!H", frame[udp_off + 2:udp_off + 4])[0]
    if dport != want_dport:
        return None
    udp_len = struct.unpack("!H", frame[udp_off + 4:udp_off + 6])[0]
    return max(0, udp_len - 8)         # tira o cabeçalho UDP (8 B)


class VideoTap:
    """Observador passivo do vídeo UDP. Abstrai 'raw' vs 'reuseport'."""

    def __init__(self, port, iface=None, prefer_raw=True):
        self.port = port
        self.mode = None
        self.sock = None
        if prefer_raw:
            try:
                self.sock = _open_raw(iface)
                self.mode = "raw"
            except PermissionFallback as e:
                print(f"[SNIFF] modo raw indisponível: {e}")
        if self.sock is None:
            self.sock = _open_reuseport(port)
            self.mode = "reuseport"
        print(f"[SNIFF] captura na porta {port} em modo '{self.mode}'"
              + (f" (iface={iface})" if iface and self.mode == "raw" else ""))

    def recv(self):
        """
        Devolve:
          (ts, payload_len)  — um pacote de vídeo observado
          None               — timeout (sem tráfego nesta janela)
          False              — trama capturada que NÃO é vídeo (só modo raw)
        """
        try:
            data = self.sock.recv(65535)
        except socket.timeout:
            return None
        ts = time.perf_counter()
        if self.mode == "reuseport":
            return (ts, len(data))
        plen = _udp_payload_len_to_port(data, self.port)
        if plen is None:
            return False
        return (ts, plen)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
