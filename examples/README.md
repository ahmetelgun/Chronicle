# Example Log Files

The `.log` files in this directory are **reference examples** of the standard
Chronicle log format that scripts produce with `job_logger` (generated from real
runs, with paths/users neutralized).

| File | Scenario |
|---|---|
| `mail_report-...log` | **SUCCESS** — custom header (`env`, `campaign`, `version`), `email` events, metrics, resource measurement, and custom footer (`delivery_rate_pct`, `recipients_total`) |
| `backup-...log` | **FAILED** — `ERROR`/`ERR` lines, exit code 1 |
| `long_running-...log` | **TIMEOUT** — run killed by the scheduler |

## Format

```
# ===================== EXECUTION LOG (UTC) =====================
# job / script / cwd / trigger / user / pid / started   + custom header fields
# ==============================================================
<YYYY-MM-DD HH:MM:SS.mmm>  <LEVEL>  <message>     # all times in UTC
# --------------------------------------------------------------
# status / exit_code / finished / duration_sec
# cpu_time_sec / cpu_pct / max_rss_mb
# summary_events / summary_metrics                + custom footer fields
# ==============================================================
```

- **The presence of the footer = the job has finished.** If there is no footer:
  "Running" if the process is alive, "Aborted" (ABORTED) if it has died.
- Levels: `OUT`, `ERR`, `INFO`, `WARN`, `ERROR`, `EVENT`, `METRIC`.
- File name: `<script_stem>-<YYYYmmddHHMMSS_UTC>-<pid>.log` (the PID prevents collisions).
