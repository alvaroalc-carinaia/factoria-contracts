#!/usr/bin/env python3
"""Deterministic, read-only, fail-closed eligibility check.

NO LLM calls, NO Jira state writes. This supplements (does not replace) the
orchestrator's own re-check just before In Progress.

Zero configuration, like the previous pilot (Licitaciones PR #16 / contracts
PR #5): with ``--issue`` it checks exactly that key and no other. With an
empty ``--issue`` it selects deterministically (REST/JQL, no LLM) up to
``--max-issues`` eligible issues (1–3, default 3) by Jira ``Rank ASC``
(Ready/Listo + agent-ready + ONLY engine-opencode, every blocker
Done/Finalizada or covered by the pinned agent PR head, no existing ``agent/<key>`` branch/PR). Automatic builds
can pass ``--wait`` to admit later waves within one shared deadline and cap.
"""
import argparse
import base64
from functools import cache
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
# "Repository: owner/repo", "Repositorio: owner/repo" or
# "Repositorio destino: owner/repo" (markdown bold/code and a github.com URL
# are tolerated). No declaration => defaults to the current GITHUB_REPOSITORY.
REPO_LINE = re.compile(
    r"(?im)^[\s>*_`-]*(?:Repository|Repositorio(?:\s+destino)?)[*_`\s]*:[*_`\s]*"
    r"(?:https?://github\.com/)?([\w.\-]+(?:/[\w.\-]+)?)"
)
TEXT_BLOCKER = re.compile(
    r"(?i)\b(?:blocked\s+by|is\s+blocked\s+by|depends\s+on|requires|"
    r"bloquead[oa]\s+por|depende\s+de|prerrequisito(?:s)?)\s*\)?\s*[:\-]?\s*"
    r"((?:[A-Z][A-Z0-9_]*-[0-9]+)(?:\s*[,;/y&]\s*"
    r"[A-Z][A-Z0-9_]*-[0-9]+)*)"
)
BLOCKER_WORDS = ("is blocked by", "blocked by", "depends on", "requires", "depende de", "bloqueado por", "bloqueada por")
OUTWARD_DEPENDS = ("depends on", "requires", "depende de")
DEPENDENCY_HEADERS = ("dependencies", "dependencias", "prerequisites", "prerrequisitos", "blocking issues")

# Same rule as the Claude contract (multiprovider/claude/
# 01-jira-three-parallel-STRICT-ROUTING.md, "Localized status names") and the
# Cursor contract (multiprovider/cursor/01-scheduled-implement.md):
#   "Jira may return translated status.name values depending on the account
#    language. Treat Ready and Listo as the same status, and Done and
#    Finalizada as the same status, in every check of this contract (candidate
#    selection, dependency gate and re-checks). Any other name is not
#    Ready/Done."
# Only case/whitespace normalization is permitted. No configuration needed:
# JIRA_READY_STATUS / JIRA_DONE_STATUS are deliberately NOT honoured, so the
# three providers behave identically.
STATUS_EQUIVALENTS = {
    "ready": ("Ready", "Listo"),
    "done": ("Done", "Finalizada"),
}
DEFAULT_HUMAN_REVIEW_STATUS = "Human Review"
ENGINES = {"engine-claude", "engine-cursor", "engine-opencode"}
WAIT_SECONDS = 340 * 60
POLL_SECONDS = 10 * 60


def accepted_statuses(env_name, kind):
    """Return the accepted names for ``kind``. ``env_name`` is ignored on purpose."""
    names = STATUS_EQUIVALENTS[kind]
    return {n.casefold() for n in names}, "/".join(names)


def status_is(name, kind):
    return " ".join(str(name or "").split()).casefold() in accepted_statuses(None, kind)[0]


class GateError(Exception):
    pass


class GateInfraError(GateError):
    """Jira/GitHub unreachable or unverifiable: abort the run, never skip silently."""


class AgentDependenciesPending(GateError):
    """Only known, agent-owned prerequisites prevent admission on this scan."""


INLINE_ADF = {"text", "hardBreak", "mention", "emoji", "inlineCard", "date", "status"}


def flatten_adf(content):
    """ADF -> text. Inline runs of a paragraph stay on ONE line (so
    "**Repositorio destino:** `owner/repo`" is one line); blocks and hardBreak
    become newlines."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if content and all(isinstance(x, dict) and x.get("type") in INLINE_ADF for x in content):
            return "".join(flatten_adf(x) for x in content)
        return "\n".join(filter(None, (flatten_adf(x) for x in content)))
    if isinstance(content, dict):
        kind = content.get("type")
        if kind == "hardBreak":
            return "\n"
        if kind == "text":
            return str(content.get("text", ""))
        if kind == "mention":
            return str((content.get("attrs") or {}).get("text", ""))
        if kind == "inlineCard":
            return str((content.get("attrs") or {}).get("url", ""))
        if "content" in content:
            return flatten_adf(content["content"])
        return ""
    return ""


def declared_repositories(description):
    found = []
    for raw in REPO_LINE.findall(description or ""):
        value = raw.strip().rstrip(".,;:")
        if value.lower().endswith(".git"):
            value = value[:-4]
        if value:
            found.append(value)
    return found


def extract_text_blockers(text):
    blockers = set()
    for m in TEXT_BLOCKER.finditer(text):
        blockers.update(re.findall(r"[A-Z][A-Z0-9_]*-\d+", m.group(1)))
    # Support explicit '## Dependencies' sections when an item is just an issue key.
    lines = text.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip().lstrip("# ").strip().lower()
        header, sep, value = stripped.partition(":")
        if sep and header.strip() in DEPENDENCY_HEADERS:
            in_section = not value.strip()
            if value.strip() and value.strip() not in ("none", "ninguna", "ninguno"):
                keys = re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", line.partition(":")[2])
                if not keys:
                    raise GateError("Ambiguous textual dependency without Jira key")
                blockers.update(keys)
            continue
        if line.lstrip().startswith("#"):
            in_section = any(stripped.startswith(h) for h in DEPENDENCY_HEADERS)
            continue
        if in_section and (line.strip() == "" or line.lstrip().startswith(("-", "*"))):
            if any(word in stripped for word in ("none", "ninguna", "ninguno")):
                continue
            blockers.update(re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", line))
        elif in_section and line.strip() and not line.lstrip().startswith(("-", "*")):
            # A section with unclear prose: leave interpretation to orchestrator;
            # a documented ambiguity would be safer than trusting a clean gate.
            if any(x in stripped for x in ("pending", "pendiente", "blocked", "bloquead")) and not re.search(r"[A-Z][A-Z0-9_]*-\d+", line):
                raise GateError("Ambiguous textual dependency without Jira key")
    return blockers


def blocking_links(links):
    if not isinstance(links, list):
        raise GateError("Jira issue links missing/invalid")
    found = set()
    for link in links:
        if not isinstance(link, dict):
            raise GateError("Malformed Jira issue link")
        relation = link.get("type") or {}
        if not isinstance(relation, dict):
            raise GateError("Malformed Jira link type")
        inward = (relation.get("inward") or "").lower().strip()
        outward = (relation.get("outward") or "").lower().strip()
        name = (relation.get("name") or "").lower().strip()
        for direction, label in (("inwardIssue", inward), ("outwardIssue", outward)):
            linked = link.get(direction)
            if linked is None:
                continue
            key = linked.get("key") if isinstance(linked, dict) else None
            if not isinstance(key, str) or not KEY.fullmatch(key):
                raise GateError("Malformed linked Jira issue key")
            if any(s in label for s in BLOCKER_WORDS) or (direction == "outwardIssue" and any(s in label for s in OUTWARD_DEPENDS)):
                found.add(key)
            elif ("block" in name or "depend" in name or "bloque" in name) and not label:
                raise GateError("Ambiguous dependency direction in Jira issue link")
    return found


def dependency_field_keys(value):
    """A configured prerequisites field may contain Jira issue objects or text."""
    if value is None:
        return set()
    if isinstance(value, list):
        return {key for item in value for key in dependency_field_keys(item)}
    if isinstance(value, dict) and "key" in value:
        key = value["key"]
        if isinstance(key, str) and KEY.fullmatch(key):
            return {key}
        raise GateError("Invalid issue key in dependency field")
    text = flatten_adf(value).strip()
    if not text and not isinstance(value, str):
        raise GateError("Unreadable dependency field")
    if text.casefold() in ("", "none", "ninguna", "ninguno"):
        return set()
    keys = set(re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", text))
    if not keys:
        raise GateError("Ambiguous dependency field without Jira key")
    return keys


def jira_client():
    base = os.environ["JIRA_URL"].rstrip("/")
    user = os.environ["JIRA_USERNAME"]
    token = os.environ["JIRA_API_TOKEN"]
    creds = base64.b64encode(f"{user}:{token}".encode()).decode()
    if not base.startswith("https://"):
        raise GateError("JIRA_URL must use HTTPS")

    def get_issue(key):
        if not KEY.fullmatch(key):
            raise GateError("Invalid Jira key")
        selected = ["summary", "status", "labels", "description", "issuelinks"]
        for config_name in ("JIRA_REPOSITORY_FIELD_ID", "JIRA_DEPENDENCIES_FIELD_ID"):
            if os.environ.get(config_name):
                selected.append(os.environ[config_name])
        fields = ",".join(selected)
        url = f"{base}/rest/api/3/issue/{urllib.parse.quote(key)}?fields={fields}"
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + creds, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as reply:
                return json.load(reply)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GateInfraError(f"Cannot read Jira {key}: {type(exc).__name__}") from None
    return get_issue


def jira_search_client():
    """Candidate keys in Jira Rank ASC order (JQL is the INITIAL filter only)."""
    base = os.environ["JIRA_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise GateError("JIRA_URL must use HTTPS")
    creds = base64.b64encode(f"{os.environ['JIRA_USERNAME']}:{os.environ['JIRA_API_TOKEN']}".encode()).decode()
    headers = {"Authorization": "Basic " + creds, "Accept": "application/json"}

    def search(jql, limit=50):
        params = {"jql": jql, "fields": "summary,status,labels", "maxResults": str(limit)}
        last = None
        # /search/jql is the current Jira Cloud endpoint; /search is the legacy one.
        for path in ("/rest/api/3/search/jql", "/rest/api/3/search"):
            tokens = set()
            while True:
                url = base + path + "?" + urllib.parse.urlencode(params)
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as reply:
                        data = json.load(reply)
                except urllib.error.HTTPError as exc:
                    if exc.code in (404, 405, 410) and not tokens and "startAt" not in params:
                        last = exc
                        break
                    raise GateInfraError(f"Cannot search Jira: HTTP {exc.code}") from None
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    raise GateInfraError(f"Cannot search Jira: {type(exc).__name__}") from None
                issues = data.get("issues")
                if not isinstance(issues, list):
                    raise GateInfraError("Malformed Jira search response")
                for item in issues:
                    if isinstance(item, dict) and isinstance(item.get("key"), str):
                        yield item["key"]
                if path.endswith("/jql"):
                    token = data.get("nextPageToken")
                    if not token:
                        if data.get("isLast") is False:
                            raise GateInfraError("Missing Jira pagination token")
                        return
                    if token in tokens:
                        raise GateInfraError("Repeated Jira pagination token")
                    tokens.add(token)
                    params["nextPageToken"] = token
                    continue
                offset = params.get("startAt", 0) + len(issues)
                if not issues or offset >= data.get("total", offset):
                    return
                params["startAt"] = offset
        raise GateInfraError(f"Cannot search Jira: {type(last).__name__}")
    return search


def github_existing(issue_key, branch):
    if not os.environ.get("GH_TOKEN"):
        raise GateInfraError("GH_TOKEN absent; cannot check for existing PR")
    p = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--head", branch,
         "--json", "number,headRefName,body,url"],
        capture_output=True, text=True, check=False, timeout=25,
    )
    if p.returncode != 0:
        raise GateInfraError("Could not verify existing open PRs via gh")
    try:
        prs = json.loads(p.stdout)
    except ValueError:
        raise GateInfraError("Malformed GitHub PR list") from None
    if prs:
        raise GateError(f"PR already exists for branch {branch}; do not duplicate or overwrite")
    other = subprocess.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
                           capture_output=True, text=True, check=False, timeout=20)
    if other.returncode != 0:
        raise GateInfraError("Could not check existing remote branches")
    if other.stdout.strip():
        raise GateError(f"Remote branch {branch} already exists; manual recovery required")


def is_waitable_agent_blocker(fields, status):
    labels = fields.get("labels")
    human_review = os.getenv("JIRA_HUMAN_REVIEW_STATUS") or DEFAULT_HUMAN_REVIEW_STATUS
    stages = {"listo", "ready", "in progress", "en curso", "ai review", human_review.strip().casefold()}
    return (bool(status) and " ".join(status.split()).casefold() in stages
            and isinstance(labels, list) and "agent-ready" in labels
            and len(ENGINES.intersection(labels)) == 1)


def github_api(endpoint, *flags):
    result = subprocess.run(["gh", "api", endpoint, *flags], capture_output=True, text=True,
                            encoding="utf-8", timeout=60)
    if result.returncode:
        raise GateInfraError("Cannot verify dependency PRs via GitHub")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise GateInfraError("Malformed GitHub dependency response") from None


def open_pull_requests(repo):
    pages = github_api(f"repos/{repo}/pulls?state=open&per_page=100", "--paginate", "--slurp")
    return [pr for page in pages for pr in page]


def parent_pr(prs, repo, key, engine):
    matches = []
    for pr in prs:
        body = pr.get("body") or ""
        head = pr["head"]
        markers = re.findall(r"^Factory Jira: (\S+)\s*$", body, re.M)
        engines = re.findall(r"^Factory Engine: (\S+)\s*$", body, re.M)
        if markers:
            if markers != [key] or engines != [engine]:
                continue
        else:
            # Older PRs may publish only the engine marker and the Jira URL.
            if engines and engines != [engine]:
                continue
            jira_url = os.environ["JIRA_URL"].rstrip("/") + "/browse/" + key
            if (not re.search(re.escape(jira_url) + r"(?![\w-])", body)
                    or not re.search(r"(?<![A-Z0-9])" + key + r"(?![A-Z0-9])", head["ref"], re.I)):
                continue
        if (head.get("repo") or {}).get("full_name", "").casefold() != repo.casefold():
            continue
        branch, sha = head["ref"], head["sha"]
        if (branch == "master" or not branch or any(ord(c) < 32 for c in branch)
                or not re.fullmatch(r"[0-9a-f]{40}", sha)):
            raise GateError(f"Unverifiable PR branch or commit for {key}")
        matches.append({"issue": key, "branch": branch, "sha": sha, "pr": pr["html_url"]})
    if len(matches) > 1:
        raise GateError(f"Multiple open parent PRs for {key}")
    return matches[0] if matches else None


def stack_base(repo, parents):
    """Pick one published head containing every unfinished prerequisite."""
    for candidate in parents:
        for parent in parents:
            if parent["sha"] == candidate["sha"]:
                continue
            comparison = github_api(f"repos/{repo}/compare/{parent['sha']}...{candidate['sha']}?per_page=1")
            if comparison["status"] != "ahead":
                break
        else:
            return candidate
    raise GateError("Parent PRs have independent heads; no single branch contains all prerequisites")


def repository_source(fields, description, repo):
    repo_field = os.environ.get("JIRA_REPOSITORY_FIELD_ID", "").strip()
    declared = []
    if repo_field:
        field_value = flatten_adf(fields.get(repo_field)).strip()
        if field_value:
            declared = declared_repositories("Repository: " + field_value) or [field_value]
    if not declared:
        declared = declared_repositories(description)
    # No Repository/Repositorio declaration at all => the repo running the
    # workflow (GITHUB_REPOSITORY). A declaration that names ANOTHER repo fails.
    repo_name = repo.split("/", 1)[1].lower()
    for value in declared:
        matches = value.lower() == repo.lower() if "/" in value else value.lower() == repo_name
        if not matches:
            raise GateError(f"Story Repository {value!r} does not match current GitHub repo {repo!r}")
    return "story" if declared else "default GITHUB_REPOSITORY"


def validate(key, mode, get_issue, check_github=True, evaluate_wait=False, get_prs=None):
    if not KEY.fullmatch(key):
        raise GateError("Invalid issue key")
    project = project_key(key)
    if key.split("-")[0] != project:
        raise GateError("Issue is not in configured JIRA_PROJECT_KEY")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
        raise GateInfraError("GITHUB_REPOSITORY not available")
    item = get_issue(key)
    fields = item.get("fields")
    if not isinstance(fields, dict):
        raise GateError("Incomplete Jira issue response")
    actual_status = str((fields.get("status") or {}).get("name") or "").strip()
    ready_set, ready_label = accepted_statuses("JIRA_READY_STATUS", "ready")
    if not status_is(actual_status, "ready"):
        raise GateError(f"Issue status {actual_status!r}; expected Ready status {ready_label!r} (no automatic status transitions)")
    labels = fields.get("labels")
    if not isinstance(labels, list):
        raise GateError("Cannot inspect Jira labels")
    engines = [l for l in labels if l in ENGINES]
    if engines != ["engine-opencode"] or "agent-ready" not in labels:
        raise GateError("Issue must have agent-ready and exactly one engine-opencode label")
    description = flatten_adf(fields.get("description"))
    repo_source = repository_source(fields, description, repo)
    if not description.strip() or len(description) < 60:
        raise GateError("Jira issue description too short to provide approved technical spec")
    blockers = blocking_links(fields.get("issuelinks")) | extract_text_blockers(description)
    deps_field = os.environ.get("JIRA_DEPENDENCIES_FIELD_ID", "").strip()
    if deps_field:
        if deps_field not in fields:
            raise GateError("Configured Jira dependency field missing")
        blockers.update(dependency_field_keys(fields[deps_field]))
    if key in blockers:
        raise GateError("Issue depends on itself")
    unfinished = []
    for dependency in sorted(blockers):
        dep_fields = get_issue(dependency).get("fields") or {}
        status = str((dep_fields.get("status") or {}).get("name") or "").strip()
        if status_is(status, "done"):
            continue
        if not is_waitable_agent_blocker(dep_fields, status):
            raise GateError(f"Blocker {dependency} is {status!r}, not exact Done/Finalizada or an active agent task")
        repository_source(dep_fields, flatten_adf(dep_fields.get("description")), repo)
        engine = next(label for label in dep_fields["labels"] if label in ENGINES)
        unfinished.append((dependency, status, engine.removeprefix("engine-")))

    parents = []
    pending = []
    get_prs = get_prs or cache(open_pull_requests)
    human_review = (os.getenv("JIRA_HUMAN_REVIEW_STATUS") or DEFAULT_HUMAN_REVIEW_STATUS).strip().casefold()
    for dependency, status, engine in unfinished:
        if check_github and not status_is(status, "ready"):
            parent = parent_pr(get_prs(repo), repo, dependency, engine)
            if parent:
                parents.append(parent)
                continue
        reason = f"Blocker {dependency} is {status!r}, not exact Done/Finalizada; no verified parent PR"
        if not evaluate_wait or status.casefold() == human_review:
            raise GateError(reason)
        pending.append(reason)
    branch = "agent/" + key.lower()
    if check_github:
        github_existing(key, branch)
    if pending:
        raise AgentDependenciesPending("; ".join(pending))
    base = stack_base(repo, parents) if parents else {"branch": "master", "sha": ""}
    return {"issue": key, "repo": repo, "repo_source": repo_source, "status": actual_status, "blockers": sorted(blockers),
            "base_branch": base["branch"], "base_sha": base["sha"], "parents": parents,
            "branch": branch, "summary": str(fields.get("summary") or "")[:120]}


def project_key(issue_key=""):
    """JIRA_PROJECT_KEY if set; else the prefix of the given key; else KAN."""
    configured = os.environ.get("JIRA_PROJECT_KEY", "").strip().upper()
    if configured:
        return configured
    if issue_key and KEY.fullmatch(issue_key):
        return issue_key.split("-")[0]
    return "KAN"


def candidate_jql(project):
    # Status is NOT put in the JQL (an unknown status name makes Jira reject the
    # whole query); Ready/Listo is checked per issue on the full detail.
    return (f'project = "{project}" AND labels = "agent-ready" AND labels = "engine-opencode" '
            'AND statusCategory != Done ORDER BY Rank ASC')


def parse_max_issues(raw):
    """Accept only 1, 2 or 3. Anything else is a hard gate failure."""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        raise GateError("max_issues must be an integer from 1 to 3") from None
    if n < 1 or n > 3:
        raise GateError("max_issues must be an integer from 1 to 3")
    return n


def select(mode, get_issue, search, check_github=True, limit=50, max_issues=3, admitted=(), evaluate_wait=False):
    """Up to ``max_issues`` eligible issues in Rank ASC order.

    Returns ``(chosen, skipped)``. ``chosen`` is empty when nothing qualifies.
    Infra errors abort (fail closed) and are not turned into skips.
    """
    max_issues = parse_max_issues(max_issues)
    project = project_key()
    skipped = []
    chosen = []
    seen = set(admitted)
    get_prs = cache(open_pull_requests)
    for key in search(candidate_jql(project), limit):
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
            continue
        seen.add(key)
        try:
            result = validate(key, mode, get_issue, check_github, evaluate_wait, get_prs)
        except GateInfraError:
            raise
        except GateError as exc:
            skipped.append({"issue": key, "reason": str(exc), "waitable": isinstance(exc, AgentDependenciesPending)})
            continue
        result["selected"] = "auto"
        chosen.append(result)
        if len(chosen) == max_issues:
            break
    return chosen, skipped


def select_wave(mode, max_issues, admitted, deadline):
    remaining = max_issues - len(admitted)
    if remaining <= 0:
        return [], [], False
    get_issue, search = jira_client(), jira_search_client()
    while True:
        chosen, skipped = select(mode, get_issue, search, max_issues=remaining,
                                 admitted=admitted, evaluate_wait=bool(deadline))
        delay = deadline - time.time()
        can_wait = (delay > 0 and len(chosen) < remaining and any(s["waitable"] for s in skipped))
        if chosen or not can_wait:
            return chosen, skipped, can_wait
        print("WAIT_DEPENDENCIES " + json.dumps([s for s in skipped if s["waitable"]]), flush=True)
        time.sleep(min(POLL_SECONDS, delay))


def write_outputs(values):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as out:
            for k, v in values.items():
                out.write(f"{k}={v}\n")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", default="", help="Exact key; empty = deterministic auto-selection")
    parser.add_argument("--mode", choices=["inspect", "build"], default="inspect")
    parser.add_argument("--max-issues", default="3", help="Auto-select cap, integer 1-3 (ignored when --issue is set)")
    parser.add_argument("--wait", action="store_true", help="In automatic build mode, poll for agent dependencies")
    parser.add_argument("--admitted", default="[]", help="JSON keys already dispatched in this run")
    parser.add_argument("--deadline", type=int, help="Shared deadline (Unix time) for subsequent selections")
    args = parser.parse_args(argv)
    requested = (args.issue or "").strip().upper()
    try:
        admitted = []
        can_wait = False
        deadline = 0
        if requested:
            # An explicit key is the whole batch, whatever --max-issues says.
            result = validate(requested, args.mode, jira_client())
            result["selected"] = "requested"
            results, skipped = [result], []
        else:
            max_issues = parse_max_issues(args.max_issues)
            admitted = json.loads(args.admitted)
            if (not isinstance(admitted, list) or not all(isinstance(k, str) and KEY.fullmatch(k) for k in admitted)
                    or len(set(admitted)) != len(admitted) or len(admitted) > max_issues):
                raise GateError("Invalid list of previously admitted issues")
            if args.wait and args.mode == "build":
                deadline = args.deadline if args.deadline is not None else int(time.time()) + WAIT_SECONDS
            results, skipped, can_wait = select_wave(args.mode, max_issues, admitted, deadline)
        keys = [item["issue"] for item in results]
        outcome = "ELIGIBLE" if keys else ("NO_MORE_WORK" if admitted else "NO_WORK")
        print(outcome + " " + json.dumps({"issues": results, "skipped": skipped}, ensure_ascii=False))
        write_outputs({
            "issues": json.dumps(keys),
            "admitted": json.dumps(admitted + keys),
            "deadline": deadline,
            "can_wait": str(can_wait).lower(),
            "issue": keys[0] if keys else "",
            "branch": results[0]["branch"] if keys else "",
            "base_branch": results[0]["base_branch"] if keys else "",
            "base_sha": results[0]["base_sha"] if keys else "",
            "parents": json.dumps(results[0]["parents"] if keys else []),
            "has_work": str(bool(keys)).lower(),
        })
    except (GateError, KeyError, json.JSONDecodeError) as exc:
        print(f"GATE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
