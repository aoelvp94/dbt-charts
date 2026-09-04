"""The Cloud setup API's wire contract — one definition, both ends.

Cloud's ``/api/`` views serialize their responses through these models and the
``dct cloud`` client parses them back, so a response shape cannot change on the
server without the type the CLI reads changing in the same commit. That is the whole reason this lives in the ``dbt-charts`` package rather
than in ``apps/cloud``: the monorepo lets Cloud import the client's types, never
the reverse.

The OAuth device-grant models and the ``login``/``whoami`` result shapes are
the exception to "both ends": those are what the CLI reads from the
authorization server, or emits itself, and no Cloud view serializes them.

Nothing here may import ``dbt_charts.core`` or Django. These are transport
shapes — they carry no board semantics and run on the CLI's side of the wire,
where neither exists.

**Auth-failure shape.** ``ErrorCode`` encodes the decision this API pins for
every token surface after it:

- a missing or unusable credential is ``UNAUTHENTICATED`` (401);
- a credential whose *scope* does not cover the operation is
  ``INSUFFICIENT_SCOPE`` (403) and names the scope, because the refusal is a
  fact about the token alone — it is decided before any resource is looked up,
  so it identifies no org and enumerates nothing;
- every resource the caller may not see is ``NOT_FOUND`` (404), whether or not
  it exists. Org slugs are company names; a 403/404 split on them would hand any
  token holder a map of every org in the deployment.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, enum.Enum):
    """The machine-readable half of every error response."""

    UNAUTHENTICATED = "unauthenticated"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    VALIDATION_FAILED = "validation_failed"
    CONFLICT = "conflict"
    CONNECTION_TEST_FAILED = "connection_test_failed"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"


class ApiError(BaseModel):
    """The one error body every endpoint returns."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode = Field(description="Machine-readable failure kind.")
    message: str = Field(description="Human-readable failure summary.")
    field_errors: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-field messages, keyed by request field name.",
    )


# --- OAuth device grant (RFC 8628) and discovery (RFC 8414) ----------------
#
# These three carry wire shapes a server we don't own defines -- Cloud's OAuth
# toolkit, not this package's API. `extra="ignore"` lets them add fields
# (scopes_supported, refresh_token, ...) without breaking this client; every
# other model in this file is OUR contract and keeps `extra="forbid"`.


class AuthorizationServerMetadata(BaseModel):
    """The RFC 8414 document a host publishes its OAuth endpoints in."""

    model_config = ConfigDict(extra="ignore")

    token_endpoint: str = Field(description="Where to poll for a device token.")
    revocation_endpoint: str = Field(description="Where to revoke a token.")
    device_authorization_endpoint: str = Field(
        description="Where to start a device login."
    )


class DeviceAuthorization(BaseModel):
    """The answer to starting a device login: a code to show, one to poll with."""

    model_config = ConfigDict(extra="ignore")

    device_code: str = Field(
        description="The code this client polls the token endpoint with."
    )
    user_code: str = Field(
        description="The code the user types at the verification URI."
    )
    verification_uri: str = Field(description="Where the user approves the login.")
    verification_uri_complete: str | None = Field(
        default=None, description="verification_uri with the user_code pre-filled."
    )
    expires_in: int = Field(description="Seconds until device_code stops being valid.")
    interval: int = Field(default=5, description="Minimum seconds between polls.")


class DeviceToken(BaseModel):
    """The answer to a successful token poll."""

    model_config = ConfigDict(extra="ignore")

    access_token: str = Field(description="The bearer token to store.")
    token_type: str = Field(description="Always `Bearer`.")
    expires_in: int | None = Field(default=None, description="Seconds until expiry.")
    scope: str = Field(default="", description="Scopes actually granted.")


class LoginResult(BaseModel):
    """What `dct cloud login` reports on success. Never the token."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(description="The Cloud deployment now signed in to.")
    organizations: list[OrgSummary] = Field(
        default_factory=list, description="Organizations the new token can reach."
    )


class WhoAmI(BaseModel):
    """What `dct cloud whoami` reports."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(description="The Cloud deployment in use.")
    credential_source: Literal["env", "config"] = Field(
        description="Whether the token came from DCT_CLOUD_TOKEN or the config file."
    )
    organizations: list[OrgSummary] = Field(
        default_factory=list, description="Organizations this credential can reach."
    )


class OrgSummary(BaseModel):
    """One organization, as the caller sees it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe organization identifier.")
    name: str = Field(description="Display name.")
    role: str = Field(description="The caller's membership role in this org.")


class OrgList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizations: list[OrgSummary] = Field(
        default_factory=list, description="Organizations the caller belongs to."
    )


class MemberSummary(BaseModel):
    """One organization member."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="The member's account email.")
    name: str = Field(description="Display name; empty if never set.")
    role: str = Field(description="Membership role.")
    joined_at: datetime = Field(description="When the membership was created.")


class MemberList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[MemberSummary] = Field(
        default_factory=list, description="The organization's members."
    )


class InviteResult(BaseModel):
    """The answer to inviting one address."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="The invited address.")
    role: str = Field(description="Role the invitation confers on acceptance.")
    already_member: bool = Field(
        description="True if the address already belongs to the organization."
    )


class InvitationSummary(BaseModel):
    """One pending invitation."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="The invited address.")
    role: str = Field(description="Role the invitation confers on acceptance.")
    created_at: datetime = Field(description="When the invitation was created.")
    expires_at: datetime = Field(
        description="When the invitation stops being redeemable."
    )


class InvitationList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitations: list[InvitationSummary] = Field(
        default_factory=list, description="Pending invitations."
    )


class DeleteResult(BaseModel):
    """The answer to deleting a resource."""

    model_config = ConfigDict(extra="forbid")

    deleted: bool = Field(description="Whether this call deleted the resource.")
    message: str = Field(description="What happened, in one line.")


class GrantSummary(BaseModel):
    """One live connector session against an organization."""

    model_config = ConfigDict(extra="forbid")

    grant_id: str = Field(description="The grant's id.")
    user_email: str = Field(description="The account that consented.")
    application_name: str = Field(description="The OAuth client this grant authorizes.")
    scopes: list[str] = Field(description="Scopes consented for this client.")
    created_at: datetime = Field(description="When this grant was recorded.")


class GrantList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grants: list[GrantSummary] = Field(
        default_factory=list, description="Live connector grants in this organization."
    )


class GrantRevokeResult(BaseModel):
    """The answer to revoking a connector grant."""

    model_config = ConfigDict(extra="forbid")

    revoked: bool = Field(description="Whether this call revoked the grant.")
    self_revoked: bool = Field(
        description=(
            "True when the revoked grant also authorized the credential making"
            " this very call — that credential dies with it."
        )
    )
    other_organizations_affected_count: int = Field(
        default=0,
        description=(
            "How many OTHER organizations this revoke also disconnected — the"
            " client shares one credential per (user, application), so"
            " revoking one grant kills every sibling grant for the same pair."
            " Always accurate, regardless of which of those organizations the"
            " caller can see."
        ),
    )
    other_organizations_affected: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the affected organizations the CALLER administers —"
            " never a full roster: naming an organization the caller has no"
            " admin relationship with would disclose its existence to them."
            " May be shorter than `other_organizations_affected_count`."
        ),
    )
    message: str = Field(description="What happened, in one line.")


class BoardSummary(BaseModel):
    """One board's render state, for the read-only board listing."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe board identifier.")
    title: str = Field(description="Board title.")
    render_status: str = Field(
        description="`ready`, `warning` (last render failed), or `not_rendered`."
    )
    error: str = Field(
        default="", description="The last render's failure text; empty otherwise."
    )
    url: str = Field(description="Where to view this board.")


class BoardList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boards: list[BoardSummary] = Field(
        default_factory=list, description="Boards visible to the caller."
    )


class ProjectSummary(BaseModel):
    """One connected project."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe project identifier.")
    name: str = Field(description="Display name.")
    repo_label: str = Field(
        description="Credential-free label for the repo the boards come from."
    )
    trunk_branch: str = Field(description="Branch Cloud pulls from.")
    work_branch: str = Field(description="Branch Cloud commits edits to.")
    git_subdirectory: str = Field(
        description="Path to the dbt project inside the repo; empty for the root."
    )
    unmapped_source_count: int = Field(
        description="Declared sources with no connection behind them yet."
    )


class ProjectList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectSummary] = Field(
        default_factory=list, description="Projects in the organization."
    )


class ConnectionSummary(BaseModel):
    """One warehouse connection. Carries no credential material, ever."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe connection identifier.")
    name: str = Field(description="Display name.")
    connection_type: str = Field(description="Warehouse kind, e.g. bigquery.")
    is_active: bool = Field(description="Whether boards may use this connection.")
    last_test_success: bool | None = Field(
        default=None, description="Result of the most recent test; null if untested."
    )
    last_test_error: str = Field(
        default="", description="Failure text from the most recent test."
    )


class ConnectionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connections: list[ConnectionSummary] = Field(
        default_factory=list, description="Connections the caller may use."
    )


class ConnectionTestResult(BaseModel):
    """The outcome of asking Cloud to reach a warehouse."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(description="Whether the warehouse answered.")
    message: str = Field(description="Driver or guard text; empty on success.")
    connection: ConnectionSummary = Field(description="The connection that was tested.")


class SourceSummary(BaseModel):
    """One `sources:` name declared by the project's dbt_charts.yml."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Source name as boards reference it.")
    connection_slug: str | None = Field(
        default=None, description="Connection backing this source; null if unmapped."
    )
    schema_override: str = Field(
        default="", description="Schema this source resolves against, when overridden."
    )
    is_default: bool = Field(description="Whether boards use this source by default.")


class SourceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceSummary] = Field(
        default_factory=list, description="The project's declared sources."
    )
    unmapped_count: int = Field(description="How many have no connection yet.")


class DbtRoot(BaseModel):
    """A dbt project root discovered in a picked repository."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Folder holding dbt_project.yml; empty for the root.")
    is_dct: bool = Field(description="Whether the folder also declares dbt_charts.yml.")


# The two values a project-create request may send for ``dbt_root_choice``
# instead of a discovered ``DbtRoot.path``. They are wire vocabulary, not an
# implementation detail of either end: the browser form posts them from a radio
# group and the CLI posts them from its flags, and the same server-side form
# reads both. Defined here so a rename cannot land on one end alone — the sole
# remaining copy is the radio group's own ``value=`` in
# ``templates/projects/_project_create_form_fields.html``, where a template
# cannot import a constant.
DBT_ROOT_REPO_ROOT = "__root__"
DBT_ROOT_OTHER = "__other__"


class RepoPick(BaseModel):
    """The repository a user picked in the browser, for the CLI to resume from.

    Records the outcome of the browser flow; it is not a way to make a pick.
    Repository authorization still comes from the user's own GitHub OAuth
    listing, in the browser, every time.
    """

    model_config = ConfigDict(extra="forbid")

    repo_id: str = Field(description="Cloud's id for the picked repository.")
    full_name: str = Field(description="owner/name of the picked repository.")
    default_branch: str = Field(description="The repository's own default branch.")
    private: bool = Field(description="Whether the repository is private.")
    picked_at: datetime = Field(description="When the browser pick completed.")
    dbt_roots: list[DbtRoot] = Field(
        default_factory=list, description="dbt project roots found in the repository."
    )


class SyncResult(BaseModel):
    """The answer to "pull this project's repo"."""

    model_config = ConfigDict(extra="forbid")

    queued: bool = Field(description="Whether this call enqueued a new sync.")
    message: str = Field(description="What happened, in one line.")


class RenderResult(BaseModel):
    """The answer to "render this project's unrendered boards"."""

    model_config = ConfigDict(extra="forbid")

    started: int = Field(description="Board renders this call started.")
    unrendered_remaining: int = Field(
        description="Boards still unrendered after this batch."
    )


class SetupStage(str, enum.Enum):
    """One step of the org setup state machine, in completion order.

    ``MISSING_PROJECT`` < ``UNSYNCED`` < ``UNTESTED_CONNECTION`` <
    ``UNMAPPED_SOURCES`` < ``UNRENDERED_BOARDS`` < ``DONE``. The "no org yet"
    stage the initiative's spec describes belongs to the ``dct cloud status``
    verb, never to this endpoint: an org-scoped GET cannot express "there is
    no org" (its URL already names one), so ``MISSING_PROJECT`` is the floor
    an org-scoped status can report.
    """

    MISSING_PROJECT = "missing_project"
    UNSYNCED = "unsynced"
    UNTESTED_CONNECTION = "untested_connection"
    UNMAPPED_SOURCES = "unmapped_sources"
    UNRENDERED_BOARDS = "unrendered_boards"
    DONE = "done"


class ProjectStatus(BaseModel):
    """One project's own place in the setup state machine.

    ``unrendered_board_count`` counts only boards a render batch would
    actually start (``not_rendered``, no attempt in flight) — a board whose
    last attempt FAILED is never counted here, so this reaching 0 never hides
    a board a retry can't touch, and neither is a board already mid-render
    (see ``rendering_board_count``). ``failed_board_count``/``failed_board_slugs``
    report those separately: they never block ``stage`` from reaching
    ``DONE`` (nothing left for ``dct cloud render`` to start), but they are
    still an action item — see ``OrgStatus.next_step``.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe project identifier.")
    stage: SetupStage = Field(description="This project's own setup stage.")
    synced: bool = Field(description="Whether the trunk branch has completed a sync.")
    unmapped_source_count: int = Field(
        description="Declared sources with no connection behind them yet."
    )
    board_count: int = Field(
        description="Boards visible to the caller in this project."
    )
    unrendered_board_count: int = Field(
        description="Visible, startable boards with no successful render yet."
    )
    rendering_board_count: int = Field(
        description=(
            "Visible boards with a render already in flight (PENDING) and "
            "young enough to trust — neither startable nor failed. While "
            "this is nonzero the stage cannot be DONE: a status read taken "
            "between starting a render and it finishing must not report the "
            "project as finished. A PENDING render older than the pipeline's "
            "own stale-worker bound counts toward failed_board_count "
            "instead, never here — a dead worker must not pin a project at "
            "this stage forever."
        )
    )
    failed_board_count: int = Field(
        description=(
            "Visible boards whose most recent render attempt FAILED, plus "
            "any PENDING render stale enough to presume its worker died."
        )
    )
    failed_board_slugs: list[str] = Field(
        default_factory=list, description="Slugs of the boards counted above."
    )


class OrgStatus(BaseModel):
    """The agent contract: one org-scoped read of the setup state machine.

    Two concerns, deliberately split:

    - ``stage`` and ``next_step`` are ORG TRUTH — computed from the org's
      full, unfiltered state, never narrowed by which scopes this particular
      caller's credential happens to admit. An org that finished setup is
      ``done`` for every caller, including one whose own token grants no
      ``connections.*`` atom (a bare ``dashboards:read`` token, or this
      endpoint's own minimum scope); reporting a caller-narrowed
      ``untested_connection`` instead would hand back a ``next_step`` the
      caller cannot itself run. ``next_step`` may legitimately name an admin
      act for exactly this reason: it describes what the ORG needs next, not
      what this caller is personally permitted to do about it. Disclosure
      stays coarse either way: a stage name, an instruction, and at most the
      slug of a connection an org project's sources are already mapped to —
      never a connection's type, host, credentials, or test output, and never
      the existence of one no project points at. That one slug is what makes
      ``untested_connection`` actionable: the gate is those specific
      connections passing their test, so an instruction that cannot name them
      is one a client can follow forever without the stage moving.
    - ``connection_count``/``tested_connection_count`` are CALLER-RELATIVE,
      resolved through ``usable_connections`` — the same treatment board
      counts always had. A setup-driving agent normally holds admin scopes,
      so its view is the complete one; a narrower caller (e.g. an org-tier
      Viewer, who holds no ``connections.*`` atom) sees zero here, exactly as
      it would on the connections page — never more. This is purely a
      disclosure limit on the two count fields; it does not feed the stage
      machine.

    ``stage``/``next_step`` are otherwise the org's own answer: the earliest
    incomplete stage across ``projects`` (``SetupStage`` order), so a client
    following ``next_step`` alone always closes the org's actual bottleneck. A
    project's own stage gates on the connections ITS sources are actually
    mapped to, not merely on the org having some tested connection — a
    project mapped to a different, untested connection is not done just
    because a sibling connection passed its test elsewhere in the org.

    ``next_step`` is null only when every project is fully ``DONE`` *and* no
    project has a failed board to inspect. Two cases never tell a client to
    call ``dct cloud render`` when render will not touch anything: a project
    stuck only on failed boards reports ``stage: done`` (nothing left a retry
    would start) with a non-null generic ``next_step`` — it says failed
    boards exist and points at ``dct cloud boards``; the board paths
    themselves appear only in each project's caller-scoped
    ``failed_board_slugs``, so org-truth advice never names a board the
    caller's ACL hides — and, on the same rule, the untested-connection
    ``next_step`` names only connections this caller can list, falling back
    to a generic pointer at ``dct cloud connections`` when it can list none;
    a project with renders already in flight (``rendering_board_count`` > 0,
    no boards left it could start) reports ``stage: unrendered_boards`` still
    — never ``done`` — with a ``next_step`` that says to poll again, not to
    re-render. A PENDING render whose age exceeds the render pipeline's own
    stale-worker bound is treated as failed for both purposes (it folds into
    ``failed_board_count``, never ``rendering_board_count``), so a dead
    worker cannot pin a project at ``unrendered_boards`` forever.
    """

    model_config = ConfigDict(extra="forbid")

    stage: SetupStage = Field(
        description="Earliest incomplete stage across all projects, as org truth."
    )
    next_step: str | None = Field(
        default=None,
        description=(
            "What the ORG needs next; null only when every project is done "
            "with no failed boards to inspect. May name an admin act this "
            "caller cannot itself perform."
        ),
    )
    connection_count: int = Field(
        description="Connections in this organization the caller may use."
    )
    tested_connection_count: int = Field(
        description="Of those, how many have a passing last test."
    )
    projects: list[ProjectStatus] = Field(
        default_factory=list, description="Per-project setup state, sorted by slug."
    )
