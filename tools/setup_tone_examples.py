#!/usr/bin/env python3
"""Interactive tone + style-example questionnaire for install.sh."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _load_prompts(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} must be a JSON object")
    return cfg


def _atomic_write_json(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tone-", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _prompt_line(label: str, *, example: str | None = None, required: bool = False) -> str:
    if example:
        print(f"  e.g. {example}")
    suffix = "" if required else " (Enter to skip)"
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        value = ""
    return value


def _compile_tone_guidelines(answers: dict[str, str]) -> str:
    parts: list[str] = []
    for key in ("casing", "length", "formality", "emoji"):
        val = answers.get(key, "").strip()
        if val:
            parts.append(val)
    return "; ".join(parts)


def _build_style_example(prompt: dict, reply: str) -> dict:
    item: dict[str, str] = {"reply": reply.strip()}
    label = (prompt.get("label") or "").strip()
    context = (prompt.get("context") or "").strip()
    incoming = prompt.get("incoming")
    if label:
        item["label"] = label
    if context:
        item["context"] = context
    if isinstance(incoming, str) and incoming.strip():
        item["incoming"] = incoming.strip()
    return item


def run_questionnaire(
    config_path: Path,
    prompts_path: Path,
    *,
    interactive: bool = True,
) -> int:
    questionnaire = _load_prompts(prompts_path)
    tone_questions = questionnaire.get("tone_questions") or []
    style_prompts = questionnaire.get("style_example_prompts") or []

    if not interactive or not sys.stdin.isatty():
        print("[install] Non-interactive — skipping tone / style questionnaire.", file=sys.stderr)
        return 2

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[install] Tone & style examples (optional)")
    print()
    print("  The conversation-planner can read message_rules.tone,")
    print("  message_rules.tone_guidelines, and message_rules.style_examples")
    print("  to mirror how you actually write on LinkedIn.")
    print()
    print("  If you opt in, you'll answer a short tone questionnaire, then")
    print("  write sample replies for common outreach scenarios.")
    print("  Skip any individual prompt with Enter.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    try:
        proceed = input("[install] Run tone & style questionnaires now? [y/N] ").strip()
    except EOFError:
        proceed = ""
    if proceed.lower() not in {"y", "yes"}:
        print("[install] Skipped — run later via Claude Code: /setup-outreach (Step 3).")
        return 3

    tone_short = ""
    tone_guideline_parts: dict[str, str] = {}

    print()
    print("[install] — Tone questionnaire —")
    for item in tone_questions:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "")
        question = str(item.get("question") or "").strip()
        example = item.get("example")
        if not question:
            continue
        print()
        print(f"  {question}")
        answer = _prompt_line("  Your answer", example=str(example) if example else None)
        if not answer:
            continue
        if qid == "tone_adjectives" or item.get("maps_to") == "message_rules.tone":
            tone_short = answer
        else:
            tone_guideline_parts[qid] = answer

    tone_guidelines = _compile_tone_guidelines(tone_guideline_parts)

    examples: list[dict] = []
    total = len(style_prompts)

    print()
    print("[install] — Style example questionnaire —")
    print(f"  {total} outreach scenarios. Write how you would actually reply.")
    print("  Press Enter on a reply prompt to skip that scenario.")
    print()

    for idx, prompt in enumerate(style_prompts, start=1):
        if not isinstance(prompt, dict):
            continue
        question = str(prompt.get("question") or "").strip()
        label = str(prompt.get("label") or prompt.get("id") or f"scenario {idx}").strip()
        hint = str(prompt.get("hint") or "").strip()
        incoming = prompt.get("incoming")

        print(f"  [{idx}/{total}] {label}")
        print(f"  {question}")
        if isinstance(incoming, str) and incoming.strip():
            print(f"  Prospect said: \"{incoming.strip()}\"")
        if hint:
            print(f"  Hint: {hint}")

        reply = _prompt_line("  Your reply")
        print()
        if not reply:
            continue
        examples.append(_build_style_example(prompt, reply))

    if not tone_short and not tone_guidelines and not examples:
        print("[install] No tone or examples provided — leaving config untouched.")
        return 4

    cfg = _load_config(config_path)
    rules = cfg.setdefault("message_rules", {})
    if not isinstance(rules, dict):
        print("[install] message_rules is not an object; aborting.", file=sys.stderr)
        return 1

    if tone_short:
        rules["tone"] = tone_short
    if tone_guidelines:
        rules["tone_guidelines"] = tone_guidelines
    elif "tone_guidelines" not in rules:
        rules["tone_guidelines"] = ""

    if examples:
        existing = rules.get("style_examples")
        if not isinstance(existing, list):
            existing = []
        rules["style_examples"] = existing + examples
    elif "style_examples" not in rules:
        rules["style_examples"] = []

    _atomic_write_json(config_path, cfg)

    print(f"[install] Updated {config_path}")
    print(f"[install]   tone:             {rules.get('tone', '')}")
    print(
        f"[install]   tone_guidelines:  "
        f"{rules.get('tone_guidelines', '') or '(blank)'}"
    )
    print(f"[install]   style_examples:   {len(rules.get('style_examples', []))} entry(ies)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to conversation_planner.json",
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        required=True,
        help="Path to style_example_prompts.json",
    )
    args = parser.parse_args()

    if not args.config.is_file():
        print(f"[install] Planner config not found: {args.config}", file=sys.stderr)
        return 5
    if not args.prompts.is_file():
        print(f"[install] Questionnaire not found: {args.prompts}", file=sys.stderr)
        return 5

    try:
        return run_questionnaire(args.config, args.prompts)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[install] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
