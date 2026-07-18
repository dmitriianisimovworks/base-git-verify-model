import math
from collections import Counter
from datetime import UTC, datetime, timedelta

from gitverify.base import CodeProfile, RepoFacts, Signal

FRESHNESS_WINDOW = timedelta(days=180)
# raised 500->5000 (2026-07-16): real-data collection (tests/real_profiles_scores.csv)
# showed most senior/legend GitHub accounts saturate impact=100 at cap=500,
# killing discrimination in exactly the segment that should differentiate most.
# log-shape keeps the low end (target audience: 1-5 stars) nearly unchanged -
# see the calibration case in ai/memory/decisions.md.
STARS_LOG_CAP = math.log1p(5000)
# 1 year = 25, 2 = 50, 3 = 75, 4 = 100 - just registering shouldn't buy much
ACCOUNT_AGE_CAP_DAYS = 365 * 4
# issues+PRs+reviews per year for full credit on this signal - these are
# server-timestamped at creation, unlike commit dates which can be backdated
# by rewriting local git history before pushing
SERVER_ACTIVITY_CAP = 30


def _production_repos(profile: CodeProfile) -> list[RepoFacts]:
    prod = [r for r in profile.repos if r.has_ci or r.release_count > 0]
    return prod or profile.repos


def check_account_age(profile: CodeProfile) -> Signal:
    age_days = (datetime.now(UTC) - profile.account_created_at).days
    value = min(age_days / ACCOUNT_AGE_CAP_DAYS, 1.0)
    return Signal(
        name="account_age",
        value=value,
        weight=1.0,
        evidence=f"account created {profile.account_created_at.date()}, {age_days} days ago",
        axis="consistency",
    )


def check_contribution_density(profile: CodeProfile) -> Signal:
    days_with_activity = sum(1 for count in profile.contribution_calendar.values() if count > 0)
    total_days = len(profile.contribution_calendar) or 1
    value = days_with_activity / total_days
    return Signal(
        name="contribution_density",
        value=value,
        # demoted from 1.5: this is commit-date-based, which can be
        # backdated by rewriting local git history before pushing - see
        # check_server_activity for the harder-to-fake equivalent
        weight=0.75,
        evidence=f"active on {days_with_activity}/{total_days} calendar days",
        axis="consistency",
    )


def check_server_activity(profile: CodeProfile) -> Signal:
    total = (
        profile.total_issue_contributions
        + profile.total_pr_contributions
        + profile.total_review_contributions
    )
    value = min(total / SERVER_ACTIVITY_CAP, 1.0)
    return Signal(
        name="server_activity",
        value=value,
        weight=2.0,
        evidence=f"{total} issues/PRs/reviews this year (server-timestamped, can't be backdated)",
        axis="consistency",
    )


def check_ownership(profile: CodeProfile) -> Signal:
    if not profile.repos:
        return Signal(
            name="ownership", value=0.0, weight=1.5, evidence="no repositories", axis="authenticity"
        )
    original = sum(1 for r in profile.repos if not r.is_fork)
    value = original / len(profile.repos)
    return Signal(
        name="ownership",
        value=value,
        weight=1.5,
        evidence=f"{original}/{len(profile.repos)} repos are not forks",
        axis="authenticity",
    )


def check_ci_coverage(profile: CodeProfile) -> Signal:
    if not profile.repos:
        return Signal(
            name="ci_coverage", value=0.0, weight=1.0, evidence="no repositories", axis="craft"
        )
    with_ci = sum(1 for r in profile.repos if r.has_ci)
    value = with_ci / len(profile.repos)
    return Signal(
        name="ci_coverage",
        value=value,
        weight=1.0,
        evidence=f"{with_ci}/{len(profile.repos)} repos have CI",
        axis="craft",
    )


def check_test_coverage(profile: CodeProfile) -> Signal:
    if not profile.repos:
        return Signal(
            name="test_coverage", value=0.0, weight=1.0, evidence="no repositories", axis="craft"
        )
    with_tests = sum(1 for r in profile.repos if r.has_tests)
    value = with_tests / len(profile.repos)
    return Signal(
        name="test_coverage",
        value=value,
        weight=1.0,
        evidence=f"{with_tests}/{len(profile.repos)} repos have tests",
        axis="craft",
    )


def check_releases(profile: CodeProfile) -> Signal:
    has_release = any(r.release_count > 0 for r in profile.repos)
    return Signal(
        name="releases",
        value=1.0 if has_release else 0.0,
        weight=1.0,
        evidence="has a release/tag in at least one repo" if has_release else "no releases",
        axis="craft",
    )


def check_freshness(profile: CodeProfile) -> Signal:
    # falls back to the contribution calendar when there are no owned repos
    # (e.g. an org-only contributor) instead of hardcoding 0 - "no repos"
    # isn't the same signal as "no recent activity"
    if profile.repos:
        latest_date = max(r.pushed_at for r in profile.repos).date()
    else:
        active_days = [d for d, count in profile.contribution_calendar.items() if count > 0]
        if not active_days:
            return Signal(
                name="freshness",
                value=0.0,
                weight=1.0,
                evidence="no activity data",
                axis="consistency",
            )
        latest_date = max(active_days)

    days_since = (datetime.now(UTC).date() - latest_date).days
    is_fresh = days_since < FRESHNESS_WINDOW.days
    return Signal(
        name="freshness",
        value=1.0 if is_fresh else 0.0,
        weight=1.0,
        evidence=f"last active {latest_date}",
        axis="consistency",
    )


def check_stack_depth(profile: CodeProfile) -> Signal:
    if not profile.repos:
        return Signal(
            name="stack_depth", value=0.0, weight=0.5, evidence="no repositories", axis="craft"
        )
    bytes_by_language: Counter[str] = Counter()
    for repo in _production_repos(profile):
        for language, size in repo.languages.items():
            bytes_by_language[language] += size
    top = bytes_by_language.most_common(3)
    value = min(len(bytes_by_language) / 4, 1.0)
    evidence = ", ".join(f"{name} ({size}b)" for name, size in top) or "no languages detected"
    return Signal(name="stack_depth", value=value, weight=0.5, evidence=evidence, axis="craft")


def check_tech_topics(profile: CodeProfile) -> Signal:
    prod = _production_repos(profile)
    if not prod:
        return Signal(
            name="tech_topics", value=0.0, weight=0.75, evidence="no repositories", axis="craft"
        )
    with_topics = sum(1 for r in prod if r.topics)
    value = with_topics / len(prod)
    sample_topics = sorted({t for r in prod for t in r.topics})[:5]
    evidence = (
        f"{with_topics}/{len(prod)} production repos have stack tags"
        + (f": {', '.join(sample_topics)}" if sample_topics else "")
    )
    return Signal(name="tech_topics", value=value, weight=0.75, evidence=evidence, axis="craft")


def check_stars(profile: CodeProfile) -> Signal:
    original = [r for r in profile.repos if not r.is_fork]
    if not original:
        return Signal(
            name="stars",
            value=0.0,
            weight=0.75,
            evidence="no owned repositories",
            axis="impact",
        )
    total_stars = sum(r.stars for r in original)
    top_repo = max(original, key=lambda r: r.stars)
    value = min(math.log1p(total_stars) / STARS_LOG_CAP, 1.0)
    return Signal(
        name="stars",
        value=value,
        weight=0.75,
        evidence=f"{total_stars} stars total, top repo {top_repo.name} ({top_repo.stars})",
        axis="impact",
    )


CHECKS = [
    check_account_age,
    check_contribution_density,
    check_server_activity,
    check_ownership,
    check_ci_coverage,
    check_test_coverage,
    check_releases,
    check_freshness,
    check_stack_depth,
    check_tech_topics,
    check_stars,
]

# have nothing to measure without owned repos - an org-only contributor
# (issues/PRs/reviews in other people's/org repos) isn't "faked everything",
# they just don't own repos; excluding these lets score() renormalize
# weight onto the axes that do have data instead of averaging in silent
# zeros (see score.py's dynamic weight renormalization)
_REPO_DEPENDENT_CHECKS = {
    check_ownership,
    check_ci_coverage,
    check_test_coverage,
    check_releases,
    check_stack_depth,
    check_tech_topics,
    check_stars,
}


def run_checks(profile: CodeProfile) -> list[Signal]:
    checks = CHECKS
    if not profile.contribution_calendar:
        # no calendar data (e.g. GitLab has no public equivalent) - skip
        # rather than score it as zero activity
        checks = [c for c in checks if c is not check_contribution_density]
    if not profile.repos:
        checks = [c for c in checks if c not in _REPO_DEPENDENT_CHECKS]
    return [check(profile) for check in checks]
