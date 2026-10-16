import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from schema import load_config, split_columns
from validate import validate_batch

EXTRA = ["batch_id", "ingested_at", "source_file"]


def log(cfg, msg):
    log_dir = Path(cfg["paths"]["logs"])
    log_dir.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(log_dir / "ingest.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def master_files(master_dir):
    return sorted(Path(master_dir).glob("*.parquet"))


def master_spectral(master_dir, cfg):
    """Spectral column names (and order) of the existing master, or None if empty."""
    files = master_files(master_dir)
    if not files:
        return None
    cols = pq.read_schema(files[0]).names
    _, spectral = split_columns(pd.DataFrame(columns=cols), cfg)
    return [c for c in spectral if c not in EXTRA]


def master_sources(master_dir):
    """source_file values already in the master (reads only that column)."""
    if not master_files(master_dir):
        return set()
    return set(pd.read_parquet(master_dir, columns=["source_file"])["source_file"].unique())


def file_class(path, cfg):
    name = path.stem.lower()
    hits = [
        cls
        for cls, spec in cfg["file_classes"].items()
        if any(k in name for k in spec["keywords"])
    ]
    return hits[0] if len(hits) == 1 else None


def sample_from_name(path, cfg):
    m = re.search(cfg["sample_id_regex"], path.stem)
    return m.group(1) if m else None


def read_table(path):
    """Read a CSV or Excel file; normalise column names so 1700.0 and 1700 match."""
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)  # first sheet only
    else:
        df = pd.read_csv(path)
    df.columns = [
        str(int(c)) if isinstance(c, float) and c.is_integer() else str(c).strip()
        for c in df.columns
    ]
    return df


def is_stable(path, wait=5):
    """True if the file size doesn't change for a few seconds (copy finished)."""
    size = path.stat().st_size
    time.sleep(wait)
    return size == path.stat().st_size


def stage_parquet(df, final):
    """Write to a hidden temp file; the caller renames it into the master."""
    tmp = final.with_name("." + final.name + ".tmp")  # leading dot: never read as master data
    df.to_parquet(tmp, index=False)
    return tmp, final


def init_master(path, cfg):
    """One-off: build the master from the first (already clean) file, which has a Sample ID column."""
    master = Path(cfg["paths"]["master"])
    master.mkdir(parents=True, exist_ok=True)
    if master_files(master):
        sys.exit("Master already exists. Refusing to re-initialise.")
    df = read_table(path)
    errors, warnings = validate_batch(df, cfg)
    for w in warnings:
        log(cfg, f"WARNING {w}")
    if errors:
        for e in errors:
            log(cfg, f"ERROR {e}")
        sys.exit("Initial file is invalid. Nothing written.")
    df["source_file"] = "initial"
    df["batch_id"] = "initial"
    df["ingested_at"] = datetime.now().isoformat(timespec="seconds")
    tmp, final = stage_parquet(df, master / "initial.parquet")
    tmp.replace(final)
    log(cfg, f"INIT master created from {path.name}: {len(df)} rows")


def add_sample_id(df, path, cfg):
    """Step 1: put the Sample ID from the file name (e.g. SB052) in the first column.
    Returns (df, sample, error, warnings)."""
    sid = cfg["columns"]["sample_id"]
    sample = sample_from_name(path, cfg)
    if sample is None:
        return df, None, f"no Sample ID found in the file name (pattern {cfg['sample_id_regex']})", []
    warnings = []
    if sid in df.columns:
        warnings.append(f"file already had a '{sid}' column; replaced by '{sample}' from the file name")
        df = df.drop(columns=[sid])
    df.insert(0, sid, sample)
    return df, sample, None, warnings


def check_file(path, cfg, cls):
    """Add Sample ID (and label if absent), then validate. Returns (df, errors, warnings, sample)."""
    p = cfg["paths"]
    label = cfg["columns"]["label"]
    df = read_table(path)
    df = df.drop(columns=[c for c in cfg.get("drop_columns", []) if c in df.columns])
    df, sample, error, warnings = add_sample_id(df, path, cfg)  # step 1
    if error:
        return df, [error], warnings, None

    expected = cfg["file_classes"][cls]["label"]
    if label not in df.columns:
        warnings.append(f"no '{label}' column; filled with '{expected}' from the file name")
        df[label] = expected

    errors, w = validate_batch(df, cfg, reference_spectral=master_spectral(p["master"], cfg))
    warnings += w

    other = sorted(set(df[label].dropna().unique()) - {expected})
    if other:
        errors.append(f"{cls} file contains other labels: {other}")
    if path.stem in master_sources(p["master"]):
        errors.append(f"'{path.stem}' was already ingested")
    return df, errors, warnings, sample


def run(cfg):
    p = cfg["paths"]
    files = [
        f
        for f in sorted(Path(p["incoming"]).iterdir())
        if f.suffix.lower() in (".csv", ".xlsx")
        and not f.name.startswith("~$")  # temporary file Excel creates while a file is open
        and is_stable(f)
    ]
    if not files:
        log(cfg, "No CSV/Excel files in incoming")
        return

    by_class = {cls: [] for cls in cfg["file_classes"]}
    unknown = []
    for f in files:
        cls = file_class(f, cfg)
        (by_class[cls] if cls else unknown).append(f)

    counts = {cls: len(v) for cls, v in by_class.items()}
    if unknown or any(n != 1 for n in counts.values()):
        log(
            cfg,
            f"WAITING: need exactly one file per class, found {counts}; "
            f"unrecognised names: {[f.name for f in unknown]}. Nothing moved.",
        )
        return
    pair = {cls: v[0] for cls, v in by_class.items()}

    data, samples, errors = {}, {}, []
    for cls, f in pair.items():
        df, e, w, sample = check_file(f, cfg, cls)
        data[cls], samples[cls] = df, sample
        errors += [f"{f.name}: {m}" for m in e]
        for m in w:
            log(cfg, f"WARNING {f.name}: {m}")

    if not errors and len(set(samples.values())) != 1:
        errors.append(f"The two files belong to different samples: {samples}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if errors:
        for f in pair.values():
            dest = Path(p["rejected"]) / f"{stamp}_{f.name}"
            shutil.move(str(f), dest)
            dest.with_name(dest.name + ".reasons.txt").write_text("\n".join(errors), encoding="utf-8")
        for e in errors:
            log(cfg, f"ERROR {e}")
        log(cfg, f"REJECTED both files -> {p['rejected']}")
        return

    ingested = datetime.now().isoformat(timespec="seconds")
    staged = []
    for cls, f in pair.items():
        df = data[cls]
        df["source_file"] = f.stem
        df["batch_id"] = stamp
        df["ingested_at"] = ingested
        staged.append(stage_parquet(df, Path(p["master"]) / f"{stamp}_{f.stem}.parquet"))
    for tmp, final in staged:  # both files are fully written before either enters the master
        tmp.replace(final)
    for cls, f in pair.items():
        shutil.move(str(f), Path(p["raw"]) / f"{stamp}_{f.name}")
        log(cfg, f"ACCEPTED {f.name}: {len(data[cls])} rows, sample {samples[cls]}")


if __name__ == "__main__":
    cfg = load_config()
    if len(sys.argv) == 3 and sys.argv[1] == "--init":
        init_master(Path(sys.argv[2]), cfg)
    else:
        run(cfg)