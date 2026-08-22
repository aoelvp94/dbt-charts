"""Typed cross-file reference models.

Stage: COMPILE (Input)
Purpose: Replace magic string cross-file refs with validated Pydantic models.

YAML stays unchanged:
    variables:
      regn: shared.yml.variables.regn   # coerced to VariableRef at parse time

The `mode="before"` validators coerce a bare string into {"ref": "..."} so the
grammar check fires at the type boundary — not scattered through compiler,
normalizer, and validator.

Also exports `normalize_query_value` — the single shared query normalization helper
used by both `parser._normalize_query_definitions` and `AuthoredBoard._normalize_queries`.
Living here breaks the import cycle (parser.py → authored.py via this module is fine;
the reverse parser → authored would be circular).
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# File-path portion: an optional leading run of literal "../" segments (to
# climb into a sibling directory), then a normal path starting with a
# letter/underscore. A bare leading "." is deliberately NOT admitted here —
# that would also let through ".hidden", "...junk", etc. Escaping above the
# project root is rejected downstream by assert_relpath, not by this grammar.
_REF_FILE_PATH = r"(?:\.\./)*[A-Za-z_][\w/\-.]*"
_VAR_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.variables\.[A-Za-z_]\w*$")
_QUERY_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.queries\.[A-Za-z_]\w*$")
_CHART_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.charts\.[A-Za-z_]\w*$")


def infer_query_type_from_keys(query_dict: dict[str, Any]) -> str:
    """Infer query type from dictionary keys."""
    if (
        "rows" in query_dict
        or "values" in query_dict
        or ("columns" in query_dict and "model" not in query_dict)
    ):
        return "values"
    if "metrics" in query_dict or "dimensions" in query_dict:
        return "metricflow"
    if "url" in query_dict:
        return "http"
    return "sql"


def normalize_query_value(query_def: Any) -> Any:
    """Normalize a single query value to a full dict with a 'type' field.

    Cross-file refs become {"ref": "..."} so Pydantic coerces them to QueryRef.
    Bare SQL strings become {"sql": ..., "type": "sql"}.
    Dict definitions get a type field inferred when absent.
    Already-typed model instances (QueryRef, AuthoredQuery) pass through unchanged.

    Called by both parser._normalize_query_definitions (top-level YAML) and
    AuthoredBoard._normalize_queries (nested board model validator). The validator
    runs on mode="before" and may receive already-typed instances when callers
    construct AuthoredBoard directly via Python (e.g. QueryRef(ref=...)).
    """
    # Already a typed model instance — leave for Pydantic to handle.
    if not isinstance(query_def, (str, dict)):
        return query_def

    if isinstance(query_def, str):
        if _QUERY_REF_RE.fullmatch(query_def.strip()):
            return {"ref": query_def.strip()}
        return {"sql": query_def, "type": "sql"}

    # dict path
    if "type" in query_def or "ref" in query_def:
        # "ref" key → QueryRef; skip type inference to avoid adding a spurious
        # "type": "sql" that would be rejected as an extra field by QueryRef.
        return query_def

    return {**query_def, "type": infer_query_type_from_keys(query_def)}


class CrossFileRef(BaseModel):
    """A pointer to a definition in another file, not the definition itself.

    A marker rather than shared implementation — each ref keeps its own grammar
    and prose. What it publishes is the one bit they share, which an editor
    needs and cannot otherwise ask for: the object under this key is authored
    somewhere else, so there is nothing here to edit but the pointer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class VariableRef(CrossFileRef):
    """Cross-file variable reference. Bare string is coerced automatically."""

    ref: str = Field(
        description="Reference path: '<file>.variables.<name>'. May start with one or more "
        "'../' segments to reach a sibling directory. A bare string value is coerced automatically."
    )

    @model_validator(mode="before")
    @classmethod
    def coerce_string(cls, data: object) -> object:
        return {"ref": data} if isinstance(data, str) else data

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not _VAR_REF_RE.fullmatch(v):
            raise ValueError(
                f"Invalid variable reference {v!r}. "
                "Expected '<file>.variables.<name>', optionally prefixed with '../' segments."
            )
        return v


class QueryRef(CrossFileRef):
    """Cross-file query reference. Bare string is coerced automatically."""

    ref: str = Field(
        description="Reference path: '<file>.queries.<name>'. May start with one or more "
        "'../' segments to reach a sibling directory. A bare string value is coerced automatically."
    )

    @model_validator(mode="before")
    @classmethod
    def coerce_string(cls, data: object) -> object:
        return {"ref": data} if isinstance(data, str) else data

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not _QUERY_REF_RE.fullmatch(v):
            raise ValueError(
                f"Invalid query reference {v!r}. "
                "Expected '<file>.queries.<name>', optionally prefixed with '../' segments."
            )
        return v


class ChartRef(CrossFileRef):
    """Cross-file chart reference. Bare string is coerced automatically."""

    ref: str = Field(
        description="Reference path: '<file>.charts.<name>'. May start with one or more "
        "'../' segments to reach a sibling directory. A bare string value is coerced automatically."
    )

    @model_validator(mode="before")
    @classmethod
    def coerce_string(cls, data: object) -> object:
        return {"ref": data} if isinstance(data, str) else data

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not _CHART_REF_RE.fullmatch(v):
            raise ValueError(
                f"Invalid chart reference {v!r}. "
                "Expected '<file>.charts.<name>', optionally prefixed with '../' segments."
            )
        return v
