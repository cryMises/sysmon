# sysmon

A small, read-only Linux system monitor for **Ubuntu running inside Termux** (including `proot-distro`). It renders CPU load, memory/swap usage, disk usage, and uptime as a [Rich](https://github.com/Textualize/rich) terminal dashboard.

No root permissions, no writes, and no system settings are touched.

## Features

- CPU load averages (1/5/15 min), CPU usage, and core count.
- Container-aware CPU and memory limits when cgroup v2 is readable.
- RAM and swap usage with bars and human-readable sizes.
- Disk usage for one or more paths.
- Uptime and boot time, extrapolated when `/proc/uptime` is frozen.
- One-shot dashboard or live-refreshing watch mode.
- Watch mode adds live-only details:
  - Network RX/TX totals and throughput rates.
  - Live CPU usage even when `/proc/stat` is frozen (via per-process CPU time).
  - Running/total process counts.
  - Top processes by live CPU time, with a `/proc` memory and `ps` fallback.
  - Sample counter, session duration, and refresh status.
- JSON output for scripting, including network and process details.
- Graceful degradation: missing `/proc` entries or external utilities produce a warning panel, not a traceback.
- Responsive layout: side-by-side panels on wide terminals, stacked on narrow Termux screens.
- ASCII bar mode and `--no-color` for limited terminals.

## Requirements

- Python 3.10 or newer.
- [Rich](https://pypi.org/project/rich/) 13.7+ (installed from `requirements.txt`).

## Install

### Termux (native)

```bash
pkg update
pkg install python
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

If installed with `pip install -e .`, replace `python -m sysmon` with `sysmon`.

### Options

| Option | Description |
| --- | --- |
| `-w`, `--watch` | Refresh until `Ctrl+C`, with network, process, and session details. Default is one snapshot. |
| `--once` | Explicitly print one snapshot and exit. |
| `-i`, `--interval SECONDS` | Watch refresh interval, minimum `0.5` (default `2.0`). |
| `-p`, `--path PATH` | Filesystem path to report. Repeat for multiple paths. Default `/`. |
| `--json` | Print raw data as JSON, including network and process details. Cannot be combined with `--watch`. |
| `--ascii` | Use `#`/`-` bars instead of Unicode blocks. |
| `--no-color` | Disable colors. |
| `--version` | Print the version. |

When `--watch` is used without an interactive terminal, sysmon prints one snapshot and exits instead of looping. This keeps logs and pipes predictable.

### Watch mode details

`sysmon -w` refreshes the dashboard in an alternate screen and adds three live-only things:

1. **Network** — RX/TX totals plus bytes-per-second rates. Loopback is excluded when other interfaces are present. The first frame says `rate pending`; later frames use counter deltas. Sources are tried in order: `/proc/net/dev`, `/sys/class/net`, Android's `netstats` binder service (via `service call netstats 13`), then `ip -s -j link`.
2. **Processes** — running/total counts from `/proc`, plus the five busiest processes. CPU percentages are computed from per-process `/proc/[pid]/stat` time deltas. If those counters are unavailable, sysmon falls back to `ps`; if that also fails, it shows the five largest resident-memory processes from `/proc` with CPU as `n/a`.
3. **Session footer** — refresh interval, sample number, and how long the watch session has been running.

The footer looks like:

```text
Ctrl+C to quit  ·  refresh 2s  ·  sample #12  ·  watching 24s
```

On standard Linux, network accounting uses `/proc/net/dev`. Android denies unprivileged apps access to it, so sysmon falls back to the `netstats` binder service and can still show device-wide RX/TX totals and rates. If every source is blocked, sysmon shows `Network data unavailable` and a warning. Process details and session status still work. Process CPU uses `/proc` deltas in watch mode; values from the `ps` fallback are lifetime averages.

## Example output

The layout below is from this workspace at 100 columns. In this PRoot environment `/proc/stat` counters are static, so CPU usage is derived from per-process CPU time and labelled accordingly. `/proc/net/dev` is blocked, so the Network panel uses Android's `netstats` service.

```text
sysmon  system monitor                                                           2026-10-21 21:32:02
localhost · Ubuntu 26.04.1 LTS · aarch64
────────────────────────────────────────────────────────────────────────────────────────────────────
╭─ CPU ─────────────────────────────────────────╮ ╭─ Memory ───────────────────────────────────────╮
│ load 1/5/15 0.12 / 0.07 / 0.02                │ │ RAM   ████████░░░░░░░░ 49.8%                   │
│ usage       █░░░░░░░░░░░░░░░ 5.6%             │ │       5.5 GiB used / 11.1 GiB total            │
│ cores       8                                 │ │ SWAP  ███████████░░░░░ 70.1%                   │
╰─ src: /proc/loadavg + /proc/[pid]/stat ───────╯ │       5.6 GiB used / 8.0 GiB total             │
                                                  ╰─ src: /proc/meminfo ───────────────────────────╯
╭─ Disk ────────────────────────────────────────╮ ╭─ Uptime ───────────────────────────────────────╮
│ /                                             │ │ 2m 4s                                          │
│ █████░░░░░░░░░░░ 31.4%                        │ │ booted 2026-10-21 21:29                        │
│ 146.0 GiB / 465.4 GiB used · 318.9 GiB free   │ ╰─ src: /proc/uptime ────────────────────────────╯
╰─ src: statvfs ────────────────────────────────╯                                                   
Run with --watch for live updates  ·  --json for machine-readable output
```

On a narrow terminal the four panels stack vertically.

In live mode, two more panels are added below them:

```text
╭─ Network ─────────────────────────────────────╮ ╭─ Processes ────────────────────────────────────╮
│ RX  5.0 GiB total   33.2 KiB/s                │ │ 2 running · 42 processes                       │
│ TX  2.0 GiB total   8.3 KiB/s                 │ │    PID  COMMAND                CPU         MEM │
│                                               │ │   1234  python               12.5%   512.0 MiB │
╰─ src: android netstats ───────────────────────╯ │   5678  opencode              6.1%   322.0 MiB │
                                                  │   9012  bash                  0.4%    64.0 MiB │
                                                  │   3456  node                  0.2%   128.0 MiB │
                                                  │   7890  sshd                  0.1%    12.0 MiB │
                                                  ╰─ src: /proc ───────────────────────────────────╯
Ctrl+C to quit  ·  refresh 2s  ·  sample #12  ·  watching 24s
```

The footer tracks samples and watch-session time. Network rates appear from the second frame onward.

## How data is collected

sysmon is read-only. It prefers `/proc` and the Python standard library, then falls back to read-only commands only when the primary source is unavailable and the command exists.

| Metric | Primary source | Fallback | If everything fails |
| --- | --- | --- | --- |
| CPU load | `/proc/loadavg` | `os.getloadavg()` | `n/a` + warning |
| CPU usage | cgroup v2 `cpu.stat` (containers) or `/proc/stat` delta | per-process `/proc/[pid]/stat` CPU-time delta, then `/proc/stat` average since boot | `n/a` + warning |
| Memory / swap | cgroup v2 `memory.current`/`memory.max` when limited, else `/proc/meminfo` | `free -b` | `n/a` + warning |
| Disk | `shutil.disk_usage` (`statvfs`) | `df -Pk PATH` | skipped path + warning |
| Uptime | `/proc/uptime` (extrapolated if frozen) | `uptime -s` | `n/a` + warning |
| Network (watch/JSON) | `/proc/net/dev` | `/sys/class/net`, Android `netstats`, `ip -s -j link` | `n/a` + warning |
| Process counts (watch/JSON) | `/proc/[pid]/stat` | none | `n/a` |
| Top processes (watch/JSON) | `/proc/[pid]/stat` CPU delta | `ps -eo pid=,pcpu=,rss=,comm=`, then `/proc/[pid]/statm` sorted by RSS | panel unavailable |

External commands:

- Run without a shell, with a 2-second timeout.
- Receive `LC_ALL=C` for stable parsing.
- Are optional: `free`, `df`, `uptime`, and `ps` are fallbacks; `ps` supplies top-process CPU only when `/proc` deltas are unavailable.
- Never block the app from starting when missing.

CPU usage takes a short sample (`0.12s`). A readable cgroup v2 `cpu.stat` is preferred so containers report their own CPU time; otherwise sysmon uses the `/proc/stat` delta. If those counters are frozen, as they can be under PRoot/Android, usage is computed from per-process CPU-time deltas and labelled accordingly. Only if those counters are also unavailable does it show the average since boot. A frozen `/proc/uptime` is advanced with monotonic elapsed time and labelled `(extrapolated)`, so uptime and boot time keep moving. Network totals prefer `/proc/net/dev` and fall back to sysfs, Android's `netstats` binder service, or `ip -s -j link`, so the panel can still work when Android blocks procfs. Process statistics remain independent of network access.

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
    "interfaces": 0,
    "source": "android netstats"
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
    "source": "/proc"
  },
  "warnings": []
}
```

Timestamps are local ISO 8601. Sizes are bytes; percentages are rounded to one decimal. The real output includes every field from the models (for example `available_bytes`, `free_bytes`, and swap fields). `--json` collects a detailed single sample, so throughput rates are `null` because there is no previous sample to diff against. `cores` can be fractional when a cgroup CPU quota is active.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The suite covers:

- Byte/duration/percent/rate formatting.
- `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `/proc/uptime`, `/proc/net/dev`, `/sys/class/net`, `ip -s -j link`, Android `netstats`, cgroup v2 values, `ps`, `df -Pk`, `free -b`, and `os-release` parsing.
- CPU delta, since-boot, and per-process CPU-time calculations.
- Frozen-uptime extrapolation and cgroup CPU/memory limit handling.
- Network rate calculations across samples and network source fallbacks.
- Process counts, live per-process CPU ranking, and the `/proc` memory fallback.
- Command fallbacks with a fake runner.
- Missing `/proc` files and missing utilities, asserting warnings instead of crashes.
- Dashboard rendering at wide and narrow widths, live-only panels, ASCII bars, and warning escapes.
- CLI one-shot, JSON, option validation, path expansion, and non-TTY watch behavior.

Current result on Ubuntu 26.04 aarch64 / Python 3.14 / Rich 15:

```text
................................................................................
80 passed
```

Interactive watch was also exercised under a pseudo-terminal: it rendered multiple live frames with network/process/session panels, handled `Ctrl+C`, printed `sysmon stopped.`, and exited with code 0.

## Project layout

```text
sysmon/
├── __main__.py      # python -m sysmon
├── cli.py           # argument parsing, one-shot/watch/JSON modes
├── collectors.py     # /proc parsers, fallbacks, read-only collection
├── dashboard.py      # Rich panels, meters, responsive layout
├── formatting.py     # byte/duration/percent helpers
└── models.py         # immutable dataclasses + JSON conversion
tests/
├── test_cli.py
├── test_collectors.py
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
- **Restricted networking**: Android and some PRoot setups deny access to `/proc/net/dev` and `/sys/class/net`. sysmon then queries the `netstats` binder service via `service call netstats 13`; if that is blocked too, the Network panel shows unavailable and a warning.
- **No history**: there are no charts or retained samples. Each refresh is independent; only network rates and process CPU need the previous sample.
- **Process scope**: watch mode shows counts and the top five processes, not a full process browser. CPU comes from `/proc` deltas; 100% means one core, so a multi-threaded process can exceed 100%. The `ps` fallback reports lifetime averages, and the final `/proc` fallback ranks by resident memory and leaves CPU as `n/a`.
- **Disk space semantics**: usage comes from `statvfs` when possible, so reserved blocks can make `used + free` differ slightly from `total`.
- **Colors**: Rich disables color automatically when output is redirected. Use `--no-color` or `--ascii` on limited terminals.
- **Sampling cost**: one snapshot blocks for about `0.12s` to measure CPU usage. Detailed watch/JSON collection also scans `/proc` for per-process CPU and runs network queries; Android `netstats` can add roughly `0.1-0.3s`, so watch mode enforces a minimum interval of `0.5s`.

## Troubleshooting

- `ModuleNotFoundError: No module named 'rich'`: install `requirements.txt` with the same Python interpreter used to run sysmon (activate the venv first).
- `ensurepip is not available` in Ubuntu: install `python3-venv` once, then recreate `.venv`.
- CPU usage shows `n/a`: cgroup and `/proc/stat` counters are unreadable, and per-process CPU counters in `/proc/[pid]/stat` cannot be read either. CPU load can still be shown if `/proc/loadavg` or `os.getloadavg()` works.
- Uptime source says `(extrapolated)`: `/proc/uptime` is frozen, which is common under PRoot. sysmon advances uptime from monotonic elapsed time so the panel and boot time stay consistent.
- Network shows unavailable: `/proc/net/dev`, `/sys/class/net`, Android's `netstats` service, and `ip -s -j link` all failed. This can happen in locked-down Termux/proot setups; the rest of the dashboard still works. On Android, check that `/system/bin/service` is visible inside the container.
- Processes show `n/a` for CPU: `/proc` CPU deltas and `ps` both failed, so top processes come from `/proc` memory usage.
- Disk panel shows a warning: the path is not visible to the current user/container. Try `--path "$HOME"`.
- Watch mode exits immediately: stdout is not a TTY. Run it directly in Termux, not through a pipe or log redirect.
