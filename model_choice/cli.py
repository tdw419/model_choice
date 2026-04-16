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
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip response cache for this call")
    parser.add_argument("--no-fallback", action="store_true",
                        help="Don't retry with other providers on failure")
    parser.add_argument("--stats", action="store_true",
                        help="Show usage stats and exit")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear the response cache and exit")
    parser.add_argument("-T", "--template",
                        help="Use a named template (e.g. ollama_only, ai_daemon)")
    parser.add_argument("--templates", action="store_true",
                        help="List available templates and exit")
    parser.add_argument("--manage-ollama", action="store_true",
                        help="Auto-start ollama and pull models if unavailable")
    parser.add_argument("--ollama-status", action="store_true",
                        help="Show ollama status and exit")
    parser.add_argument("--ollama-start", action="store_true",
                        help="Start ollama and exit")
    parser.add_argument("--ollama-restart", action="store_true",
                        help="Restart ollama and exit")
    parser.add_argument("--ollama-pull",
                        help="Pull an ollama model and exit")

    args = parser.parse_args()

    from model_choice import (list_models, generate, generate_json, pick,
                               cost_summary, cache_stats, clear_cache,
                               _resolve_complexity, list_templates,
                               ollama_status, ollama_start, ollama_restart,
                               ollama_pull)

    if args.list:
        models = list_models()
        for m in models:
            status = "OK" if m["available"] else "--"
            print(f"  [{status}] {m['provider']:8s} "
                  f"{m['model']:30s} {m['label']}")
        sys.exit(0)

    if args.templates:
        tmpls = list_templates()
        if not tmpls:
            print("  (no templates defined)")
        for name, cfg in tmpls.items():
            providers = ", ".join(cfg["providers"])
            print(f"  {name:15s} providers=[{providers}] "
                  f"complexity={cfg['default_complexity']}")
        sys.exit(0)

    if args.ollama_status:
        status = ollama_status()
        if status["running"]:
            print("  Ollama: running")
            for m in status["models"]:
                print(f"    {m}")
        else:
            print("  Ollama: not running")
        sys.exit(0)

    if args.ollama_start:
        ok = ollama_start()
        print(f"  Ollama: {'running' if ok else 'failed to start'}")
        sys.exit(0 if ok else 1)

    if args.ollama_restart:
        ok = ollama_restart()
        print(f"  Ollama: {'running' if ok else 'failed to restart'}")
        sys.exit(0 if ok else 1)

    if args.ollama_pull:
        print(f"  Pulling {args.ollama_pull}...")
        ok = ollama_pull(args.ollama_pull)
        print(f"  {'Done' if ok else 'Failed'}")
        sys.exit(0 if ok else 1)

    if args.stats:
        summary = cost_summary()
        totals = cache_stats()
        print("Provider usage:")
        if not summary:
            print("  (no calls yet)")
        for name, stats in summary.items():
            print(f"  {name:10s} {stats['calls']} calls "
                  f"({stats['failures']} failed) "
                  f"{stats['total_tokens']} tokens")
        print()
        print(f"Cache: {totals['entries']} entries, "
              f"{totals['hits']} hits / {totals['misses']} misses "
              f"({totals['hit_rate']:.0%} hit rate)")
        sys.exit(0)

    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        sys.exit(0)

    if not args.prompt:
        parser.error("prompt is required unless --list/--templates/--ollama-status/--ollama-start/--ollama-restart/--ollama-pull/--stats/--clear-cache is given")

    if args.verbose:
        # Show which model would be picked (runs classifier if auto)
        resolved = _resolve_complexity(args.complexity, args.prompt or "")
        provider = pick(complexity=resolved, model=args.model,
                        template=args.template,
                        manage_ollama=args.manage_ollama)
        if provider:
            if args.complexity == "auto":
                print(f"[model_choice] classified as {resolved}, using {provider.label}",
                      file=sys.stderr)
            else:
                tmpl_str = f" (template={args.template})" if args.template else ""
                print(f"[model_choice] {provider.label}{tmpl_str}",
                      file=sys.stderr)
        else:
            print("[model_choice] no model available", file=sys.stderr)
            sys.exit(1)

    use_cache = not args.no_cache
    use_fallback = not args.no_fallback

    try:
        if args.json:
            result = generate_json(
                prompt=args.prompt,
                model=args.model,
                complexity=args.complexity,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                system=args.system,
                use_cache=use_cache,
                fallback=use_fallback,
                template=args.template,
                manage_ollama=args.manage_ollama,
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
                use_cache=use_cache,
                fallback=use_fallback,
                template=args.template,
                manage_ollama=args.manage_ollama,
            )
            print(result)
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
