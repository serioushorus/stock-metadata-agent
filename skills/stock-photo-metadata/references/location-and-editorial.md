# Location And Editorial

## GPS And Location

- Run `scripts/extract_exif_context.py` before reviewing images so each file's capture date, GPS presence, and coordinates are known in advance.
- Treat EXIF GPS as the first location clue for that exact file, not as a substitute for image review.
- If GPS exists, use it to anchor country first, then refine to city or landmark only when the visible image content supports that level of detail.
- If GPS is missing, determine location wording from the visible image only.
- Treat coordinates as location evidence, not automatic landmark proof.
- If the image and GPS together justify a location or landmark, include that place wording in both `Description` and `Keywords`.
- If the location is plausible but not fully certain, keep the wording generic.
- Never carry location wording from a neighboring image by sequence momentum.

## Species And Taxa

- Stay conservative on species claims.
- Include scientific or common names only when Codex/OpenAI image review supports them.
- If species-level identification is uncertain, keep the wording at the genus, family, or generic subject level.
- Use `Notes` for plain-language uncertainty; do not add workflow markers that imply external API validation.

## Editorial Risk

Mark `Editorial: yes` conservatively when the image visibly includes material such as:

- identifiable people without confirmed releases
- recognizable brands, products, logos, or packaging
- readable signs, place markers, or branded text
- copyrighted artwork, murals, or graffiti
- distinctive private property or interiors with unclear rights
- event coverage, protests, performances, or documentary scenes

When `Editorial: yes`:

- Use Shutterstock dateline description format: `CITY, STATE/COUNTRY - MONTH DAY, YEAR: factual sentence describing the subject matter.`
- If any documentary fact is unknown, keep the dateline format and use bracketed placeholders such as `[City], [Country] - [Month Day, Year]:`.
- Keep the sentence factual, neutral, and non-promotional.
- Do not invent city, country, event, or date details.
