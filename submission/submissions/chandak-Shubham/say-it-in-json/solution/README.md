# PipelineForge Config Migration Harness (`solution/`)

This folder contains my solution for migrating PipelineForge `.pfcfg` configuration files to JSON. It includes converter, JSON schema,  evaluator,  verifier and the `run.py` which is used to run the complete migration and this checking workkflow. 

---

## Quick Start 

From the repository root, run:

```bash
cd submissions/chandak-Shubham/say-it-in-json/solution
python run.py
``` 

---

## 1. File Responsibilities

| File | Responsibility |
|------|----------------|
| `schema.json` | Defines the JSON structure expected after conversion. |
| `converter.py` | Parses legacy `.pfcfg` files and converts them into the JSON representation. |
| `evaluator.py` | Evaluates both `.pfcfg` and JSON configurations to produce effective settings. |
| `verifier.py` | Compares the effective settings from the old format to new JSON configurations across environment fixtures. |
| `run.py` | Runs the complete conversion, validation, evaluation, verification, and reporting workflow. |
| `unmigratable_report.json` | Generated report listing configuration items that could not be resolved automatically. |

---

## 2. Prerequisites & Setup

- **Python**: Python 3.8+ or newer
- **Dependencies**: No third-party dependencies required
- **Schema Validation**: `converter.py` provides `validate_converted_json()`, which uses built-in version assertions by default. If the `jsonschema` package is installed (`pip install jsonschema`).

---

## 3. Usage & CLI Options

### Run the Complete Workflow

From the `solution/` directory:

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


---

## 4. Effective Settings & Equivalence

By "effective settings", I mean the final values that are obtained after all the rules in a `.pfcfg` file have been processed.

The evaluator handles things like:

- `@include` and `@include_once` files.
- Conditions such as `@ifdef`, `@ifndef`, and `when`.
- Overrides between sections.
- Environment variables such as `${VAR}` and `${VAR:-default}`.
- References to other keys such as `$(section.key)`.

For equivalence, I wanted to check that the conversion to JSON does not change the actual result of the configuration.

So, for each environment fixture, the original `.pfcfg` file and the converted JSON are evaluated separately using the same environment variables. Their final settings are then compared key by key.

If both produce the same settings, I consider the conversion equivalent for that test environment.

---

## 5. Environment Fixtures

The verifier tests the configurations with a few different environment setups. I used these to cover the main conditional and environment-variable cases in the sample configurations.

The five fixtures are:

1. **CI Environment** — `CI=true`
2. **Non-CI Environment** — no `CI` variable is set
3. **Production Environment** — `PRODUCTION=true` and `CI=true`
4. **Vault & Beta Environment** — includes `VAULT_ADDR`, `FEATURE_BETA`, and `SLACK_WEBHOOK`
5. **Full Environment** — includes the above variables as well as the required signing secret and API endpoint.

Using different fixtures is useful because a configuration can behave differently depending on which environment variables are available. It also lets the verifier check that the converted JSON behaves the same way as the original `.pfcfg` under different conditions.

---

## 6. Verification Status

The verifier gives each test one of three results:

- **`[ PASS ]`**: The original `.pfcfg` and the converted JSON produce the same effective settings, and there are no unresolved variables or references.

- **`[ UNMIGRATABLE ]`**: The original and converted configurations still behave the same, but some value could not be resolved in that environment. For example, a required environment variable may not be set, or there may be a circular reference between keys.

- **`[ FAIL ]`**: The two configurations produce different results, or there is an error while parsing or evaluating the configuration.

I kept `UNMIGRATABLE` separate from `FAIL` because an unresolved value does not necessarily mean that the conversion itself changed the configuration. It is useful to report these cases separately so they can be fixed or checked later.
---

## 7. Unmigratable Report

Some configurations cannot be fully resolved in every environment. For example, a required environment variable may be missing or two configuration keys may refer to each other and create a circular reference.

Instead of treating these cases as normal failures, the verifier records them separately in `unmigratable_report.json`. This makes it easier to see which parts of the configuration need attention.

The report contains the file, section, key, and reason for each unresolved item. For example:

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
