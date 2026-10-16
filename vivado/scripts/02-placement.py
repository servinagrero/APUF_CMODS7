#!/usr/bin/env python3

import itertools
import os
import sys
from operator import itemgetter
from pathlib import Path

import polars as pl

CLOCK_TO_SLICE = {
    "X0Y0": "LEFT-LOWER",
    "X0Y1": "LEFT-UPPER",
    "X1Y0": "RIGHT-LOWER",
    "X1Y1": "RIGHT-UPPER",
}
LEFT2_SITES = {
    "LEFT-LOWER-0": ("LEFT-LOWER", 5),
    "LEFT-LOWER-1": ("LEFT-LOWER", 22),
    "LEFT-UPPER-0": ("LEFT-UPPER", 5),
    "LEFT-UPPER-1": ("LEFT-UPPER", 22),
}
DECOR_LEFT2_SITES = {
    # stage index order is unchanged. Reverse traversal also reverses the arbiter
    # end, so stages near index 63 remain closest to the arbiter.
    "LEFT-LOWER-0": {
        "region": "LEFT-LOWER",
        "offset": 5,
        "segment": 0,
        "path_mode": "rl",
        "bel_order": "dcba",
        "reverse_rows": False,
    },
    "LEFT-LOWER-1": {
        "region": "LEFT-LOWER",
        "offset": 22,
        "segment": 0,
        "path_mode": "lr",
        "bel_order": "abcd",
        "reverse_rows": True,
    },
    "LEFT-UPPER-0": {
        "region": "LEFT-UPPER",
        "offset": 5,
        "segment": 0,
        "path_mode": "lr",
        "bel_order": "badc",
        "reverse_rows": True,
    },
    "LEFT-UPPER-1": {
        "region": "LEFT-UPPER",
        "offset": 22,
        "segment": 0,
        "path_mode": "rl",
        "bel_order": "cdab",
        "reverse_rows": False,
    },
}

LUT3_LOCK_PINS = "I0:A6 I1:A5 I2:A1"
LUT2_LOCK_PINS = "I0:A6 I1:A5"

STAGES_LIST = [64]
SITES = list(LEFT2_SITES)
GAPS = [1]
OFFSETS = [0]
BEL_ORDERS = {
    "abcd": ("A6LUT", "B6LUT", "C6LUT", "D6LUT"),
    "badc": ("B6LUT", "A6LUT", "D6LUT", "C6LUT"),
    "cdab": ("C6LUT", "D6LUT", "A6LUT", "B6LUT"),
    "dcba": ("D6LUT", "C6LUT", "B6LUT", "A6LUT"),
}
PATH_MODES = ("rl",)
SITE_PROFILES = ("left2", "decor_left2")


def contiguous_ranges(values):
    for _, group in itertools.groupby(enumerate(values), lambda ix: ix[0] - ix[1]):
        segment = list(map(itemgetter(1), group))
        yield range(segment[0], segment[-1] + 1)


def build_topology(df: pl.DataFrame, gap: int) -> dict:
    regions_map = {}

    for clock_region in df["clock_region"].unique():
        slice_name = CLOCK_TO_SLICE.get(clock_region)
        if not slice_name:
            continue

        region_df = df.filter(pl.col("clock_region") == clock_region)
        unique_x = sorted(region_df["X"].unique().to_list())
        segments = []

        for x_left in unique_x:
            x_right = x_left + gap
            if x_right not in unique_x:
                continue

            ys_left = set(region_df.filter(pl.col("X") == x_left)["Y"].to_list())
            ys_right = set(region_df.filter(pl.col("X") == x_right)["Y"].to_list())
            common_ys = sorted(ys_left.intersection(ys_right))

            for y_range in contiguous_ranges(common_ys):
                if len(y_range) > 32:
                    segments.append(((x_left, x_right), y_range))

        segments.sort(key=lambda s: len(s[1]), reverse=True)
        regions_map[slice_name] = segments

    return regions_map


def require_region(slice_type, regions_dict):
    if slice_type not in regions_dict or not regions_dict[slice_type]:
        raise ValueError(f"Slice region {slice_type} has no valid column pairs.")

    return regions_dict[slice_type][0]


def placement_id(variant, gap, offset):
    return f"{variant}_g{gap}_o{offset}"


def cell_regex(stage_idx, cell_name):
    return f".*puf0/STAGE\\[{stage_idx}\\]\\.{cell_name}$"


def parse_variant(variant):
    site_profile = None
    for profile in sorted(SITE_PROFILES, key=len, reverse=True):
        if variant == profile:
            return None, None, profile
        suffix = f"_{profile}"
        if variant.endswith(suffix):
            site_profile = profile
            variant = variant.removesuffix(suffix)
            break

    if site_profile == "decor_left2":
        return None, None, site_profile

    path_mode, bel_order_name = variant.rsplit("_", 1)
    return path_mode, bel_order_name, site_profile


def stage_cell(stage_idx, cell_name):
    return f"[get_cells -hierarchical -regexp {{{cell_regex(stage_idx, cell_name)}}}]"


def puf_cell(cell_name):
    return f"[get_cells -hierarchical -regexp {{.*puf0/{cell_name}$}}]"


def stage_columns(path_mode, stage_idx, x_left, x_right):
    if path_mode == "lr":
        return x_left, x_right
    if path_mode == "rl":
        return x_right, x_left
    if path_mode == "alt_stage":
        return (x_right, x_left) if stage_idx % 2 else (x_left, x_right)
    if path_mode == "alt_row":
        return (x_right, x_left) if (stage_idx // 4) % 2 else (x_left, x_right)

    raise ValueError(f"Unknown path mode: {path_mode}")


def add_lut3_stage_constraints(constraints, x_upper, x_lower, y_val, stage_idx, lut_bel):
    upper_cell = stage_cell(stage_idx, "upper_mux")
    lower_cell = stage_cell(stage_idx, "lower_mux")

    constraints.extend(
        [
            f"set_property BEL {lut_bel} {upper_cell}",
            f"set_property LOC SLICE_X{x_upper}Y{y_val} {upper_cell}",
            f"set_property LOCK_PINS {{{LUT3_LOCK_PINS}}} {upper_cell}",
            f"set_property BEL {lut_bel} {lower_cell}",
            f"set_property LOC SLICE_X{x_lower}Y{y_val} {lower_cell}",
            f"set_property LOCK_PINS {{{LUT3_LOCK_PINS}}} {lower_cell}",
        ]
    )


def add_arbiter_constraints(constraints, x_left, x_right, y_val):
    upper_cell = puf_cell("nand_upper")
    lower_cell = puf_cell("nand_lower")

    constraints.extend(
        [
            f"set_property BEL A6LUT {upper_cell}",
            f"set_property LOC SLICE_X{x_left}Y{y_val} {upper_cell}",
            f"set_property LOCK_PINS {{{LUT2_LOCK_PINS}}} {upper_cell}",
            f"set_property BEL A6LUT {lower_cell}",
            f"set_property LOC SLICE_X{x_right}Y{y_val} {lower_cell}",
            f"set_property LOCK_PINS {{{LUT2_LOCK_PINS}}} {lower_cell}",
        ]
    )


def add_pblock_constraints(constraints, site_name, x_left, x_right, y_values):
    pblock_name = f"pblock_puf_{site_name.lower().replace('-', '_')}"
    x_min, x_max = sorted((x_left, x_right))
    y_min, y_max = min(y_values), max(y_values)

    constraints.extend(
        [
            "",
            "# Coarse Pblock keeps the PUF hierarchy inside the selected fabric window.",
            f"create_pblock {pblock_name}",
            (
                f"add_cells_to_pblock [get_pblocks {pblock_name}] "
                "[get_cells -hierarchical -regexp {.*puf0(/.*)?$}]"
            ),
            (
                f"resize_pblock [get_pblocks {pblock_name}] "
                f"-add {{SLICE_X{x_min}Y{y_min}:SLICE_X{x_max}Y{y_max}}}"
            ),
        ]
    )


def site_recipe(site_name, site_profile, offset):
    if site_profile == "decor_left2":
        if site_name not in DECOR_LEFT2_SITES:
            raise ValueError(f"Site {site_name} is not defined by the {site_profile} profile.")
        recipe = dict(DECOR_LEFT2_SITES[site_name])
        recipe["offset"] += offset
        return recipe

    if site_profile == "left2":
        if site_name not in LEFT2_SITES:
            raise ValueError(f"Site {site_name} is not defined by the {site_profile} profile.")
        region_name, site_offset = LEFT2_SITES[site_name]
        return {
            "region": region_name,
            "offset": site_offset + offset,
            "segment": 0,
            "path_mode": None,
            "bel_order": None,
            "reverse_rows": False,
        }

    return {
        "region": site_name,
        "offset": offset,
        "segment": 0,
        "path_mode": None,
        "bel_order": None,
        "reverse_rows": False,
    }


def generate_constraints(stages, site_name, regions_dict, variant, gap, offset):
    path_mode, bel_order_name, site_profile = parse_variant(variant)
    recipe = site_recipe(site_name, site_profile, offset)
    region_name = recipe["region"]
    effective_offset = recipe["offset"]
    segment_index = recipe["segment"]
    path_mode = recipe["path_mode"] or path_mode
    bel_order_name = recipe["bel_order"] or bel_order_name
    bel_order = BEL_ORDERS[bel_order_name]
    if region_name not in regions_dict or segment_index >= len(regions_dict[region_name]):
        raise ValueError(
            f"Slice region {region_name} has no column pair at segment index {segment_index}."
        )
    (x_left, x_right), y_range = regions_dict[region_name][segment_index]
    y_values = list(y_range)
    required_rows = (stages + 3) // 4 + 1
    if effective_offset + required_rows > len(y_values):
        raise ValueError(
            f"Cannot fit {stages} LUT3-pair stages at site {site_name}. "
            f"Needs rows [{effective_offset}, {effective_offset + required_rows}), "
            f"but only {len(y_values)} rows are available."
        )
    y_values = y_values[effective_offset : effective_offset + required_rows]
    if recipe["reverse_rows"]:
        y_values = list(reversed(y_values))

    constraints = [
        f"# Fixed two-LUT3 APUF stage placement: {placement_id(variant, gap, offset)}",
        (
            f"# Logical site: {site_name}; physical region: {region_name}; "
            f"segment={segment_index}; effective offset={effective_offset}."
        ),
        (
            f"# Base columns: SLICE_X{x_left} and SLICE_X{x_right}; gap={gap}; "
            f"path={path_mode}; bel_order={bel_order_name}; reverse_rows={recipe['reverse_rows']}."
        ),
        "# The logical challenge stream is identical for all variants.",
        "# Each stage is upper_mux/lower_mux under puf0/STAGE[index].",
    ]

    for i in range(stages):
        y_val = y_values[i // 4]
        x_upper, x_lower = stage_columns(path_mode, i, x_left, x_right)
        add_lut3_stage_constraints(constraints, x_upper, x_lower, y_val, i, bel_order[i % 4])

    add_arbiter_constraints(constraints, x_left, x_right, y_values[(stages + 3) // 4])
    add_pblock_constraints(constraints, site_name, x_left, x_right, y_values)
    return "\n".join(constraints)


csv_path = Path("./valid_A6LUTs_by_clock_region.csv")
if not csv_path.exists():
    print("Error: Run 'vivado -mode batch -source scripts/01-extract_luts.tcl' first")
    sys.exit(1)

df = pl.read_csv(csv_path)

INVALID_X = [0, 16, 32]
INVALID_Y = [0, 96, 97, 98, 99]
df_filtered = df.filter(~pl.col("X").is_in(INVALID_X), ~pl.col("Y").is_in(INVALID_Y))

os.makedirs("constraints", exist_ok=True)

variants = [
    f"{path_mode}_{bel_order_name}_{site_profile}"
    for path_mode in PATH_MODES
    for bel_order_name in ("dcba",)
    for site_profile in SITE_PROFILES
    if site_profile != "decor_left2"
]
variants.append("decor_left2")

for gap in GAPS:
    try:
        REGIONS = build_topology(df_filtered, gap)
    except Exception as e:
        print(f"Failed to extract fabric layout for gap={gap}: {e}")
        continue

    for offset in OFFSETS:
        for variant_name in variants:
            for s in STAGES_LIST:
                for loc in SITES:
                    place_id = placement_id(variant_name, gap, offset)
                    try:
                        content = generate_constraints(
                            s, loc, REGIONS, variant_name, gap, offset
                        )
                        filename = f"constraints/placement_{loc}_{s}_{place_id}.xdc"
                        with open(filename, "w") as f:
                            f.write(content + "\n")
                        print(f"Generated {loc}-{s}-{place_id}")
                    except ValueError as e:
                        print(f"Skipping {loc}-{s}-{place_id}: {e}")
