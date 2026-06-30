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


def _get_github_token() -> str | None:
    """Try GITHUB_TOKEN env var first, then fall back to `gh auth token`."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


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
        resp = requests.get(url, headers=headers, params=params if "?" not in url else None)
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
                "labels": [
                    {"name": l["name"], "color": l["color"]} for l in issue["labels"]
                ],
                "comments": issue["comments"],
                "state": issue["state"],
                "title_check": bool(title_pattern.match(issue["title"])),
            }
        )

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


if __name__ == "__main__":
    app.run(port=5050, debug=True)
