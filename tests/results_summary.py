#!/usr/bin/env python3
"""
results_summary.py — Agregação e tabelas de resultados para tese

Uso:
  python3 results_summary.py               # lê JSONs no diretório atual
  python3 results_summary.py --dir /path   # lê de diretório específico

Produz:
  - Tabela RTT (direto vs relay, média das repetições)
  - Tabela Convergência
  - Tabela Throughput
  - Ficheiro results_summary.txt com tudo
"""

import json
import glob
import argparse
import os
import statistics
import sys

# ── utilidades ────────────────────────────────────────────────────────────────

def load_jsons(pattern):
    results = []
    for f in sorted(glob.glob(pattern)):
        try:
            with open(f) as fh:
                results.append(json.load(fh))
        except Exception as e:
            print(f"  AVISO: não foi possível ler {f}: {e}", file=sys.stderr)
    return results

def avg(lst):
    return statistics.mean(lst) if lst else 0.0

def stdev(lst):
    return statistics.stdev(lst) if len(lst) > 1 else 0.0

def fmt(v, dec=2):
    return f"{v:.{dec}f}" if isinstance(v, (int, float)) else "N/A"

# ── agrupamento por prefixo (remove _rN do label) ────────────────────────────

def group_by_base(results, key="label"):
    import re
    groups = {}
    for r in results:
        base = re.sub(r'_r\d+$', '', r.get(key, "?"))
        groups.setdefault(base, []).append(r)
    return groups

# ── tabelas ───────────────────────────────────────────────────────────────────

def table_rtt(results, out):
    groups = group_by_base(results)
    if not groups:
        out.append("  (sem resultados RTT)\n")
        return

    header = (
        "\n┌──────────────────────────┬────────┬────────┬────────┬────────┬────────┬──────────┐\n"
        "│  Cenário                 │  Runs  │Avg(ms) │Min(ms) │Max(ms) │Std(ms) │Jitter(ms)│\n"
        "├──────────────────────────┼────────┼────────┼────────┼────────┼────────┼──────────┤"
    )
    out.append(header)
    for base, runs in sorted(groups.items()):
        n     = len(runs)
        avgs  = avg([r["avg_ms"]    for r in runs])
        mins  = min(r["min_ms"]    for r in runs)
        maxs  = max(r["max_ms"]    for r in runs)
        stds  = avg([r["std_ms"]   for r in runs])
        jits  = avg([r["jitter_ms"] for r in runs])
        topo  = runs[0].get("topology","?")
        label = base[:26]
        line = (f"\n│  {label:<24}  │ {n:>6} │{avgs:>7.2f} │{mins:>7.2f} │"
                f"{maxs:>7.2f} │{stds:>7.2f} │{jits:>9.3f} │")
        out.append(line)
    out.append("\n└──────────────────────────┴────────┴────────┴────────┴────────┴────────┴──────────┘")


def table_convergence(results, out):
    if not results:
        out.append("  (sem resultados de convergência)\n")
        return

    groups = group_by_base(results)
    header = (
        "\n┌──────────────────────┬────────┬─────────────┬──────────────┬──────────────┐\n"
        "│  Cenário             │  Runs  │  Conv.(ms)  │IA_antes(ms)  │IA_depois(ms) │\n"
        "├──────────────────────┼────────┼─────────────┼──────────────┼──────────────┤"
    )
    out.append(header)
    for base, runs in sorted(groups.items()):
        n      = len(runs)
        convs  = [r["convergence_ms"] for r in runs if r.get("convergence_ms") is not None]
        befs   = [r["inter_arrival_before_ms"]["avg"]
                  for r in runs
                  if isinstance(r.get("inter_arrival_before_ms"), dict)
                  and "avg" in r["inter_arrival_before_ms"]]
        afts   = [r["inter_arrival_after_ms"]["avg"]
                  for r in runs
                  if isinstance(r.get("inter_arrival_after_ms"), dict)
                  and "avg" in r["inter_arrival_after_ms"]]
        conv_s = f"{avg(convs):.0f} ± {stdev(convs):.0f}" if convs else "N/A"
        bef_s  = f"{avg(befs):.1f}" if befs else "N/A"
        aft_s  = f"{avg(afts):.1f}" if afts else "N/A"
        label  = base[:22]
        line   = (f"\n│  {label:<20}  │ {n:>6} │ {conv_s:>11} │ {bef_s:>12} │ {aft_s:>12} │")
        out.append(line)
    out.append("\n└──────────────────────┴────────┴─────────────┴──────────────┴──────────────┘")


def table_throughput(results, out):
    if not results:
        out.append("  (sem resultados de throughput)\n")
        return

    groups = group_by_base(results)
    header = (
        "\n┌──────────────────────────┬────────┬──────────┬──────────┬──────────────┐\n"
        "│  Cenário                 │  Runs  │  PktSize │  Topolog │  Kbps (sent) │\n"
        "├──────────────────────────┼────────┼──────────┼──────────┼──────────────┤"
    )
    out.append(header)
    for base, runs in sorted(groups.items()):
        n     = len(runs)
        psz   = runs[0].get("pkt_size_bytes","?")
        topo  = runs[0].get("topology","?")[:8]
        kbps  = avg([r["throughput_kbps"] for r in runs if "throughput_kbps" in r])
        label = base[:26]
        line  = (f"\n│  {label:<24}  │ {n:>6} │ {str(psz):>8} │ {topo:>8} │ {kbps:>12.1f} │")
        out.append(line)
    out.append("\n└──────────────────────────┴────────┴──────────┴──────────┴──────────────┘")


def comparison_table(rtt_results, thru_results, out):
    """Tabela comparativa direto vs relay — formato pronto para tese.
    Mostra RTT e Throughput separadamente; cada bloco aparece se tiver dados
    de ambos os modos (direto e relay)."""
    _comparison_rtt(rtt_results, out)
    _comparison_throughput(thru_results, out)


def _comparison_throughput(thru_results, out):
    groups = group_by_base(thru_results)
    direct = [r for base, runs in groups.items() if "direct" in base for r in runs]
    relay  = [r for base, runs in groups.items() if "relay"  in base for r in runs]
    if not direct or not relay:
        return
    d_kbps = avg([r["throughput_kbps"] for r in direct if "throughput_kbps" in r])
    r_kbps = avg([r["throughput_kbps"] for r in relay  if "throughput_kbps" in r])
    overhead_pct = (d_kbps - r_kbps) / d_kbps * 100 if d_kbps else 0.0
    out.append(
        "\n┌──────────────────────────────────────────────────────────────────────┐\n"
        "│  Comparação Direto vs Relay — Throughput de vídeo                    │\n"
        "├────────────────────┬────────────────────┬────────────────────────────┤\n"
        "│  Métrica           │  Direto (N1→N3)    │  Relay  (N1→N2→N3)        │\n"
        "├────────────────────┼────────────────────┼────────────────────────────┤\n"
       f"│  Throughput (kbps) │ {d_kbps:>18.1f} │ {r_kbps:>18.1f}           │\n"
       f"│  Overhead relay    │ {'':>18}  {overhead_pct:+.1f} %                     │\n"
        "└────────────────────┴────────────────────┴────────────────────────────┘"
    )


def _comparison_rtt(rtt_results, out):
    groups = group_by_base(rtt_results)

    direct_runs = [r for base, runs in groups.items() if "direct" in base for r in runs]
    relay_runs  = [r for base, runs in groups.items() if "relay"  in base for r in runs]

    if not direct_runs or not relay_runs:
        out.append("\n  RTT: faltam dados de relay (corre o rtt_test em modo relay — "
                   "já incluído no run_all.sh actualizado).")
        return

    d_avg = avg([r.get("avg_ms",    0) for r in direct_runs])
    d_min = min(r.get("min_ms",    0) for r in direct_runs)
    d_max = max(r.get("max_ms",    0) for r in direct_runs)
    d_std = avg([r.get("std_ms",   0) for r in direct_runs])
    d_jit = avg([r.get("jitter_ms",0) for r in direct_runs])
    d_pdr = avg([r.get("pdr_pct", 0)  for r in direct_runs])

    r_avg = avg([r.get("avg_ms",    0) for r in relay_runs])
    r_min = min(r.get("min_ms",    0) for r in relay_runs)
    r_max = max(r.get("max_ms",    0) for r in relay_runs)
    r_std = avg([r.get("std_ms",   0) for r in relay_runs])
    r_jit = avg([r.get("jitter_ms",0) for r in relay_runs])
    r_pdr = avg([r.get("pdr_pct",  0) for r in relay_runs])

    overhead = r_avg - d_avg

    out.append(
        "\n┌──────────────────────────────────────────────────────────────────────┐\n"
        "│  Comparação Direto vs Relay — RTT                                    │\n"
        "├────────────────────┬────────────────────┬────────────────────────────┤\n"
        "│  Métrica           │  Direto (N3↔N1)    │  Relay  (N3→N2→N1)        │\n"
        "├────────────────────┼────────────────────┼────────────────────────────┤\n"
       f"│  RTT médio (ms)    │ {d_avg:>18.2f} │ {r_avg:>18.2f}           │\n"
       f"│  RTT mínimo (ms)   │ {d_min:>18.2f} │ {r_min:>18.2f}           │\n"
       f"│  RTT máximo (ms)   │ {d_max:>18.2f} │ {r_max:>18.2f}           │\n"
       f"│  Desvio padrão     │ {d_std:>18.2f} │ {r_std:>18.2f}           │\n"
       f"│  Jitter (ms)       │ {d_jit:>18.3f} │ {r_jit:>18.3f}           │\n"
       f"│  PDR (%)           │ {d_pdr:>18.1f} │ {r_pdr:>18.1f}           │\n"
       f"│  Overhead relay    │ {'':>18}  + {overhead:.2f} ms                    │\n"
        "└────────────────────┴────────────────────┴────────────────────────────┘"
    )

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="Diretório com ficheiros JSON")
    args = parser.parse_args()

    d = args.dir
    if not os.path.isdir(d):
        print(f"ERRO: pasta não encontrada: {d}")
        print(f"  Estás em: {os.getcwd()}")
        print(f"  Dica: se já estás dentro de tests/, usa só o nome da pasta, ex.:")
        print(f"    python3 results_summary.py --dir results_AAAAMMDD_HHMMSS")
        sys.exit(1)
    rtt_results  = load_jsons(os.path.join(d, "rtt_results_*.json"))
    conv_results = load_jsons(os.path.join(d, "convergence_*.json"))
    thru_results = load_jsons(os.path.join(d, "throughput_*.json"))

    out = []
    out.append("\n" + "=" * 72)
    out.append("  RA-TDMAs+ — Resultados de Tese")
    out.append("=" * 72)

    out.append("\n\n── 1. RTT ────────────────────────────────────────────────────────────")
    table_rtt(rtt_results, out)

    out.append("\n\n── 2. Comparação Direto vs Relay ─────────────────────────────────────")
    comparison_table(rtt_results, thru_results, out)

    out.append("\n\n── 3. Convergência de Topologia ──────────────────────────────────────")
    table_convergence(conv_results, out)

    out.append("\n\n── 4. Throughput UDP ─────────────────────────────────────────────────")
    table_throughput(thru_results, out)

    out.append("\n")

    report = "\n".join(out)
    print(report)

    # guarda em ficheiro de texto
    summary_file = os.path.join(d, "results_summary.txt")
    with open(summary_file, "w") as f:
        f.write(report)
    print(f"\n  Guardado em: {summary_file}")

if __name__ == "__main__":
    main()
