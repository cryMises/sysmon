# sysmon

A small, read-only Linux system monitor for **Ubuntu running inside Termux** (including `proot-distro`). It renders CPU load and frequency, memory/swap usage, disk usage, uptime, and battery status as a [Rich](https://github.com/Textualize/rich) terminal dashboard.

No root permissions, no writes, and no system settings are touched.

## Features

- CPU load averages (1/5/15 min), CPU usage, core count, and per-cluster frequencies from `cpufreq` sysfs.
- Container-aware CPU and memory limits when cgroup v2 is readable.
- RAM and swap usage with bars and human-readable sizes.
- Disk usage for one or more paths.
- Uptime and boot time, extrapolated when `/proc/uptime` is frozen.
- Battery level, charging state, temperature, health, technology, power draw, estimated time remaining, and cache age via `termux-battery-status` when available.
- One-shot dashboard or live-refreshing watch mode.
- Watch mode adds live-only details:
  - Network RX/TX totals, throughput rates, and a per-interface breakdown.
  - Live CPU usage even when `/proc/stat` is frozen (via per-process CPU time).
  - Running/total process counts, plus configurable top-N, sort order, and command filter.
  - In-memory trend strips (sparklines) for CPU, memory, RX/TX, and battery.
  - Threshold alerts for CPU, memory, disk, and battery.
  - Sample counter, session duration, and refresh status.
- JSON output for scripting, including network, process, and battery details.
- JSON Lines streaming: `--json --watch` prints one compact JSON object per refresh.
- Optional JSON config file for paths, interval, process settings, trends, and alert thresholds.
- Graceful degradation: missing `/proc` entries or external utilities produce a warning panel, not a traceback.
- Responsive layout: side-by-side panels on wide terminals, stacked on narrow Termux screens.
- ASCII bar/sparkline mode and `--no-color` for limited terminals.
- Continuous integration: ruff lint, strict mypy, and pytest with coverage on Python 3.10–3.14.

## Requirements

- Python 3.10 or newer.
- [Rich](https://pypi.org/project/rich/) 13.7+ (installed from `requirements.txt`).
- Optional: [Termux:API](https://wiki.termux.com/wiki/Termux:API) (`pkg install termux-api` plus the Termux:API app) for the battery panel. Without it, the panel is hidden.

## Install

### Termux (native)

```bash
pkg update
pkg install python
pkg install termux-api    # optional: enables the battery panel
cd /path/to/sysmon
python -m pip install -r requirements.txt
```

### Ubuntu inside Termux (`proot-distro`)

Run these inside the Ubuntu container:

```bash
cd /path/to/sysmon
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

If `python3 -m venv` reports that `ensurepip` is missing, install the distro's `python3-venv` package once. That is environment setup only; sysmon itself never needs root.

Optional editable install to get a `sysmon` command:

```bash
python -m pip install -e .
```

### Plain Ubuntu VM (e.g. Azure)

On a regular cloud VM there is no Termux and no battery; sysmon detects
that on its own (the battery panel hides itself, and the Android/PRoot
fallbacks stay unused because the real `/proc` counters work). Install
and run it the same way:

```bash
git clone --branch azure-vm https://github.com/cryMises/sysmon.git
cd sysmon
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
sysmon --watch
```

The `azure-vm` branch adds one thing a VM host wants: a **Docker panel**
(live mode and JSON only) listing each running container with its CPU %
and memory usage/limit, read from
`docker stats --no-stream --format {{json .}}`. The panel is
best-effort — if Docker is missing, stopped, or the socket is not
readable by your user, it hides itself instead of warning. Reading the
Docker socket requires membership of the `docker` group (or running
sysmon with `sudo`); disable the panel entirely with `--no-docker` or
`"docker": false` in the config file.

`config.vm.json` in this branch is a ready-made config for a small
Docker host — root disk only, battery off, processes sorted by memory:

```bash
sysmon --watch --config config.vm.json
```

## Run

One snapshot (the default):

```bash
python -m sysmon
```

Live dashboard, refreshing every 2 seconds until `Ctrl+C`:

```bash
python -m sysmon --watch
```

Faster refresh and two filesystem paths:

```bash
python -m sysmon --watch --interval 1 --path / --path "$HOME"
```

JSON:

```bash
python -m sysmon --json
python -m sysmon --json | python -m json.tool
```

JSON Lines (one object per refresh, useful for logging):

```bash
python -m sysmon --watch --json --count 10 | jq -c '.cpu.usage_percent'
```

If installed with `pip install -e .`, replace `python -m sysmon` with `sysmon`.

### Options

| Option | Description |
| --- | --- |
| `-w`, `--watch` | Refresh until `Ctrl+C`, with network, process, trend, and session details. Default is one snapshot. |
| `--once` | Explicitly print one snapshot and exit. |
| `-i`, `--interval SECONDS` | Watch refresh interval, minimum `0.5` (default `2.0`). |
| `-p`, `--path PATH` | Filesystem path to report. Repeat for multiple paths. Default `/`. |
| `--config PATH` | Load settings from a JSON config file. Command-line options win over it. |
| `--top N` | Number of processes to show, `1`–`50` (default `5`). |
| `--sort {cpu,mem,pid}` | Process sort order (default `cpu`). |
| `--filter REGEX` | Only show processes whose command matches this regular expression. |
| `--full-command` | Show the full command line instead of only the process name. |
| `--json` | Print raw data as JSON. With `--watch`, emit JSON Lines instead of the dashboard. |
| `--no-battery` | Skip the `termux-battery-status` query. |
| `--no-docker` | Skip the `docker stats` query for running containers (`azure-vm` branch). |
| `--no-trends` | Disable the in-memory watch-mode trend strips. |
| `--trend-samples N` | Number of trend samples to retain, `2`–`1000` (default `60`). |
| `--count N` | Stop watch/JSON Lines after `N` samples. |
| `--ascii` | Use `#`/`-` bars and `.`–`@` sparklines instead of Unicode blocks. |
| `--no-color` | Disable colors. |
| `--version` | Print the version. |

When `--watch` is used without an interactive terminal, sysmon prints one snapshot and exits instead of looping. This keeps logs and pipes predictable. `--json --watch` is the exception: it always streams JSON Lines, because that mode exists to be piped.

### Configuration file

`--config PATH` loads a small JSON file. Every key is optional; command-line options override the file, and anything left unset uses the defaults.

```json
{
  "interval": 2.0,
  "paths": ["/", "/data"],
  "battery": true,
  "processes": {
    "limit": 5,
    "sort": "cpu",
    "filter": null,
    "full_command": false
  },
  "trends": {
    "enabled": true,
    "samples": 60
  },
  "thresholds": {
    "cpu": { "warning": 75, "critical": 90 },
    "memory": { "warning": 80, "critical": 92 },
    "disk": { "warning": 85, "critical": 95 },
    "battery": { "warning": 30, "critical": 15 }
  },
  "ascii": false,
  "no_color": false
}
```

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `interval` | number | `2.0` | Watch refresh interval, minimum `0.5`. |
| `paths` | list of strings | `/` | Filesystem paths to report. |
| `battery` | bool | `true` | Query `termux-battery-status`. |
| `processes.limit` | int | `5` | `1`–`50`. |
| `processes.sort` | string | `cpu` | `cpu`, `mem`, or `pid`. |
| `processes.filter` | string or null | `null` | Regular expression matched against the command. |
| `processes.full_command` | bool | `false` | Use `/proc/[pid]/cmdline` instead of `comm`. |
| `trends.enabled` | bool | `true` | Show the watch-mode trend strips. |
| `trends.samples` | int | `60` | `2`–`1000` retained samples. |
| `thresholds.<metric>` | object | see above | `warning` and `critical` percentages, `0`–`100`. |
| `ascii` | bool | `false` | ASCII bars and sparklines. |
| `no_color` | bool | `false` | Disable colors. |

Unknown keys, wrong types, out-of-range values, and invalid regular expressions are rejected with a clear error message instead of a traceback.

### Thresholds and alerts

Each metric has a `warning` and a `critical` percentage. CPU, memory, and disk alert when usage is **at or above** the threshold; battery alerts when the charge is **at or below** it (so battery thresholds are inverted, and `critical` must not exceed `warning`).

When a metric crosses a threshold, the dashboard shows an `Alerts` panel above the other panels, and the corresponding meter changes colour (green → yellow → red). Thresholds are configured through the config file only; the JSON output always contains the raw measurements.

### Watch mode details

`sysmon -w` refreshes the dashboard in an alternate screen and adds four live-only things (the Battery panel is separate and appears whenever its command is available):

1. **Network** — RX/TX totals plus bytes-per-second rates. Loopback is excluded when other interfaces are present. The first frame says `rate pending`; later frames use counter deltas. When per-interface counters are readable, the busiest interfaces are listed with their own RX/TX rates. Sources are tried in order: `/proc/net/dev`, `/sys/class/net`, Android's `netstats` binder service (via `service call netstats 13`), then `ip -s -j link`.
2. **Processes** — running/total counts from `/proc`, plus the top processes (five by default). CPU percentages are computed from per-process `/proc/[pid]/stat` time deltas. If those counters are unavailable, sysmon falls back to `ps`; if that also fails, it shows the largest resident-memory processes from `/proc` with CPU as `n/a`. `--top`, `--sort`, `--filter`, and `--full-command` change what is listed; the counts always describe every process.
3. **Trends** — an in-memory history (default 60 samples) rendered as sparklines for CPU, memory, RX/TX, and battery, each with the current value and the period maximum (minimum for battery). The history lives only in the running process and is never written to disk. `--no-trends` turns the panel off.
4. **Session footer** — refresh interval, sample number, and how long the watch session has been running.

The footer looks like:

```text
Ctrl+C to quit  ·  refresh 2s  ·  sample #12  ·  watching 24s
```

When `termux-battery-status` is available, a Battery panel is shown in both one-shot and watch modes. It reports charge level, charging/plug state, temperature, health, and battery technology, plus an estimated power draw (voltage × current) and the time remaining while discharging. Termux:API round trips can take a couple of seconds, so watch mode caches the result for 30 seconds and shows how old the cached reading is; `--no-battery` skips the query entirely.

On standard Linux, network accounting uses `/proc/net/dev`. Android denies unprivileged apps access to it, so sysmon falls back to the `netstats` binder service and can still show device-wide RX/TX totals and rates (without a per-interface breakdown, which Android does not expose to apps). If every source is blocked, sysmon shows `Network data unavailable` and a warning. Process details and session status still work. Process CPU uses `/proc` deltas in watch mode; values from the `ps` fallback are lifetime averages.

## Example output

The layout below is from this workspace at 100 columns. In this PRoot environment `/proc/stat` counters are static, so CPU usage is derived from per-process CPU time and labelled accordingly. `/proc/net/dev` is blocked, so the Network panel uses Android's `netstats` service.

```text
sysmon  system monitor                                                           2026-10-22 14:39:11
localhost · Ubuntu 26.04.1 LTS · aarch64
────────────────────────────────────────────────────────────────────────────────────────────────────
╭─ CPU ─────────────────────────────────────────╮ ╭─ Memory ───────────────────────────────────────╮
│ load 1/5/15 0.12 / 0.07 / 0.02                │ │ RAM   ██████████░░░░░░  60.8%                  │
│ usage       ██░░░░░░░░░░░░░░  11.3%           │ │       6.7 GiB used / 11.1 GiB total            │
│ cores       8                                 │ │ SWAP  ███████████░░░░░  67.0%                  │
│ CPU 0-3     480 MHz / 2.20 GHz max            │ │       5.4 GiB used / 8.0 GiB total             │
│ CPU 4-6     2.20 GHz / 3.20 GHz max           │ ╰─ src: /proc/meminfo ───────────────────────────╯
│ CPU 7       400 MHz / 3.35 GHz max            │
╰─ src: /proc/loadavg + /proc/[pid]/stat ───────╯
╭─ Disk ────────────────────────────────────────╮ ╭─ Uptime ───────────────────────────────────────╮
│ /                                             │ │ 2m 4s                                          │
│ █████░░░░░░░░░░░  31.8%                       │ │ booted 2026-10-22 14:37                        │
│ 148.1 GiB / 465.4 GiB used · 316.8 GiB free   │ ╰─ src: /proc/uptime ────────────────────────────╯
╰─ src: statvfs ────────────────────────────────╯
╭─ Battery ────────────────────────────────────────────────────────────────────────────────────────╮
│ ████████░░░░░░░░  49.0%  Discharging · Unplugged                                                 │
│ 33.9°C · Good · Li-poly · 2.17 W · ~3h 50m left                                                  │
╰─ src: termux-battery-status ─────────────────────────────────────────────────────────────────────╯
Run with --watch for live updates  ·  --json for JSON
```

On a narrow terminal the panels stack vertically.

In live mode, three more panels are added below the battery (when present):

```text
╭─ Trends ───────────────────────────────────────────────────────────────────────────────────────────────────╮
│ CPU ▂▂▂ 18.7%  max 18.7%                                                                                   │
│ RAM ▅▅▅ 54.7%  max 54.7%                                                                                   │
│ RX   █▃ 250 B/s  peak 1.0 KiB/s                                                                            │
│ TX   █▁ 0 B/s  peak 960 B/s                                                                                │
│ BAT ▇▇▇ 81.0%  low 81.0%                                                                                   │
╰─ src: in-memory history ───────────────────────────────────────────────────────────────────────────────────╯
╭─ Network ──────────────────────────────────────────╮ ╭─ Processes ─────────────────────────────────────────╮
│ RX  2.2 GiB total   250 B/s                        │ │ 3 running · 13 processes                            │
│ TX  698.2 MiB total   0 B/s                        │ │    PID  COMMAND                     CPU         MEM │
╰─ src: android netstats ────────────────────────────╯ │   5468  proot                     39.8%     4.3 MiB │
                                                       │  26465  opencode                  35.8%   229.8 MiB │
                                                       │   6306  opencode                  17.3%   314.5 MiB │
                                                       │  16595  python                    10.6%    18.8 MiB │
                                                       │  28945  com.termux                 4.0%   120.1 MiB │
                                                       ╰─ src: /proc ────────────────────────────────────────╯
Ctrl+C to quit  ·  refresh 2s  ·  sample #12  ·  watching 24s
```

The footer tracks samples and watch-session time. Network rates appear from the second frame onward.

## How data is collected

sysmon is read-only. It prefers `/proc` and the Python standard library, then falls back to read-only commands only when the primary source is unavailable and the command exists.

| Metric | Primary source | Fallback | If everything fails |
| --- | --- | --- | --- |
| CPU load | `/proc/loadavg` | `os.getloadavg()` | `n/a` + warning |
| CPU usage | cgroup v2 `cpu.stat` (containers) or `/proc/stat` delta | per-process `/proc/[pid]/stat` CPU-time delta, then `/proc/stat` average since boot | `n/a` + warning |
| CPU frequency | `/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq` | none | panel row omitted (no warning) |
| Memory / swap | cgroup v2 `memory.current`/`memory.max` when limited, else `/proc/meminfo` | `free -b` | `n/a` + warning |
| Disk | `shutil.disk_usage` (`statvfs`) | `df -Pk PATH` | skipped path + warning |
| Uptime | `/proc/uptime` (extrapolated if frozen) | `uptime -s` | `n/a` + warning |
| Battery | `termux-battery-status` JSON | none | panel hidden; warning if the command fails |
| Network (watch/JSON) | `/proc/net/dev` | `/sys/class/net`, Android `netstats`, `ip -s -j link` | `n/a` + warning |
| Per-interface network | `/proc/net/dev` | `/sys/class/net`, `ip -s -j link` | device-wide totals only (Android) |
| Process counts (watch/JSON) | `/proc/[pid]/stat` | none | `n/a` |
| Top processes (watch/JSON) | `/proc/[pid]/stat` CPU delta | `ps -eo pid=,pcpu=,rss=,comm=`, then `/proc/[pid]/statm` sorted by RSS | panel unavailable |

External commands:

- Run without a shell, with a 2-second timeout by default (5 seconds for `termux-battery-status`).
- Receive `LC_ALL=C` for stable parsing.
- Are optional: `free`, `df`, `uptime`, `ps`, and `termux-battery-status` (battery panel); `ps` supplies top-process CPU only when `/proc` deltas are unavailable.
- Never block the app from starting when missing.

CPU usage takes a short sample (`0.12s`). A readable cgroup v2 `cpu.stat` is preferred so containers report their own CPU time; otherwise sysmon uses the `/proc/stat` delta. If those counters are frozen, as they can be under PRoot/Android, usage is computed from per-process CPU-time deltas and labelled accordingly. Only if those counters are also unavailable does it show the average since boot. A frozen `/proc/uptime` is advanced with monotonic elapsed time and labelled `(extrapolated)`, so uptime and boot time keep moving. Network totals prefer `/proc/net/dev` and fall back to sysfs, Android's `netstats` binder service, or `ip -s -j link`, so the panel can still work when Android blocks procfs. Process statistics remain independent of network access.

CPU cluster rows come from the kernel's `cpufreq` policies. Each policy becomes one row with its affected CPU range, the current frequency, and the maximum frequency. Devices without `cpufreq` (many containers and virtual machines) simply show no extra rows, without a warning.

Battery data comes from the JSON emitted by `termux-battery-status`. The command is optional and is skipped silently when it is not installed; a command failure or malformed response becomes a warning. Because Termux:API calls can be slow, results are cached for 30 seconds and the command has a 5-second timeout. Use `--no-battery` to skip the query.

## JSON

```json
{
  "timestamp": "2026-10-21T21:28:34+07:00",
  "hostname": "localhost",
  "os": "Ubuntu 26.04.1 LTS",
  "machine": "aarch64",
  "cpu": {
    "load_1m": 0.12,
    "load_5m": 0.07,
    "load_15m": 0.02,
    "usage_percent": 5.6,
    "cores": 8,
    "clusters": [
      {
        "label": "CPU 0-3",
        "current_khz": 1400000,
        "min_khz": 480000,
        "max_khz": 2200000,
        "source": "sysfs cpufreq"
      }
    ],
    "source": "/proc/loadavg + /proc/[pid]/stat"
  },
  "memory": {
    "total_bytes": 11894140928,
    "used_bytes": 6401724416,
    "used_percent": 53.8,
    "source": "/proc/meminfo"
  },
  "disks": [
    {
      "path": "/",
      "total_bytes": 499757580288,
      "used_bytes": 156802469888,
      "used_percent": 31.4,
      "source": "statvfs"
    }
  ],
  "uptime": {
    "seconds": 124.1,
    "boot_time": "2026-10-21T21:26:30+07:00",
    "source": "/proc/uptime"
  },
  "network": {
    "rx_bytes": 5368709120,
    "tx_bytes": 2147483648,
    "rx_bytes_per_sec": null,
    "tx_bytes_per_sec": null,
    "interfaces": 2,
    "interface_details": [
      {
        "name": "wlan0",
        "rx_bytes": 4294967296,
        "tx_bytes": 1073741824,
        "rx_bytes_per_sec": 1400.0,
        "tx_bytes_per_sec": 400.0
      }
    ],
    "source": "/proc/net/dev"
  },
  "processes": {
    "total": 42,
    "running": 2,
    "top": [
      {
        "pid": 1234,
        "command": "python",
        "cpu_percent": 12.5,
        "memory_bytes": 536870912
      }
    ],
    "source": "/proc",
    "sort": "cpu",
    "limit": 5,
    "filter": null
  },
  "battery": {
    "present": true,
    "percentage": 45.0,
    "status": "DISCHARGING",
    "plugged": "UNPLUGGED",
    "temperature_c": 37.5,
    "health": "GOOD",
    "technology": "Li-poly",
    "voltage_mv": 3813,
    "current_ua": 801000,
    "current_average_ua": -3000,
    "charge_counter_uah": 2015000,
    "power_w": 3.1,
    "time_remaining_seconds": 9056,
    "cache_age_seconds": 0.0,
    "source": "termux-battery-status"
  },
  "warnings": []
}
```

Timestamps are local ISO 8601. Sizes are bytes; percentages are rounded to one decimal. The real output includes every field from the models (for example `available_bytes`, `free_bytes`, and swap fields). `--json` collects a detailed single sample, so throughput rates are `null` because there is no previous sample to diff against. `cores` can be fractional when a cgroup CPU quota is active. `battery` is `null` when `termux-battery-status` is unavailable or no battery is present. `power_w` is `voltage × current` and `time_remaining_seconds` is only estimated while discharging.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Lint, type check, and coverage:

```bash
ruff check .
mypy
pytest --cov=sysmon --cov-report=term-missing
```

The suite covers:

- Byte/duration/percent/rate/frequency formatting and sparkline rendering.
- `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `/proc/uptime`, `/proc/net/dev`, `/sys/class/net`, `ip -s -j link`, Android `netstats`, cgroup v2 values, `ps`, `df -Pk`, `free -b`, and `os-release` parsing.
- CPU delta, since-boot, and per-process CPU-time calculations.
- Frozen-uptime extrapolation and cgroup CPU/memory limit handling.
- cpufreq cluster reading, including missing sysfs and missing `scaling_cur_freq`.
- Network rate calculations across samples, per-interface rates, and network source fallbacks.
- Process counts, live per-process CPU ranking, sorting, filtering, full command lines, and the `/proc` memory fallback.
- Battery JSON parsing, power and time estimates, percentage fallback, missing/failed command handling, and cache expiry.
- Config file parsing, validation errors, and CLI/config precedence.
- Command fallbacks with a fake runner.
- Missing `/proc` files and missing utilities, asserting warnings instead of crashes.
- Dashboard rendering at wide and narrow widths, battery/live/trend/alert panels, ASCII bars, and warning escapes.
- CLI one-shot, JSON, JSON Lines, option validation, path expansion, config loading, `--no-battery`, `--no-trends`, and non-TTY watch behavior.

Current result on Ubuntu 26.04 aarch64 / Python 3.14 / Rich 15:

```text
157 passed
```

Coverage is 89% of statements (`pytest --cov=sysmon`).

Interactive watch was also exercised under a pseudo-terminal: it rendered multiple live frames with battery/network/process/trend panels, handled `Ctrl+C`, printed `sysmon stopped.`, and exited with code 0.

Continuous integration runs the same commands (`ruff check .`, `mypy`, `pytest --cov=sysmon`) on Python 3.10, 3.11, 3.12, 3.13, and 3.14 via GitHub Actions (`.github/workflows/ci.yml`).

## Project layout

```text
sysmon/
├── __main__.py      # python -m sysmon
├── cli.py           # argument parsing, config merging, one-shot/watch/JSON modes
├── collectors.py     # /proc parsers, fallbacks, read-only collection
├── config.py         # optional JSON config file parsing and validation
├── dashboard.py      # Rich panels, meters, sparklines, responsive layout
├── formatting.py     # byte/duration/percent/frequency/sparkline helpers
└── models.py         # immutable dataclasses + JSON conversion
tests/
├── test_cli.py
├── test_collectors.py
├── test_config.py
├── test_dashboard.py
└── test_formatting.py
```

### Extending it

The collectors expose pure parsers (`parse_meminfo`, `parse_cpu_stat`, etc.) separately from I/O, so new metrics can be tested without a host.

To add a metric:

1. Add a frozen dataclass and a field on `Snapshot` in `models.py` (plus `to_dict` output if desired).
2. Add a collector method in `collectors.py` that reads a primary source, tries an optional fallback, and appends a human-readable string to `warnings` on failure.
3. Add a Rich panel in `dashboard.py`.
4. Add parser/fallback unit tests and a dashboard rendering assertion.

## Limitations and notes

- **No root**: sysmon only reads files and calls read-only utilities. It does not change kernel settings, files, or services.
- **Container values**: inside PRoot, `/proc` reflects the shared kernel/container view, not necessarily every Android host statistic. cgroup v2 CPU and memory limits are used when readable. Frozen `/proc/stat` counters are handled with per-process CPU-time deltas (then the boot average as a last resort), and a frozen `/proc/uptime` is extrapolated with monotonic time.
- **Restricted storage**: Android scoped storage may block paths such as `/sdcard`. Point `--path` at an accessible directory; inaccessible paths appear as warnings.
- **Restricted networking**: Android and some PRoot setups deny access to `/proc/net/dev` and `/sys/class/net`. sysmon then queries the `netstats` binder service via `service call netstats 13`; if that is blocked too, the Network panel shows unavailable and a warning. Android only exposes device-wide totals, so the per-interface list is empty there.
- **In-memory history only**: the trend strips are kept in RAM for the lifetime of the process. Nothing is written to disk, and one-shot mode has no history.
- **Process scope**: watch mode shows counts and the top processes (five by default), not a full process browser. CPU comes from `/proc` deltas; 100% means one core, so a multi-threaded process can exceed 100%. The `ps` fallback reports lifetime averages, and the final `/proc` fallback ranks by resident memory and leaves CPU as `n/a`. `--filter` only hides rows; the running/total counts still cover every process.
- **Battery scope**: the panel requires `termux-battery-status` from the `termux-api` package and the Termux:API app. It is hidden when the command is absent or the device reports no battery. The command can take a couple of seconds, so watch mode caches the last result for 30 seconds; use `--no-battery` to skip it entirely. Power draw and time remaining are estimates: the API exposes no full-charge counter, so time to full is never shown.
- **Disk space semantics**: usage comes from `statvfs` when possible, so reserved blocks can make `used + free` differ slightly from `total`.
- **Colors**: Rich disables color automatically when output is redirected. Use `--no-color` or `--ascii` on limited terminals.
- **Sampling cost**: one snapshot blocks for about `0.12s` to measure CPU usage. Detailed watch/JSON collection also scans `/proc` for per-process CPU and runs network queries; Android `netstats` can add roughly `0.1-0.3s`. The battery query can add up to its 5-second timeout (typically around 2 seconds), though watch mode refreshes it only every 30 seconds. Watch mode enforces a minimum interval of `0.5s`.

## Troubleshooting

- `ModuleNotFoundError: No module named 'rich'`: install `requirements.txt` with the same Python interpreter used to run sysmon (activate the venv first).
- `ensurepip is not available` in Ubuntu: install `python3-venv` once, then recreate `.venv`.
- `sysmon: error: unknown config key: ...`: the config file contains a key sysmon does not know. Remove it or fix the spelling; the file must be a JSON object.
- `sysmon: error: thresholds.battery.critical must be less than or equal to warning`: battery thresholds are inverted — the warning level must be at or above the critical level.
- CPU usage shows `n/a`: cgroup and `/proc/stat` counters are unreadable, and per-process CPU counters in `/proc/[pid]/stat` cannot be read either. CPU load can still be shown if `/proc/loadavg` or `os.getloadavg()` works.
- No CPU frequency rows: the kernel exposes no `cpufreq` policies (common in containers and VMs). This is not an error and produces no warning.
- Uptime source says `(extrapolated)`: `/proc/uptime` is frozen, which is common under PRoot. sysmon advances uptime from monotonic elapsed time so the panel and boot time stay consistent.
- Network shows unavailable: `/proc/net/dev`, `/sys/class/net`, Android's `netstats` service, and `ip -s -j link` all failed. This can happen in locked-down Termux/proot setups; the rest of the dashboard still works. On Android, check that `/system/bin/service` is visible inside the container.
- Processes show `n/a` for CPU: `/proc` CPU deltas and `ps` both failed, so top processes come from `/proc` memory usage.
- Battery panel is missing: `termux-battery-status` is not installed/visible, or the device reports no battery. In Termux, run `pkg install termux-api` and install the Termux:API app; otherwise this is expected and no warning is shown.
- Battery shows a warning: the command exists but Termux:API failed or returned malformed JSON. The panel stays hidden until the next successful query. Use `--no-battery` to skip the query.
- Disk panel shows a warning: the path is not visible to the current user/container. Try `--path "$HOME"`.
- Watch mode exits immediately: stdout is not a TTY. Run it directly in Termux, not through a pipe or log redirect — or use `--json --watch`, which streams JSON Lines instead.
