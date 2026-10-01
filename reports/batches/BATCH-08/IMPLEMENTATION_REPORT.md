# BATCH-08 implementation report — repair attempt 3

Status: `COMPLETED` / `IMPLEMENTED` for the authorized implementation repair only. This is not an independent verification PASS and not an integration receipt.

This round repaired only `B08-F01` from verification report `bce2c606a03ea3c0f6d2d588600d7ed66b1799c7`. The JPEG probe now records DQT/DHT definitions and checks SOF quantization selectors plus SOS DC/AC Huffman selectors before `ProviderImageInput` construction. Missing DQT and missing DHT are permanent negative tests. Each uses the same malformed bytes under two filenames and asserts the same coded rejection, zero provider dispatch calls, and zero `ProviderImageInput` constructions.

Evidence:

- Repair commit: `d06754cfd8974164e1ba87aa00695d033877b743`
- Tests: `14 passed`; focused DQT/DHT negatives: `2 passed`
- Ruff: passed
- Pip check: exit `0`, `No broken requirements found.`
- Real-image probe: `5/5` resolved, existing hashes/dimensions/byte lengths matched, no model call
- Interpreter: `C:\\cov-run\\batch-08-repair-1\\venv\\Scripts\\python.exe`
- `sys.prefix`: `C:\\cov-run\\batch-08-repair-1\\venv`
- Longest venv path: `165 < 250`
- `requirements-dev.lock`: unchanged; no dependency added
- Plan hashes: raw `git show` from `integration/covenia-b` commit `190d8c884b912103d799441d50213d192e6b4d78`

Independent verification remains pending. No `VERIFICATION_REPORT.json`, verification evidence, integration merge, or push was performed.
