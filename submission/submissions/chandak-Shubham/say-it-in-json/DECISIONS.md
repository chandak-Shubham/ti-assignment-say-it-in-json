# Decisions — Say It in JSON

## 1. JSON Schema Design & Tradeoffs
The schema (`schema.json`) models `.pfcfg` configurations as a structured JSON tree (`version: 1`) containing `imports`, `sections`, and `overrides`.

- **Core Rationale:** Preserved raw interpolation expressions (`${VAR:-default}`, `$(section.key)`) and conditional `when` blocks in JSON rather than pre-resolving them during conversion. This decision ensures environment variables—which are only known at deployment time—can be evaluated dynamically in the target environment.
- **Tradeoffs:** Kept non-evaluated interpolation tokens as raw strings while preserving typed primitives (booleans, numbers) where literal values exist. This shifts interpolation logic to the JSON evaluator while maintaining multi-environment deployment portability.

## 2. Effective Settings & Verification
- **Definition:** "Effective settings" refers to the fully evaluated, section-grouped dictionary produced after:
  1. Recursively merging `@include` / `@include_once` imports.
  2. Evaluating conditional blocks (`@ifdef`, `@ifndef`, `when`) against target deployment environment variables.
  3. Sequentially applying section overrides.
  4. Resolving `${VAR}` environment defaults and `$(sec.key)` cross-references.
- **Verification:** Evaluated both legacy `.pfcfg` trees and converted JSON trees using dual evaluation engines in `evaluator.py`. `verifier.py` runs both against multiple environment fixtures and checks for key-value identity across tested environments.

## 3. What the Verifier Proves & Does Not Prove
- **Proves:**
  - **Semantic Equivalence for Tested Fixtures:** Converted JSON files yield identical effective settings to legacy `.pfcfg` trees for valid configurations across defined test fixtures.
  - **Refined Status Reporting:** Initially, treating unmigratable configs (missing required env vars or circular references) as a standard `PASS` proved misleading. I separated verification outcomes into three explicit statuses: **`PASS`** (equivalent with zero errors), **`UNMIGRATABLE`** (equivalent settings structure, but contains unresolvable env vars/keys), and **`FAIL`** (settings mismatch or parsing errors).
- **Does Not Prove:**
  - **Unlisted Environments:** Does not guarantee equivalence for unlisted, untested environment variable combinations.
  - **Source Syntax & Comments:** Line indices and comments are omitted during conversion.

## 4. Known Gaps
- **Error Line Numbers:** `unmigratable_report.json` isolates the failing section and key name, but does not capture the original line number in `.pfcfg`.
- **Nested Env Expansion:** Dynamic inner variable references (e.g. `${PREFIX_${ENV}}`) are not recursively expanded in single-pass evaluation.

## 5. What to Build Next (4 More Hours)
- **AST Source Line Mapping:** Attach original file line numbers to AST key nodes during conversion for precise error reporting.
- **Interactive Migration CLI:** Implement a CLI tool to automatically suggest default values (e.g., `${VAR:-default}`) for unmigratable keys.
- **CI Verification Hook:** Add pre-commit/CI pipeline runners to validate newly written JSON configs against `schema.json`.
