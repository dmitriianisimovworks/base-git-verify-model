from dataclasses import dataclass, field

from gitverify.base import Signal
from gitverify.checks import ACCOUNT_AGE_CAP_DAYS

BANDS = (
    (70.0, "Strong"),
    (35.0, "Solid"),
    (0.0, "Thin"),
)

SCORE_VERSION = 3

# Чем труднее подделать сигнал, тем больше вес: impact (чужие звёзды/форки -
# решение принимал не сам кандидат) > consistency (нужны годы, не подделать
# за неделю) > authenticity (нужен настоящий труд, но можно изобразить) >
# craft (осознанный инженер это делает, но можно навести за пару вечеров).
#
# Попытка №4 (fable): вынести authenticity из суммы в штрафующий множитель
# (0.5-1.0 поверх итога) - ОТКАЧЕНО. У 45/50 синтетических профилей
# authenticity=100, то есть множитель=1.0 (ничего не добавляет), а раньше
# эти же 100*0.20=20 баллов были гарантированной частью суммы. Убрав их без
# замены, весь средний сегмент без craftsman/impact-буста проваливается
# в Thin (напр. middle_freelancer 50.6->38.3, senior_old_account 29.1->11.3) -
# ровно та аудитория, которую фикс №1 должен был поднять. Нужна отдельная
# перекалибровка бендов, если возвращаться к этой идее - не быстрый фикс.
AXIS_WEIGHTS = {
    "impact": 0.35,
    "consistency": 0.30,
    "authenticity": 0.20,
    "craft": 0.15,
}

# Прокси-порог на нашей же 0-100 шкале, не истинный перцентиль - для этого
# нужна калибровка на своей накопленной базе кандидатов, а не на чужой
# выборке (см. ai/memory/decisions.md). Смысл: выдающееся достижение в одной
# оси не должно "усредняться" посредственностью в остальных - но только
# вверх, слабая ось не топит остальные.
#
# Применяется только к оси impact: это единственная ось, где 100 - реальная
# редкость (решение принимал не сам кандидат - чужие звёзды/форки). На
# остальных осях 100 достижимо честной нормой (например ownership=100% -
# норма для соло-дева, не достижение) и раньше давало ложный buff (живой
# случай в ai/memory/decisions.md, authenticity=100 поднимал 42.5 -> 80).
DOMINANCE_AXIS = "impact"
DOMINANCE_THRESHOLD = 85.0
# Base factor is scaled by consistency (see score()): a live legend
# (consistency 60+) keeps almost the full 0.8, a dead account with only an
# old viral repo (low consistency) drops toward ~0.4 - the raw star count
# alone no longer guarantees the same boost regardless of everything else.
DOMINANCE_FACTOR = 0.8

# Hard fraud-gate cap, not a boost reduction: an account younger than this
# has too little history to earn a top-tier band no matter what the axes
# say (star-farms are cheap, account age is not). This replaces the old
# account-age floor on the impact dominance path specifically - it's
# stricter and applies to the whole score, not just one dominance path.
FRAUD_GATE_ACCOUNT_AGE_DAYS = 180
FRAUD_GATE_CAP = 69.0

# Second, independent dominance path: craft AND consistency both high is the
# "quiet professional" signature this product's actual audience (contractors
# with private client repos, no public stars - see decisions.md) can
# realistically hit, unlike impact. Two hard-to-fake axes both clearing the
# bar deserve the same boost as one viral repo (fable's finding #1: a
# freelancer with full CI/tests/releases capped at ~50-60 while a dead
# account with an old viral repo hit 80).
CRAFTSMAN_THRESHOLD = 75.0
CRAFTSMAN_FACTOR = 0.8

# Third dominance path: all three substantive axes (impact/consistency/craft)
# clearing a lower bar together is the "all-rounder" signature - no single
# extraordinary axis, but nothing weak either. authenticity is excluded here
# too (same reason as elsewhere: ~100 for almost everyone, not discriminating).
ALLROUNDER_THRESHOLD = 70.0
ALLROUNDER_MULTIPLIER = 1.25
ALLROUNDER_FACTOR = 0.8


@dataclass
class Score:
    value: float
    band: str
    signals: list[Signal]
    axes: dict[str, float] = field(default_factory=dict)


def band_for(value: float) -> str:
    for threshold, name in BANDS:
        if value >= threshold:
            return name
    return "Thin"


def _axis_score(signals: list[Signal], axis: str) -> float:
    axis_signals = [s for s in signals if s.axis == axis]
    if not axis_signals:
        return 0.0
    total_weight = sum(s.weight for s in axis_signals) or 1.0
    return sum(s.value * s.weight for s in axis_signals) / total_weight * 100


def _signal_value(signals: list[Signal], name: str) -> float:
    return next((s.value * 100 for s in signals if s.name == name), 0.0)


def _account_age_days(signals: list[Signal]) -> float:
    # account_age signal is normalized age_days/ACCOUNT_AGE_CAP_DAYS (capped
    # at 1.0) - below the cap this converts back to raw days exactly, and the
    # fraud gate threshold is always well under the cap so no distortion.
    return _signal_value(signals, "account_age") / 100 * ACCOUNT_AGE_CAP_DAYS


def score(signals: list[Signal]) -> Score:
    axes = {axis: round(_axis_score(signals, axis), 1) for axis in AXIS_WEIGHTS}

    # weight renormalized across only the axes that actually have signals -
    # matters for profiles with no owned repos (org-only contributors), where
    # checks.run_checks skips impact/authenticity/craft entirely rather than
    # emitting silent zeros. Without this, such a profile's real consistency
    # signal would still only count for its usual 30% share and could never
    # reach Solid; a repo-having profile always has all 4 axes present, so
    # this is a no-op for every profile scored before this fix.
    active_axes = {s.axis for s in signals}
    active_weights = {a: w for a, w in AXIS_WEIGHTS.items() if a in active_axes}
    total_active_weight = sum(active_weights.values()) or 1.0
    weighted = sum(axes[a] * w / total_active_weight for a, w in active_weights.items())

    # blended, not max(): a dominance path pulls the score toward
    # FACTOR*dominant instead of snapping to it outright - otherwise every
    # profile that clears a dominance bar collapses to the same number
    # (0.8*100=80.0 regardless of how much stronger the rest of the profile
    # is), which is exactly the "80.0 cluster" fable flagged as
    # indistinguishable. Blending keeps the other axes' contribution visible.
    value = weighted
    if axes[DOMINANCE_AXIS] >= DOMINANCE_THRESHOLD:
        velocity_factor = DOMINANCE_FACTOR * (0.5 + 0.5 * axes["consistency"] / 100)
        dominant_value = velocity_factor * axes[DOMINANCE_AXIS] + (1 - velocity_factor) * weighted
        value = max(value, dominant_value)
    if axes["craft"] >= CRAFTSMAN_THRESHOLD and axes["consistency"] >= CRAFTSMAN_THRESHOLD:
        craftsman_value = CRAFTSMAN_FACTOR * min(axes["craft"], axes["consistency"]) + (
            1 - CRAFTSMAN_FACTOR
        ) * weighted
        value = max(value, craftsman_value)
    if (
        axes["impact"] >= ALLROUNDER_THRESHOLD
        and axes["consistency"] >= ALLROUNDER_THRESHOLD
        and axes["craft"] >= ALLROUNDER_THRESHOLD
    ):
        candidate = min(axes["impact"], axes["consistency"], axes["craft"]) * ALLROUNDER_MULTIPLIER
        candidate = min(candidate, 100.0)
        allrounder_value = ALLROUNDER_FACTOR * candidate + (1 - ALLROUNDER_FACTOR) * weighted
        value = max(value, allrounder_value)

    # hard cap, not a boost reduction - applies last, after every dominance
    # path, so a young account can't get to a top band through any route
    if _account_age_days(signals) < FRAUD_GATE_ACCOUNT_AGE_DAYS:
        value = min(value, FRAUD_GATE_CAP)

    value = round(value, 1)
    return Score(value=value, band=band_for(value), signals=signals, axes=axes)


AXIS_ADVICE = {
    "impact": "publish open-source that solves someone else's problem — stars and forks can't be self-awarded",
    "consistency": "commit/review/fix issues regularly — this signal is built over years, there's no shortcut",
    "authenticity": "publish your own projects, not forks of others' — it proves the work is yours",
    "craft": "add CI, tests, and releases to your repos — the fastest lever of them all",
}


def explain_axes(axes: dict[str, float]) -> dict[str, str]:
    """3-line human-readable summary: what's pulling the score up, what's
    pulling it down, what to do about it. Takes just the axes dict (not a
    full Score) so callers reading stored axes don't need to reconstruct
    Signal objects."""
    if not axes:
        return {}
    strongest = max(axes, key=lambda a: axes[a])
    weakest = min(axes, key=lambda a: axes[a])
    return {
        "up": f"{strongest} ({axes[strongest]:.0f}/100) — pulling the score up the most",
        "down": f"{weakest} ({axes[weakest]:.0f}/100) — pulling the score down the most",
        "next_action": AXIS_ADVICE[weakest],
    }


def aggregate_truth_score(provider_scores: list[float]) -> float | None:
    """Кросс-провайдерная агрегация: max + небольшой бонус за второе
    подтверждение, не среднее - не наказываем за пустой профиль на одной
    площадке, если на другой сильный сигнал."""
    if not provider_scores:
        return None
    ranked = sorted(provider_scores, reverse=True)
    bonus = 0.15 * ranked[1] if len(ranked) > 1 else 0.0
    return round(min(ranked[0] + bonus, 100.0), 1)
