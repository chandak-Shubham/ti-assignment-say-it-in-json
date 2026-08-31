import glob
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Import converter and evaluator without modifying them
from converter import convert_pfcfg_file
from evaluator import (
    EvaluationResult,
    JSONEvaluator,
    PFCfgEvaluator,
    UnmigratableItem,
    evaluate_json,
    evaluate_pfcfg,
)


@dataclass
class EquivalenceResult:
    """Result of equivalence verification for a single configuration file under an environment fixture."""
    config_file: str
    fixture_name: str
    is_equivalent: bool
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    unmigratable_items: List[UnmigratableItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """
        Returns one of:
        - PASS: Settings match 100% with zero unmigratable items or errors.
        - UNMIGRATABLE: Settings match, but unresolvable keys present (missing env vars or circular refs).
        - FAIL: Settings mismatch or conversion/evaluation error.
        """
        if not self.is_equivalent or len(self.mismatches) > 0 or len(self.errors) > 0:
            return "FAIL"
        if len(self.unmigratable_items) > 0:
            return "UNMIGRATABLE"
        return "PASS"


class EquivalenceVerifier:
    """Verification engine that compares legacy .pfcfg effective settings against JSON effective settings."""

    DEFAULT_FIXTURES = {
        "CI Environment (CI=true)": {"CI": "true"},
        "Non-CI Environment (CI unset)": {},
        "Production Environment": {"PRODUCTION": "true", "CI": "true"},
        "Vault & Beta Environment": {
            "VAULT_ADDR": "https://vault.example.invalid",
            "FEATURE_BETA": "true",
            "SLACK_WEBHOOK": "https://hooks.slack.com",
        },
        "Full Environment (with secrets & endpoints)": {
            "CI": "true",
            "PRODUCTION": "true",
            "VAULT_ADDR": "https://vault.example.invalid",
            "FEATURE_BETA": "true",
            "REQUIRED_SIGNING_SECRET": "secret_key_12345",
            "REQUIRED_API_ENDPOINT": "https://api.example.invalid",
        },
    }

    def __init__(self, fixtures: Optional[Dict[str, Dict[str, str]]] = None):
        self.fixtures = fixtures if fixtures is not None else self.DEFAULT_FIXTURES

    def verify_single_config(
        self,
        config_path: Union[str, Path],
        env: Dict[str, str],
        fixture_name: str
    ) -> EquivalenceResult:
        p = Path(config_path).resolve()

        # 1. Legacy Evaluation
        res_pfcfg = evaluate_pfcfg(p, env=env)

        # 2. Conversion to JSON
        try:
            json_data = convert_pfcfg_file(p)
        except Exception as e:
            return EquivalenceResult(
                config_file=str(p),
                fixture_name=fixture_name,
                is_equivalent=False,
                errors=[f"Conversion failed: {e}"]
            )

        # 3. Target JSON Evaluation
        res_json = evaluate_json(json_data, base_dir=p.parent, env=env)

        # 4. Compare Settings
        mismatches = self._diff_settings(res_pfcfg.settings, res_json.settings)

        # 5. Collect Unmigratable Items (deduplicated)
        unmigratable_map: Dict[Tuple[str, str, str], UnmigratableItem] = {}
        for item in res_pfcfg.unmigratable_items + res_json.unmigratable_items:
            key_tuple = (item.file if item.file else str(p), item.section, item.key)
            if key_tuple not in unmigratable_map:
                unmigratable_map[key_tuple] = item

        is_equivalent = (len(mismatches) == 0) and (res_pfcfg.errors == res_json.errors)

        return EquivalenceResult(
            config_file=str(p),
            fixture_name=fixture_name,
            is_equivalent=is_equivalent,
            mismatches=mismatches,
            unmigratable_items=list(unmigratable_map.values()),
            errors=res_pfcfg.errors + res_json.errors
        )

    def _diff_settings(
        self,
        legacy_settings: Dict[str, Dict[str, Any]],
        json_settings: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        mismatches = []

        all_sections = set(legacy_settings.keys()) | set(json_settings.keys())
        for sec in sorted(all_sections):
            if sec not in legacy_settings:
                mismatches.append({
                    "section": sec,
                    "reason": f"Section '{sec}' present in JSON but missing in legacy settings"
                })
                continue
            if sec not in json_settings:
                mismatches.append({
                    "section": sec,
                    "reason": f"Section '{sec}' present in legacy settings but missing in JSON"
                })
                continue

            sec_legacy = legacy_settings[sec]
            sec_json = json_settings[sec]
            all_keys = set(sec_legacy.keys()) | set(sec_json.keys())

            for k in sorted(all_keys):
                if k not in sec_legacy:
                    mismatches.append({
                        "section": sec,
                        "key": k,
                        "reason": f"Key '{k}' present in JSON but missing in legacy settings"
                    })
                elif k not in sec_json:
                    mismatches.append({
                        "section": sec,
                        "key": k,
                        "reason": f"Key '{k}' present in legacy settings but missing in JSON"
                    })
                elif sec_legacy[k] != sec_json[k]:
                    mismatches.append({
                        "section": sec,
                        "key": k,
                        "legacy_value": sec_legacy[k],
                        "json_value": sec_json[k],
                        "reason": f"Value mismatch for '{sec}.{k}': legacy '{sec_legacy[k]}' vs JSON '{sec_json[k]}'"
                    })

        return mismatches

    def verify_all(self, config_paths: List[Union[str, Path]]) -> List[EquivalenceResult]:
        results = []
        for path in config_paths:
            for fixture_name, env in self.fixtures.items():
                res = self.verify_single_config(path, env, fixture_name)
                results.append(res)
        return results

    def generate_unmigratable_report(
        self,
        results: List[EquivalenceResult],
        output_file: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        unique_items: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        workspace_root = find_workspace_root(Path(output_file).parent)

        for res in results:
            for item in res.unmigratable_items:
                raw_file = item.file if item.file else res.config_file
                try:
                    file_rel = str(Path(raw_file).relative_to(workspace_root)).replace("\\", "/")
                except Exception:
                    file_rel = str(Path(raw_file)).replace("\\", "/")

                key_tuple = (file_rel, item.section, item.key)
                if key_tuple not in unique_items:
                    entry = item.to_dict()
                    entry["file"] = file_rel
                    unique_items[key_tuple] = entry

        report_data = list(unique_items.values())

        out_path = Path(output_file)
        out_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        return report_data


def find_workspace_root(start_dir: Path) -> Path:
    curr = start_dir.resolve()
    while curr != curr.parent:
        if (curr / "starter" / "configs").exists():
            return curr
        curr = curr.parent
    return start_dir.resolve()


def run_verification_cli(config_paths: Optional[List[str]] = None) -> int:
    """Runs the equivalence verifier CLI against specified config paths or default starter configs."""
    solution_dir = Path(__file__).parent.resolve()
    workspace_root = find_workspace_root(solution_dir)

    if not config_paths:
        starter_dir = workspace_root / "starter" / "configs"
        if starter_dir.exists():
            config_paths = sorted(glob.glob(str(starter_dir / "**" / "*.pfcfg"), recursive=True))
        else:
            config_paths = []

    if not config_paths:
        print("No .pfcfg configuration files found to verify.")
        return 1

    verifier = EquivalenceVerifier()
    print("================================================================================")
    print("           PIPELINEFORGE EQUIVALENCE VERIFIER & MIGRATION HARNESS               ")
    print("================================================================================\n")

    results = verifier.verify_all(config_paths)

    total_runs = len(results)
    pass_runs = sum(1 for r in results if r.status == "PASS")
    unmig_runs = sum(1 for r in results if r.status == "UNMIGRATABLE")
    fail_runs = sum(1 for r in results if r.status == "FAIL")

    # Group output by file
    files_map: Dict[str, List[EquivalenceResult]] = {}
    for r in results:
        files_map.setdefault(r.config_file, []).append(r)

    for cfg_file, file_results in files_map.items():
        rel_file = cfg_file
        try:
            rel_file = str(Path(cfg_file).relative_to(workspace_root)).replace("\\", "/")
        except Exception:
            pass

        print(f"Config: {rel_file}")
        for r in file_results:
            if r.status == "PASS":
                status_str = "[ PASS ]        "
            elif r.status == "UNMIGRATABLE":
                status_str = "[ UNMIGRATABLE ]"
            else:
                status_str = "[ FAIL ]        "

            print(f"  {status_str} {r.fixture_name}")

            if r.status == "FAIL":
                for m in r.mismatches:
                    print(f"                   -> MISMATCH: {m['reason']}")
                for err in r.errors:
                    print(f"                   -> ERROR: {err}")

            if r.unmigratable_items:
                for item in r.unmigratable_items:
                    print(f"                   -> UNRESOLVED [{item.section}.{item.key}]: {item.reason}")
        print()

    # Generate Unmigratable Report
    report_path = solution_dir / "unmigratable_report.json"
    report_items = verifier.generate_unmigratable_report(results, report_path)

    print("================================================================================")
    print("                              SUMMARY REPORT                                    ")
    print("================================================================================")
    print(f"  Total Configuration Files Tested : {len(files_map)}")
    print(f"  Total Verification Runs          : {total_runs}")
    print(f"  Passed (100% Equivalent) Runs    : {pass_runs}")
    print(f"  Unmigratable (Contains Errors)   : {unmig_runs}")
    print(f"  Failed (Mismatched) Runs         : {fail_runs}")
    print(f"  Unique Unmigratable Items        : {len(report_items)}")
    print(f"  Machine-Readable Report Saved    : {report_path}")
    print("================================================================================\n")

    return 0 if fail_runs == 0 else 1


if __name__ == "__main__":
    paths = sys.argv[1:] if len(sys.argv) > 1 else None
    sys.exit(run_verification_cli(paths))
