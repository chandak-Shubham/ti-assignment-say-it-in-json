#!/usr/bin/env python3
"""
PipelineForge Migration Harness CLI Entry Point (run.py)

Executes the complete migration workflow:
  1. Conversion: Converts legacy .pfcfg files into JSON format matching schema.json.
  2. Evaluation: Evaluates effective settings for both legacy .pfcfg and target JSON trees.
  3. Verification: Assesses equivalence across multiple environment fixtures.
  4. Report Generation: Exports machine-readable unmigratable_report.json.
"""

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Import existing modules without modifying them
from converter import convert_pfcfg_file, validate_converted_json
from evaluator import evaluate_json, evaluate_pfcfg
from verifier import EquivalenceVerifier, find_workspace_root


def run_pipeline(target_path: Optional[str] = None) -> int:
    """Executes the full conversion, evaluation, verification, and reporting workflow."""
    solution_dir = Path(__file__).parent.resolve()
    workspace_root = find_workspace_root(solution_dir)
    schema_path = solution_dir / "schema.json"

    # Determine files to process
    if target_path:
        tp = Path(target_path).resolve()
        if tp.is_file():
            config_files = [str(tp)]
        elif tp.is_dir():
            config_files = sorted(glob.glob(str(tp / "**" / "*.pfcfg"), recursive=True))
        else:
            print(f"Error: Target path '{target_path}' does not exist.")
            return 1
    else:
        starter_dir = workspace_root / "starter" / "configs"
        if starter_dir.exists():
            config_files = sorted(glob.glob(str(starter_dir / "**" / "*.pfcfg"), recursive=True))
        else:
            print("Error: Could not find starter/configs directory.")
            return 1

    if not config_files:
        print("No .pfcfg configuration files found.")
        return 1

    print("================================================================================")
    print("             PIPELINEFORGE MIGRATION & EQUIVALENCE HARNESS CLI                  ")
    print("================================================================================")
    print(f"  Target Workspace Root : {workspace_root}")
    print(f"  Schema Location       : {schema_path}")
    print(f"  Files to Process      : {len(config_files)}")
    print("================================================================================\n")

    # Step 1: Conversion Verification
    print("--------------------------------------------------------------------------------")
    print("  STEP 1: CONVERSION (.pfcfg -> JSON Schema Validation)")
    print("--------------------------------------------------------------------------------")
    conversion_successes = 0
    converted_cache: Dict[str, dict] = {}

    for cfg_path in config_files:
        rel_file = cfg_path
        try:
            rel_file = str(Path(cfg_path).relative_to(workspace_root)).replace("\\", "/")
        except Exception:
            pass

        try:
            data = convert_pfcfg_file(cfg_path)
            valid = validate_converted_json(data, schema_path) if schema_path.exists() else True
            if valid:
                conversion_successes += 1
                converted_cache[cfg_path] = data
                print(f"  [ OK ] {rel_file} -> Version {data.get('version', 1)} JSON")
            else:
                print(f"  [FAIL] {rel_file} -> Schema Validation Error")
        except Exception as e:
            print(f"  [ERR ] {rel_file} -> Conversion Error: {e}")

    print(f"\n  Conversion Summary: {conversion_successes}/{len(config_files)} files successfully converted to JSON.\n")

    # Step 2 & 3: Evaluation & Equivalence Verification
    print("--------------------------------------------------------------------------------")
    print("  STEP 2 & 3: EVALUATION & EQUIVALENCE VERIFICATION ACROSS FIXTURES")
    print("--------------------------------------------------------------------------------")

    verifier = EquivalenceVerifier()
    results = verifier.verify_all(config_files)

    files_map = {}
    for r in results:
        files_map.setdefault(r.config_file, []).append(r)

    for cfg_file, file_results in files_map.items():
        rel_file = cfg_file
        try:
            rel_file = str(Path(cfg_file).relative_to(workspace_root)).replace("\\", "/")
        except Exception:
            pass

        print(f"\nConfig: {rel_file}")
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

    # Step 4: Report Generation
    print("\n--------------------------------------------------------------------------------")
    print("  STEP 4: UNMIGRATABLE REPORT GENERATION")
    print("--------------------------------------------------------------------------------")

    report_path = solution_dir / "unmigratable_report.json"
    report_items = verifier.generate_unmigratable_report(results, report_path)
    print(f"  Generated machine-readable report: {report_path}")
    print(f"  Captured {len(report_items)} unique unmigratable items.\n")

    # Step 5: Final Summary Block
    total_runs = len(results)
    pass_runs = sum(1 for r in results if r.status == "PASS")
    unmig_runs = sum(1 for r in results if r.status == "UNMIGRATABLE")
    fail_runs = sum(1 for r in results if r.status == "FAIL")

    print("================================================================================")
    print("                         WORKFLOW SUMMARY REPORT                                ")
    print("================================================================================")
    print(f"  Files Processed                  : {len(config_files)}")
    print(f"  Files Successfully Converted     : {conversion_successes}/{len(config_files)}")
    print(f"  Total Equivalence Test Runs      : {total_runs}")
    print(f"  Passed (100% Equivalent) Runs    : {pass_runs}")
    print(f"  Unmigratable (Contains Errors)   : {unmig_runs}")
    print(f"  Failed (Mismatched) Runs         : {fail_runs}")
    print(f"  Unique Unmigratable Items        : {len(report_items)}")
    print(f"  Unmigratable Report Location     : {report_path}")
    print("================================================================================\n")

    if fail_runs > 0:
        print("RESULT: WORKFLOW COMPLETED WITH MISMATCH ERRORS.")
        return 1
    else:
        print("RESULT: WORKFLOW COMPLETED SUCCESSFULLY WITH 0 MISMATCHES.")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="PipelineForge Migration Harness: Converter, Evaluator, and Verifier CLI"
    )
    parser.add_argument(
        "--target",
        "-t",
        type=str,
        default=None,
        help="Path to a specific .pfcfg file or directory containing configs (default: starter/configs)"
    )

    args = parser.parse_args()
    sys.exit(run_pipeline(args.target))


if __name__ == "__main__":
    main()
