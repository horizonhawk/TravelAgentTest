"""Reviewer-friendly setup and explicit session lifecycle; no model calls on import."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .config import AppError, Profile, check_profile, initialize_config, load_settings
from .persistence import ArtifactStore
from .session import Sessions
from .terminal import Terminal


def parser():
    root = argparse.ArgumentParser(prog="trip-agent", description="Model-directed trip ideas with saved session evidence")
    root.add_argument("--config", type=Path, default=Path(os.environ.get("TRIP_AGENT_CONFIG", "trip-agent.toml")))
    root.add_argument("--data-dir", type=Path, default=Path(os.environ.get("TRIP_AGENT_DATA_DIR", ".trip-agent")))
    commands = root.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config", help="Initialize or check model profiles").add_subparsers(dest="action", required=True)
    init = config.add_parser("init", help="Create a configuration without overwriting an existing file")
    init.add_argument("--provider", choices=["openai", "anthropic", "bedrock", "openrouter"], default="openai")
    init.add_argument("--model", help="Defaults to gpt-6.1-sol for OpenAI; required for other providers")
    check = config.add_parser("check", help="Validate local settings; --live additionally invokes the agent")
    check.add_argument("--profile")
    check.add_argument("--live", action="store_true")
    check.add_argument("--debug", action="store_true", help="Show indented tool inputs/results and evidence IDs")
    config.add_parser("show", help="Show non-secret settings")

    session = commands.add_parser("session", help="Create, resume, inspect, or manage a session").add_subparsers(dest="action", required=True)
    create = session.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--profile")
    listing = session.add_parser("list")
    listing.add_argument("--deleted", action="store_true")
    for action in ("show", "resume", "rename", "delete", "restore", "set-model"):
        sub = session.add_parser(action)
        sub.add_argument("session", help="Full UUID or session name")
        if action == "resume":
            sub.add_argument("--debug", action="store_true", help="Show indented tool inputs/results and evidence IDs")
        if action == "rename":
            sub.add_argument("name")
        if action == "set-model":
            sub.add_argument("--profile", required=True)

    run = commands.add_parser("run", help="Send one message to an existing session and exit")
    run.add_argument("--session", required=True)
    run.add_argument("--json", action="store_true", help="Print only the final JSON on stdout; progress stays on stderr")
    run.add_argument("--debug", action="store_true", help="Show indented tool inputs/results and evidence IDs")
    run.add_argument("request")

    artifacts = commands.add_parser("artifacts", help="Inspect session evidence without an LLM")
    artifacts.add_argument("--session", required=True)
    artifacts.add_argument("--kind", choices=sorted(ArtifactStore.KINDS))
    artifacts.add_argument("--read", metavar="ARTIFACT_ID")
    logbook = commands.add_parser("logbook", help="Generate a new immutable edition of the integrated HTML logbook")
    logbook.add_argument("--session", required=True)
    logbook.add_argument("--open", action="store_true", help="Open the logbook in your browser")
    return root


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def render(result, as_json=False, debug=False):
    if as_json:
        emit(result)
        return
    response = result["response"]
    terminal = Terminal(sys.stdout)
    terminal.write()
    terminal.write("Agent", "heading")
    terminal.write("─" * terminal.width, "muted")
    terminal.prose(response["message"])
    for suggestion in response["suggestions"]:
        terminal.write()
        terminal.write(suggestion['destination_id'].title(), "label")
        terminal.prose(suggestion['reasoning'])
        terminal.prose(f"Budget: {suggestion['rough_budget']}")
        for caveat in suggestion["caveats"]:
            terminal.prose(caveat, "muted", prefix="  Note: ")
    # Avoid repeating a question already included verbatim in the main reply.
    normalized_message = " ".join(response["message"].casefold().split())
    questions = list(dict.fromkeys(q for q in response["questions"]
                                  if " ".join(q.casefold().split()) not in normalized_message))
    if questions:
        terminal.write()
        terminal.write("To continue", "label")
        for question in questions:
            terminal.prose(question, prefix="  ? ")
    for label, values in (("Assumptions", response["assumptions"]), ("Caveats", response["caveats"])):
        if values:
            terminal.write()
            terminal.write(label + " · supporting details", "muted")
            for value in dict.fromkeys(values):
                terminal.prose(value, "muted", prefix="  • ")
    terminal.write()
    terminal.write("─" * terminal.width, "muted")
    diagnostics = Terminal(sys.stderr)
    if debug:
        diagnostics.debug(f"Session: {result['session_id']}")
        diagnostics.debug(f"Saved response: {result['artifact_id']}")
    else:
        diagnostics.debug("Conversation and evidence saved. Use --debug for full tool JSON and artifact IDs.")


def execute(args):
    load_dotenv(args.config.parent / ".env", override=False)
    if args.command == "config":
        if args.action == "init":
            model = args.model or ("gpt-6.1-sol" if args.provider == "openai" else None)
            if not model:
                raise AppError("Pass --model with the model ID for this provider")
            initialize_config(args.config, args.provider, model)
            print(f"Created {args.config}. Add credentials to .env, then run: trip-agent config check")
            return
        settings = load_settings(args.config)
        if args.action == "show":
            emit(settings.model_dump(mode="json"))
            return
        name, profile = settings.select(args.profile)
        problems = check_profile(profile)
        if problems:
            raise AppError("\n".join(problems))
        print(f"Profile '{name}': {profile.provider} / {profile.model_id}. Local configuration is valid.")
        if profile.provider == "bedrock":
            print("AWS credential resolution and model access are checked by --live, not this local check.")
        if args.live:
            from .agent import run_turn
            from .persistence import now
            sessions = Sessions(args.data_dir)
            metadata = sessions.create(f"Connection check {now()}", name, profile)
            result = run_turn(sessions, metadata["session_id"],
                              "Please use search_destinations to inspect Porto, then ask me for my departure city. "
                              "This is a connection check, not a request for prices.", debug=args.debug)
            store = ArtifactStore(sessions.resolve(metadata["session_id"]))
            calls = [store.read(a["artifact_id"])["data"] for a in store.list("tool_calls")]
            if not any(call["name"] == "search_destinations" for call in calls):
                raise AppError("Model responded but did not perform the requested tool check; inspect its session artifacts.")
            render(result, debug=args.debug)
            print("Live model, tool execution and structured output check passed.")
        return

    sessions = Sessions(args.data_dir)
    if args.command == "session":
        if args.action == "create":
            settings = load_settings(args.config)
            name, profile = settings.select(args.profile)
            metadata = sessions.create(args.name, name, profile)
            emit(metadata)
            print(f"Resume: trip-agent session resume {metadata['session_id']}", file=sys.stderr)
            for problem in check_profile(profile):
                print(f"Before your first live turn: {problem}", file=sys.stderr)
        elif args.action == "list":
            emit(sessions.list(deleted=args.deleted))
        elif args.action == "rename":
            emit(sessions.rename(args.session, args.name))
        elif args.action in ("delete", "restore"):
            emit(sessions.move(args.session, restore=args.action == "restore"))
        elif args.action == "set-model":
            sessions.resolve(args.session)
            raise AppError("In-session model switching is deferred. This session was not modified or replaced.")
        else:
            path = sessions.resolve(args.session)
            if args.action == "show":
                with sessions.lock(path.name):
                    metadata = sessions.metadata(path)
                    current = path / "current_trip.json"
                    emit({**metadata, "current_trip": json.loads(current.read_text()) if current.exists() else None,
                          "artifact_count": len(ArtifactStore(path).list()), "path": str(path)})
            elif args.action == "resume":
                from .agent import run_turn
                with sessions.lock(path.name):
                    metadata = sessions.metadata(path)
                    ArtifactStore(path).event("session_resumed")
                terminal = Terminal(sys.stdout)
                terminal.write(f"Travel agent · {metadata['name']}", "heading")
                terminal.write("Type /exit to leave. Your conversation is saved automatically.", "muted")
                Terminal(sys.stderr).debug("Tool activity below is diagnostic output. "
                    + ("Full JSON details enabled." if args.debug else "Add --debug for full JSON details."))
                while True:
                    try:
                        request = input("\nYou> ").strip()
                    except EOFError:
                        break
                    if request in ("/exit", "/quit"):
                        break
                    if request:
                        try:
                            render(run_turn(sessions, path.name, request, debug=args.debug), debug=args.debug)
                        except AppError as exc:
                            print(f"Error: {exc}", file=sys.stderr)
        return
    if args.command == "run":
        from .agent import run_turn
        render(run_turn(sessions, args.session, args.request, debug=args.debug), args.json, debug=args.debug)
        return
    if args.command == "logbook":
        from .logbook import write_logbook
        path = sessions.resolve(args.session)
        with sessions.lock(path.name):
            target = write_logbook(path)
        print(target)
        if args.open:
            import webbrowser
            if not webbrowser.open(target.as_uri()):
                print("Open the path above in your browser.", file=sys.stderr)
        return
    if args.command == "artifacts":
        path = sessions.resolve(args.session)
        with sessions.lock(path.name):
            store = ArtifactStore(path)
            emit(store.read(args.read) if args.read else store.list(args.kind))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        execute(args)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Existing session evidence has been retained.", file=sys.stderr)
        return 130
    except (AppError, OSError, ValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
