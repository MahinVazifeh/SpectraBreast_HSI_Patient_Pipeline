import sys
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ["pixel_x", "pixel_y"]
LABEL = "label"
EXCLUDE = {LABEL, "label_idx"}


def load(path):
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(p)
    else:
        df = pd.read_excel(p)
    df.columns = df.columns.astype(str).str.strip()
    return df


def prepare(df, name):
    n_dup = int(df.duplicated(KEY).sum())
    if n_dup:
        print(f"WARNING {name}: {n_dup} duplicate keys, keeping the first for comparison")
        df = df[~df.duplicated(KEY, keep="first")]
    return df.set_index(KEY)


a_raw, b_raw = load(sys.argv[1]), load(sys.argv[2])
print(f"A: {len(a_raw)} rows, {a_raw[KEY[0]].nunique()} samples")
print(f"B: {len(b_raw)} rows, {b_raw[KEY[0]].nunique()} samples")

a, b = prepare(a_raw, "A"), prepare(b_raw, "B")

# ---- 1. Columns ----
only_a_cols = [c for c in a.columns if c not in b.columns]
only_b_cols = [c for c in b.columns if c not in a.columns]
common_cols = [c for c in a.columns if c in b.columns]
spectral = [
    c
    for c in common_cols
    if c not in EXCLUDE
    and pd.api.types.is_numeric_dtype(a[c])
    and pd.api.types.is_numeric_dtype(b[c])
]
print("\n--- Columns ---")
print("only in A:", only_a_cols[:10], "(first 10)" if len(only_a_cols) > 10 else "")
print("only in B:", only_b_cols[:10], "(first 10)" if len(only_b_cols) > 10 else "")
print("same columns in same order:", list(a.columns) == list(b.columns))
print("spectral columns compared:", len(spectral))

# ---- 2. Same pixels (Sample ID + x + y) ----
common = a.index.intersection(b.index).sort_values()
print("\n--- Pixels by position (Sample ID, x, y) ---")
print("in both files:", len(common))
print("only in A:", len(a.index.difference(b.index)))
print("only in B:", len(b.index.difference(a.index)))
if len(common):
    print("shared pixels per sample:")
    print(common.get_level_values(0).value_counts().sort_index().to_string())

    A = a.loc[common, spectral].to_numpy(dtype=float)
    B = b.loc[common, spectral].to_numpy(dtype=float)
    exact = ((A == B) | (np.isnan(A) & np.isnan(B))).all(axis=1)
    close = np.isclose(A, B, rtol=1e-6, atol=1e-9, equal_nan=True).all(axis=1)
    print(f"\nshared pixels with identical spectra: {int(exact.sum())} / {len(common)}")
    print(f"shared pixels with nearly identical spectra (1e-6): {int(close.sum())} / {len(common)}")
    if not exact.all():
        print("max absolute difference:", float(np.nanmax(np.abs(A - B))))

    la = a.loc[common, LABEL].fillna("").to_numpy()
    lb = b.loc[common, LABEL].fillna("").to_numpy()
    print(f"shared pixels with different labels: {int((la != lb).sum())}")

# ---- 3. Same spectra, ignoring coordinates and labels ----
print("\n--- Spectra regardless of position ---")
ha = pd.util.hash_pandas_object(a_raw[spectral].round(6), index=False).to_numpy()
hb = pd.util.hash_pandas_object(b_raw[spectral].round(6), index=False).to_numpy()
shared = np.intersect1d(ha, hb)
print("distinct spectra in A:", len(np.unique(ha)))
print("distinct spectra in B:", len(np.unique(hb)))
print("spectra found in both files:", len(shared))

# ---- Verdict ----
print("\n--- Verdict ---")
if len(common) == 0 and len(shared) == 0:
    print("Different data: no shared pixels and no shared spectra.")
elif (
    not only_a_cols
    and not only_b_cols
    and len(common) == len(a) == len(b)
    and exact.all()
    and (la == lb).all()
):
    print("The two files contain the same pixel data.")
else:
    print("Partial overlap or differences: see the numbers above.")