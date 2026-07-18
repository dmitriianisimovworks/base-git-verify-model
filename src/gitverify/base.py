from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class RepoFacts:
    name: str
    is_fork: bool
    stars: int
    pushed_at: datetime
    created_at: datetime
    languages: dict[str, int]
    topics: list[str]
    has_ci: bool
    has_tests: bool
    has_dockerfile: bool
    release_count: int


@dataclass
class CodeProfile:
    handle: str
    account_created_at: datetime
    repos: list[RepoFacts] = field(default_factory=list)
    contribution_calendar: dict[date, int] = field(default_factory=dict)
    # server-timestamped contribution counts (issues/PRs/reviews) - unlike
    # commit dates these can't be backdated by rewriting local git history,
    # and they count activity in org/other-owned repos the OWNER-only repo
    # list below never sees (org-only contributors would otherwise score 0
    # on craft/authenticity/impact just for not owning their own repos)
    total_issue_contributions: int = 0
    total_pr_contributions: int = 0
    total_review_contributions: int = 0
    bio: str | None = None
    website_url: str | None = None
    twitter_username: str | None = None
    company: str | None = None
    email: str | None = None
    social_accounts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Signal:
    name: str
    value: float
    weight: float
    evidence: str
    axis: str


class Provider(ABC):
    source: str

    @abstractmethod
    async def fetch(self, handle: str) -> CodeProfile: ...
