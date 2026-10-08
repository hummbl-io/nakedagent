# Trusted publishing across registries

Companion to `PUBLISHING_RUNBOOK.md` (PyPI). Question answered here: for each language we plan to
port nakedagent to, can we publish the way we do on PyPI, with short-lived OIDC credentials and no
stored token? Researched 2026-10-08 from the registries' own documentation; every claim below links
its source, and anything not confirmed is marked **unverified**.

## How the PyPI flow works (the model to copy)

`.github/workflows/publish-pypi.yml` runs on a `v*` tag, verifies the tag is on `main`, builds, then a
publish job with `permissions: id-token: write` and `environment: pypi` presents GitHub's OIDC token to
PyPI, which exchanges it for a short-lived upload token scoped to that project. The registry-side
"trusted publisher" record pins owner, repository, workflow file and environment. No secret is stored.

## Summary

| Language | Registry | OIDC trusted publishing? | First release | Registry-side config | CI action |
|---|---|---|---|---|---|
| Python | PyPI | yes (in use) | n/a | publisher record: owner, repo, workflow, environment | `pypa/gh-action-pypi-publish` |
| Rust | crates.io | **yes** (GitHub Actions only) | **manual**, with a token | crate settings -> trusted publisher: owner, repo, workflow file, optional environment | `rust-lang/crates-io-auth-action@v1` |
| Node | npm | **yes** (GitHub Actions, GitLab, CircleCI; GitHub-hosted runners only) | package must **already exist** | package settings -> trusted publisher: workflow filename, owner, repo, optional environment | none; npm CLI >= 11.5.1 and Node >= 22.14 |
| Deno | JSR | **yes** (GitHub Actions only) | create the package on JSR first (the docs imply this but do not say it outright), then link the repo | package settings -> link GitHub repo | `deno publish` (no extra action) |
| Ruby | RubyGems | **yes** | **no manual step**: a "pending" publisher can be created before the gem exists | gem page -> Trusted publishers (or pending publisher): owner, repo, workflow, environment | `rubygems/release-gem` |
| C# | NuGet | **yes** (GitHub Actions, GitLab) | policy can be created up front; temporary for 7 days on private repos | nuget.org -> Trusted Publishing policy: owner, repo, workflow file, optional environment | `NuGet/login@v1` |
| Java | Maven Central | **no** (user token only, as documented) | n/a | none | none; token plus PGP signing key as secrets |
| Haskell | Hackage | **no** (feature request open) | n/a | none | API token as a secret |
| Go | module proxy | n/a: nothing is uploaded | n/a | none | a signed, protected tag is the release |
| Swift | SwiftPM / Swift Package Index | n/a: nothing is uploaded | n/a | none (index submission is separate) | a signed, protected tag is the release |

## Per registry

### crates.io (Rust): yes
* "To get started with Trusted Publishing, you'll need to publish your first release manually"; after that the crate owner
  adds a trusted publisher in the crate's settings (GitHub owner, repository, workflow file under `.github/workflows/`,
  optional environment). GitHub Actions only for now. [Rust blog, 2025-07-11](https://blog.rust-lang.org/2025/07/11/crates-io-development-update-2025-07).
* In the workflow, `rust-lang/crates-io-auth-action@v1` exchanges the OIDC token for a short-lived token that is passed to
  `cargo publish` as `CARGO_REGISTRY_TOKEN` and revoked when the job ends. [action](https://github.com/rust-lang/crates-io-auth-action).
  A third-party summary puts the lifetime at about 30 minutes (**unverified** against crates.io docs).
* Needs: the crates.io account you already created, one manual first publish with a short-lived scoped token that you then delete.

### npm (Node): yes
* Needs npm CLI >= 11.5.1 and Node >= 22.14; **the package must already exist**; supports GitHub Actions (GitHub-hosted
  runners), GitLab.com shared runners and CircleCI cloud; self-hosted runners are not supported. Up to 10 trusted publishers
  per package. A new configuration must complete a successful publish within 2 days. Existing configurations cannot be edited
  (delete and recreate). Provenance is automatic for public repos and public packages, not private. **Tokens stay allowed unless
  you restrict them**, so tighten the package's publishing access after switching. [npm docs](https://docs.npmjs.com/trusted-publishers),
  [GitHub changelog](https://github.blog/changelog/2025-07-31-npm-trusted-publishing-with-oidc-is-generally-available/).
* The very first publish of a new package therefore needs a token (or a placeholder publish), then switch.

### JSR (Deno): yes
* Link the GitHub repository in the package's settings; the workflow needs `contents: read` and `id-token: write`;
  provenance is generated automatically. "Tokenless OIDC publishing is only available from GitHub Actions." `deno publish` skips
  a version that is already published. [JSR docs](https://jsr.io/docs/publishing-packages).
* Node ports can also be published to JSR; that is optional and separate from npm.

### RubyGems (Ruby): yes, and best onboarding of the lot
* Create a **pending** trusted publisher before the gem exists (owner, repo, workflow, environment); the first successful push
  turns it into a normal one and makes the pusher the gem owner. Recommended action: `rubygems/release-gem`; the job needs
  `id-token: write`. [RubyGems guide](https://guides.rubygems.org/trusted-publishing).

### NuGet (C#): yes
* Add a policy at nuget.org (Trusted Publishing): repository owner, repository, workflow file name only, optional environment;
  policy owner is a user or an organisation and goes inactive if that owner changes. In CI, `NuGet/login@v1` exchanges the OIDC
  token for a temporary API key valid for **1 hour**, one token per key. Policies for private repos are active for 7 days until
  a publish records the repo and owner IDs. [Microsoft Learn](https://learn.microsoft.com/nuget/nuget-org/trusted-publishing).

### Maven Central (Java): no OIDC, per the Central Portal docs
* The Portal publishing API authenticates with a **user token** generated on the account page; the page describes no OIDC or
  tokenless CI option. [Central Portal API](https://central.sonatype.org/publish/publish-portal-api/). That page not mentioning
  OIDC is evidence, not proof; recheck Sonatype's announcements before relying on it.
* Central also requires signed artifacts (PGP). That is from general knowledge, **unverified here**; confirm before building the workflow.
* Plan: store the Portal token and a dedicated signing key as secrets of a protected GitHub environment (see "Compensating controls").

### Hackage (Haskell): no
* Hackage tokens have unbounded lifetime and cover every package the user maintains; trusted publishing was requested in
  [haskell/hackage-server#1443](https://github.com/haskell/hackage-server/issues/1443) (opened 2025-11-30). When I read it the page showed
  no maintainer response or linked work; I could not confirm anything newer, so **treat it as unsupported and recheck**.
  `haskell-actions/hackage-publish` is named in the issue as an existing release helper (not evaluated).
* Plan: Hackage API token from a dedicated bot account that maintains only this package, stored as an environment secret.

### Go and Swift: nothing to upload
* Go modules and Swift packages are released by pushing a semver git tag; there is no registry credential to protect
  ([Swift Package Index](https://swiftpackageindex.com/blog/what-is-a-package-registry)). The control that matters is who can create
  tags, so protect them (below). For a Go module that lives in a subdirectory of this repo, the tag must be prefixed with the
  directory (for example `ports/go/v0.1.0`); **confirm the exact tag rule against the Go modules reference before the first release**.

## Compensating controls where OIDC is unavailable (Maven Central, Hackage)

1. One protected GitHub **environment** per registry holding the secret, with required reviewers, restricted to the `main` and tag refs.
2. Secret exists only for the publish job; the build job has no access. Pin third-party actions by commit SHA as the PyPI workflow does.
3. Dedicated bot/publisher account per registry, maintainer of this project only, with a scoped token where the registry allows it.
4. Rotate on a calendar and after any change of maintainer; record the expiry date next to the secret.
5. Re-check quarterly whether the registry has shipped OIDC, and switch when it does.

## Controls that apply to every registry

* Release only from tags on `main` (the PyPI workflow already verifies this); protect the `v*` tag pattern with a repository ruleset.
* Request `id-token: write` only on the publish job, never at workflow level.
* Set the registry-side environment name to match a GitHub environment that requires approval.
* Verify the version in the manifest equals the tag, run the port's conformance vectors, and assert zero runtime dependencies before publishing
  (the PyPI workflow's `Check zero runtime dependencies` step is the model).
* After a trusted publisher works, delete the bootstrap token and, where the registry allows, disallow token publishing (npm).

## What to do now

1. **crates.io:** publish a `0.0.1` placeholder or the first real release by hand, add the trusted publisher, delete the token.
2. **RubyGems, NuGet, JSR:** register the publisher or policy first; no first-publish token needed for RubyGems and NuGet.
3. **npm:** create the package (first publish by hand), then configure the trusted publisher and restrict tokens.
4. **Maven Central and Hackage:** create the bot accounts, environments and secrets; accept the token risk and document the rotation date.
5. **Go and Swift:** add the tag ruleset; nothing else.

Reference for the cross-registry design: [OpenSSF, Trusted Publishers for All Package Repositories](https://repos.openssf.org/trusted-publishers-for-all-package-repositories).
