from dataclasses import dataclass

from gitverify.base import CodeProfile, Provider
from gitverify.checks import run_checks
from gitverify.score import Score, score


@dataclass
class VerificationResult:
    profile: CodeProfile
    score: Score


async def verify_candidate(handle: str, provider: Provider) -> VerificationResult:
    profile = await provider.fetch(handle)
    signals = run_checks(profile)
    return VerificationResult(profile=profile, score=score(signals))
