---
name: stock-photo-metadata
description: Generate stock photo upload metadata from local image folders and export Shutterstock, Adobe Stock, and iStock CSV files, including separate iStock commercial and editorial exports plus numbered iStock upload batches. Use when Codex needs to inspect many photos, write one metadata markdown file per image, classify each image against Shutterstock and Adobe category lists, mark editorial risk conservatively, organize editorial-marked assets, split iStock uploads by image count, and then hand fixed workflow steps to stock_metadata_agent.workflow and generate_stock_metadata.py without external taxonomy APIs.
---

# Stock Photo Metadata

Use this skill to review local photo batches and produce per-image markdown plus Shutterstock, Adobe Stock, and iStock CSV exports, including upload-size iStock batches. Inspect originals with Codex/OpenAI image review only; do not use external taxonomy APIs.

## Repository Program Source

Use the local `stock-metadata-agent` repository as the only source for executable workflow code, exporter code, helper scripts, provider authority files, CSV templates, tests, and dependency metadata. Run commands from the `stock-metadata-agent` repository root whenever possible so `workflow.py` can resolve `processed_photos.txt`, provider authorities, `.env`, and generated outputs consistently.

Do not copy or reimplement repository program logic inside this skill. If an executable step is missing, stale, or failing, update or report the blocker in `stock-metadata-agent` instead of falling back to a skill-bundled script.

## Runtime Contract

Prefer the repository workflow over manual setup, validation, export, and ledger updates.

1. From the `stock-metadata-agent` repository root, run `stock_metadata_agent/workflow.py` with `--review-mode codex` for the target batch.
2. If the workflow prints a Codex review queue path, read that `.stock_metadata_review_queue.json` file and treat its `items` list as the source of truth for images needing visual review.
3. For each queued item, open the exact `image_path` with `view_image`, read that item's `exif`, and write exactly one markdown file to `metadata_path`.
4. Do not update `processed_photos.txt` manually during visual review.
5. After all queued markdown files are written, rerun the same workflow command with `--review-mode codex` and any required export flags such as `--overwrite-csv`.
6. Consider the batch complete only after the workflow validates metadata, exports CSVs, and updates `processed_photos.txt`.

Example:

```powershell
cd stock-metadata-agent
python stock_metadata_agent\workflow.py 260420 --review-mode codex --overwrite-csv
```

If the first run creates a queue, complete the visual review items, then rerun the command.

## iStock CSV Outputs

The exporter must produce iStock metadata in separated upload files as well as the combined compatibility file:

- `istock_metadata_generated.csv`: all validated metadata items.
- `istock_metadata_commercial_generated.csv`: only items with `Editorial: no`.
- `istock_metadata_editorial_generated.csv`: only items with `Editorial: yes`.

When rebuilding CSVs, use the repository workflow or repository `generate_stock_metadata.py`; do not manually split iStock CSV rows after export.

## iStock Batch Split

iStock uploads have a per-batch image limit. When preparing iStock upload folders after CSV export and commercial/editorial separation, use the repository splitter instead of manually moving images or editing CSV rows.

Run the splitter from the `stock-metadata-agent` repository root against either a single commercial/editorial upload folder or a parent folder that contains multiple upload folders:

```powershell
cd stock-metadata-agent
python stock_metadata_agent\scripts\split_istock_batches.py path\to\istock_root --max-images 100
```

Rules:

- Default to `--max-images 100` unless the user gives a different iStock upload limit.
- The splitter must discover both commercial and editorial iStock CSVs.
- It must move each CSV-referenced image and its matching `.md` file into numbered folders such as `batch_001`, `batch_002`, and `batch_003`.
- Each numbered folder must contain the matching provider CSV for that subset: `istock_metadata_commercial_generated.csv` for commercial folders and `istock_metadata_editorial_generated.csv` for editorial folders.
- Do not manually split, reorder, or rewrite iStock rows after export. If the splitter fails because images, markdown, or CSV rows do not match, stop and fix the source folder before continuing.

The splitter accepts both current generated CSV names and `_all` source CSV names, including `istock_metadata_commercial_generated.csv`, `istock_metadata_commercial_generated_all.csv`, `istock_metadata_editorial_generated.csv`, and `istock_metadata_editorial_generated_all.csv`.

## Editorial Asset Organization

When asked to separate editorial images from commercial images, use the repository script instead of hand-moving files. It scans date folders named like `YYMMDD` or `YYMMDD_2`, reads root-level per-image markdown, selects files with `Editorial: yes` or `Editorial: true`, creates an `editorial` subfolder in each date folder, then moves both the referenced image from the markdown `Filename` field and the markdown file.

Always dry-run first from the workspace root:

```powershell
cd stock-metadata-agent
python stock_metadata_agent\scripts\organize_editorial_assets.py .
```

If the dry-run reports no missing images or destination conflicts, run:

```powershell
cd stock-metadata-agent
python stock_metadata_agent\scripts\organize_editorial_assets.py . --execute
```

The script intentionally skips aggregate/provider markdown such as `adobe_categories.md`, `shutterstock_categories.md`, and `shutterstock_metadata_*.md`. Do not update `processed_photos.txt` for this organization-only step.

## Codex Responsibilities

- Inspect each original image one by one with `view_image`.
- Write each image's markdown immediately after viewing that image and before opening the next original.
- Confirm the viewer filename, queue `filename`, markdown filename, and markdown `Filename` field match exactly.
- Base title, description, keywords, categories, editorial status, country, created date, and notes on the original image, the queued EXIF context, and provider authorities.
- Prevent adjacent-file swaps: when nearby filenames look similar or come from the same burst, A/B check the neighboring originals before saving.
- For plant or animal subjects, include scientific or common names only when Codex/OpenAI image review supports them.
- If species-level identification is uncertain, keep wording at genus, family, or generic subject level and note the uncertainty plainly.

## Workflow Responsibilities

The Python workflow is responsible for fixed, machine-checkable steps:

- read `processed_photos.txt`
- read provider authorities and CSV headers
- enumerate real source images and exclude helper artifacts
- extract EXIF context before review
- generate the Codex review queue for missing or intentionally overwritten markdown
- validate markdown against source filenames and provider categories
- run `generate_stock_metadata.py` to build Shutterstock, Adobe Stock, and iStock CSVs, including `istock_metadata_commercial_generated.csv` and `istock_metadata_editorial_generated.csv`
- when preparing iStock upload folders with per-upload limits, run `stock_metadata_agent\scripts\split_istock_batches.py` to split commercial and editorial assets into numbered upload batches by image count
- update `processed_photos.txt` only after validation and export succeed

Do not manually duplicate these steps unless the workflow is unavailable or failing; fix the workflow or report the blocker first.

## Required References

Use these files when writing markdown:

- [references/metadata-template.md](./references/metadata-template.md)
- [references/provider-authorities.md](./references/provider-authorities.md)
- [references/location-and-editorial.md](./references/location-and-editorial.md)
- [references/writing-guidance.md](./references/writing-guidance.md)

Use the queue's `authority_context` for the active allowed Shutterstock and Adobe category lists. Treat Shutterstock and Adobe categories as separate authorities.

## Visual Review Rules

- Read each queued file's EXIF context before visual classification.
- Use GPS first to guide country, city, and landmark reasoning, but treat GPS as location evidence, not landmark proof.
- Use landmark names only when both coordinates and visible subject support them.
- If GPS is missing, determine location wording from the visible image only.
- After identifying a usable location or landmark, include it in both `Description` and `Keywords`.
- Stay conservative on landmarks, species, brands, copyrighted works, private property, recognizable people, and editorial risk.
- If `Editorial: yes`, the `Description` must use Shutterstock dateline format; use bracketed placeholders instead of inventing facts.
- Leave releases empty unless the user provides release names.
- Use `Mature content: no` and `Illustration: no` for normal photographs unless the image clearly requires otherwise.

Decision rules:

- Human subject clearly visible: lead title and early keywords with the person, people, portrait, action, or role terms.
- GPS present: derive coarse country from that file first, then name city or landmark only if the image content supports that level of detail.
- GPS absent: never import location assumptions from neighboring files; rely on the visible image only.
- Landmark, species, brand, or event not clearly supported: keep it generic.
- Editorial risk uncertain: choose `Editorial: yes` and keep the wording factual.
- Sequence drift suspected: stop and re-open the surrounding originals before continuing.

## Stop Conditions

Stop and fix the batch before continuing if:

- the workflow did not run before image review
- the queue item, opened image, markdown path, or markdown `Filename` field do not match
- adjacent-file swaps or sequence drift are suspected
- `Country` or location wording depends on missing or conflicting EXIF evidence
- landmark, species, brand, or editorial claims are not visually supported
- categories are invalid or mixed across providers
- an editorial description does not follow the dateline rule
- exporter validation fails

