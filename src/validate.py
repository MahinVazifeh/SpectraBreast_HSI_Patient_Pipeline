import sys

import pandas as pd

from schema import load_config, split_columns


def validate_batch(df, cfg, reference_spectral=None):
    """Return (errors, warnings). An empty errors list means the batch is valid."""
    errors, warnings = [], []
    c = cfg["columns"]
    sid, x, y, lab = c["sample_id"], c["x"], c["y"], c["label"]

    # 1. Required columns
    missing_cols = [col for col in (sid, x, y, lab) if col not in df.columns]
    if missing_cols:
        return [f"Missing required columns: {missing_cols}"], warnings

    _, spectral = split_columns(df, cfg)
    if not spectral:
        errors.append("No spectral columns found")

    # 2. Spectral columns must match the reference (names and order)
    if reference_spectral is not None and spectral != reference_spectral:
        extra = [col for col in spectral if col not in reference_spectral]
        absent = [col for col in reference_spectral if col not in spectral]
        errors.append(
            f"Spectral columns differ from master "
            f"(extra: {extra[:5]}, missing: {absent[:5]}) or are in a different order"
        )

    # 3. Sample ID not empty
    empty_ids = df[sid].isna() | (df[sid].astype(str).str.strip() == "")
    if empty_ids.any():
        errors.append(f"{int(empty_ids.sum())} rows with empty '{sid}'")

    # 4. Coordinates: non-negative integers
    for col in (x, y):
        if not pd.api.types.is_integer_dtype(df[col]):
            errors.append(f"'{col}' must be integer with no missing values")
        elif (df[col] < 0).any():
            errors.append(f"'{col}' has negative values")

    # 5. (Sample ID, x, y) must be unique
    n_dup = int(df.duplicated([sid, x, y]).sum())
    if n_dup:
        errors.append(f"{n_dup} duplicate ({sid}, {x}, {y}) rows")

    # 6. Labels
    allowed = set(cfg["labels"]["allowed"])
    unknown = set(df[lab].dropna().unique()) - allowed
    if unknown:
        errors.append(f"Unknown labels: {sorted(unknown)}")
    n_unlabeled = int(df[lab].isna().sum())
    if n_unlabeled:
        msg = f"{n_unlabeled} rows with empty '{lab}'"
        if cfg["labels"]["allow_missing"]:
            warnings.append(msg)
        else:
            errors.append(msg)

    # 7. Spectral values: numeric, no missing
    if spectral:
        non_numeric = [col for col in spectral if not pd.api.types.is_numeric_dtype(df[col])]
        if non_numeric:
            errors.append(f"Non-numeric spectral columns: {non_numeric[:5]}")
        else:
            n_nan = int(df[spectral].isna().sum().sum())
            if n_nan:
                errors.append(f"{n_nan} missing values in spectral columns")

    return errors, warnings


if __name__ == "__main__":
    cfg = load_config()
    df = pd.read_csv(sys.argv[1])
    errors, warnings = validate_batch(df, cfg)
    print(f"{len(df)} rows, {df[cfg['columns']['sample_id']].nunique()} samples")
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:", e)
    print("RESULT:", "INVALID" if errors else "VALID")
    sys.exit(1 if errors else 0)