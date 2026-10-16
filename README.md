# Arbiter PUF on CMODS7

## Workflow

```bash
$ git clone https://codeberg.org/servinagrero/APUF_CMODS7.git
$ cd APUF_CMODS7
$ uv sync --dev
$ cp config.example.toml config.toml
```

First, the script `scripts/01-extract_luts.tcl` will use vivado to obtain a list of valid LUTS that can be used to map the Arbiter PUF. The results will be written to `valid_A6LUTs_by_clock_region.csv` at the project's root, with the fields `clock_region,X,Y`

```bash 
$ cd vivado
$ vivado -mode batch -source scripts/01-extract_luts.tcl
```

Then the following scripts will generate the placement and routing constraints and generate all bitstreams respectively.

```bash
$ python3 scripts/02-placement.py
$ bash scripts/03-generate_bitstreams.sh
```

While some studies can make use of the seeded PRNG to create reproducibles challenges, it's possible to create a numpy array with bespoke challenges for some studies. The following script can be modified to create the challenges and store the `.npy` files in the data directory.

```bash
$ python3 scripts/04-generate_challenges.py
```

Copy `config.example.toml` to `config.toml` and adapt the local device,
output, and challenge-file settings as needed. The example configures the
published 64-stage `decor_left2_g1_o0` implementation at its four logical
locations.

Run acquisition independently for each connected batch of devices:

```bash
$ uv run apuf-run --config config.toml --max_nodes 7 study all_readouts
```

When all device acquisitions are available, merge and export them explicitly:

```bash
$ uv run python scripts/merge_dbs.py --db-dir data/all

$ uv run python scripts/export_csvs.py data/all/all_merged.db
```

Both utilities refuse to overwrite existing output unless `--force` is passed.
