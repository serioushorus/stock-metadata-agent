# Provider Authorities

Read these workspace files before writing metadata:

- `shutterstock_categories.md`
- `adobe_categories.md`
- `shutterstock_content_upload.csv`
- `Sample_Adobe_Stock_CSV_upload.csv`
- `iStockMetadataTemplate.csv`

Provider rules:

- Shutterstock and Adobe category systems are separate authorities.
- Shutterstock categories must match `shutterstock_categories.md` verbatim.
- Adobe category must match `adobe_categories.md` verbatim; `generate_stock_metadata.py` converts it to the Adobe numeric id.
- Never place Adobe-only categories in Shutterstock metadata. Example: `Travel` is valid for Adobe but not for Shutterstock.
- Prefer one or two Shutterstock categories.

CSV expectations:

- Shutterstock export fields: `Filename`, `Description`, `Keywords`, `Categories`, `Editorial`, `Mature content`, `illustration`
- Adobe export fields: `Filename`, `Title`, `Keywords`, `Category`, `Releases`
- iStock export fields: `file name`, `created date`, `description`, `country`, `title`, `keywords`
- iStock must preserve the exact header spelling and order from `iStockMetadataTemplate.csv` and be written as UTF-8 without BOM.
