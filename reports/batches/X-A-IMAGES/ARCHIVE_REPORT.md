# X-A-IMAGES archive report

- Status: COMPLETED
- Gate status: ACCEPTED
- Delivered by: Zack
- Delivered at: 2026-09-12
- Injection pairs: NOT_STARTED, unchanged in the manifest
- Blockers: none

## Source-to-target mappings

| Source | Target | Bytes | Expected SHA-256 | Archive-commit blob SHA-256 | Copy mode |
| --- | --- | ---: | --- | --- | --- |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/assets/evidence-inbox/s00001-product-overview.jpg | frontend/public/evidence/s00001-product-overview.jpg | 71574 | E2C6BBD230F906F113D75F2F582E778B6E79AEA37544C2383F1FFDA15A5295D5 | E2C6BBD230F906F113D75F2F582E778B6E79AEA37544C2383F1FFDA15A5295D5 | COPY_VERBATIM |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/assets/evidence-inbox/s00001-pump-detail.jpg | frontend/public/evidence/s00001-pump-detail.jpg | 66764 | 4709D7529803846D4FF4E123BFCC034D420449AE23923CB54468BE573BD8CFC7 | 4709D7529803846D4FF4E123BFCC034D420449AE23923CB54468BE573BD8CFC7 | COPY_VERBATIM |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/assets/evidence-inbox/s00001-package-context.jpg | frontend/public/evidence/s00001-package-context.jpg | 129230 | C734BFB5A70FFA39E10B2535DC8321EACE3C1FB358293FA22B590B9F7B5836BD | C734BFB5A70FFA39E10B2535DC8321EACE3C1FB358293FA22B590B9F7B5836BD | COPY_VERBATIM |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/assets/evidence-inbox/s00001-gift-evidence.jpg | frontend/public/evidence/s00001-gift-evidence.jpg | 130254 | E52DF258CDBC5761D175F31985639337F2274211FBEB3DDB82A0B773150AA7F5 | E52DF258CDBC5761D175F31985639337F2274211FBEB3DDB82A0B773150AA7F5 | COPY_VERBATIM |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/assets/evidence-inbox/s00001-blurred-pump.jpg | frontend/public/evidence/s00001-blurred-pump.jpg | 55664 | 634D2B4B0665FAE49DEC286628B13D8116808B3FFF7A39A9DD7CDEA9E7DE3143 | 634D2B4B0665FAE49DEC286628B13D8116808B3FFF7A39A9DD7CDEA9E7DE3143 | COPY_VERBATIM |
| C:/Users/WONG Tsun Ming/Desktop/欧莱雅黑客松/handoff/a/images-manifest.json | handoff/a/images-manifest.json | 9233 | 4D596C87F3483166915E25A0F250292FA9CCE1A654463C09DBFC0EF97310352E | 4D596C87F3483166915E25A0F250292FA9CCE1A654463C09DBFC0EF97310352E | COPY_VERBATIM |

## Hash method

- Source hashes are SHA-256 over raw source-file bytes.
- Final target evidence is SHA-256 over raw bytes emitted by git show <archive_sha>:<target>.
- No source or target is text-decoded, re-encoded, formatted, or newline-normalized. Working-tree comparisons were byte-for-byte before commit; working-tree hashes are not used as final evidence.

## Scope audit

Changed files:

- frontend/public/evidence/s00001-product-overview.jpg
- frontend/public/evidence/s00001-pump-detail.jpg
- frontend/public/evidence/s00001-package-context.jpg
- frontend/public/evidence/s00001-gift-evidence.jpg
- frontend/public/evidence/s00001-blurred-pump.jpg
- handoff/a/images-manifest.json
- reports/batches/X-A-IMAGES/ARCHIVE_REPORT.json
- reports/batches/X-A-IMAGES/ARCHIVE_REPORT.md

Violations: none.

## Handoff notes

All five signed-off images and the manifest were archived with COPY_VERBATIM. No BATCH was started or modified.
