import json
import os
import re
import subprocess
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

AUTHORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "authors.json")

DEFAULT_AUTHORS = [
    "delfianura",
    "denayarahaya",
    "dimitrijrs",
    "henry-wicaksono",
    "kevin-yauris",
    "michellshandaka",
]

GITHUB_REPO = "GDP-ADMIN/gl-sdk"
GITHUB_ORG = "GDP-ADMIN"
GITHUB_PROJECT_NUMBER = 69
GITHUB_GRAPHQL = "https://api.github.com/graphql"


def _get_github_token() -> str | None:
    """Try GITHUB_TOKEN env var first, then fall back to `gh auth token`."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _graphql_headers():
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "gl-sdk-backlog-manager",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"bearer {token}"
    return headers


def _graphql(query, variables=None):
    """Execute a GitHub GraphQL query and return the full response."""
    resp = requests.post(
        GITHUB_GRAPHQL,
        headers=_graphql_headers(),
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GraphQL API error (HTTP {resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data


def _get_project_metadata():
    """Fetch the project's node ID and field definitions."""
    query = """
    query($org: String!, $projectNumber: Int!) {
      organization(login: $org) {
        projectV2(number: $projectNumber) {
          id
          fields(first: 20) {
            nodes {
              __typename
              ... on ProjectV2Field { id name }
              ... on ProjectV2SingleSelectField { id name }
              ... on ProjectV2IterationField { id name }
            }
          }
        }
      }
    }
    """
    result = _graphql(query, {"org": GITHUB_ORG, "projectNumber": GITHUB_PROJECT_NUMBER})
    return result.get("data", {}).get("organization", {}).get("projectV2")


_project_cache = {"items": None, "timestamp": 0}


def _get_project_items(project_id):
    """Return dict[issue_number] -> {status: str, team: str}.

    Only fetches items belonging to GITHUB_REPO.  Caches for 5 minutes.
    """
    now = time.time()
    if _project_cache["items"] is not None and now - _project_cache["timestamp"] < 300:
        return _project_cache["items"]

    items = {}
    cursor = None
    page_count = 0
    MAX_PAGES = 20

    query = """
    query($projectId: ID!, $cursor: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              content {
                __typename
                ... on Issue {
                  number
                  repository { nameWithOwner }
                }
              }
              fieldValues(first: 20) {
                nodes {
                  __typename
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    field { ... on ProjectV2SingleSelectField { name } }
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    while page_count < MAX_PAGES:
        page_count += 1
        result = _graphql(query, {"projectId": project_id, "cursor": cursor})
        page = result["data"]["node"]["items"]

        for node in page.get("nodes", []):
            if not node or not node.get("content"):
                continue
            # Only keep issues from our target repo
            repo = (node["content"].get("repository") or {}).get("nameWithOwner", "")
            if repo != GITHUB_REPO:
                continue

            issue_number = node["content"]["number"]
            info = {"status": "", "team": ""}

            for fv in (node.get("fieldValues") or {}).get("nodes", []):
                if not fv or fv["__typename"] != "ProjectV2ItemFieldSingleSelectValue":
                    continue
                field_name = (fv.get("field") or {}).get("name", "")
                val = fv.get("name", "")
                if field_name == "Status":
                    info["status"] = val
                elif field_name == "Team":
                    info["team"] = val

            items[issue_number] = info

        pag = page.get("pageInfo", {})
        if not pag.get("hasNextPage"):
            break
        cursor = pag.get("endCursor")

    _project_cache["items"] = items
    _project_cache["timestamp"] = now
    return items


def _fetch_project_data():
    """High-level helper: returns (project_items_dict, error_string_or_None)."""
    try:
        project = _get_project_metadata()
        if not project:
            return {}, "Project not found"
        return _get_project_items(project["id"]), None
    except Exception as e:
        app.logger.warning("Failed to fetch project data: %s", e)
        return {}, str(e)


def load_authors():
    if os.path.exists(AUTHORS_FILE):
        with open(AUTHORS_FILE) as f:
            return json.load(f)
    return list(DEFAULT_AUTHORS)


def save_authors(authors):
    with open(AUTHORS_FILE, "w") as f:
        json.dump(authors, f, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/issues")
def get_issues():
    selected_authors = request.args.getlist("author")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "gl-sdk-backlog-manager",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"

    params = {"state": "open", "per_page": 100, "direction": "desc"}

    # GitHub API paginates — fetch every page via Link header
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    all_raw = []

    while url:
        resp = requests.get(url, headers=headers, params=params if "?" not in url else None, timeout=30)
        resp.raise_for_status()
        all_raw.extend(resp.json())

        # Follow rel="next" if present
        link = resp.links.get("next")
        url = link["url"] if link else None
        params = None  # params are already baked into the next URL

    # GitHub's issues endpoint returns PRs mixed in — filter them out
    issues = [i for i in all_raw if "pull_request" not in i]

    result = []
    title_pattern = re.compile(r"^\[[a-z-]+\]")
    for issue in issues:
        created_at = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
        result.append(
            {
                "number": issue["number"],
                "title": issue["title"],
                "created_at": created_at.strftime("%b %d, %Y"),
                "author": issue["user"]["login"],
                "author_avatar": issue["user"]["avatar_url"],
                "html_url": issue["html_url"],
                "node_id": issue["node_id"],
                "labels": [
                    {"name": l["name"], "color": l["color"]} for l in issue["labels"]
                ],
                "comments": issue["comments"],
                "state": issue["state"],
                "title_check": bool(title_pattern.match(issue["title"])),
                "in_project": False,
                "project_status": "",
                "project_team": "",
            }
        )

    # Enrich with project-board data
    project_items, _ = _fetch_project_data()
    for issue_data in result:
        pinfo = project_items.get(issue_data["number"])
        if pinfo:
            issue_data["in_project"] = True
            issue_data["project_status"] = pinfo.get("status", "")
            issue_data["project_team"] = pinfo.get("team", "")

    if selected_authors:
        result = [i for i in result if i["author"] in selected_authors]

    return jsonify(result)


@app.route("/api/authors", methods=["GET", "POST"])
def handle_authors():
    if request.method == "POST":
        data = request.json
        if not isinstance(data, list):
            return jsonify({"error": "Expected a list of usernames"}), 400
        save_authors(data)
        return jsonify({"status": "ok"})
    return jsonify(load_authors())


@app.route("/api/issues/<int:number>/title", methods=["PATCH"])
def update_issue_title(number):
    data = request.json
    new_title = data.get("title", "").strip()
    if not new_title:
        return jsonify({"error": "Title is required"}), 400

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "gl-sdk-backlog-manager",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"

    resp = requests.patch(
        f"https://api.github.com/repos/{GITHUB_REPO}/issues/{number}",
        headers=headers,
        json={"title": new_title},
        timeout=30,
    )
    if not resp.ok:
        msg = resp.json().get("message", "GitHub API error")
        return jsonify({"error": msg}), resp.status_code

    return jsonify({"status": "ok", "title": new_title})


@app.route("/api/issues/<int:number>/add-to-project", methods=["POST"])
def add_issue_to_project(number):
    data = request.json
    node_id = data.get("node_id")
    if not node_id:
        return jsonify({"error": "node_id is required"}), 400

    # Resolve project ID
    project = _get_project_metadata()
    if not project:
        return jsonify({"error": "Project not found or inaccessible"}), 404

    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
        item { id }
      }
    }
    """
    try:
        _graphql(mutation, {"projectId": project["id"], "contentId": node_id})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=5050, debug=True)
