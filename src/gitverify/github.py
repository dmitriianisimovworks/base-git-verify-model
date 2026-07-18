import asyncio
from datetime import datetime

import aiohttp

from gitverify.base import CodeProfile, Provider, RepoFacts

GRAPHQL_URL = "https://api.github.com/graphql"

_CONCURRENCY = asyncio.Semaphore(5)

QUERY = """
fragment RepoFields on Repository {
  name
  isFork
  stargazerCount
  pushedAt
  createdAt
  releases {
    totalCount
  }
  languages(first: 5) {
    edges {
      size
      node { name }
    }
  }
  repositoryTopics(first: 10) {
    nodes {
      topic { name }
    }
  }
  object(expression: "HEAD:") {
    ... on Tree {
      entries { name }
    }
  }
  ci: object(expression: "HEAD:.github") {
    ... on Tree {
      entries { name }
    }
  }
}

query($login: String!) {
  user(login: $login) {
    createdAt
    bio
    websiteUrl
    twitterUsername
    company
    email
    socialAccounts(first: 10) {
      nodes {
        provider
        url
      }
    }
    contributionsCollection {
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    repositories(first: 15, ownerAffiliations: OWNER, isFork: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { ...RepoFields }
    }
    # separate top-by-stars query: the recency-ordered list above can miss a
    # prolific account's actual best repo entirely (e.g. a real profile with
    # thousands of repos where the 15 most recently pushed all have 0 stars),
    # which made the impact axis see 0 stars for accounts with real ones
    topStarred: repositories(first: 10, ownerAffiliations: OWNER, isFork: false, orderBy: {field: STARGAZERS, direction: DESC}) {
      nodes { ...RepoFields }
    }
  }
}
"""

WHOAMI_QUERY = "query { viewer { login } }"

CI_MARKERS = {"workflows", ".gitlab-ci.yml"}
TEST_MARKERS = {"tests", "test", "spec"}
DOCKERFILE_MARKERS = {"Dockerfile"}


def _has_marker(entry_names: set[str], markers: set[str]) -> bool:
    return bool(entry_names & markers)


class GitHubProvider(Provider):
    source = "github"

    def __init__(self, token: str):
        self.token = token

    async def whoami(self) -> str:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with _CONCURRENCY:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(GRAPHQL_URL, json={"query": WHOAMI_QUERY}) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()
        if payload.get("errors"):
            raise ValueError(f"GitHub GraphQL error: {payload['errors']}")
        return payload["data"]["viewer"]["login"]

    async def fetch(self, handle: str) -> CodeProfile:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with _CONCURRENCY:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(
                    GRAPHQL_URL, json={"query": QUERY, "variables": {"login": handle}}
                ) as resp:
                    resp.raise_for_status()
                    payload = await resp.json()

        if payload.get("errors"):
            raise ValueError(f"GitHub GraphQL error for {handle}: {payload['errors']}")

        user = payload["data"]["user"]
        if user is None:
            raise ValueError(f"GitHub user not found: {handle}")

        contributions = user["contributionsCollection"]
        calendar = {}
        for week in contributions["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                calendar[datetime.fromisoformat(day["date"]).date()] = day["contributionCount"]

        seen_names: set[str] = set()
        repo_nodes = []
        for node in user["repositories"]["nodes"] + user["topStarred"]["nodes"]:
            if node["name"] not in seen_names:
                seen_names.add(node["name"])
                repo_nodes.append(node)

        repos = []
        for node in repo_nodes:
            root_entries = {e["name"] for e in (node["object"] or {}).get("entries", [])}
            github_dir_entries = {e["name"] for e in (node["ci"] or {}).get("entries", [])}
            languages = {
                edge["node"]["name"]: edge["size"] for edge in node["languages"]["edges"]
            }
            topics = [t["topic"]["name"] for t in node["repositoryTopics"]["nodes"]]
            repos.append(
                RepoFacts(
                    name=node["name"],
                    is_fork=node["isFork"],
                    stars=node["stargazerCount"],
                    pushed_at=datetime.fromisoformat(node["pushedAt"]),
                    created_at=datetime.fromisoformat(node["createdAt"]),
                    languages=languages,
                    topics=topics,
                    has_ci=_has_marker(github_dir_entries, CI_MARKERS)
                    or ".gitlab-ci.yml" in root_entries,
                    has_tests=_has_marker(root_entries, TEST_MARKERS),
                    has_dockerfile=_has_marker(root_entries, DOCKERFILE_MARKERS),
                    release_count=node["releases"]["totalCount"],
                )
            )

        social_accounts = [
            {"provider": n["provider"], "url": n["url"]}
            for n in user["socialAccounts"]["nodes"]
        ]

        return CodeProfile(
            handle=handle,
            account_created_at=datetime.fromisoformat(user["createdAt"]),
            repos=repos,
            contribution_calendar=calendar,
            total_issue_contributions=contributions["totalIssueContributions"],
            total_pr_contributions=contributions["totalPullRequestContributions"],
            total_review_contributions=contributions["totalPullRequestReviewContributions"],
            bio=user.get("bio"),
            website_url=user.get("websiteUrl"),
            twitter_username=user.get("twitterUsername"),
            company=user.get("company"),
            email=user.get("email"),
            social_accounts=social_accounts,
        )
