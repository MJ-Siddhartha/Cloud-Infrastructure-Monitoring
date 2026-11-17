# Experiment Results (raw data)

Every number quoted in the project report, the README and the presentation comes from the files in
this folder. They were produced on 17 November 2026 by `scripts/run_experiments.py` against the
running Docker Compose stack (single laptop, see the report for the hardware) and are kept unedited.

| File | Produced by | Contents |
|---|---|---|
| `service_failure_runs.json` | `run_experiments.py service --runs 10` | Per-run timings of the nginx failure → alert → webhook → Telegram → live SSH restart → verification → resolution pipeline, plus a summary (mean / median / min / max / stdev) |
| `flap_cooldown_test.json` | `run_experiments.py flap` | A second failure right after an automatic recovery; shows the cooldown skipping the restart |
| `cpu_fault_runs.json` | `run_experiments.py cpu --runs 2` | CPU saturation: pending/firing times, peak CPU per node, incidents created, Alertmanager inhibition |
| `memory_fault_runs.json` | `run_experiments.py memory --runs 2` | Memory pressure: allocation size, peak memory, HighMemoryUsage timing |
| `cleanup_playbook_test.json` | `run_experiments.py cleanup` | Live disk-cleanup playbook: files before/after, recovery output |
| `webhook_benchmark.json` | `run_experiments.py bench --requests 500` | Webhook latency percentiles and throughput at concurrency 1, 10 and 50 (from the Windows host) |
| `webhook_benchmark_in_network.json` | same, run inside the backend container | Same benchmark without the host network path |
| `overhead_and_scrape.json` | `run_experiments.py overhead` | Node Exporter CPU/RSS, scrape success, scrape and rule-evaluation durations, container footprint |
| `test_results.txt` | pytest / verification suite | Output of the unit, verification, integration and performance test suites |
| `timeseries/*.csv` | `scripts/plot_results.py` | Prometheus time series behind the report figures (unix time, series, value) |

Timestamps are taken from the Docker VM clock (container `date`, Prometheus, Alertmanager,
PostgreSQL rows, `docker logs --timestamps`). Times observed by the harness itself are converted
using a host→VM clock offset measured before each run (`clock_offset_s`).

Known limitations of the data: all nodes are containers sharing one kernel, so CPU and memory
readings are host-wide and identical on every node. Benchmark clients use `127.0.0.1` (on Windows,
`localhost` adds ~45 ms per request through an IPv6 fallback). In `service_failure_runs.json` the
e-mail times were read from the backend log with a 60 s window (see `summary.note`); the harness now
waits up to 60 s itself. The backend ran with four workers (`BACKEND_WORKERS=4`) for all results.
