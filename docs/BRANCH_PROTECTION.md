# Branch protection — `main`

`main` is the release branch: every image published to GHCR is built from it (see
`.github/workflows/ci.yml`). Protect it so nothing merges without a green CI and history
can't be rewritten. This is a one-time GitHub setting (UI or API — it can't live in the
repo).

## Via the GitHub UI

**Settings → Branches → Add branch ruleset** (or *Add classic branch protection rule*),
target branch `main`, and enable:

- **Require a pull request before merging** — no direct pushes to `main`.
- **Require status checks to pass before merging**, and mark these checks required:
  - `test`
  - `images`
  - `security`
  (Search by name after at least one CI run has reported them.)
- **Require branches to be up to date before merging** (so checks run against the merge).
- **Block force pushes** (classic: uncheck *Allow force pushes*).
- **Restrict deletions** (classic: uncheck *Allow deletions*).

Leave "Do not allow bypassing the above settings" on so admins are held to the same gate.

## Via the API (equivalent)

Requires an admin token. Classic protection:

```bash
gh api --method PUT repos/GridixCompute/Gridix-infra/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_pull_request_reviews.required_approving_review_count=0' \
  -F 'required_status_checks.strict=true' \
  -f 'required_status_checks.checks[][context]=test' \
  -f 'required_status_checks.checks[][context]=images' \
  -f 'required_status_checks.checks[][context]=security' \
  -F 'enforce_admins=true' \
  -F 'restrictions=null' \
  -F 'allow_force_pushes=false' \
  -F 'allow_deletions=false'
```

## Result (Definition of Done)

- A PR whose `test` (or `images`/`security`) check is red **cannot be merged**.
- `main` cannot be force-pushed or deleted.
- All changes reach `main` through a pull request.
