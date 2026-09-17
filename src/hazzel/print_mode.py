"""Non-interactive one-shot mode (`hazzel -p "prompt"`).

Runs a single prompt through the agent loop, prints the reply, and exits with a
script-friendly code. Stdout carries only the final answer (or a JSON payload);
all progress UI, diffs, and prompts stay silent. Without -y/--yes the turn is
read-only: file writes and shell commands are blocked with an explanatory
message instead of hanging on an approval prompt.
"""

import argparse
import json
import sys

STDIN_MAX_CHARS = 24000

EXIT_OK = 0
EXIT_TURN_FAILED = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130

_CONTACT_FAILURE_PREFIXES = ("unable to contact the model", "unable to connect")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hazzel",
        description="Hazzel — a small terminal coding agent. Run with no arguments for the interactive REPL.",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="prompt",
        nargs="?",
        const="",
        default=None,
        metavar="TEXT",
        help="run one prompt non-interactively and print the reply, then exit (prompt may come from piped stdin instead)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        dest="approve",
        action="store_true",
        help="pre-approve file writes and shell commands in -p mode (default is read-only)",
    )
    parser.add_argument(
        "--output-format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="print the reply as plain text (default) or a JSON object with response, model, and usage",
    )
    parser.add_argument("--version", "-V", dest="version", action="store_true", help="show the Hazzel version and exit")
    return parser


def read_piped_stdin(stdin=None):
    stream = stdin if stdin is not None else sys.stdin
    try:
        if stream.isatty():
            return None
    except Exception:
        return None
    try:
        text = stream.read()
    except (OSError, ValueError):
        return ""
    if not isinstance(text, str):
        return ""
    if len(text) > STDIN_MAX_CHARS:
        text = text[:STDIN_MAX_CHARS] + f"\n[... piped input truncated to {STDIN_MAX_CHARS} chars ...]"
    return text


def combine_prompt(prompt_text, piped):
    prompt = (prompt_text or "").strip()
    pipe = (piped or "").strip()
    if prompt and pipe:
        return prompt + "\n\n<piped_input>\n" + piped
    if prompt:
        return prompt
    if pipe:
        return pipe
    return None


def _restore_piped_process():
    # Standard CLI behavior: die quietly (SIGPIPE) instead of tracebacking when
    # downstream (e.g. `head`) closes the pipe.
    try:
        from signal import SIG_DFL, SIGPIPE, signal

        signal(SIGPIPE, SIG_DFL)
    except Exception:
        pass


def run_print(prompt, approve=False, output_format="text"):
    from hazzel import agent, config, ui
    from hazzel.agent.dispatch import set_print_approvals

    _restore_piped_process()
    agent.reset_conversation_state()
    ui.set_quiet(True)
    ui.set_print_mode(True)
    ui.set_auto_approve(bool(approve))
    set_print_approvals(bool(approve))
    try:
        try:
            needs_key = config.get_current_provider() not in config.KEYLESS_PROVIDERS and not config.has_any_key()
        except Exception:
            needs_key = False
        if needs_key:
            sys.stderr.write("No API key — run `hazzel` once and use /model to add one, or set a provider key (e.g. GROQ_API_KEY). Ollama needs no key.\n")
            return EXIT_USAGE
        messages = [{"role": "system", "content": agent.build_system_prompt(config.PROJECT_ROOT)}]
        try:
            result = agent.run(messages, prompt)
        except KeyboardInterrupt:
            return EXIT_CANCELLED
        except Exception as error:
            sys.stderr.write(f"Turn failed ({error}). Nothing was changed; try again.\n")
            return EXIT_TURN_FAILED
        if isinstance(result, tuple) and len(result) == 3:
            response = result[0]
        else:
            response = result
        response = (response or "").strip() or "(no reply)"
        if response.strip().lower() == "cancelled.":
            sys.stderr.write("Cancelled.\n")
            return EXIT_CANCELLED
        failed = response.lower().startswith(_CONTACT_FAILURE_PREFIXES)
        if failed:
            sys.stderr.write(response + "\n")
            return EXIT_TURN_FAILED
        if output_format == "json":
            try:
                model = config.get_current_display_name()
            except Exception:
                model = "hazzel"
            try:
                usage = agent.get_last_turn_usage()
            except Exception:
                usage = {}
            payload = {"success": True, "response": response, "model": model, "usage": usage}
            try:
                sys.stdout.write(json.dumps(payload, indent=2) + "\n")
            except BrokenPipeError:
                return EXIT_OK
            return EXIT_OK
        try:
            sys.stdout.write(response + "\n")
        except BrokenPipeError:
            return EXIT_OK
        return EXIT_OK
    finally:
        ui.set_quiet(False)
        ui.set_print_mode(False)
        ui.set_auto_approve(False)
        set_print_approvals(None)
