"""Typed cross-file reference models.

Stage: COMPILE (Input)
Purpose: Replace magic string cross-file refs with validated Pydantic models.

YAML stays unchanged:
    variables:
      regn: shared.yml.variables.regn   # coerced to VariableRef at parse time

The bare-string-to-{"ref": "..."} coercion is declared where each ref class is
used as a union arm (``authored.py``'s ``VariableOrRef``/``QueryOrRef``/
``ChartOrRef``), via ``Annotated[RefCls, BeforeValidator(coerce_ref_string,
json_schema_input_type=str | RefCls)]`` — not as a ``model_validator`` here.
A model-level validator is invisible to JSON Schema (introspection reads field
annotations, not validator bodies); declaring the coercion on the annotation
lets ``schema/introspection.py`` read it back via ``json_schema_input_type``,
so the derived schema — what the migrator gates on — knows a bare string is
accepted too. The grammar check still fires at the type boundary (`ref: str`'s
`field_validator`) — not scattered through compiler, normalizer, and validator.

Also exports `normalize_query_value` — the query normalization helper attached as
the `BeforeValidator` on `authored.py`'s `QueryOrRef`. Living here breaks the
import cycle (parser.py → authored.py via this module is fine; the reverse
parser → authored would be circular).
"""

import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# File-path portion: an optional leading run of literal "../" segments (to
# climb into a sibling directory), then a normal path starting with a
# letter/underscore. A bare leading "." is deliberately NOT admitted here —
# that would also let through ".hidden", "...junk", etc. Escaping above the
# project root is rejected downstream by assert_relpath, not by this grammar.
_REF_FILE_PATH = r"(?:\.\./)*[A-Za-z_][\w/\-.]*"
VAR_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.variables\.[A-Za-z_]\w*$")
QUERY_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.queries\.[A-Za-z_]\w*$")
CHART_REF_RE = re.compile(rf"^{_REF_FILE_PATH}\.charts\.[A-Za-z_]\w*$")

# Pattern-constrained string arms for VariableOrRef/ChartOrRef's json_schema_input_type
# (authored.py) — StringConstraints doesn't change runtime validation (coerce_ref_string
# still accepts any string; the field_validator above enforces the grammar for real), it
# only tells schema/introspection.py's pattern tracking what to put in the derived
# schema's "pattern" key, so a malformed ref string reads as invalid in the IDE/migrator
# too, not just at parse time. queries: has no such constant — normalize_query_value
# treats any string failing QUERY_REF_RE as SQL, so its string arm stays unconstrained.
VAR_REF_PATTERN_STR = Annotated[str, StringConstraints(pattern=VAR_REF_RE.pattern)]
CHART_REF_PATTERN_STR = Annotated[str, StringConstraints(pattern=CHART_REF_RE.pattern)]


def infer_query_type_from_keys(query_dict: dict[str, Any]) -> str:
    """Infer query type from dictionary keys."""
    if "rows" in query_dict or "values" in query_dict or "columns" in query_dict:
        return "values"
    if "url" in query_dict:
        return "http"
    return "sql"


def normalize_query_value(query_def: Any) -> Any:
    """Normalize a single query value to a full dict with a 'type' field.

    Cross-file refs become {"ref": "..."} so Pydantic coerces them to QueryRef.
    Bare SQL strings become {"sql": ..., "type": "sql"}.
    Dict definitions get a type field inferred when absent.
    Already-typed model instances (QueryRef, AuthoredQuery) pass through unchanged.

    Attached as the `BeforeValidator` on `authored.py`'s `QueryOrRef`, so it runs
    per-entry on every `queries:` dict value — top-level and nested boards alike —
    before the `AuthoredQuery | QueryRef` union validates. May receive
    already-typed instances when callers construct AuthoredBoard directly via
    Python (e.g. QueryRef(ref=...)).
    """
    # Already a typed model instance — leave for Pydantic to handle.
    if not isinstance(query_def, (str, dict)):
        return query_def

    if isinstance(query_def, str):
        if QUERY_REF_RE.fullmatch(query_def.strip()):
            return {"ref": query_def.strip()}
        return {"sql": query_def, "type": "sql"}

    # dict path
    if "type" in query_def or "ref" in query_def:
        # "ref" key → QueryRef; skip type inference to avoid adding a spurious
        # "type": "sql" that would be rejected as an extra field by QueryRef.
        return query_def

    return {**query_def, "type": infer_query_type_from_keys(query_def)}


def coerce_ref_string(
    data: object,  # type-state: object_annotation — validator input: pydantic hands this any raw YAML scalar/mapping pre-coercion; narrowed by isinstance below
) -> object:  # type-state: object_annotation — same boundary as the parameter above
    """Coerce a bare string to {"ref": "..."} ahead of a CrossFileRef subclass.

    Shared by VariableOrRef/QueryRef/ChartOrRef's "@ref" union arm (authored.py)
    as a `BeforeValidator`, replacing what used to be each ref class's own
    `coerce_string` `model_validator(mode="before")`. A model-level validator
    can't be described in JSON Schema; attaching this at the annotation instead
    lets `json_schema_input_type=str | RefCls` tell introspection a bare string
    is accepted too.
    """
    return {"ref": data} if isinstance(data, str) else data


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

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not VAR_REF_RE.fullmatch(v):
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

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not QUERY_REF_RE.fullmatch(v):
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

    @field_validator("ref")
    @classmethod
    def validate_grammar(cls, v: str) -> str:
        if not CHART_REF_RE.fullmatch(v):
            raise ValueError(
                f"Invalid chart reference {v!r}. "
                "Expected '<file>.charts.<name>', optionally prefixed with '../' segments."
            )
        return v


def ref_or_inline(
    v: object,  # type-state: object_annotation — Discriminator callable receives raw pre-validation input
    ref_cls: type[CrossFileRef],
) -> str:
    """Classify a union value as '@ref' or '@inline'.

    Returns '@ref' when v is already a typed ref instance, a bare cross-file ref
    string, or a dict that contains a 'ref' key. Returns '@inline' otherwise.

    Tag names start with '@' to prevent collision with user-chosen YAML keys
    ('ref', 'inline') in Pydantic error locs.

    Routing any dict with a 'ref' key to the ref branch produces a clean
    'extra inputs not permitted' error from the ref model (extra="forbid")
    rather than an opaque 'extra inputs' error on the inline model.
    """
    if isinstance(v, ref_cls):
        return "@ref"
    if isinstance(v, str):
        return "@ref"
    if isinstance(v, dict) and "ref" in v:
        return "@ref"
    return "@inline"
