# gitverify

A self-hosted CLI that scores a GitHub profile's authenticity from public
signals — commits, PRs, issues, releases, CI, ownership — instead of a
self-reported resume. Runs locally with your own token; nothing is sent
anywhere except GitHub's API.

The score is split into 4 axes, weighted by how hard each is to fake:

- **impact** (0.35) — stars/forks, a signal the account owner doesn't control
- **consistency** (0.30) — account age, activity spread over time, server-timestamped events
- **authenticity** (0.20) — owned repos vs forks
- **craft** (0.15) — CI, tests, releases

Bands: `Strong` (≥70) / `Solid` (≥35) / `Thin` (below).

## Install

```
pipx install .
```

or, without installing:

```
uvx --from . gitverify <handle>
```

## Auth

Log in once — no token to create by hand:

```
gitverify auth login
```

This opens a code you enter at github.com/login/device; the token is cached
at `~/.config/gitverify/token`. `gitverify auth logout` clears it.

For CI/scripting (no interactive browser), export a token with `read:user`
scope instead:

```
export GITHUB_TOKEN=ghp_...
gitverify <handle>
```

## Usage

```
gitverify octocat
gitverify octocat --json
```

## Development

```
pip install -e .
python -m gitverify <handle>
```
