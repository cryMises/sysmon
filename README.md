# sysmon

A small, read-only Linux system monitor for **Ubuntu running inside Termux** (including `proot-distro`). It renders CPU load, memory/swap usage, disk usage, and uptime as a [Rich](https://github.com/Textualize/rich) terminal dashboard.

No root permissions, no writes, and no system settings are touched.

## Features

- CPU load averages (1/5/15 min), CPU usage, and core count.
- RAM and swap usage with bars and human-readable sizes.
- Disk usage for one or more paths.
- Uptime and boot time.
- One-shot dashboard or live-refreshing watch mode.
- JSON output for scripting.
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
| `-w`, `--watch` | Refresh until `Ctrl+C`. Default is one snapshot. |
| `--once` | Explicitly print one snapshot and exit. |
| `-i`, `--interval SECONDS` | Watch refresh interval, minimum `0.5` (default `2.0`). |
| `-p`, `--path PATH` | Filesystem path to report. Repeat for multiple paths. Default `/`. |
| `--json` | Print raw data as JSON. Cannot be combined with `--watch`. |
| `--ascii` | Use `#`/`-` bars instead of Unicode blocks. |
| `--no-color` | Disable colors. |
| `--version` | Print the version. |

When `--watch` is used without an interactive terminal, sysmon prints one snapshot and exits instead of looping. This keeps logs and pipes predictable.

## Example output

The layout below is from this workspace at 100 columns. In this PRoot environment `/proc/stat` counters are static, so CPU usage falls back to the average since boot and is labelled `boot avg`.

```text
sysmon  system monitor                                                           2026-10-21 21:32:02
localhost · Ubuntu 26.04.1 LTS · aarch64
────────────────────────────────────────────────────────────────────────────────────────────────────
╭─ CPU ─────────────────────────────────────────╮ ╭─ Memory ───────────────────────────────────────╮
│ load 1/5/15 0.12 / 0.07 / 0.02                │ │ RAM   ████████░░░░░░░░ 49.8%                   │
│ usage       █░░░░░░░░░░░░░░░ 5.6%             │ │       5.5 GiB used / 11.1 GiB total            │
│ cores       8                                 │ │ SWAP  ███████████░░░░░ 70.1%                   │
╰─ src: /proc/loadavg + /proc/stat (boot avg) ──╯ │       5.6 GiB used / 8.0 GiB total             │
                                                  ╰─ src: /proc/meminfo ───────────────────────────╯
╭─ Disk ────────────────────────────────────────╮ ╭─ Uptime ───────────────────────────────────────╮
│ /                                             │ │ 2m 4s                                          │
│ █████░░░░░░░░░░░ 31.4%                        │ │ booted 2026-10-21 21:29                        │
│ 146.0 GiB / 465.4 GiB used · 318.9 GiB free   │ ╰─ src: /proc/uptime ────────────────────────────╯
╰─ src: statvfs ────────────────────────────────╯                                                   
Run with --watch for live updates  ·  --json for machine-readable output
```

On a narrow terminal the four panels stack vertically.

## How data is collected

sysmon is read-only. It prefers `/proc` and the Python standard library, then falls back to read-only commands only when the primary source is unavailable and the command exists.

| Metric | Primary source | Fallback | If everything fails |
| --- | --- | --- | --- |
| CPU load | `/proc/loadavg` | `os.getloadavg()` | `n/a` + warning |
| CPU usage | `/proc/stat` delta | `/proc/stat` average since boot when counters do not advance | `n/a` + warning |
| Memory / swap | `/proc/meminfo` | `free -b` | `n/a` + warning |
| Disk | `shutil.disk_usage` (`statvfs`) | `df -Pk PATH` | skipped path + warning |
| Uptime | `/proc/uptime` | `uptime -s` | `n/a` + warning |

External commands:

- Run without a shell, with a 2-second timeout.
- Receive `LC_ALL=C` for stable parsing.
- Are never required for the app to start.
- Are only used when the primary source fails.

CPU usage takes a short sample (`0.12s`). If `/proc/stat` is frozen, as it can be under PRoot/Android, sysmon shows the average since boot with an explicit source label rather than inventing an instantaneous value.

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
    "source": "/proc/loadavg + /proc/stat (boot avg)"
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
  "warnings": []
}
```

Timestamps are local ISO 8601. Sizes are bytes; percentages are rounded to one decimal. The real output includes every field from the models (for example `available_bytes`, `free_bytes`, and swap fields).

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The suite covers:

- Byte/duration/percent formatting.
- `/proc/loadavg`, `/proc/meminfo`, `/proc/stat`, `/proc/uptime`, `df -Pk`, `free -b`, and `os-release` parsing.
- CPU delta and since-boot calculations.
- Command fallbacks with a fake runner.
- Missing `/proc` files and missing utilities, asserting warnings instead of crashes.
- Dashboard rendering at wide and narrow widths, ASCII bars, and warning escapes.
- CLI one-shot, JSON, option validation, path expansion, and non-TTY watch behavior.

Current result on Ubuntu 26.04 aarch64 / Python 3.14 / Rich 15:

```text
.............................................
45 passed
```

Interactive watch was also exercised under a pseudo-terminal: it rendered multiple live frames, handled `Ctrl+C`, printed `sysmon stopped.`, and exited with code 0.

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
- **Container values**: inside PRoot, `/proc` reflects the shared kernel/container view, not necessarily every Android host statistic. Frozen `/proc/stat` counters are handled with the boot-average fallback.
- **Restricted storage**: Android scoped storage may block paths such as `/sdcard`. Point `--path` at an accessible directory; inaccessible paths appear as warnings.
- **No history**: there are no charts or retained samples. Each refresh is independent.
- **No process list**: sysmon intentionally focuses on host-level CPU, memory, disk, and uptime.
- **Disk space semantics**: usage comes from `statvfs` when possible, so reserved blocks can make `used + free` differ slightly from `total`.
- **Colors**: Rich disables color automatically when output is redirected. Use `--no-color` or `--ascii` on limited terminals.
- **Sampling cost**: one snapshot blocks for about `0.12s` to measure CPU usage. Watch mode enforces a minimum interval of `0.5s`.

## Troubleshooting

- `ModuleNotFoundError: No module named 'rich'`: install `requirements.txt` with the same Python interpreter used to run sysmon (activate the venv first).
- `ensurepip is not available` in Ubuntu: install `python3-venv` once, then recreate `.venv`.
- CPU usage shows `n/a`: `/proc/stat` is unreadable. CPU load can still be shown if `/proc/loadavg` or `os.getloadavg()` works.
- Disk panel shows a warning: the path is not visible to the current user/container. Try `--path "$HOME"`.
- Watch mode exits immediately: stdout is not a TTY. Run it directly in Termux, not through a pipe or log redirect.
