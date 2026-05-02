# Stock Metadata Agent Guidance

- Treat `processed_photos.txt` as the authoritative processed-image ledger. For a fresh clone it starts empty; read it before batch work and update it only after validation and export succeed.
- The repository authority files are `shutterstock_categories.md`, `adobe_categories.md`, `shutterstock_content_upload.csv`, `Sample_Adobe_Stock_CSV_upload.csv`, and `iStockMetadataTemplate.csv`. Do not invent provider headers or mix category systems.
- Metadata decisions must come from the original image for that filename. Contact sheets and sequence order can help navigation, but not final metadata.
- Write per-image markdown immediately after reviewing that image so filename, image, and markdown stay synchronized.
- Keep machine-checkable rules in `generate_stock_metadata.py` or `stock_metadata_agent/workflow.py` whenever practical. Use the bundled skill for runtime sequencing and judgment calls, not long validation checklists.
- The bundled Codex skill lives in `skills/stock-photo-metadata`. It should delegate executable workflow, validation, export, and ledger updates to the repository Python code rather than carrying duplicate scripts.
