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
cannot supply. One browser sitting stays human: approving `dct cloud login`
(Step 1) and, right after it, installing the GitHub App on the repository
(Step 3). Everything else you do yourself, showing the boards locally as you
go.

> This skill is **CLI-only** (`surfaces: [cli]`) — `dct cloud` has no MCP
> tool surface. Syntax for every verb below lives in `--help`; this skill
> only orders the steps and tells you what to check before each one.

> "Cloud" here is dbt charts Cloud (dbtcharts.com), not dbt Labs' dbt Cloud
> (getdbt.com). Local-only charts need no account — `dct serve` renders them.

## Before you start

Confirm the tools and access exist before relying on them:

- `dct --version` — dbt charts is installed. If not: `uv tool install dbt-charts`.
- `gh auth status` — Cloud deploys from a **GitHub** repository, public or
  private, connected through the dbt charts GitHub App; other git hosts are not
  supported. `gh` is optional: it lets you pre-check admin rights on the repo
  (Step 3) and is how a repo that isn't on GitHub yet gets there (`gh repo
  create`). Offer `gh auth login` if it is installed but signed out.
- `dct cloud status` needs a project directory only if you plan to infer org
  and project from `git remote`; run it from the repo you're connecting once
  one exists.
- Warehouse CLI detection, so you know which credential-minting path applies
  later: `gcloud auth list` (BigQuery), `which snowsql` (Snowflake), `which
  psql` (Postgres/Redshift). Missing tooling isn't fatal — it just means the
  user supplies the credential instead of you minting one.
- **Where the data lives.** Cloud connection types are exactly
  `bigquery, postgresql, redshift, snowflake`. A `dbt_charts.yml` source of
  `type: duckdb` or `type: sqlite` (or a local `.duckdb` file with no project
  yet) is **local-only** — Cloud never reads the file, even when it is
  committed to the repo. Say so *now*, before any board is authored in that
  dialect, and offer the two ways forward: load the tables into one of the
  four warehouses (then write the boards against it), or export each table to
  a Parquet/CSV/JSON file committed in the repo and register it once under
  `sources:` (`type: csv | json | parquet`, a `files:` map, paths relative to
  the project root) — every query then references it by name, and it renders
  identically locally and on Cloud with no connection step. Reach for the
  inline one-off form (`source: ../data/orders.parquet`, resolved from the
  board's own directory or the project root) only when a board is the sole
  reader of that one file. Don't build DuckDB boards and discover this at
  Step 5.

### Pick the repo and folder

Cloud deploys from a git repo, so settle where the project lives before you
authenticate — don't silently scaffold one:

- **Already in a git repo with a dbt charts project** (a `dbt_charts.yml` plus a
  `charts/` directory) — use it as-is.
- **In a git repo but no project yet** — ask whether to make *this* repo the
  home, or to start a **new repo** for it. `dct init` scaffolds the project
  (`dbt_charts.yml` + a starter `charts/`) beside the nearest project marker (a
  `dbt_project.yml` counts), so where you run it matters. Cloud tracks the repo
  **plus the subfolder that holds the project**, so whatever folder init lands
  in is the one to connect in Step 3 — keep them the same. Do whichever the
  user chooses; don't scaffold without asking.
- **Not in a git repo** — offer to initialize one (`git init`, or point them at
  a fresh repo). Cloud has nothing to connect without it.

Whichever it is, the repo must be on GitHub with at least one commit pushed
before Step 3; boards can follow, every push syncs.

## Step 1: Authenticate

Run a read-only verb (`dct cloud orgs`) first — if `DCT_CLOUD_TOKEN` is
already set or a token is already stored, it just works and this step is
done. Otherwise run `dct cloud login`. It prints a code and a URL; hand that
URL to the user — only they can complete the browser approval.

**You are not creating an account, and not having one is not a blocker.** All
you do is hand the user the login URL; on that page **signing in and signing
up happen in the same place** — the user can sign up right there, with no
separate registration step first. So never refuse this for "I can't make you
an account," and never point the user at another product's login. Let them
sign in or sign up at the `dct cloud login` URL, then pick or create the
organization the CLI should reach and approve.

`dct cloud login` blocks until the approval lands (it prints `Logged in`) or
the code expires (about 30 minutes; an expired code's page is a dead end, and
the only fix is running login again). Your shell tool's timeout is shorter
than that and the user may be slow, so run it like this:

```bash
dct cloud login > /tmp/dct-login.log 2>&1 &
sleep 2 && grep -o 'https://[^ ]*' /tmp/dct-login.log
```

Hand the user that URL **immediately, as the only thing you say** — no
summary first; every minute spent writing notes eats the code's lifetime.
Also say **which account** to approve with when they have several: the CLI
becomes whoever approves, so the org this creates or joins belongs to that
account, and the board URLs only open in a browser signed in as a member.
Then, in the same turn, wait in the foreground with your longest timeout:

```bash
until grep -qE 'Logged in|expired|denied|error' /tmp/dct-login.log; do sleep 5; done
cat /tmp/dct-login.log
```

This returns the moment the user approves, so you continue on your own —
don't ask the user to tell you when they're done. If the wait times out,
run the same `until` loop again; if the log says expired, start over from
the login command and hand over the new URL. Never guess a token value, and
never try to complete the browser step yourself — it is the user signing in,
not you.

## Step 2: Organization

List orgs (`dct cloud orgs`) — the consent screen in Step 1 always leaves at
least one, picked or created there. Note the slug of the one this repository
is for: Step 3 names it with `--org`. `project connect` never reads the
`dct cloud use` default (a repo being connected matches nothing yet, so the
default would silently answer every time), so `dct cloud use <org>` is
optional — it only saves `--org` on verbs run outside the repo later. `dct
cloud org create` remains available if the user wants to create an
additional organization later.

## Step 3: Connect the project

Do this right after login, while the user is still in the browser — not after
an hour of board authoring.

Pre-flight: with `gh` available, check `gh api repos/<owner>/<repo> --jq
.permissions.admin`. Cloud's repo picker only offers repos you administer —
a non-admin lands on a refusal page with no way forward. If the check fails,
tell the user up front whose account needs admin rights rather than sending
them into a dead end.

Two paths, both naming the org from Step 2 with `--org <org>`:

- **Public GitHub repo**: connect headlessly with
  `dct cloud project connect --org <org> --git-url
  https://github.com/<owner>/<repo>`. No browser hop.
- **Otherwise**: connect without a URL. It prints an install link and waits
  for the user to install the GitHub App and pick the repository. Run it in
  the background like login, hand over the link at once, and carry on with
  Step 4 while it waits:

  ```bash
  dct cloud project connect --org <org> --timeout 1800 > /tmp/dct-connect.log 2>&1 &
  sleep 2 && grep -o 'https://[^ ]*' /tmp/dct-connect.log
  ```

  Before Step 5, wait for it: `until grep -qE 'Picked|Connected|rror'
  /tmp/dct-connect.log; do sleep 5; done`. If the App already covers the
  repo, the pick is a single click. The page after the pick tells the user
  to come back to the terminal; nothing on it needs pressing.

## Step 4: Boards, if none exist yet

This skill connects a repo and a warehouse; it doesn't author boards. If the
repo has no boards the user actually authored — an empty `charts/`, or only
the starter board `dct init` scaffolds — hand off to the board-build skill
first: inspect the warehouse schema, author board YAML, validate and render
locally, commit, push. Don't render the starter board as if it were the
user's own board.

**Show the work.** As soon as one board renders locally, serve it:

```bash
dct serve > /tmp/dct-serve.log 2>&1 &
sleep 3 && grep -o 'http://[^ ]*' /tmp/dct-serve.log
```

Open that URL (`open` on macOS, `xdg-open` on Linux), tell the user it is
there — then keep going; this is not an approval stop. Leave it running: it
re-renders on every save, so the user watches boards appear while you finish
the Cloud side. One `dct serve` per repo; a second writer fights the first.

## Step 5: Warehouse connection

**Skip this whole step if every source is a file source.** A project whose
`sources:` are all `type: csv | json | parquet` needs no connection, no
credential and no mapping — it resolves from the repo. Go straight to Step 7.
`connections: 0` is the correct end state there, not an unfinished one.

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
create call also tests it, and a failing test saves nothing: the command exits
non-zero and prints the warehouse's own error. Fix the credential and re-run
the same command rather than moving on; there is no leftover connection to
delete first, and no need to invent a different alias.

Later verbs address the connection by its slug. Pass `--name` to choose it, or
let it default to the field that names the warehouse (BigQuery's `project`,
otherwise the `database`) and read the slug off the success line.

## Step 6: Map sources

Every board declares a `source:` name. Point each one at the connection you
just created — a file source (`type: csv`, `json`, `parquet`) needs no
mapping; it resolves straight from the repo with no connection step.

Cloud never reads a warehouse source's credential fields (`password:`,
`keyfile:`, an `env_var()` in either) from the committed `dbt_charts.yml`;
those are for local rendering. On Cloud the mapped connection supplies the
credential, so an unresolvable `env_var()` in the file is not an error there.

Mapping re-renders the project's boards on its own. The first render fired at
sync, before anything was mapped, so its cards read `ERR-SOURCE-NOT-FOUND ·
Available sources: none configured`; the mapping makes those renders stale
and Cloud sweeps them the way it does after a push. Give it a minute, then
read `dct cloud status` again rather than editing a board to provoke a render.

## Step 7: Render

Trigger rendering for the project's boards — but only once `dct cloud status`
shows no unmapped sources. Rendering an unmapped project succeeds
mechanically: every chart's query fails, the render still completes, and the
board is served as a page of error cards. That board is `errored`, not
`ready`: `status` counts it as `errored` on the project's `boards:` line and
names it on the project's own `boards with chart errors:` line, and `dct cloud boards`
reports it `errored` with the first chart's diagnostic. `ready` means a
render exists **and** its charts came back clean. Never tell the user the
boards are live while `status` still names a next step.

`dct cloud render` starts only boards that have no render yet. If a board
stays `errored` after its source is mapped and its query is right — the
warehouse opened a firewall, a credential was rotated on the connection —
`dct cloud render --force` re-renders every board with fresh query results.
It is a project admin's act: a Creator or Viewer gets the same not-found
answer any admin-only verb gives them.

## Step 8: Tell the user how to ship a change

Setup is day one; every day after is "I edited a board, get it live." Two
facts decide whether that works, and neither is discoverable:

- **A push republishes on its own, but not instantly.** For a repo
  connected through the GitHub App the push webhook syncs within seconds; a
  `--git-url` project is polled hourly and has no webhook at all. Don't sit
  watching for either — `dct cloud project sync` pulls the new commit and
  re-renders what changed. The verb returns as soon as the sync is queued;
  the new render is usually live about eight seconds later.
- **`ready` does not mean "your version".** `dct cloud boards` reports
  whether *a* render exists, not whether it is a render of your commit —
  there is no timestamp and no SHA. After a sync, confirm the change by
  looking at the board, not by reading a status.

Record where the project lives, too. Nothing in the repo says which org
publishes it, and the org slug is chosen at org creation — it has no
relationship to the GitHub owner, so it cannot be guessed from the remote. The
recovery is `dct cloud orgs` and then `dct cloud projects`, matching the
`REPOSITORY` column against the clone. Save the next person that hunt: put the
org and project slug in the repo's README as you finish.

## The loop that actually drives this

Don't hardcode the step order above as a fixed script — after step 2, drive
the rest from `dct cloud status`. It reports the org's setup stage and names
the exact next step in plain language (create a project, sync it, create or
test a connection, map a source, author and push a board, render). Read that
instruction, run the
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

`dct cloud status` reports every project done and names no next step, with
no unmapped sources, no unrendered boards, and no failed or errored boards
on any project's `boards:` line. A `boards:` line reading `unknown` for
`ready`/`errored` means this Cloud is older than this dct and hasn't
deployed that count yet — that is not a failure to fix, ignore it and judge
readiness from the rest of the line. A project can be `done` with a broken board
on it: `done`
means nothing is left for you to start, and the next step is what tells you
whether anything is left to fix. It reports stages and counts, not
addresses — read the
board URLs from `dct cloud boards` and give those to the user next to the
local URL, and say the local server is still running (`pkill -f "dct serve"`
stops it).

**Fetch the board before you hand it over.** Your own login token reads board
pages, so check each URL yourself instead of inferring from `status` that it
works:

```bash
TOKEN="${DCT_CLOUD_TOKEN:-$(awk '$1=="token:" {print $2}' \
  "${XDG_CONFIG_HOME:-$HOME/.config}/dbt-charts/config.yml")}"
dct cloud boards --json | jq -r '.boards[].url' | while read -r url; do
  printf '%s ' "$url"
  curl -sS -o /tmp/dct-board.html -w '%{http_code}\n' \
    -H "Authorization: Bearer $TOKEN" "$url"
done
```

`200` on every board, with the board's title in `/tmp/dct-board.html`, is the
check. Never echo `$TOKEN` — it is the user's credential.

A `403`, or a redirect to a login page, means your token did not authenticate
this fetch, not that the board is broken: report those boards as unverified
and hand the URLs over. Only the *completed* board is readable this way: if
`dct cloud boards` has not yet reported that board `ready`, wait rather than
reading the refusal as a failure. The fetch is read-only: it creates,
edits, and publishes nothing.

Tell the user how to ship their next change (Step 8) before you sign off —
`status` will never prompt you to.
