# Stock Metadata Agent

Generate stock-photo metadata markdown files and provider CSV exports for Shutterstock, Adobe Stock, and iStock.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Add your OpenAI API key to `.env`.

## Required Workspace Files

The workflow expects these authority and template files in the repository root:

- `shutterstock_categories.md`
- `adobe_categories.md`
- `shutterstock_content_upload.csv`
- `Sample_Adobe_Stock_CSV_upload.csv`
- `iStockMetadataTemplate.csv`
- `processed_photos.txt`

## Usage

```powershell
python stock_metadata_agent\workflow.py path\to\image_batch --overwrite-metadata --overwrite-csv
```

To reprocess files already listed in `processed_photos.txt`:

```powershell
python stock_metadata_agent\workflow.py path\to\image_batch --include-processed --overwrite-metadata --overwrite-csv
```

When an image is classified as editorial and EXIF GPS is available, the workflow
automatically reverse-geocodes the coordinates to fill the dateline city when
needed. Results are cached in `.cache\reverse_geocode_cache.json`. To disable
network reverse geocoding:

```powershell
python stock_metadata_agent\workflow.py path\to\image_batch --no-reverse-geocode
```

## Codex Review Mode

Use Codex review mode when Codex should inspect images and write per-image
markdown, while the workflow handles setup, EXIF extraction, validation, CSV
export, and ledger updates:

```powershell
python stock_metadata_agent\workflow.py path\to\image_batch --review-mode codex --overwrite-csv
```

If markdown is missing, the workflow writes `.stock_metadata_review_queue.json`
in the output folder and stops before export. Complete the queued visual review
items in Codex, then rerun the same command to validate, export, and update
`processed_photos.txt`.

## Bundled Codex Skill

This repository includes the Codex skill used for guided stock-photo metadata
review at `skills\stock-photo-metadata`.

To install or refresh it in your local Codex skills directory from the
repository root:

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.codex\skills\stock-photo-metadata | Out-Null
Copy-Item -Recurse -Force skills\stock-photo-metadata\* $env:USERPROFILE\.codex\skills\stock-photo-metadata\
```

After installing, use `$stock-photo-metadata` in Codex when running review-mode
batches. The skill delegates executable workflow, validation, CSV export, and
ledger updates to this repository's Python code.

## Validation And Export Only

The exporter can rebuild CSVs from existing metadata markdown:

```powershell
python generate_stock_metadata.py path\to\image_batch --metadata-dir path\to\image_batch --output-dir path\to\image_batch --overwrite-csv
```

## iStock Batch Split

iStock uploads have a per-batch image limit. After separating commercial and
editorial assets and writing iStock CSVs, split every detected upload folder
under a parent directory into numbered upload batches:

```powershell
python stock_metadata_agent\scripts\split_istock_batches.py path\to\istock_root --max-images 100
```

The script scans for commercial and editorial iStock CSVs, moves each
referenced image and its matching `.md` file into `batch_001`, `batch_002`, and
so on, then writes one matching iStock CSV per batch:

- commercial: `istock_metadata_commercial_generated.csv`
- editorial: `istock_metadata_editorial_generated.csv`

You can still pass a single commercial or editorial folder directly:

```powershell
python stock_metadata_agent\scripts\split_istock_batches.py path\to\editorial 100
```
