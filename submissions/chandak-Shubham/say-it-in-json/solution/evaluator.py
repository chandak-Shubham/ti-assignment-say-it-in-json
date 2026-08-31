import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Import converter without modifying it
from converter import convert_pfcfg_file


@dataclass
class UnmigratableItem:
    """Represents a configuration item that cannot be resolved or migrated automatically."""
    file: str
    section: str
    key: str
    reason: str
    line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "file": self.file,
            "section": self.section,
            "key": self.key,
            "reason": self.reason
        }
        if self.line is not None:
            result["line"] = self.line
        return result


class EvaluationError(Exception):
    """Base exception for configuration evaluation errors."""
    pass


class UnmigratableError(EvaluationError):
    """Raised when a key cannot be resolved due to missing required env vars or missing keys."""
    def __init__(self, message: str, section: str = "", key: str = ""):
        super().__init__(message)
        self.message = message
        self.section = section
        self.key = key


class CircularReferenceError(EvaluationError):
    """Raised when a circular cross-key reference is detected."""
    def __init__(self, message: str, section: str = "", key: str = ""):
        super().__init__(message)
        self.message = message
        self.section = section
        self.key = key


@dataclass
class EvaluationResult:
    """Holds the result of evaluating a configuration tree under a given environment."""
    file: str
    settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    unmigratable_items: List[UnmigratableItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.unmigratable_items) == 0 and len(self.errors) == 0


def is_env_set(var_name: str, env: Dict[str, str]) -> bool:
    """Returns True if var_name is present in env and non-empty."""
    return var_name in env and bool(env[var_name])


def is_env_unset(var_name: str, env: Dict[str, str]) -> bool:
    """Returns True if var_name is absent from env or empty."""
    return var_name not in env or not bool(env[var_name])


def evaluate_condition(cond: Dict[str, str], env: Dict[str, str]) -> bool:
    """Evaluates a condition dict with env_set or env_unset against env."""
    if "env_set" in cond:
        return is_env_set(cond["env_set"], env)
    if "env_unset" in cond:
        return is_env_unset(cond["env_unset"], env)
    return True


def evaluate_cond_stack(cond_stack: List[Dict[str, str]], env: Dict[str, str]) -> bool:
    """Evaluates whether all conditions in a stack are satisfied."""
    return all(evaluate_condition(cond, env) for cond in cond_stack)


class Interpolator:
    """Resolves environment variables and cross-key references in configuration settings."""

    def __init__(self, settings: Dict[str, Dict[str, Any]], env: Optional[Dict[str, str]] = None):
        self.settings = settings
        self.env = env if env is not None else {}

    def resolve_all(self, source_file: str = "") -> Tuple[Dict[str, Dict[str, Any]], List[UnmigratableItem]]:
        """
        Resolves all string values in settings.
        Returns a tuple of (resolved_settings, unmigratable_items).
        """
        resolved: Dict[str, Dict[str, Any]] = {}
        unmigratable_items: List[UnmigratableItem] = []

        for section_name, section_dict in self.settings.items():
            resolved[section_name] = {}
            for key, raw_val in section_dict.items():
                if not isinstance(raw_val, str):
                    resolved[section_name][key] = raw_val
                    continue

                active_stack: Set[Tuple[str, str]] = {(section_name, key)}
                try:
                    res_val = self._resolve_expression(raw_val, section_name, key, active_stack)
                    resolved[section_name][key] = res_val
                except EvaluationError as e:
                    unmigratable_items.append(
                        UnmigratableItem(
                            file=source_file,
                            section=section_name,
                            key=key,
                            reason=str(e)
                        )
                    )
                    # Keep raw string in resolved dict for partial reporting
                    resolved[section_name][key] = raw_val

        return resolved, unmigratable_items

    def _resolve_expression(
        self,
        expr: str,
        section: str,
        key: str,
        active_stack: Set[Tuple[str, str]]
    ) -> Any:
        # First pass: Expand environment variables ${...}
        expr_after_env = self._expand_env_vars(expr, section, key, active_stack)

        # If the value is a primitive literal string representation, return resolved
        if not isinstance(expr_after_env, str):
            return expr_after_env

        # Second pass: Expand cross-key references $(...)
        expr_after_keys = self._expand_cross_keys(expr_after_env, section, key, active_stack)
        return expr_after_keys

    def _expand_env_vars(
        self,
        expr: str,
        section: str,
        key: str,
        active_stack: Set[Tuple[str, str]]
    ) -> str:
        """Expands ${VAR}, ${VAR:-default}, and ${VAR:+alt} in expr."""
        result = []
        i = 0
        n = len(expr)

        while i < n:
            if expr[i:i+2] == "${":
                brace_depth = 1
                j = i + 2
                while j < n and brace_depth > 0:
                    if expr[j] == '{':
                        brace_depth += 1
                    elif expr[j] == '}':
                        brace_depth -= 1
                    j += 1

                if brace_depth != 0:
                    raise UnmigratableError(
                        f"Syntax error: unclosed environment variable syntax in '{expr}'",
                        section=section, key=key
                    )

                body = expr[i+2:j-1]
                val = self._evaluate_env_body(body, section, key, active_stack)
                result.append(str(val))
                i = j
            else:
                result.append(expr[i])
                i += 1

        return "".join(result)

    def _evaluate_env_body(
        self,
        body: str,
        section: str,
        key: str,
        active_stack: Set[Tuple[str, str]]
    ) -> str:
        """Parses and evaluates body of ${...} expression."""
        op = None
        op_idx = -1
        depth = 0

        for idx in range(len(body)):
            ch = body[idx]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            elif depth == 0:
                if body[idx:idx+2] in (":-", ":+"):
                    op = body[idx:idx+2]
                    op_idx = idx
                    break

        if op is None:
            var_name = body.strip()
            if var_name in self.env and self.env[var_name] != "":
                return self.env[var_name]
            elif var_name in self.env and self.env[var_name] == "":
                return ""
            else:
                raise UnmigratableError(
                    f"Unresolved environment variable '${{{var_name}}}' — variable is unset and has no default value",
                    section=section, key=key
                )
        else:
            var_name = body[:op_idx].strip()
            operand = body[op_idx+2:]
            env_val = self.env.get(var_name)

            if op == ":-":
                if env_val is not None and env_val != "":
                    return env_val
                else:
                    return str(self._resolve_expression(operand, section, key, active_stack))
            elif op == ":+":
                if env_val is not None and env_val != "":
                    return str(self._resolve_expression(operand, section, key, active_stack))
                else:
                    return ""
            return ""

    def _expand_cross_keys(
        self,
        expr: str,
        section: str,
        key: str,
        active_stack: Set[Tuple[str, str]]
    ) -> str:
        """Expands $(section.key) cross-key references in expr."""
        result = []
        i = 0
        n = len(expr)

        while i < n:
            if expr[i:i+2] == "$(":
                j = expr.find(")", i + 2)
                if j == -1:
                    raise UnmigratableError(
                        f"Syntax error: unclosed cross-key reference in '{expr}'",
                        section=section, key=key
                    )

                ref_path = expr[i+2:j].strip()
                ref_val = self._lookup_and_resolve_key(ref_path, section, key, active_stack)
                result.append(str(ref_val))
                i = j + 1
            else:
                result.append(expr[i])
                i += 1

        return "".join(result)

    def _lookup_and_resolve_key(
        self,
        ref_path: str,
        current_section: str,
        current_key: str,
        active_stack: Set[Tuple[str, str]]
    ) -> Any:
        if "." not in ref_path:
            raise UnmigratableError(
                f"Invalid reference '$({ref_path})' — must be formatted as section.key",
                section=current_section, key=current_key
            )

        target_section, target_key = ref_path.rsplit(".", 1)

        if target_section not in self.settings or target_key not in self.settings[target_section]:
            raise UnmigratableError(
                f"Unresolved reference '$({ref_path})' — key '{target_key}' in section '{target_section}' not found",
                section=current_section, key=current_key
            )

        target_item = (target_section, target_key)
        if target_item in active_stack:
            chain = " -> ".join(f"{s}.{k}" for s, k in active_stack) + f" -> {target_section}.{target_key}"
            raise CircularReferenceError(
                f"Unresolved $({ref_path}) — circular reference detected ({chain})",
                section=current_section,
                key=current_key
            )

        raw_target_val = self.settings[target_section][target_key]
        if not isinstance(raw_target_val, str):
            return raw_target_val

        active_stack.add(target_item)
        try:
            return self._resolve_expression(raw_target_val, target_section, target_key, active_stack)
        finally:
            active_stack.remove(target_item)


class PFCfgEvaluator:
    """Reference evaluator for legacy .pfcfg configuration trees."""

    def __init__(self, env: Optional[Dict[str, str]] = None):
        self.env = env if env is not None else {}
        self.visited_once: Set[Path] = set()

    def evaluate(self, entry_file_path: Union[str, Path]) -> EvaluationResult:
        path = Path(entry_file_path).resolve()
        raw_settings: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []

        try:
            self._parse_file(path, raw_settings, cond_stack=[])
        except Exception as e:
            errors.append(f"Failed to parse legacy config '{path}': {e}")

        interpolator = Interpolator(raw_settings, self.env)
        effective_settings, unmigratable_items = interpolator.resolve_all(source_file=str(path))

        return EvaluationResult(
            file=str(path),
            settings=effective_settings,
            unmigratable_items=unmigratable_items,
            errors=errors
        )

    def _parse_file(
        self,
        file_path: Path,
        settings: Dict[str, Dict[str, Any]],
        cond_stack: List[Dict[str, str]]
    ) -> None:
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        lines = file_path.read_text(encoding="utf-8").splitlines()
        current_section: Optional[str] = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            line = self._strip_inline_comment(line)
            if not line:
                continue

            # Handle Directives
            if line.startswith("@"):
                parts = line.split(maxsplit=1)
                directive = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if directive in ("@include", "@include_once"):
                    if evaluate_cond_stack(cond_stack, self.env):
                        inc_path = (file_path.parent / arg).resolve()
                        if directive == "@include_once":
                            if inc_path in self.visited_once:
                                continue
                            self.visited_once.add(inc_path)
                        self._parse_file(inc_path, settings, cond_stack)

                elif directive == "@ifdef":
                    cond_stack.append({"env_set": arg})

                elif directive == "@ifndef":
                    cond_stack.append({"env_unset": arg})

                elif directive == "@endif":
                    if cond_stack:
                        cond_stack.pop()

                continue

            # Skip line if active condition stack is not satisfied
            if not evaluate_cond_stack(cond_stack, self.env):
                continue

            # Section headers
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                if current_section not in settings:
                    settings[current_section] = {}
                continue

            # Key-value pairs
            if "=" in line:
                key, val_str = line.split("=", 1)
                key = key.strip()
                val_str = val_str.strip()

                if current_section is None:
                    current_section = "global"
                    if current_section not in settings:
                        settings[current_section] = {}

                parsed_val = self._parse_value(val_str)
                settings[current_section][key] = parsed_val

    def _strip_inline_comment(self, line: str) -> str:
        in_quotes = False
        for i, char in enumerate(line):
            if char == '"' and (i == 0 or line[i-1] != '\\'):
                in_quotes = not in_quotes
            elif not in_quotes and char in ('#', ';'):
                if i == 0 or line[i-1].isspace():
                    return line[:i].strip()
        return line.strip()

    def _parse_value(self, val_str: str) -> Union[str, int, float, bool]:
        if len(val_str) >= 2 and val_str.startswith('"') and val_str.endswith('"'):
            inner = val_str[1:-1]
            return inner.replace('\\"', '"').replace('\\\\', '\\')
        if val_str.lower() == "true":
            return True
        if val_str.lower() == "false":
            return False
        if "${" not in val_str and "$(" not in val_str:
            if re.match(r"^-?\d+$", val_str):
                return int(val_str)
        return val_str


class JSONEvaluator:
    """Evaluates converted JSON target configurations (conforming to schema.json)."""

    def __init__(self, env: Optional[Dict[str, str]] = None):
        self.env = env if env is not None else {}
        self.visited_once: Set[Path] = set()

    def evaluate_file(self, json_file_path: Union[str, Path]) -> EvaluationResult:
        path = Path(json_file_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        return self.evaluate_dict(data, base_dir=path.parent, source_file=str(path))

    def evaluate_dict(
        self,
        data: Dict[str, Any],
        base_dir: Union[str, Path],
        source_file: str = ""
    ) -> EvaluationResult:
        base_path = Path(base_dir).resolve()
        raw_settings: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []

        try:
            self._flatten_json(data, base_path, raw_settings)
        except Exception as e:
            errors.append(f"Failed to process JSON configuration: {e}")

        interpolator = Interpolator(raw_settings, self.env)
        effective_settings, unmigratable_items = interpolator.resolve_all(source_file=source_file)

        return EvaluationResult(
            file=source_file,
            settings=effective_settings,
            unmigratable_items=unmigratable_items,
            errors=errors
        )

    def _flatten_json(
        self,
        data: Dict[str, Any],
        base_dir: Path,
        settings: Dict[str, Dict[str, Any]]
    ) -> None:
        # 1. Process Imports
        for imp in data.get("imports", []):
            when = imp.get("when")
            if when and not evaluate_condition(when, self.env):
                continue

            rel_path = imp.get("path")
            if not rel_path:
                continue

            imp_path = (base_dir / rel_path).resolve()
            if imp.get("once", False):
                if imp_path in self.visited_once:
                    continue
                self.visited_once.add(imp_path)

            if imp_path.suffix == ".pfcfg":
                converted_data = convert_pfcfg_file(imp_path)
                self._flatten_json(converted_data, imp_path.parent, settings)
            elif imp_path.suffix == ".json":
                imp_data = json.loads(imp_path.read_text(encoding="utf-8"))
                self._flatten_json(imp_data, imp_path.parent, settings)

        # 2. Process Static Sections
        for sec_name, sec_keys in data.get("sections", {}).items():
            if sec_name not in settings:
                settings[sec_name] = {}
            for k, v in sec_keys.items():
                settings[sec_name][k] = v

        # 3. Process Overrides
        for override in data.get("overrides", []):
            when = override.get("when", {})
            if evaluate_condition(when, self.env):
                for sec_name, sec_keys in override.get("sections", {}).items():
                    if sec_name not in settings:
                        settings[sec_name] = {}
                    for k, v in sec_keys.items():
                        settings[sec_name][k] = v


def evaluate_pfcfg(file_path: Union[str, Path], env: Optional[Dict[str, str]] = None) -> EvaluationResult:
    """Convenience helper to evaluate a legacy .pfcfg entry file into effective settings."""
    evaluator = PFCfgEvaluator(env=env)
    return evaluator.evaluate(file_path)


def evaluate_json(
    json_data_or_path: Union[str, Path, Dict[str, Any]],
    base_dir: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None
) -> EvaluationResult:
    """Convenience helper to evaluate a converted JSON config into effective settings."""
    evaluator = JSONEvaluator(env=env)
    if isinstance(json_data_or_path, (str, Path)) and Path(json_data_or_path).is_file():
        return evaluator.evaluate_file(json_data_or_path)
    elif isinstance(json_data_or_path, dict):
        if base_dir is None:
            base_dir = Path.cwd()
        return evaluator.evaluate_dict(json_data_or_path, base_dir=base_dir)
    else:
        raise ValueError("Invalid argument for evaluate_json: expected file path or dictionary")
