import json
import os
import re
import subprocess
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
              ... on ProjectV2SingleSelectField { id name options { id name } }
              ... on ProjectV2IterationField { id name }
            }
          }
        }
      }
    }
    """
    result = _graphql(query, {"org": GITHUB_ORG, "projectNumber": GITHUB_PROJECT_NUMBER})
    return result.get("data", {}).get("organization", {}).get("projectV2")


def _enrich_issues_with_project_data(issues):
    """Add in_project, project_status, project_team to each issue dict in-place.

    Batch-queries each issue's projectItems via GraphQL nodes() —
    far faster than paginating through the entire project board.
    """
    try:
        project = _get_project_metadata()
        if not project:
            return
        project_id = project["id"]
    except Exception as e:
        app.logger.warning("Failed to fetch project metadata: %s", e)
        return

    node_ids = [i["node_id"] for i in issues]
    if not node_ids:
        return

    query = """
    query($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on Issue {
          number
          projectItems(first: 5) {
            nodes {
              id
              project { id }
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

    project_map = {}
    # GitHub accepts up to ~100 IDs per nodes() call
    for i in range(0, len(node_ids), 100):
        chunk = node_ids[i : i + 100]
        try:
            result = _graphql(query, {"ids": chunk})
        except Exception as e:
            app.logger.warning("GraphQL batch query failed: %s", e)
            continue

        for node in result["data"]["nodes"]:
            if not node:
                continue
            issue_number = node["number"]
            our_items = [
                item
                for item in (node.get("projectItems") or {}).get("nodes", [])
                if item and item.get("project", {}).get("id") == project_id
            ]
            if not our_items:
                continue
            item = our_items[0]
            info = {"status": "", "team": "", "story_tag": "", "project_item_id": item.get("id")}
            for fv in (item.get("fieldValues") or {}).get("nodes", []):
                if not fv or fv["__typename"] != "ProjectV2ItemFieldSingleSelectValue":
                    continue
                field_name = (fv.get("field") or {}).get("name", "")
                val = fv.get("name", "")
                if field_name == "Status":
                    info["status"] = val
                elif field_name == "Team":
                    info["team"] = val
                elif field_name == "Story/Tag":
                    info["story_tag"] = val
            project_map[issue_number] = info

    for issue in issues:
        pinfo = project_map.get(issue["number"])
        if pinfo:
            issue["in_project"] = True
            issue["project_status"] = pinfo["status"]
            issue["project_team"] = pinfo["team"]
            issue["project_item_id"] = pinfo["project_item_id"]
            issue["story_tag"] = pinfo["story_tag"]


def _get_project_metadata_for_mutation():
    """Fetch just the project ID (no fields) — used by the add-to-project endpoint."""
    query = """
    query($org: String!, $projectNumber: Int!) {
      organization(login: $org) { projectV2(number: $projectNumber) { id } }
    }
    """
    result = _graphql(query, {"org": GITHUB_ORG, "projectNumber": GITHUB_PROJECT_NUMBER})
    return result.get("data", {}).get("organization", {}).get("projectV2")


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
                "project_item_id": None,
                "story_tag": "",
            }
        )

    # Enrich with project-board data
    _enrich_issues_with_project_data(result)

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
    project = _get_project_metadata_for_mutation()
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
        result = _graphql(mutation, {"projectId": project["id"], "contentId": node_id})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    item_id = result["data"]["addProjectV2ItemById"]["item"]["id"]
    return jsonify({"status": "ok", "project_item_id": item_id})


@app.route("/api/issues/<int:number>/toggle-backlog", methods=["POST"])
def toggle_backlog(number):
    data = request.json
    project_item_id = data.get("project_item_id")
    current_value = data.get("current_value", "")

    if not project_item_id:
        return jsonify({"error": "project_item_id is required"}), 400

    # Resolve project and Story/Tag field info
    project = _get_project_metadata()
    if not project:
        return jsonify({"error": "Project not found"}), 404

    story_tag_field_id = None
    backlog_option_id = None
    for field in project.get("fields", {}).get("nodes", []):
        if field.get("__typename") == "ProjectV2SingleSelectField" and field["name"] == "Story/Tag":
            story_tag_field_id = field["id"]
            for opt in field.get("options", []):
                if opt["name"] == "GL SDK Backlog":
                    backlog_option_id = opt["id"]
                    break
            break

    if not story_tag_field_id or not backlog_option_id:
        return jsonify({"error": "Story/Tag field or GL SDK Backlog option not found"}), 500

    # Toggle: if currently "GL SDK Backlog", clear it; otherwise set it
    new_value = "" if current_value == "GL SDK Backlog" else "GL SDK Backlog"
    option_id = None if current_value == "GL SDK Backlog" else backlog_option_id

    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String) {
      updateProjectV2ItemFieldValue(
        input: {
          projectId: $projectId
          itemId: $itemId
          fieldId: $fieldId
          value: { singleSelectOptionId: $optionId }
        }
      ) { projectV2Item { id } }
    }
    """
    try:
        _graphql(
            mutation,
            {
                "projectId": project["id"],
                "itemId": project_item_id,
                "fieldId": story_tag_field_id,
                "optionId": option_id,
            },
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok", "story_tag": new_value})


if __name__ == "__main__":
    app.run(port=5050, debug=True)
