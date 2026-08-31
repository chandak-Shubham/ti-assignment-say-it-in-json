# Decisions — Say It in JSON

## 1. JSON Schema Design & Tradeoffs

I kept the JSON structure close to the way the original `.pfcfg` files are organised. The main parts are `imports`, `sections`, and `overrides`, along with a `version` field.

One important choice was to keep expressions such as `${VAR:-default}` and `$(section.key)` in the converted JSON instead of resolving them during conversion. The actual environment may not be known at conversion time, so resolving them later allows the same JSON configuration to work with different environments.

I also kept normal values as their actual JSON types where possible, such as booleans and numbers, instead of converting everything to strings. Values containing interpolation expressions are kept as strings so that they can be resolved by the evaluator later.

The main tradeoff is that the JSON is not completely self-contained after conversion. It still needs the evaluator and the target environment to resolve these expressions but this keeps the behaviour of the original configuration.

## 2. Effective Settings & Verification

By "effective settings", I mean the final configuration values after all the rules in the original `.pfcfg` file have been processed.

This includes:

- Processing `@include` and `@include_once` files.
- Checking conditions such as `@ifdef`, `@ifndef`, and `when`.
- Applying the defined overrides.
- Resolving environment variables such as `${VAR}` and `${VAR:-default}`.
- Resolving references to other configuration keys such as `$(section.key)`.

To check that the conversion did not change the behaviour of a configuration, I evaluate both the original `.pfcfg` file and the converted JSON using the same environment fixture.

The verifier then compares their final effective settings. If the values and keys match, the conversion is considered equivalent for that environment.

I tested this across the environment fixtures provided in the verifier rather than checking only one environment.

## 3. What the Verifier Proves & Does Not Prove

The verifier checks whether the converted JSON produces the same effective settings as the original `.pfcfg` for the environment fixtures that I tested.

### What it proves

- The converted JSON matches the original configuration for the tested environment fixtures when their effective settings are the same.
- Differences between the two configurations are reported as `FAIL`.
- Cases where values cannot be resolved, such as missing required environment variables or circular references, are reported separately as `UNMIGRATABLE`.

### What it does not prove

- It does not prove equivalence for every possible environment. Only the environment fixtures used by the verifier are tested.
- It does not prove that formatting, comments or the original line structure are preserved in the JSON.
- Passing the current fixtures does not guarantee that a new or unusual `.pfcfg` configuration will always convert correctly.

This is why I treat the verifier as a practical equivalence check for the tested cases rather than a proof that the converter works for every possible configuration.

## 4. Known Gaps

There are a few areas that I would improve with more time:

- The `unmigratable_report.json` identifies the file, section, and key, but it does not currently give the exact source line from the original `.pfcfg` file.
- The evaluator does not handle every possible form of nested or dynamically constructed environment-variable expansion.
- The verifier only checks the environment fixtures that are currently defined, so additional environment combinations could still reveal cases that are not covered by the tests.
