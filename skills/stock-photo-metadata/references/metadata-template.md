# Metadata Template

Use this exact structure for each image metadata file:

```md
# Metadata

- Filename: `IMAGE_FILENAME`
- Created date: YYYY-MM-DD
- Country:
- Title: Short descriptive title
- Description: One factual sentence describing the visible image content.
- Keywords: keyword 1, keyword 2, keyword 3
- Shutterstock Categories: Nature, Parks/Outdoor
- Adobe Category: Landscapes
- Editorial: no
- Mature content: no
- Illustration: no
- Releases:
- Notes:
```

Rules:

- The markdown filename should match the image stem, for example `IMG_1234.md` for `IMG_1234.jpg`.
- `Filename` must match the source image filename exactly.
- `Created date` is optional unless the workflow needs it for iStock or editorial context. Allowed formats: `YYYY-MM-DD`, `MM/DD/YYYY`, `YYYY-MM-DD HH:MM`, `YYYY-MM-DD HH:MM +HH:MM`.
- `Country` should stay blank unless the file's own EXIF and visible context support a country-level claim.
- `Shutterstock Categories` must use exact Shutterstock category names.
- `Adobe Category` must use the exact Adobe category name; numeric conversion happens during export.
- `Notes` is for short caveats, including uncertainty about species or common-name identification.
