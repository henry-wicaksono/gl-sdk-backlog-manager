# GL SDK Backlog Manager

Browse and filter open GitHub issues from the [GL SDK](https://github.com/GDP-ADMIN/gl-sdk) repo by author. A lightweight Flask app for backlog triage.

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager (install once: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **GitHub authentication** — one of:
  - `gh` CLI logged in (`gh auth login`) — the app will use `gh auth token`
  - `GITHUB_TOKEN` environment variable set to a [personal access token](https://github.com/settings/tokens)

## Setup

```bash
# Clone the repo
git clone https://github.com/henry-wicaksono/gl-sdk-backlog-manager.git
cd gl-sdk-backlog-manager

# Install dependencies
uv sync
```

## Run

```bash
uv run python app.py
```

Then open http://localhost:5050 in your browser.

Or use the Makefile shortcut:

```bash
make start
```

## How it works

The app fetches all open issues from `GDP-ADMIN/gl-sdk` via the GitHub API, displays them in a table, and lets you filter by author.

- **Author chips** — click to toggle which authors to include. Filtering is applied immediately.
- **Select all / Deselect all** — bulk toggle the author chips.
- **Update** — re-fetch the latest issues from GitHub (author filters are preserved).
- All author selections are stored in `authors.json` (git-ignored) so your custom list persists.

## Configuration

- The default tracked authors are defined in `app.py` (`DEFAULT_AUTHORS`). You can add/remove authors from the UI — they're saved to `authors.json` in the project root.
- The target repo is hardcoded at the top of `app.py` (`GITHUB_REPO`). Change it there if you want to point at a different repository.
