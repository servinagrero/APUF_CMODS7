import argparse
import itertools
from pathlib import Path

import numpy as np
import polars as pl
from pypuf.simulation import ArbiterPUF
from scipy.spatial.distance import pdist
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.model_selection import train_test_split


DEFAULT_BUDGETS = [100, 300, 1_000, 3_000, 10_000, 30_000, 100_000]
DEFAULT_TEST_SIZE = 5_000
DEFAULT_N_TRIALS = 5
METRIC_REPORT_COLUMNS = [
    "placement_variant",
    "placement_gap",
    "placement_offset",
    "slice",
    "device_id",
    "xor_k",
    "combination",
    "n_combinations",
    "stages",
    "n_challenges",
    "uniformity_mean",
    "uniformity_std",
    "uniformity_min",
    "uniformity_max",
    "bias_mean",
    "bias_abs_mean",
    "uniqueness_mean",
    "uniqueness_std",
    "uniqueness_min",
    "uniqueness_max",
    "jaccard_mean",
    "corr_mean",
    "corr_abs_mean",
    "corr_max_abs",
]
LOGREG_REPORT_COLUMNS = [
    "placement_variant",
    "placement_gap",
    "placement_offset",
    "device_id",
    "slice",
    "stages",
    "budget",
    "balanced_accuracy_mean",
    "balanced_accuracy_std",
    "accuracy_mean",
    "accuracy_std",
    "target_mean_test",
    "trials",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Smoke-test APUF CRP quality and learnability."
    )
    parser.add_argument(
        "--crps",
        type=Path,
        default=Path("data/all/crps_summary.csv"),
        help="CSV with one response value per challenge/device/slice/stages.",
    )
    parser.add_argument(
        "--challenges-file",
        type=Path,
        default=Path("data/challenges/all_challenges.npy"),
        help="Numpy challenge file used to collect the CRPs.",
    )
    parser.add_argument(
        "--device",
        help="Device to attack. Defaults to the first device in the CSV.",
    )
    parser.add_argument(
        "--placement-variant",
        help="Optional placement variant to analyze, e.g. lr_abcd or alt_row_dcba.",
    )
    parser.add_argument(
        "--placement-gap",
        type=int,
        help="Optional placement column gap to analyze.",
    )
    parser.add_argument(
        "--placement-offset",
        type=int,
        help="Optional placement row offset to analyze.",
    )
    parser.add_argument(
        "--budgets",
        type=int,
        nargs="+",
        default=DEFAULT_BUDGETS,
        help="Training budgets for logistic regression.",
    )
    parser.add_argument(
        "--test-size",
        type=int,
        default=DEFAULT_TEST_SIZE,
        help="Held-out test challenges per trial.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_N_TRIALS,
        help="Number of random train/test splits per budget.",
    )
    parser.add_argument(
        "--max-challenges",
        type=int,
        help="Optional cap on challenge_id for faster local smoke tests.",
    )
    parser.add_argument(
        "--take-lsb",
        action="store_true",
        help="Use the leftmost challenge columns as stage bits instead of the rightmost columns.",
    )
    parser.add_argument(
        "--xor-ks",
        type=int,
        nargs="+",
        default=[1, 2, 3, 4],
        help="k values for synthetic k-XOR metrics across slice combinations.",
    )
    return parser.parse_args()


def shannon_entropy(p):
    p = np.asarray(p, dtype=float)
    if p.size == 0:
        return p
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -((p * np.log2(p)) + ((1 - p) * np.log2(1 - p)))


def compute_metrics(crps):
    crps = np.asarray(crps, dtype=float)
    uniformity = np.mean(crps, axis=1)
    bitaliasing = np.mean(crps, axis=0)
    uniqueness = pdist(crps, "hamming") if len(crps) > 1 else np.array([])
    jaccard = pdist(crps, "jaccard") if len(crps) > 1 else np.array([])
    metrics = {
        "uniformity": uniformity,
        "upd": shannon_entropy(uniformity),
        "bitaliasing": bitaliasing,
        "upc": shannon_entropy(bitaliasing),
        "uniqueness": uniqueness,
        "uniq_h": shannon_entropy(uniqueness),
        "jaccard": jaccard,
    }
    return metrics


def summarize_metric(prefix, values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return {
            f"{prefix}_mean": None,
            f"{prefix}_std": None,
            f"{prefix}_min": None,
            f"{prefix}_max": None,
        }

    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_max": float(np.max(values)),
    }


def metrics_row(group_keys, crps, row_count, challenge_count):
    metrics = compute_metrics(crps)
    row = {
        **group_keys,
        "rows": row_count,
        "n_vectors": int(crps.shape[0]),
        "n_challenges": int(challenge_count),
    }

    for metric_name, values in metrics.items():
        row.update(summarize_metric(metric_name, values))

    return row


def add_bias_columns(df):
    if df.is_empty() or "uniformity_mean" not in df.columns:
        return df

    return df.with_columns(
        (pl.col("uniformity_mean") - 0.5).alias("bias_mean"),
        (pl.col("uniformity_mean") - 0.5).abs().alias("bias_abs_mean"),
    )


def response_matrix(df, row_col):
    arrays = []
    expected_ids = None
    for part in df.partition_by(row_col, maintain_order=True):
        part = part.sort("challenge_id")
        challenge_ids = part["challenge_id"].to_numpy()
        if expected_ids is None:
            expected_ids = challenge_ids
        elif not np.array_equal(challenge_ids, expected_ids):
            raise ValueError(
                f"Incomplete response matrix for {row_col}; not every vector has every challenge."
            )

        arrays.append(part["response"].to_numpy())

    if not arrays:
        raise ValueError(f"No response vectors found while grouping by {row_col}.")

    return np.vstack(arrays)


def labeled_response_matrix(df, row_col):
    labels = []
    arrays = []
    expected_ids = None
    for part in df.partition_by(row_col, maintain_order=True):
        part = part.sort("challenge_id")
        challenge_ids = part["challenge_id"].to_numpy()
        if expected_ids is None:
            expected_ids = challenge_ids
        elif not np.array_equal(challenge_ids, expected_ids):
            raise ValueError(
                f"Incomplete response matrix for {row_col}; not every vector has every challenge."
            )

        labels.append(part[row_col][0])
        arrays.append(part["response"].to_numpy().astype(np.int8))

    if not arrays:
        raise ValueError(f"No response vectors found while grouping by {row_col}.")

    return labels, np.vstack(arrays), expected_ids


def load_crps(
    path,
    max_challenges=None,
    placement_variant=None,
    placement_gap=None,
    placement_offset=None,
):
    if not path.exists():
        raise FileNotFoundError(f"CRP CSV not found: {path}")

    df = pl.read_csv(path)
    required = {"challenge_id", "device_id", "slice", "stages"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CRP CSV is missing required columns: {sorted(missing)}")

    response_col = "response" if "response" in df.columns else "mean_response"
    if response_col not in df.columns:
        raise ValueError("CRP CSV must contain either response or mean_response.")

    df = df.rename({response_col: "response"})
    if "placement_variant" not in df.columns:
        df = df.with_columns(pl.lit("unknown").alias("placement_variant"))
    if "placement_gap" not in df.columns:
        df = df.with_columns(pl.lit(1).alias("placement_gap"))
    if "placement_offset" not in df.columns:
        df = df.with_columns(pl.lit(0).alias("placement_offset"))

    df = df.with_columns(
        [
            pl.col("challenge_id").cast(pl.Int64),
            pl.col("stages").cast(pl.Int64),
            pl.col("placement_gap").cast(pl.Int64),
            pl.col("placement_offset").cast(pl.Int64),
            (pl.col("response").cast(pl.Float64) >= 0.5)
            .cast(pl.Int8)
            .alias("response"),
        ]
    )

    if max_challenges is not None:
        df = df.filter(pl.col("challenge_id") < max_challenges)

    if placement_variant is not None:
        df = df.filter(pl.col("placement_variant") == placement_variant)
    if placement_gap is not None:
        df = df.filter(pl.col("placement_gap") == placement_gap)
    if placement_offset is not None:
        df = df.filter(pl.col("placement_offset") == placement_offset)

    return df


def analyze_multiple_devices(df):
    rows = []
    for key, df_group in df.group_by(
        ["placement_variant", "placement_gap", "placement_offset", "slice", "stages"],
        maintain_order=True,
    ):
        placement_variant, placement_gap, placement_offset, slice_loc, stages = key
        crps = response_matrix(df_group, "device_id")
        rows.append(
            metrics_row(
                {
                    "placement_variant": placement_variant,
                    "placement_gap": int(placement_gap),
                    "placement_offset": int(placement_offset),
                    "slice": slice_loc,
                    "stages": int(stages),
                },
                crps,
                df_group.height,
                df_group["challenge_id"].n_unique(),
            )
        )

    return pl.DataFrame(rows).sort(
        ["placement_variant", "placement_gap", "placement_offset", "stages", "slice"]
    )


def analyze_one_device_across_slices(df, device):
    df_device = df.filter(pl.col("device_id") == device)
    if df_device.is_empty():
        raise ValueError(f"Device not found in CRP CSV: {device}")

    rows = []
    for key, df_group in df_device.group_by(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "device_id",
            "stages",
        ],
        maintain_order=True,
    ):
        placement_variant, placement_gap, placement_offset, device_id, stages = key
        crps = response_matrix(df_group, "slice")
        rows.append(
            metrics_row(
                {
                    "placement_variant": placement_variant,
                    "placement_gap": int(placement_gap),
                    "placement_offset": int(placement_offset),
                    "device_id": device_id,
                    "stages": int(stages),
                },
                crps,
                df_group.height,
                df_group["challenge_id"].n_unique(),
            )
        )

    return pl.DataFrame(rows).sort(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "stages",
            "device_id",
        ]
    )


def summarize_correlations(matrix):
    if matrix.shape[0] < 2:
        return {
            "corr_mean": None,
            "corr_std": None,
            "corr_min": None,
            "corr_max": None,
            "corr_abs_mean": None,
            "corr_max_abs": None,
        }

    matrix = matrix.astype(float)
    non_constant = np.std(matrix, axis=1) > 0
    matrix = matrix[non_constant]
    if matrix.shape[0] < 2:
        return {
            "corr_mean": None,
            "corr_std": None,
            "corr_min": None,
            "corr_max": None,
            "corr_abs_mean": None,
            "corr_max_abs": None,
        }

    corr = np.corrcoef(matrix)
    upper = corr[np.triu_indices_from(corr, k=1)]
    upper = upper[~np.isnan(upper)]
    if upper.size == 0:
        return {
            "corr_mean": None,
            "corr_std": None,
            "corr_min": None,
            "corr_max": None,
            "corr_abs_mean": None,
            "corr_max_abs": None,
        }

    return {
        "corr_mean": float(np.mean(upper)),
        "corr_std": float(np.std(upper)),
        "corr_min": float(np.min(upper)),
        "corr_max": float(np.max(upper)),
        "corr_abs_mean": float(np.mean(np.abs(upper))),
        "corr_max_abs": float(np.max(np.abs(upper))),
    }


def xor_response_matrix(slice_labels, slice_responses, xor_k):
    combo_labels = []
    xor_vectors = []
    for combo in itertools.combinations(range(len(slice_labels)), xor_k):
        combo_labels.append("^".join(slice_labels[idx] for idx in combo))
        xor_vectors.append(np.bitwise_xor.reduce(slice_responses[list(combo)], axis=0))

    if not xor_vectors:
        return combo_labels, np.empty((0, slice_responses.shape[1]), dtype=np.int8)

    return combo_labels, np.vstack(xor_vectors).astype(np.int8)


def grouped_slice_responses(df_group):
    slice_labels, slice_responses, challenge_ids = labeled_response_matrix(
        df_group, "slice"
    )
    order = np.argsort(np.asarray(slice_labels))
    slice_labels = [slice_labels[idx] for idx in order]
    slice_responses = slice_responses[order]
    return slice_labels, slice_responses, challenge_ids


def analyze_xor_combinations(df, device, xor_ks):
    df_device = df.filter(pl.col("device_id") == device)
    if df_device.is_empty():
        raise ValueError(f"Device not found in CRP CSV: {device}")

    rows = []
    for key, df_group in df_device.group_by(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "device_id",
            "stages",
        ],
        maintain_order=True,
    ):
        placement_variant, placement_gap, placement_offset, device_id, stages = key
        slice_labels, slice_responses, _ = grouped_slice_responses(df_group)
        n_slices = len(slice_labels)

        for xor_k in xor_ks:
            if xor_k < 1:
                raise ValueError(f"XOR k must be positive, got {xor_k}.")
            if xor_k > n_slices:
                continue

            combo_labels, xor_matrix = xor_response_matrix(
                slice_labels, slice_responses, xor_k
            )
            correlations = summarize_correlations(xor_matrix)

            for combo_label, xor_vector in zip(combo_labels, xor_matrix):
                row = metrics_row(
                    {
                        "placement_variant": placement_variant,
                        "placement_gap": int(placement_gap),
                        "placement_offset": int(placement_offset),
                        "device_id": device_id,
                        "stages": int(stages),
                        "xor_k": int(xor_k),
                        "combination": combo_label,
                    },
                    xor_vector.reshape(1, -1),
                    int(xor_vector.size),
                    int(xor_vector.size),
                )
                row.update(correlations)
                rows.append(row)

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "stages",
            "xor_k",
            "combination",
        ]
    )


def analyze_xor_inter_device(df, xor_ks):
    rows = []
    group_cols = ["placement_variant", "placement_gap", "placement_offset", "stages"]

    for key, df_group in df.group_by(group_cols, maintain_order=True):
        placement_variant, placement_gap, placement_offset, stages = key
        combo_vectors = {}
        combo_challenges = {}

        for device_group in df_group.partition_by("device_id", maintain_order=True):
            device_id = device_group["device_id"][0]
            slice_labels, slice_responses, challenge_ids = grouped_slice_responses(
                device_group
            )
            n_slices = len(slice_labels)

            for xor_k in xor_ks:
                if xor_k < 1:
                    raise ValueError(f"XOR k must be positive, got {xor_k}.")
                if xor_k > n_slices:
                    continue

                combo_labels, xor_matrix = xor_response_matrix(
                    slice_labels, slice_responses, xor_k
                )
                for combo_label, xor_vector in zip(combo_labels, xor_matrix):
                    combo_key = (int(xor_k), combo_label)
                    combo_vectors.setdefault(combo_key, []).append(
                        (device_id, xor_vector)
                    )
                    combo_challenges.setdefault(combo_key, challenge_ids)

        for (xor_k, combo_label), vectors in combo_vectors.items():
            if len(vectors) < 2:
                continue
            labels, arrays = zip(*sorted(vectors, key=lambda item: item[0]))
            crps = np.vstack(arrays).astype(np.int8)
            challenge_ids = combo_challenges[(xor_k, combo_label)]
            rows.append(
                metrics_row(
                    {
                        "placement_variant": placement_variant,
                        "placement_gap": int(placement_gap),
                        "placement_offset": int(placement_offset),
                        "stages": int(stages),
                        "xor_k": int(xor_k),
                        "combination": combo_label,
                    },
                    crps,
                    int(crps.size),
                    int(len(challenge_ids)),
                )
            )

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "stages",
            "xor_k",
            "combination",
        ]
    )


def analyze_xor_intra_device(df, xor_ks):
    rows = []
    group_cols = [
        "placement_variant",
        "placement_gap",
        "placement_offset",
        "device_id",
        "stages",
    ]

    for key, df_group in df.group_by(group_cols, maintain_order=True):
        placement_variant, placement_gap, placement_offset, device_id, stages = key
        slice_labels, slice_responses, challenge_ids = grouped_slice_responses(df_group)
        n_slices = len(slice_labels)

        for xor_k in xor_ks:
            if xor_k < 1:
                raise ValueError(f"XOR k must be positive, got {xor_k}.")
            if xor_k > n_slices:
                continue

            combo_labels, xor_matrix = xor_response_matrix(
                slice_labels, slice_responses, xor_k
            )
            correlations = summarize_correlations(xor_matrix)
            row = metrics_row(
                {
                    "placement_variant": placement_variant,
                    "placement_gap": int(placement_gap),
                    "placement_offset": int(placement_offset),
                    "device_id": device_id,
                    "stages": int(stages),
                    "xor_k": int(xor_k),
                    "combination": "all_combinations",
                },
                xor_matrix,
                int(xor_matrix.size),
                int(len(challenge_ids)),
            )
            row["n_combinations"] = int(len(combo_labels))
            row.update(correlations)
            rows.append(row)

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(
        [
            "placement_variant",
            "placement_gap",
            "placement_offset",
            "stages",
            "device_id",
            "xor_k",
        ]
    )


def select_challenge_bits(challenges, stages, take_lsb=False):
    if challenges.ndim != 2:
        raise ValueError(f"Challenges must be a 2D array, got shape {challenges.shape}")

    n_bits = challenges.shape[1]
    if stages > n_bits:
        raise ValueError(
            f"Requested {stages} stages, but challenge file has only {n_bits} bits."
        )

    if take_lsb:
        return challenges[:, :stages]

    return challenges[:, n_bits - stages : n_bits]


def suffix_parity_features(challenges):
    mapped = ((-1) ** challenges.astype(np.int8)).astype(np.int8)
    return ArbiterPUF.transform_atf(mapped, k=1).reshape(len(mapped), -1)


def response_vector_for_attack(df_group):
    df_sorted = df_group.sort("challenge_id")
    challenge_ids = df_sorted["challenge_id"].to_numpy()
    expected_ids = np.arange(len(challenge_ids))
    if not np.array_equal(challenge_ids, expected_ids):
        raise ValueError(
            "Logistic regression expects contiguous challenge_id values starting at 0 "
            "so they can be aligned with the .npy challenge rows."
        )

    return df_sorted["response"].to_numpy().astype(np.int8)


def compute_logreg_for_group(
    df_group,
    challenges,
    budgets,
    test_size,
    n_trials,
    take_lsb=False,
    random_state=12345,
):
    device = df_group["device_id"][0]
    placement_variant = df_group["placement_variant"][0]
    placement_gap = int(df_group["placement_gap"][0])
    placement_offset = int(df_group["placement_offset"][0])
    slice_loc = df_group["slice"][0]
    stages = int(df_group["stages"][0])

    responses = response_vector_for_attack(df_group)
    challenge_bits = select_challenge_bits(
        challenges[: len(responses)], stages, take_lsb
    )
    features = suffix_parity_features(challenge_bits)

    n = len(responses)
    rows = []
    for budget in budgets:
        if budget + test_size > n:
            continue

        for trial in range(n_trials):
            rng_seed = random_state + trial + budget
            train_ids, test_ids = train_test_split(
                np.arange(n),
                train_size=budget,
                test_size=test_size,
                random_state=rng_seed,
                shuffle=True,
                stratify=responses if len(np.unique(responses)) == 2 else None,
            )

            y_train = responses[train_ids]
            y_test = responses[test_ids]
            if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
                rows.append(
                    {
                        "device_id": device,
                        "placement_variant": placement_variant,
                        "placement_gap": placement_gap,
                        "placement_offset": placement_offset,
                        "slice": slice_loc,
                        "stages": stages,
                        "budget": budget,
                        "trial": trial,
                        "accuracy": None,
                        "balanced_accuracy": None,
                        "target_mean_train": float(np.mean(y_train)),
                        "target_mean_test": float(np.mean(y_test)),
                        "note": "single-class split",
                    }
                )
                continue

            clf = LogisticRegression(max_iter=1_000, C=1.0, solver="lbfgs")
            clf.fit(features[train_ids], y_train)
            y_pred = clf.predict(features[test_ids])

            accuracy = accuracy_score(y_test, y_pred)
            balanced = balanced_accuracy_score(y_test, y_pred)

            rows.append(
                {
                    "device_id": device,
                    "placement_variant": placement_variant,
                    "placement_gap": placement_gap,
                    "placement_offset": placement_offset,
                    "slice": slice_loc,
                    "stages": stages,
                    "budget": budget,
                    "trial": trial,
                    "accuracy": float(max(accuracy, 1 - accuracy)),
                    "balanced_accuracy": float(max(balanced, 1 - balanced)),
                    "target_mean_train": float(np.mean(y_train)),
                    "target_mean_test": float(np.mean(y_test)),
                    "note": None,
                }
            )

    return rows


def run_logreg(
    df, challenges_file, device, budgets, test_size, n_trials, take_lsb=False
):
    if not challenges_file.exists():
        raise FileNotFoundError(f"Challenge file not found: {challenges_file}")

    challenges = np.load(challenges_file, mmap_mode="r")
    df_device = df.filter(pl.col("device_id") == device)
    rows = []
    for _, df_group in df_device.group_by(
        ["placement_variant", "placement_gap", "placement_offset", "slice", "stages"],
        maintain_order=True,
    ):
        rows.extend(
            compute_logreg_for_group(
                df_group,
                challenges,
                budgets,
                test_size,
                n_trials,
                take_lsb=take_lsb,
            )
        )

    results = pl.DataFrame(rows)
    if results.is_empty():
        return results

    return results.sort(["stages", "slice", "budget", "trial"])


def summarize_logreg(results):
    if results.is_empty():
        return results

    return (
        results.group_by(
            [
                "placement_variant",
                "placement_gap",
                "placement_offset",
                "device_id",
                "slice",
                "stages",
                "budget",
            ]
        )
        .agg(
            [
                pl.col("accuracy").mean().alias("accuracy_mean"),
                pl.col("accuracy").std().alias("accuracy_std"),
                pl.col("balanced_accuracy").mean().alias("balanced_accuracy_mean"),
                pl.col("balanced_accuracy").std().alias("balanced_accuracy_std"),
                pl.col("target_mean_test").mean().alias("target_mean_test"),
                pl.len().alias("trials"),
            ]
        )
        .sort(
            [
                "placement_variant",
                "placement_gap",
                "placement_offset",
                "stages",
                "slice",
                "budget",
            ]
        )
    )


def select_existing(df, columns):
    return df.select([col for col in columns if col in df.columns])


def print_table(df, columns):
    print(select_existing(add_bias_columns(df), columns))


def main():
    pl.Config.set_tbl_cols(32)
    pl.Config.set_tbl_rows(200)
    pl.Config.set_tbl_width_chars(220)

    args = parse_args()
    df = load_crps(
        args.crps,
        args.max_challenges,
        args.placement_variant,
        args.placement_gap,
        args.placement_offset,
    )
    devices = df.select("device_id").unique().sort("device_id")["device_id"].to_list()
    if not devices:
        raise ValueError("No devices found in CRP CSV.")

    device = args.device or devices[0]

    print("# Analysis of multiple devices")
    multiple_devices = analyze_multiple_devices(df)
    print_table(multiple_devices, METRIC_REPORT_COLUMNS)

    print("# Analysis of one device across slices")
    one_device = analyze_one_device_across_slices(df, device)
    print_table(one_device, METRIC_REPORT_COLUMNS)

    print("# k-XOR combinations across slices")
    xor_combinations = analyze_xor_combinations(df, device, args.xor_ks)
    print_table(xor_combinations, METRIC_REPORT_COLUMNS)

    print("# k-XOR inter-device uniqueness")
    xor_inter_device = analyze_xor_inter_device(df, args.xor_ks)
    print_table(xor_inter_device, METRIC_REPORT_COLUMNS)

    print("# k-XOR intra-device uniqueness across combinations")
    xor_intra_device = analyze_xor_intra_device(df, args.xor_ks)
    print_table(xor_intra_device, METRIC_REPORT_COLUMNS)

    print("# Logistic regression attack")
    logreg_trials = run_logreg(
        df,
        args.challenges_file,
        device,
        args.budgets,
        args.test_size,
        args.trials,
        take_lsb=args.take_lsb,
    )
    logreg_summary = summarize_logreg(logreg_trials)
    print(select_existing(logreg_summary, LOGREG_REPORT_COLUMNS))

    return {
        "multiple_devices": multiple_devices,
        "one_device_across_slices": one_device,
        "xor_combinations": xor_combinations,
        "xor_inter_device": xor_inter_device,
        "xor_intra_device": xor_intra_device,
        "logreg_trials": logreg_trials,
        "logreg_summary": logreg_summary,
    }


if __name__ == "__main__":
    main()
