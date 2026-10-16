from datetime import datetime
from pathlib import Path

from ingest import log, master_sources, master_spectral, read_table, stage_parquet
from schema import load_config
from validate import validate_batch

SOURCE = "SB051_tumour_restored"
EXPECTED_LABEL = "tessuto tumorale"
EXPECTED_SAMPLE = "SB051"

cfg = load_config()
p = cfg["paths"]
label = cfg["columns"]["label"]
sid = cfg["columns"]["sample_id"]

df = read_table(Path(p["rejected"]) / "removed_duplicates.csv")
errors, warnings = validate_batch(
    df, cfg, reference_spectral=master_spectral(p["master"], cfg)
)

if set(df[label].unique()) != {EXPECTED_LABEL}:
    errors.append(f"unexpected labels: {sorted(df[label].unique())}")
if set(df[sid].unique()) != {EXPECTED_SAMPLE}:
    errors.append(f"unexpected samples: {sorted(df[sid].unique())}")
if SOURCE in master_sources(p["master"]):
    errors.append("already restored: refusing to add the rows twice")

if errors:
    for e in errors:
        print("ERROR:", e)
    raise SystemExit("Nothing written.")

df["source_file"] = SOURCE
df["batch_id"] = "restore_sb051"
df["ingested_at"] = datetime.now().isoformat(timespec="seconds")
tmp, final = stage_parquet(df, Path(p["master"]) / "restore_SB051_tumour.parquet")
tmp.replace(final)
log(cfg, f"RESTORED {len(df)} SB051 tumour rows as {SOURCE}")