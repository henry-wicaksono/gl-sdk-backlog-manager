# GL SDK Backlog Manager

Browse and filter open GitHub issues from the [GL SDK](https://github.com/GDP-ADMIN/gl-sdk) repo. A Flask app for backlog triage with project board integration.

## Features

- **Issue table** — all open issues from `GDP-ADMIN/gl-sdk` with key metadata
- **Title Check** — validates the `[category]` convention (lowercase + dashes); click ❌ to fix a title inline
- **Project board** — shows which issues are on the [project board](https://github.com/orgs/GDP-ADMIN/projects/69), along with their **Status** and **Team** values; click ❌ to add an issue to the board
- **Backlog tag** — check/set the "GL SDK Backlog" Story/Tag via a single click
- **Author filter** — select/deselect authors from the sidebar; updates instantly
- **Statistics card** — live counts for total issues, filter matches, title check pass/fail, project board status, and backlog tag
- **Collapsible guide** — explains each column and action (click to toggle)
- **Inline title editing** — click ❌ on a failing Title Check to edit the issue title directly
- **GitHub integration** — all mutations (title update, add to project, toggle tag) go through the authenticated GitHub API

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager
- **GitHub authentication** — one of:
  - `gh` CLI logged in (`gh auth login`)
  - `GITHUB_TOKEN` environment variable set to a [personal access token](https://github.com/settings/tokens) with `repo` and `project` scopes

## Setup

```bash
git clone https://github.com/henry-wicaksono/gl-sdk-backlog-manager.git
cd gl-sdk-backlog-manager
uv sync
```

## Run

```bash
uv run python app.py
```

Open http://localhost:5050 in your browser.

Or use the Makefile shortcut:

```bash
make start
```

## How it works

The app fetches all open issues from `GDP-ADMIN/gl-sdk` via the GitHub REST API, then enriches each issue with project board data via the GraphQL API. The display is split into a sidebar (author filter + statistics) and a main area (guide + table).

## Configuration

- **Tracked authors** — defined in `app.py` (`DEFAULT_AUTHORS`). Add/remove from the UI; saved to `authors.json` (git-ignored).
- **Target repo** — change `GITHUB_REPO` in `app.py` to point at a different repository.
- **Project board** — change `GITHUB_PROJECT_NUMBER` (default: `69`) in `app.py`.
