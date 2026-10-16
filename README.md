# SpectraBreast HSI Patient Pipeline

A small, safe pipeline for **adding new batches of pixel-level spectral data** (hyperspectral / Raman, one row per pixel) to a growing master dataset, with automatic validation, a full audit trail and no manual editing of data.

> **No patient data is stored in this repository.** The `data/` and `logs/` folders, and all `.csv`, `.xlsx` and `.parquet` files, are excluded by `.gitignore`. Only code and configuration are versioned. Never commit data files.

---

## 1. What problem does it solve?

New samples arrive every one to two weeks as spreadsheet files. Appending them by hand to one big file is error-prone: a shifted column, a duplicated sample or a mislabelled file silently corrupts the dataset, and nothing records what changed.

This pipeline replaces the manual step with one command (or a scheduled task):

1. new files are dropped into a folder;
2. the pipeline checks them against strict rules;
3. valid files are added to the master dataset and archived untouched;
4. invalid files are rejected with a written explanation, and the master is never changed.

---

## 2. How it works

```
data/incoming/   -->  check  -->  data/master/     (accepted: appended as new Parquet files)
 SB052_healthy.xlsx                data/raw/        (accepted: original files archived)
 SB052_tumour.xlsx    \--------->  data/rejected/   (refused: files + reasons .txt)
```

Each batch consists of **exactly one healthy file and one tumour file** for the same sample. The pipeline accepts or rejects the **pair together**: either both files enter the master, or neither does. If only one of the two files is present, the pipeline waits and moves nothing.

---

## 3. Input files

### 3.1 Naming rule (important)

The file name carries two pieces of information, because the files themselves contain no sample identifier:

| Part of the name | Meaning | Example |
|---|---|---|
| Sample ID (matches the pattern in `config.yaml`, default `SB` + digits) | Becomes the `Sample ID` column | `SB052` |
| Class keyword | `healthy` (or `adiposo`) / `tumour`, `tumor` (or `tumorale`) | `healthy` |

Correct examples:

```
SB052_healthy.xlsx
SB052_tumour.xlsx
```

Rules for names: both files of a batch must contain the **same Sample ID**, exactly one class keyword per name, and a name can be used only **once** (re-submitting the same file name is rejected as already ingested).

### 3.2 Supported formats

`.xlsx` and `.csv`. For Excel, **only the first sheet is read**. Close the files in Excel before running, since an open file is locked and cannot be moved.

### 3.3 Expected columns

| Column | Required | Notes |
|---|---|---|
| `pixel_x`, `pixel_y` | yes | non-negative integers, no missing values |
| `label` | optional | if absent, it is filled from the file class; if present, all values must match the file class |
| spectral columns (one per wavenumber, e.g. `400`, `404.5`, ..., `1700`) | yes | numeric, no missing values, **same names and order as the master** |
| `Sample ID` | no | added automatically from the file name |
| `label_idx` | no | dropped automatically (configurable in `drop_columns`) |

Labels used: `tessuto adiposo` (healthy tissue) and `tessuto tumorale` (tumour tissue). The mapping to 0/1 for machine learning is in `config.yaml` under `label_map`.

---

## 4. Validation rules

A file is rejected if any of these fail:

- required columns are missing;
- the spectral columns differ from the master (different names, extra, missing or different order);
- `Sample ID` is empty, or cannot be found in the file name;
- `pixel_x` / `pixel_y` are not non-negative integers;
- the same `(Sample ID, pixel_x, pixel_y)` appears twice inside the file;
- a label is unknown, or empty (when `allow_missing: false`);
- a healthy file contains tumour labels, or vice versa;
- spectral values are non-numeric or missing;
- the file name was already ingested;
- the two files of a batch belong to different samples.

When a batch is refused, both files are moved to `data/rejected/` next to a `.reasons.txt` file that lists every problem, and the reasons are also written to `logs/ingest.log`.

---

## 5. The master dataset

`data/master/` is a **folder of Parquet files**, one per ingested file. Adding a batch only writes new files; existing files are never rewritten, so a failure can never damage earlier data. Reading the folder gives one table.

Every row carries three tracking columns:

| Column | Meaning |
|---|---|
| `source_file` | file the pixel came from (e.g. `SB052_healthy`) |
| `batch_id` | timestamp of the ingestion |
| `ingested_at` | date and time of ingestion |

**A pixel is identified by `(Sample ID, source_file, pixel_x, pixel_y)`**, not by coordinates alone. Healthy and tumour files of the same sample can use the same coordinates for different pixels, so the source file is part of the key.

Files in `data/raw/` are the original submissions with a timestamp prefix. They are **never edited**, so the master can always be rebuilt from them.

---

## 6. Project structure

```
patient_pipeline/
├── config.yaml          # all settings (paths, labels, naming rules)
├── requirements.txt     # Python dependencies
├── run_ingest.bat       # entry point for the scheduled task (Windows)
├── src/
│   ├── ingest.py        # main script: init and regular runs
│   ├── validate.py      # validation rules
│   ├── schema.py        # config loader and column helpers
│   ├── inspect_master.py# summary of the master dataset
│   └── ...              # one-off helper scripts (comparison, cleaning, restore)
├── data/                # NOT in Git
│   ├── incoming/        # drop new files here
│   ├── raw/             # accepted originals (archive)
│   ├── rejected/        # refused files + reasons
│   └── master/          # master dataset (Parquet files)
└── logs/                # NOT in Git: ingest.log, scheduler.log
```

---

## 7. Setup

Requirements: Python 3.11 or newer, and Git.

```powershell
git clone https://github.com/MahinVazifeh/SpectraBreast_HSI_Patient_Pipeline.git
cd SpectraBreast_HSI_Patient_Pipeline

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

mkdir data\incoming, data\raw, data\rejected, data\master, logs
```

`requirements.txt`:

```
pandas
pyarrow
pyyaml
openpyxl
```

All commands below are run from the project folder (where `config.yaml` is), because the scripts look for `config.yaml` in the current directory.

---

## 8. Usage

### 8.1 One-time: create the master from an existing file

Only needed when starting from an existing, already clean dataset (with a `Sample ID` column):

```powershell
python src\ingest.py --init "data\raw\<initial_file>.csv"
```

The script refuses to run if a master already exists.

### 8.2 Regular use: add a new batch

1. Close the files in Excel.
2. Copy the two files (healthy and tumour) into `data\incoming\`, named by the rule in section 3.1.
3. Run:

```powershell
python src\ingest.py
```

4. Read the result:
   - `ACCEPTED` for both files: they are in `data\master`, and the originals are archived in `data\raw`.
   - `REJECTED`: open the `.reasons.txt` file in `data\rejected`, fix the problem and drop the corrected files into `incoming` again.
   - `WAITING`: one of the two files is missing, or a name is not recognised. Nothing was moved.

Note: the script moves files out of `incoming`, so keep your own copy of the originals elsewhere.

### 8.3 Inspect the master

```powershell
python src\inspect_master.py
```

Prints the files in the master, the total number of rows, and the rows per sample, source file and label.

### 8.4 Use the data in Python

```python
import pandas as pd

df = pd.read_parquet("data/master")                      # everything (about 1 GB+ in memory)
one = pd.read_parquet("data/master", filters=[("Sample ID", "==", "SB052")])   # one sample
meta = pd.read_parquet("data/master", columns=["Sample ID", "source_file", "label"])  # no spectra

df["y"] = df["label"].map({"tessuto adiposo": 0, "tessuto tumorale": 1})
```

Advice for machine learning:
- **Split by `Sample ID`, never by pixel.** Pixels of the same sample are highly correlated; a random pixel split leaks information and inflates results. Use group-based splits (for example `GroupKFold`) or hold out whole samples.
- Expect **class imbalance** between healthy and tumour pixels, and use class weights or balancing.

---

## 9. Scheduling (optional, Windows)

`run_ingest.bat` runs the pipeline; edit the two paths inside it for your machine. The pipeline does nothing if the pair is incomplete, so a frequent schedule is safe.

```powershell
schtasks /Create /SC DAILY /TN "PatientPipelineIngest" /ST 09:00 /TR "C:\full\path\to\run_ingest.bat"
schtasks /Run /TN "PatientPipelineIngest"                         # run it now
schtasks /Change /TN "PatientPipelineIngest" /DISABLE             # pause
schtasks /Change /TN "PatientPipelineIngest" /ENABLE              # resume
schtasks /Delete /TN "PatientPipelineIngest" /F                   # remove
```

The computer must be on and the user logged in at the scheduled time; a skipped run is picked up by the next one. Output goes to `logs/ingest.log` and `logs/scheduler.log`.

---

## 10. Configuration reference (`config.yaml`)

```yaml
paths:
  incoming: data/incoming
  raw: data/raw
  rejected: data/rejected
  master: data/master
  logs: logs

columns:
  sample_id: Sample ID
  x: pixel_x
  y: pixel_y
  label: label

labels:
  allowed: [tessuto adiposo, tessuto tumorale]
  allow_missing: false        # true = rows without a label are accepted with a warning

label_map:                    # for ML use
  tessuto adiposo: 0
  tessuto tumorale: 1

file_classes:                 # how a file's class is recognised from its name
  healthy:
    keywords: [healthy, adiposo]
    label: tessuto adiposo
  tumour:
    keywords: [tumour, tumor, tumorale]
    label: tessuto tumorale

sample_id_regex: '(SB\d+)'    # finds the Sample ID in a file name; the part in () is the ID
drop_columns: [label_idx]     # columns removed from incoming files before validation
```

To support a new class or a different ID format, change the config; no code change is needed.

---

## 11. Troubleshooting

| Message or symptom | Likely cause and fix |
|---|---|
| `WAITING: need exactly one file per class` | Only one of the two files is in `incoming`, a name has no class keyword, or a name contains both. Check the names. |
| `no Sample ID found in the file name` | The name does not match `sample_id_regex`. Rename the file or adjust the pattern. |
| `Spectral columns differ from master` | The file has extra, missing or reordered spectral columns. Add unwanted columns to `drop_columns`, or export the file with the same wavenumbers as the master. |
| `'<name>' was already ingested` | A file with that name is already in the master. Use a new name only if the data is genuinely new. |
| `... file contains other labels` | A healthy file has tumour labels (or vice versa). Check how the file was exported. |
| `PermissionError` when moving files | The file is open in Excel. Close it and run again. |
| `Missing optional dependency 'openpyxl'` | Run `pip install openpyxl`. |
| `Master already exists. Refusing to re-initialise.` | `--init` is a one-time step; the master is already there. |
| Excel files load slowly | Large `.xlsx` files take minutes to read. Exporting to `.csv` is much faster. |

---

## 12. Data protection

- The data are sensitive. Keep the project on an **encrypted, access-controlled and backed-up disk**, and follow your institution's GDPR and ethics rules.
- Sample IDs should be **pseudonymised identifiers**, never names or hospital record numbers.
- Never commit `data/`, `logs/`, spreadsheets or Parquet files. Before pushing, check that nothing sensitive is tracked:

```powershell
git ls-files | Select-String "parquet|xlsx|csv|data"
```

This must print nothing.
- Keep the repository **private** unless it has been explicitly approved for publication.

---

## 13. Design principles

- **Raw files are immutable.** Everything in the master can be rebuilt from `data/raw`.
- **All or nothing.** A batch never enters the master partially.
- **Validation as code.** Rules live in `validate.py` and `config.yaml`, not in anyone's memory.
- **Traceability.** Every row records which file and which ingestion it came from.
- **Safe writes.** Files are written under a temporary name and renamed only when complete.

---

## 14. Known limitations

- One healthy file and one tumour file per run; larger deliveries must be ingested pair by pair.
- Only the first sheet of an Excel file is read.
- The Sample ID is taken from the file name, so naming discipline matters.
- Windows commands are shown; on Linux or macOS, replace `venv\Scripts\activate` with `source venv/bin/activate`, use `cron` instead of Task Scheduler, and adapt `run_ingest.bat` to a shell script.