# FPGA workflow

## Requirements

- Linux with access to `/dev/serial/by-id`
- Xilinx Vivado 2019.2
- `openFPGALoader`
- Python 3.11 or newer and `uv`
- One or more Cmod S7 boards

The Vivado and `openFPGALoader` paths are currently defined in
`vivado/scripts/03-generate_bitstreams.sh` and `apuf/fpga_device.py`.

## Build

Run these commands from `vivado/`:

```bash
vivado -mode batch -source scripts/01-extract_luts.tcl
uv run python scripts/02-placement.py
PLACEMENTS="decor_left2:1:0" bash scripts/03-generate_bitstreams.sh
```

The first command inventories usable LUT sites. The placement generator creates
XDC files under `vivado/constraints/`. Vivado writes each bitstream and routed
checkpoint under `build/decor_left2_g1_o0/<logical-site>_64/`, together with
`puf_routes.csv` for artifact inspection.

## Challenges and acquisition

Challenges are two-dimensional NumPy arrays containing binary `uint8` values.
The example configuration expects `data/challenges/all_challenges.npy`.
The challenge file is generated once and its MD5 checksum identifies it in the
database. `samples` controls how many times the complete file is replayed.

```bash
cp config.example.toml config.toml
uv run apuf-run --config config.toml --max_nodes 4 study all_readouts
```

Boards are discovered from their persistent USB serial paths. Each challenge is
packed little-endian and sent over the 1 Mbaud UART. The FPGA returns one byte;
bit zero contains the response. Data is stored in one SQLite database per
device, so acquisition can be repeated with different connected batches.

After all batches have been collected, merge and export explicitly:

```bash
uv run python scripts/merge_dbs.py --db-dir data/all
uv run python scripts/export_csvs.py data/all/all_merged.db
```

Both commands protect existing output unless `--force` is supplied.
