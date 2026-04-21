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

## Validation And Export Only

The exporter can rebuild CSVs from existing metadata markdown:

```powershell
python generate_stock_metadata.py path\to\image_batch --metadata-dir path\to\image_batch --output-dir path\to\image_batch --overwrite-csv
```
