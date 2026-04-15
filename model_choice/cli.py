"""model_choice CLI."""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="model_choice",
        description="Universal LLM model selector and caller",
    )
    parser.add_argument("prompt", nargs="?", help="Prompt to send")
    parser.add_argument(
        "-c", "--complexity",
        choices=["fast", "balanced", "thorough", "auto"],
        default="balanced",
    )
    parser.add_argument("-m", "--model", help="Specific model to use")
    parser.add_argument("-t", "--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("-j", "--json", action="store_true",
                        help="Request JSON output (parsed and pretty-printed)")
    parser.add_argument("--list", action="store_true",
                        help="List available models and exit")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show which model was selected")
    parser.add_argument("-s", "--system", help="System prompt")

    args = parser.parse_args()

    from model_choice import list_models, generate, generate_json, pick

    if args.list:
        models = list_models()
        for m in models:
            status = "OK" if m["available"] else "--"
            print(f"  [{status}] {m['provider']:8s} "
                  f"{m['model']:30s} {m['label']}")
        sys.exit(0)

    if not args.prompt:
        parser.error("prompt is required unless --list is given")

    if args.verbose:
        # Show which model would be picked (runs classifier if auto)
        from model_choice import _resolve_complexity
        resolved = _resolve_complexity(args.complexity, args.prompt or "")
        provider = pick(complexity=resolved, model=args.model)
        if provider:
            if args.complexity == "auto":
                print(f"[model_choice] classified as {resolved}, using {provider.label}",
                      file=sys.stderr)
            else:
                print(f"[model_choice] {provider.label}", file=sys.stderr)
        else:
            print("[model_choice] no model available", file=sys.stderr)
            sys.exit(1)

    try:
        if args.json:
            result = generate_json(
                prompt=args.prompt,
                model=args.model,
                complexity=args.complexity,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                system=args.system,
            )
            print(json.dumps(result, indent=2))
        else:
            result = generate(
                prompt=args.prompt,
                model=args.model,
                complexity=args.complexity,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                system=args.system,
            )
            print(result)
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
