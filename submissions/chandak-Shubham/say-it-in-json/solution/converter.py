import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class PFCfgParser:
    """Parser for .pfcfg files into target JSON schema structure."""

    def __init__(self, content: str):
        self.content = content
        self.imports: List[Dict[str, Any]] = []
        self.sections: Dict[str, Dict[str, Any]] = {}
        self.overrides: List[Dict[str, Any]] = []

    def parse(self) -> Dict[str, Any]:
        lines = self.content.splitlines()
        current_section: Optional[str] = None
        cond_stack: List[Dict[str, str]] = []

        # Helper to get active override entry for current condition stack
        def get_or_create_override(when_cond: Dict[str, str]) -> Dict[str, Any]:
            if self.overrides and self.overrides[-1]["when"] == when_cond:
                return self.overrides[-1]
            new_override: Dict[str, Any] = {
                "when": when_cond,
                "sections": {}
            }
            self.overrides.append(new_override)
            return new_override

        for raw_line in lines:
            line = raw_line.strip()

            # Skip empty lines
            if not line:
                continue

            # Strip full-line comments or inline comments starting with '#' or ';'
            if line.startswith("#") or line.startswith(";"):
                continue

            # Handle comment on line after directive/key/header (if separated by whitespace)
            line = self._strip_inline_comment(line)
            if not line:
                continue

            # Check for directives
            if line.startswith("@"):
                parts = line.split(maxsplit=1)
                directive = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if directive in ("@include", "@include_once"):
                    is_once = directive == "@include_once"
                    import_entry: Dict[str, Any] = {
                        "path": arg,
                        "once": is_once
                    }
                    if cond_stack:
                        import_entry["when"] = dict(cond_stack[-1])
                    
                    self.imports.append(import_entry)

                elif directive == "@ifdef":
                    cond_stack.append({"env_set": arg})

                elif directive == "@ifndef":
                    cond_stack.append({"env_unset": arg})

                elif directive == "@endif":
                    if cond_stack:
                        cond_stack.pop()

                continue

            # Check for section header
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue

            # Check for key = value
            if "=" in line:
                key, val_str = line.split("=", 1)
                key = key.strip()
                val_str = val_str.strip()
                parsed_val = self._parse_value(val_str)

                if current_section is None:
                    # Key outside section - default to global section if needed
                    current_section = "global"

                if not cond_stack:
                    # Unconditional section/key
                    if current_section not in self.sections:
                        self.sections[current_section] = {}
                    self.sections[current_section][key] = parsed_val
                else:
                    # Conditional override section/key
                    when_cond = dict(cond_stack[-1])
                    override = get_or_create_override(when_cond)
                    if current_section not in override["sections"]:
                        override["sections"][current_section] = {}
                    override["sections"][current_section][key] = parsed_val

        result: Dict[str, Any] = {
            "version": 1
        }
        if self.imports:
            result["imports"] = self.imports
        if self.sections:
            result["sections"] = self.sections
        if self.overrides:
            result["overrides"] = self.overrides

        return result

    def _strip_inline_comment(self, line: str) -> str:
        """Strip comment if it occurs after whitespace or quotes."""
        in_quotes = False
        for i, char in enumerate(line):
            if char == '"' and (i == 0 or line[i-1] != '\\'):
                in_quotes = not in_quotes
            elif not in_quotes and char in ('#', ';'):
                if i == 0 or line[i-1].isspace():
                    return line[:i].strip()
        return line.strip()

    def _parse_value(self, val_str: str) -> Union[str, int, float, bool]:
        """Parse raw value string into appropriate JSON primitive."""
        # Check quoted strings
        if len(val_str) >= 2 and val_str.startswith('"') and val_str.endswith('"'):
            inner = val_str[1:-1]
            inner = inner.replace('\\"', '"').replace('\\\\', '\\')
            return inner

        # Check boolean literals (unquoted)
        if val_str.lower() == "true":
            return True
        if val_str.lower() == "false":
            return False

        # Check integer literals if no interpolation markers present
        if "${" not in val_str and "$(" not in val_str:
            if re.match(r"^-?\d+$", val_str):
                return int(val_str)

        # Default: raw string (preserving ${VAR...} and $(sec.key) expressions)
        return val_str


def convert_pfcfg_file(file_path: Union[str, Path]) -> Dict[str, Any]:
    """Reads a .pfcfg file and converts it into a JSON dict conforming to schema.json."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    parser = PFCfgParser(content)
    return parser.parse()


def validate_converted_json(data: Dict[str, Any], schema_path: Union[str, Path]) -> bool:
    """Optionally validates JSON data against schema.json if jsonschema package is available."""
    try:
        import jsonschema
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)
        return True
    except ImportError:
        assert data.get("version") == 1, "Missing or invalid version"
        return True
