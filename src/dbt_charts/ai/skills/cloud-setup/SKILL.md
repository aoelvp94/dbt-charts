---
name: cloud-setup
kind: workflow
surfaces: [cli]
description: >
  Set up a fresh dbt charts Cloud org end to end from the terminal:
  authenticate, connect a project, wire a warehouse connection, map sources,
  and render — driven by `dct cloud status` until it reports done. Use when
  the user says 'set me up with dbt charts cloud', 'deploy my dashboards to
  cloud', 'connect this repo to dbtcharts.com', or 'get my boards live'. Do
  NOT use for authoring boards (use board-build) or for deleting/removing an
  org, project, or connection — this skill never runs a destructive verb.
metadata:
  author: fivetran
---

# Setting up dbt charts Cloud

Walk a user from nothing to a live, rendered board on dbtcharts.com, running
`dct cloud` verbs and asking the user for only what your own credentials
cannot supply. At most two things stay human: approving `dct cloud login` in
a browser (Step 1), and, unless the repo is public, picking a repository in
the GitHub App install flow.

> This skill is **CLI-only** (`surfaces: [cli]`) — `dct cloud` has no MCP
> tool surface. Syntax for every verb below lives in `--help`; this skill
> only orders the steps and tells you what to check before each one.

## Before you start

Confirm the tools exist before relying on them:

- `dct --version` — dbt charts is installed. If not: `uv tool install dbt-charts`.
- `dct cloud status` needs a project directory only if you plan to infer org
  and project from `git remote`; run it from the repo you're connecting once
  one exists.
- Warehouse CLI detection, so you know which credential-minting path applies
  later: `gcloud auth list` (BigQuery), `which snowsql` (Snowflake), `which
  psql` (Postgres/Redshift). Missing tooling isn't fatal — it just means the
  user supplies the credential instead of you minting one.

## Step 1: Authenticate

Run a read-only verb (`dct cloud orgs`) first — if `DCT_CLOUD_TOKEN` is
already set or a token is already stored, it just works and this step is
done. Otherwise run `dct cloud login`. It prints a code and a URL; hand off
to the user there — only they can complete the browser approval: sign in
(or create an account), pick or create the organization the CLI should
reach, and approve. Once they confirm, continue; `dct cloud login` blocks
until the approval lands or the code expires, so re-run it if it timed out.
Never guess a token value, and never try to complete the browser step
yourself — it is the user signing in, not you.

## Step 2: Organization

List orgs (`dct cloud orgs`) — the consent screen in Step 1 always leaves at
least one, picked or created there. If the user consented to more than one,
pin the one this repository is for: `dct cloud use <org>`. `dct cloud org
create` remains available if the user wants to create an additional
organization later.

## Step 3: Boards, if none exist yet

This skill connects a repo and a warehouse; it doesn't author boards. If the
target repo has no `charts/` yet, hand off to the board-build skill first —
inspect the warehouse schema, author board YAML, validate and render
locally, commit, push. Come back here once boards exist (or skip this step
entirely if they already do).

## Step 4: Connect the project

Pre-flight before offering the browser path: with `gh` available, check
`gh auth status`, then `gh api repos/<owner>/<repo> --jq .permissions.admin`
on the target repo. Cloud's repo picker only offers repos you administer —
a non-admin lands on a refusal page with no way forward. If the check fails,
tell the user up front whose account needs admin rights (or ask them to run
the connect command themselves once signed in as that account) rather than
sending them into a dead end.

Two paths, and prefer the first whenever it applies:

- **Public repo, or any repo Cloud can clone over plain git**: connect it
  headlessly with the git-URL option. No browser hop.
- **Private repo**: connect without a URL. This prints an install link,
  waits for the user to install the GitHub App and pick the repository in
  the browser, then finishes on its own once the pick lands — the one
  irreducible browser hop for a private repo.

## Step 5: Warehouse connection

Mint the narrowest credential your own identity can, per provider, into a
temp file you delete right after — never paste a secret into a command
argument (every credential field takes a file, stdin, or a named
environment variable; a bare secret on argv sits in shell history and the
process list, so the connect verb refuses it).

| Warehouse | Minting | If you can't mint one |
|---|---|---|
| BigQuery | Create a service account scoped to the target dataset, grant it read access, mint a JSON key into a temp file, delete the file once the connection call reads it. | Ask the user's admin to grant the IAM role, or to hand you a key. |
| Snowflake | Generate a key pair, register the public half on a role-scoped user via `snowsql`, use the private key file. | Ask the user to type a password at a stdin prompt — never on the command line. |
| Postgres / Redshift | If your own credentials allow it, create a read-only role via `psql` and use its password. | Ask the user to supply or approve a read-only credential. |

Create the connection with the minted (or user-supplied) credential. The
create call also tests it — a failing test is reported as a failure, not
silently saved; fix the credential and retry rather than moving on.

## Step 6: Map sources

Every board declares a `source:` name. Point each one at the connection you
just created.

## Step 7: Render

Trigger rendering for the project's boards.

## The loop that actually drives this

Don't hardcode the step order above as a fixed script — after step 2, drive
the rest from `dct cloud status`. It reports the org's setup stage and names
the exact next step in plain language (create a project, sync it, create or
test a connection, map a source, render). Read that instruction, run the
verb it names, check status again, repeat until it reports nothing left to
do. This is more reliable than following a fixed sequence, because it
survives a user who already did some steps by hand, or a step that needs a
retry.

## Stop conditions

Hand off to the user, rather than guessing or working around it, whenever:

- `dct cloud login`'s browser approval hasn't happened yet (Step 1) — only
  the user can complete it.
- The pre-flight admin check fails before the GitHub hop — name whose
  account needs the rights.
- `status`'s next step names an administrative action your own token or
  warehouse identity cannot perform (an IAM grant, a Cloud org-admin action
  outside your scope).
- A connection test keeps failing after a credential retry — don't keep
  minting new ones speculatively; report the failure and ask.

## When you're done

`dct cloud status` reports every project done, with no unmapped sources and
no unrendered boards. It reports stages and counts, not addresses — read the
board URLs from `dct cloud boards` and give those to the user.
