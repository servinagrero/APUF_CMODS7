from pathlib import Path

import numpy as np

DATA_DIR = Path("./data").resolve()
CHALLENGES_DIR = DATA_DIR / "challenges"
CHALLENGES_DIR.mkdir(parents=True, exist_ok=True)

RNG_SEED = 123456

MAX_STAGES = 64


def ints_to_bits(x, nbits, *, bitorder="big", dtype=np.uint8):
    x = np.asarray(x, dtype=object)
    shifts = (
        np.arange(nbits - 1, -1, -1, dtype=object)
        if bitorder == "big"
        else np.arange(nbits, dtype=object)
    )
    return ((x[..., None] >> shifts) & 1).astype(dtype)


def generate_gray_code(n_bits):
    """Generates a Gray code sequence for n_bits."""
    return np.array([i ^ (i >> 1) for i in range(2**n_bits)], dtype=np.uint32)


def create_challenges_all(
    file_path,
):
    """
    Generates a baseline random 64-bit challenge file.
    """
    rng = np.random.default_rng(RNG_SEED)

    crps_baseline = rng.integers(0, 2, size=(1_005_000, MAX_STAGES), dtype=np.uint8)
    # crps_baseline = rng.integers(0, 2, size=(55_000, MAX_STAGES), dtype=np.uint8)

    print(f"Generated {len(crps_baseline)} baseline challenges.")
    np.save(CHALLENGES_DIR / file_path, crps_baseline)


def create_challenges_k_xor(file_prefix, num_crps=1_005_000, max_k=4):
    """
    Generates a master baseline challenge set, and circularly shifted
    variants for up to k slices to break hardware spatial correlation.
    """
    rng = np.random.default_rng(RNG_SEED)

    # 1. Generate the 1 Million Base Challenges
    print(f"Generating {num_crps} base challenges...")
    base_challenges = rng.integers(0, 2, size=(num_crps, MAX_STAGES), dtype=np.uint8)

    # Save the base set for Slice 0 (e.g., RIGHT-UPPER)
    np.save(CHALLENGES_DIR / f"{file_prefix}_slice0.npy", base_challenges)

    # 2. Generate shifted variants for the other slices
    # For 64 stages and up to 4-XOR, we shift by 16 bits per slice
    shift_amount = MAX_STAGES // max_k

    for slice_idx in range(1, max_k):
        current_shift = shift_amount * slice_idx
        # Circularly shift the columns (bits)
        shifted_challenges = np.roll(base_challenges, shift=current_shift, axis=1)

        np.save(
            CHALLENGES_DIR / f"{file_prefix}_slice{slice_idx}.npy", shifted_challenges
        )
        print(
            f"Generated shifted set for Slice {slice_idx} (Shifted right by {current_shift} bits)"
        )


def create_challenges_ergodicity(file_path, dither_bits=10):
    """
    dither_bits: Number of bits closest to the input to vary (e.g., 10 bits = 1024 challenges)
    """
    rng = np.random.default_rng(RNG_SEED)

    # Baseline random challenges to compare against
    crps_baseline = rng.integers(0, 2, size=(1000, MAX_STAGES), dtype=np.uint8)

    # Generate the Ergodicity Study set (i.e. Spatial Dithering)
    base_challenge = rng.integers(0, 2, size=(MAX_STAGES,), dtype=np.uint8)

    # Generate gray code for the leftmost 'dither_bits' (closest to input)
    gray_ints = generate_gray_code(dither_bits)
    gray_bits = ints_to_bits(gray_ints, dither_bits, bitorder="big")

    crps_ergodicity = np.tile(base_challenge, (2**dither_bits, 1))
    crps_ergodicity[:, :dither_bits] = gray_bits

    crps_study = np.concatenate([crps_baseline, crps_ergodicity], axis=0)
    np.save(CHALLENGES_DIR / file_path, crps_study)

    print(f"Generated {len(crps_baseline)} baseline challenges.")
    print(
        f"Generated {len(crps_ergodicity)} dithered challenges (1 base + {dither_bits} input-side bits swept)."
    )


def create_challenges_ergodicity_clusters(file_path, n_clusters=10, dither_bits=10):
    """
    dither_bits: Number of bits closest to the input to vary (e.g., 10 bits = 1024 challenges)
    """
    rng = np.random.default_rng(RNG_SEED)

    # Generate gray code for the leftmost 'dither_bits' (closest to input)
    gray_ints = generate_gray_code(dither_bits)
    gray_bits = ints_to_bits(gray_ints, dither_bits, bitorder="big")

    crps = []
    for cluster in range(n_clusters):
        # Generate the Ergodicity Study set (i.e. Spatial Dithering)
        base_challenge = rng.integers(0, 2, size=(MAX_STAGES,), dtype=np.uint8)

        crps_ergodicity = np.tile(base_challenge, (2**dither_bits, 1))
        crps_ergodicity[:, :dither_bits] = gray_bits
        crps.append(crps_ergodicity)

    crps_study = np.concatenate(crps, axis=0)
    np.save(CHALLENGES_DIR / file_path, crps_study)

    print(
        f"Generated {len(crps_ergodicity)} dithered challenges (1 base + {dither_bits} input-side bits swept)."
    )
    print(f"Generated a total of {len(crps_study)} challenges")


def create_challenges_metastability(file_path, num_crps=25_000):
    """Generate random 64-bit challenges for repeated-read metastability studies."""
    rng = np.random.default_rng(RNG_SEED)
    challenges = rng.integers(0, 2, size=(num_crps, MAX_STAGES), dtype=np.uint8)
    np.save(CHALLENGES_DIR / file_path, challenges)
    print(f"Generated {len(challenges)} metastability challenges.")


if __name__ == "__main__":
    # create_challenges_all("all_challenges.npy")
    # create_challenges_ergodicity("ergodicity_challenges.npy", dither_bits=16)
    # create_challenges_ergodicity_clusters(
    #     "ergodicity_clusters_challenges.npy", n_clusters=100, dither_bits=11
    # )
    create_challenges_metastability("metastability_challenges.npy")
