import argparse
import asyncio
import json
import os
import sys

from rich.console import Console

from gitverify import auth, history
from gitverify.art import LOGO
from gitverify.github import GitHubProvider
from gitverify.score import explain_axes
from gitverify.service import VerificationResult, verify_candidate

TOKEN_ENV = "GITHUB_TOKEN"


def _bar(value: float, width: int = 20) -> str:
    filled = round(value / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _print_banner(console: Console) -> None:
    for row in LOGO:
        console.print(f"[bold]{row}[/bold]")


def _print_result(
    console: Console, handle: str, result: VerificationResult, previous: dict | None = None
) -> None:
    score = result.score
    delta = f" [{score.value - previous['score']:+.1f}]" if previous else ""
    console.print(
        f"\ngithub truth score for [cyan]{handle}[/cyan]: "
        f"[bold]{score.value}[/bold]{delta} ({score.band})\n"
    )
    for axis, value in score.axes.items():
        console.print(f"  {axis:13} {_bar(value)} {value:.0f}")

    explanation = explain_axes(score.axes)
    if explanation:
        console.print(f"\n↑ {explanation['up']}")
        console.print(f"↓ {explanation['down']}")
        console.print(f"→ {explanation['next_action']}")


def _print_json(handle: str, result: VerificationResult) -> None:
    print(
        json.dumps(
            {
                "handle": handle,
                "provider": "github",
                "score": result.score.value,
                "band": result.score.band,
                "axes": result.score.axes,
                "signals": [
                    {
                        "name": s.name,
                        "value": s.value,
                        "weight": s.weight,
                        "axis": s.axis,
                        "evidence": s.evidence,
                    }
                    for s in result.score.signals
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


async def _analyze(handle: str, provider: GitHubProvider) -> VerificationResult:
    result = await verify_candidate(handle, provider)
    history.save_result(handle, result.score.value, result.score.band, result.score.axes)
    return result


def _resolve_token() -> str | None:
    return os.environ.get(TOKEN_ENV) or auth.load_token()


def _cmd_auth(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="gitverify auth")
    parser.add_argument("action", choices=["login", "logout"])
    args = parser.parse_args(argv)

    if args.action == "login":
        try:
            asyncio.run(auth.login())
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"authenticated — token cached at {auth.TOKEN_PATH}")
        return

    removed = auth.logout()
    print("logged out, cached token removed" if removed else "not logged in")


def _cmd_analyze(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="gitverify")
    parser.add_argument("--token")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    console = Console()
    if not args.json:
        _print_banner(console)

    token = args.token or _resolve_token()
    if not token:
        if args.json:
            print("error: not authenticated, run 'gitverify auth login'", file=sys.stderr)
            raise SystemExit(1)
        console.print("\nnot authenticated yet.")
        try:
            token = asyncio.run(auth.login())
        except Exception as exc:
            console.print(f"[red]error: {exc}[/red]")
            raise SystemExit(1) from exc
        console.print(f"authenticated — token cached at {auth.TOKEN_PATH}")

    provider = GitHubProvider(token=token)
    try:
        handle = asyncio.run(provider.whoami())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not args.json:
        console.print(f"\nanalyzing [cyan]{handle}[/cyan]...")

    previous = history.get_previous(handle)
    try:
        result = asyncio.run(_analyze(handle, provider))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        _print_json(handle, result)
        return

    _print_result(console, handle, result, previous)


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "auth":
        _cmd_auth(argv[1:])
        return
    _cmd_analyze(argv)


if __name__ == "__main__":
    main()
