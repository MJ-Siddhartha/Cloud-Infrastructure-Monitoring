#!/usr/bin/env python3
"""
plot_results.py - turn the raw experiment results into report figures.

Reads results/*.json written by scripts/run_experiments.py, exports the
relevant Prometheus time series for each experiment window to
results/timeseries/*.csv (so the figures can be regenerated offline), and
writes PDF figures to Report/figures/.

Usage:  python scripts/plot_results.py [--offline]
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
TS = RES / "timeseries"
FIG = ROOT / "Report" / "figures"
PROM = "http://localhost:9090"

plt.rcParams.update({"font.family": "serif", "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3, "figure.dpi": 150, "savefig.bbox": "tight"})
C = {"blue": "#2b6cb0", "red": "#c53030", "green": "#2f855a", "orange": "#dd6b20",
     "gray": "#718096", "purple": "#6b46c1"}


def load(name):
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ts(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()


def export_range(name, query, start, end, step="2s"):
    """Fetch a range query from Prometheus and store it as CSV (time, series, value)."""
    import httpx
    r = httpx.get(f"{PROM}/api/v1/query_range",
                  params={"query": query, "start": start, "end": end, "step": step}, timeout=30).json()
    TS.mkdir(parents=True, exist_ok=True)
    with open(TS / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["unix_time", "series", "value"])
        for s in r["data"]["result"]:
            label = s["metric"].get("instance", "") + ("/" + s["metric"]["state"] if "state" in s["metric"] else "")
            for t, v in s["values"]:
                w.writerow([t, label, v])


def read_series(name):
    out = {}
    with open(TS / f"{name}.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["series"], ([], []))
            out[row["series"]][0].append(float(row["unix_time"]))
            out[row["series"]][1].append(float(row["value"]))
    return out


# --------------------------------------------------------------------------
def fig_service_stages(svc):
    runs = [r for r in svc["runs"] if "incident_after_s" in r]
    stages = [("alertmanager_startsAt_after_s", "Alert firing\n(startsAt)"),
              ("incident_after_s", "Incident stored\n(backend)"),
              ("telegram_after_s", "Telegram\ndelivered"),
              ("email_after_s", "E-mail\naccepted"),
              ("fault_to_recovered_s", "Service restored\n(verified)"),
              ("resolved_after_s", "Alert resolved")]
    fig, ax = plt.subplots(figsize=(6.2, 3.3))
    for k, (key, label) in enumerate(stages):
        vals = [r[key] for r in runs if r.get(key) is not None]
        if not vals:
            continue
        ax.boxplot(vals, positions=[k], widths=0.45, vert=False, showfliers=False,
                   medianprops={"color": C["red"]})
        ax.scatter(vals, [k] * len(vals), s=12, color=C["blue"], alpha=0.7, zorder=3)
        ax.text(max(vals) + 1, k, f"mean {sum(vals)/len(vals):.1f} s", va="center", fontsize=7.5)
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels([s[1] for s in stages])
    ax.invert_yaxis()
    ax.set_xlabel("Time after nginx was stopped (s)")
    ax.set_title(f"Service-failure pipeline, {len(runs)} live runs", fontsize=9)
    ax.set_xlim(left=0)
    fig.savefig(FIG / "exp_service_stages.pdf")
    plt.close(fig)


def fig_service_state(svc, offline):
    t_first = ts(svc["runs"][0]["t0"]) - 30
    t_last = ts(svc["runs"][-1]["t0"]) + 90
    if not offline:
        export_range("service_state", 'node_systemd_unit_state{instance="app-server-01:9100",name="nginx.service",state="failed"}', t_first, t_last, "1s")
        export_range("service_alerts", 'ALERTS{alertname="SystemdServiceFailed",instance="app-server-01:9100"}', t_first, t_last, "1s")
    s = read_series("service_state")
    fig, ax = plt.subplots(figsize=(6.2, 1.9))
    for _, (t, v) in s.items():
        ax.step([(x - t_first) / 60 for x in t], v, where="post", color=C["red"], lw=0.9, label="nginx failed (scraped)")
    for r in svc["runs"]:
        ax.axvline((ts(r["t0"]) - t_first) / 60, color=C["gray"], lw=0.5, ls=":")
    ax.set_ylim(-0.1, 1.2)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["active", "failed"])
    ax.set_xlabel("Experiment time (min); dotted lines = fault injected")
    ax.set_title("nginx state on app-server-01 during the service-failure experiment", fontsize=9)
    fig.savefig(FIG / "exp_service_state.pdf")
    plt.close(fig)


def fig_cpu(cpu, offline):
    r = cpu["runs"][0]
    t0 = ts(r["t0"])
    start, end = t0 - 30, t0 + r["duration_s"] + 90
    if not offline:
        export_range("cpu_run1", '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)', start, end, "2s")
    s = read_series("cpu_run1")
    fig, ax = plt.subplots(figsize=(6.2, 2.6))
    for name, (t, v) in s.items():
        if name.startswith("app-server-01"):
            ax.plot([x - t0 for x in t], v, color=C["blue"], lw=1.2, label="CPU utilisation (1 m rate)")
    ax.axhline(50, color=C["orange"], ls="--", lw=0.9, label="warning threshold 50 %")
    ax.axhline(75, color=C["red"], ls="--", lw=0.9, label="critical threshold 75 %")
    ax.axvspan(0, r["duration_s"], color=C["gray"], alpha=0.12, label="stress-ng running")
    for key, col, lab in (("HighCPUUsage_firing", C["orange"], "HighCPU firing"),
                          ("CriticalCPUUsage_firing", C["red"], "CriticalCPU firing")):
        if r.get(key):
            ax.axvline(r[key], color=col, lw=1.2)
            ax.text(r[key] + 1, 5 if "High" in key else 15, lab, color=col, fontsize=7)
    ax.set_xlabel("Time since load started (s)")
    ax.set_ylabel("CPU (%)")
    ax.set_ylim(0, 100)
    ax.legend(fontsize=6.5, loc="upper right")
    ax.set_title("CPU saturation experiment (run 1)", fontsize=9)
    fig.savefig(FIG / "exp_cpu_run.pdf")
    plt.close(fig)


def fig_memory(mem, offline):
    r = mem["runs"][0]
    t0 = ts(r["t0"])
    start, end = t0 - 30, t0 + 150
    if not offline:
        export_range("memory_run1", '(1 - node_memory_MemAvailable_bytes{instance="app-server-01:9100"} / node_memory_MemTotal_bytes{instance="app-server-01:9100"}) * 100', start, end, "2s")
    s = read_series("memory_run1")
    fig, ax = plt.subplots(figsize=(6.2, 2.3))
    for _, (t, v) in s.items():
        ax.plot([x - t0 for x in t], v, color=C["purple"], lw=1.2, label="memory used")
    ax.axhline(60, color=C["orange"], ls="--", lw=0.9, label="warning threshold 60 %")
    ax.axhline(80, color=C["red"], ls="--", lw=0.9, label="critical threshold 80 %")
    if r.get("firing_after_s"):
        ax.axvline(r["firing_after_s"], color=C["orange"], lw=1.2)
        ax.text(r["firing_after_s"] + 1, 30, "HighMemory firing", color=C["orange"], fontsize=7)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Time since allocation started (s)")
    ax.set_ylabel("Memory (%)")
    ax.legend(fontsize=6.5, loc="upper right")
    ax.set_title("Memory pressure experiment (run 1)", fontsize=9)
    fig.savefig(FIG / "exp_memory_run.pdf")
    plt.close(fig)


def fig_bench(b):
    modes = [("sequential", "1"), ("concurrent_10", "10"), ("concurrent_50", "50")]
    fig, ax = plt.subplots(figsize=(6.2, 2.4))
    width = 0.25
    for k, (p, col) in enumerate((("p50_ms", C["green"]), ("p95_ms", C["orange"]), ("p99_ms", C["red"]))):
        vals = [b[m][p] for m, _ in modes]
        bars = ax.bar([i + (k - 1) * width for i in range(3)], vals, width, color=col, label=p.replace("_ms", "").upper())
        ax.bar_label(bars, fmt="%.1f", fontsize=6.5)
    ax.set_xticks(range(3))
    ax.set_xticklabels([f"concurrency {c}\n({b[m]['throughput_rps']} req/s)" for m, c in modes])
    ax.set_ylabel("Latency (ms)")
    ax.legend(fontsize=7)
    ax.set_title(f"Webhook ingestion latency ({b['sequential']['requests']} requests per mode)", fontsize=9)
    fig.savefig(FIG / "exp_webhook_latency.pdf")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use saved CSVs, do not query Prometheus")
    a = ap.parse_args()
    FIG.mkdir(parents=True, exist_ok=True)
    if (svc := load("service_failure_runs")):
        fig_service_stages(svc)
        fig_service_state(svc, a.offline)
    if (cpu := load("cpu_fault_runs")):
        fig_cpu(cpu, a.offline)
    if (mem := load("memory_fault_runs")):
        fig_memory(mem, a.offline)
    if (b := load("webhook_benchmark")):
        fig_bench(b)
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
