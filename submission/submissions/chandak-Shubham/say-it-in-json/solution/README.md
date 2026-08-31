# PipelineForge Config Migration Harness (`solution/`)

This directory contains the migration converter, JSON schema, reference evaluator, equivalence verifier, and CLI harness for migrating legacy PipelineForge `.pfcfg` configuration files to JSON.

---

## Quick Start (Reviewer Workflow)

To execute the complete migration workflow in **less than 1 minute**:

```bash
cd submissions/chandak-Shubham/say-it-in-json/solution
python run.py
```

### What to Expect:
When invoked, `run.py` executes an automated 5-step pipeline across all sample configurations in `starter/configs/`:
1. **Conversion**: Parses `.pfcfg` files into JSON format matching `schema.json`.
2. **Schema Validation**: Validates converted JSON structures.
3. **Evaluation**: Computes effective settings for both `.pfcfg` and JSON across 5 environment fixtures.
4. **Equivalence Verification**: Compares effective settings dictionaries to check for matching outputs.
5. **Report Generation**: Exports machine-readable unmigratable items to `unmigratable_report.json`.

---

## 1. File Responsibilities

| File | Responsibility |
| --- | --- |
| `schema.json` | JSON Schema (Draft 2020-12) defining the target JSON format (`version`, `imports`, `sections`, `overrides`). |
| `converter.py` | Parser and converter that transforms `.pfcfg` files into JSON structures conforming to `schema.json`. |
| `evaluator.py` | Reference evaluation engines (`PFCfgEvaluator` and `JSONEvaluator`) that resolve imports, conditionals, and interpolations into effective settings. |
| `verifier.py` | Equivalence verification engine (`EquivalenceVerifier`) that compares `.pfcfg` vs. JSON effective settings across multi-environment fixtures. |
| `run.py` | Complete workflow CLI entry point orchestrating conversion, evaluation, verification, and unmigratable reporting. |
| `unmigratable_report.json` | Machine-readable JSON output containing items that cannot be resolved automatically (e.g. missing environment variables or circular references). |

---

## 2. Prerequisites & Setup

- **Python**: Python 3.8+ (uses standard library modules: `json`, `re`, `argparse`, `pathlib`, `glob`).
- **Dependencies**: Zero mandatory third-party dependencies required.
- **Schema Validation**: `converter.py` provides `validate_converted_json()`, which uses built-in version assertions by default. If the `jsonschema` package is installed (`pip install jsonschema`), it additionally performs full draft-2020-12 JSON Schema validation.

---

## 3. Usage & CLI Options

### Run Default Workflow
To process all starter configurations (`starter/configs/`):

```bash
python run.py
```

### Run on a Specific File or Directory
To run the harness on a specific `.pfcfg` file or custom directory:

```bash
# Single configuration file
python run.py --target starter/configs/customers/globex/pipeline.pfcfg

# Specific directory
python run.py --target starter/configs/customers/globex/
```

*(You can also invoke `python verifier.py [path/to/config.pfcfg]` directly to run only the verification CLI.)*

---

## 4. Effective Settings & Equivalence Concept

- **Effective Settings**: The final, flattened dictionary of section key-value pairs produced after:
  - Recursively expanding `@include` and `@include_once` file imports.
  - Evaluating conditional blocks (`@ifdef`, `@ifndef`, `when`) against target environment variables.
  - Sequentially applying section overrides.
  - Interpolating environment variable defaults (`${VAR:-default}`) and cross-key references (`$(sec.key)`).
- **Equivalence**: Evaluated when comparing legacy `.pfcfg` settings against converted JSON settings. A configuration is considered equivalent if evaluating both paths under identical environment variable fixtures yields identical effective settings for the tested environment fixtures.

---

## 5. Environment Fixtures

The verifier evaluates each configuration against 5 built-in environment variable fixtures:

1. `CI Environment (CI=true)`: `{"CI": "true"}`
2. `Non-CI Environment (CI unset)`: `{}`
3. `Production Environment`: `{"PRODUCTION": "true", "CI": "true"}`
4. `Vault & Beta Environment`: `{"VAULT_ADDR": "https://vault.example.invalid", "FEATURE_BETA": "true", "SLACK_WEBHOOK": "https://hooks.slack.com"}`
5. `Full Environment (with secrets & endpoints)`: `{"CI": "true", "PRODUCTION": "true", "VAULT_ADDR": "https://vault.example.invalid", "FEATURE_BETA": "true", "REQUIRED_SIGNING_SECRET": "<test-secret>", "REQUIRED_API_ENDPOINT": "https://api.example.invalid"}`

---

## 6. Verification Status Definitions

- **`[ PASS ]`**: Effective settings match between legacy `.pfcfg` and JSON with zero unmigratable errors or unresolvable variables for the tested fixture.
- **`[ UNMIGRATABLE ]`**: Effective settings match structurally between `.pfcfg` and JSON, but unresolvable elements exist (e.g., missing mandatory environment variables without default values, or circular references).
- **`[ FAIL ]`**: A setting value mismatch exists between `.pfcfg` and JSON, or a conversion/parsing error occurred.

---

## 7. Unmigratable Report (`unmigratable_report.json`)

The unmigratable report is generated at `unmigratable_report.json`. It captures all unresolvable keys in a machine-readable JSON array:

```json
[
  {
    "file": "starter/configs/customers/initech/pipeline.pfcfg",
    "section": "signing",
    "key": "key_material",
    "reason": "Unresolved environment variable '${REQUIRED_SIGNING_SECRET}' — variable is unset and has no default value"
  }
]
```

Each entry contains `file` (workspace-relative path), `section`, `key`, and `reason` (`line` if available).
