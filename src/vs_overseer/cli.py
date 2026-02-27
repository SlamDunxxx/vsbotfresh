from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request

from .config import load_config
from .dashboard import ensure_site
from .game_input import (
    get_game_input_arm_state,
    run_game_input_daemon,
    run_game_input_once,
    set_game_input_arm_state,
)
from .live_signal import generate_signal_once, run_signal_daemon
from .memory_backend import MemoryBackend
from .orchestrator import Orchestrator


def _default_config_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "config" / "settings.toml"


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    orchestrator = Orchestrator(cfg)
    result = orchestrator.run(
        max_generations=args.max_generations,
        api_host=args.host,
        api_port=args.port,
        enable_api=not bool(args.no_api),
    )
    print(json.dumps({
        "generations_completed": result.generations_completed,
        "stop_reason": result.stop_reason,
        "active_policy_id": result.active_policy_id,
        "safe_pause": result.safe_pause,
    }, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    path = cfg.resolve(cfg.reporting.status_file)
    if not path.exists():
        print(json.dumps({"status": "missing", "path": str(path)}, indent=2))
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(payload, indent=2))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    path = cfg.resolve(cfg.reporting.latest_summary_file)
    if not path.exists():
        print(json.dumps({"status": "missing", "path": str(path)}, indent=2))
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(payload, indent=2))
    return 0


def cmd_site_init(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    index = ensure_site(cfg.resolve(cfg.reporting.site_dir))
    print(json.dumps({"site_index": str(index)}, indent=2))
    return 0


def cmd_live_probe(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    probe = MemoryBackend(cfg).probe()
    payload = {
        "ok": probe.ok,
        "reason": probe.reason,
        "signal": (
            {
                "objective_hint": probe.signal.objective_hint,
                "stability_hint": probe.signal.stability_hint,
                "confidence": probe.signal.confidence,
                "source": probe.signal.source,
            }
            if probe.signal is not None
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_live_signal(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.watch:
        try:
            run_signal_daemon(
                cfg,
                save_path_override=args.save_path,
                output_override=args.output,
                interval_s=args.interval,
            )
        except KeyboardInterrupt:
            return 0
        return 0
    payload = generate_signal_once(
        cfg,
        save_path_override=args.save_path,
        output_override=args.output,
    )
    print(json.dumps(payload, indent=2))
    return 0 if bool(payload.get("ok", False)) else 2


def cmd_game_input(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    dry_run_override = bool(args.dry_run) if bool(args.dry_run) else None
    if args.watch:
        try:
            run_game_input_daemon(
                cfg,
                force=bool(args.force),
                status_output_override=args.status_output,
                interval_override=(args.interval if args.interval > 0.0 else None),
                dry_run_override=dry_run_override,
            )
        except KeyboardInterrupt:
            return 0
        return 0

    result = run_game_input_once(
        cfg,
        force=bool(args.force),
        status_output_override=args.status_output,
        dry_run_override=dry_run_override,
    )
    print(json.dumps(result.payload, indent=2))
    return 0 if result.ok else 2


def cmd_game_input_safety(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    action = str(args.safety_action)
    if action == "status":
        payload = get_game_input_arm_state(cfg)
        print(json.dumps(payload, indent=2))
        return 0 if bool(payload.get("ok", False)) else 1
    if action == "arm":
        payload = set_game_input_arm_state(
            cfg,
            armed=True,
            minutes=float(args.minutes),
            reason=str(args.reason),
            menu_only=bool(args.menu_only),
        )
        print(json.dumps(payload, indent=2))
        return 0 if bool(payload.get("ok", False)) else 2
    if action == "disarm":
        payload = set_game_input_arm_state(
            cfg,
            armed=False,
            minutes=0.0,
            reason=str(args.reason),
            menu_only=False,
        )
        print(json.dumps(payload, indent=2))
        return 0
    raise SystemExit(f"unknown safety action {action}")


def cmd_control(args: argparse.Namespace) -> int:
    base = f"http://{args.host}:{args.port}"
    if args.control_action == "stop":
        payload = _post_json(f"{base}/control/stop", {})
    elif args.control_action == "pause":
        payload = _post_json(f"{base}/control/pause", {"reason": args.reason})
    elif args.control_action == "resume":
        payload = _post_json(f"{base}/control/resume", {})
    elif args.control_action == "health":
        payload = _get_json(f"{base}/health")
    elif args.control_action == "latest-summary":
        payload = _get_json(f"{base}/summary/latest")
    else:
        raise SystemExit(f"unknown control action {args.control_action}")
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VSBotFresh CLI")
    parser.add_argument("--config", default=str(_default_config_path()))
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run unattended orchestrator")
    p_run.add_argument("--max-generations", type=int, default=0, help="0 means run forever")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8787)
    p_run.add_argument("--no-api", action="store_true", help="Disable local HTTP control server")
    p_run.set_defaults(func=cmd_run)

    p_once = sub.add_parser("once", help="Run one generation")
    p_once.add_argument("--host", default="127.0.0.1")
    p_once.add_argument("--port", type=int, default=8787)
    p_once.add_argument("--no-api", action="store_true", help="Disable local HTTP control server")
    p_once.set_defaults(func=lambda args: cmd_run(argparse.Namespace(**{**vars(args), "max_generations": 1})))

    p_status = sub.add_parser("status", help="Read latest health status file")
    p_status.set_defaults(func=cmd_status)

    p_summary = sub.add_parser("summary", help="Read latest summary file")
    p_summary.set_defaults(func=cmd_summary)

    p_site = sub.add_parser("site-init", help="Create local dashboard if missing")
    p_site.set_defaults(func=cmd_site_init)

    p_probe = sub.add_parser("live-probe", help="Probe memory-backed live backend availability")
    p_probe.set_defaults(func=cmd_live_probe)

    p_signal = sub.add_parser("live-signal", help="Generate or continuously refresh memory signal file from save data")
    p_signal.add_argument("--save-path", default="", help="Override live.save_data_path")
    p_signal.add_argument("--output", default="", help="Override live.memory_signal_file")
    p_signal.add_argument("--watch", action="store_true", help="Continuously refresh signal file")
    p_signal.add_argument("--interval", type=float, default=2.0, help="Watch interval seconds")
    p_signal.set_defaults(func=cmd_live_signal)

    p_game = sub.add_parser("game-input", help="Run native game input nudge loop")
    p_game.add_argument("--watch", action="store_true", help="Continuously evaluate and nudge when needed")
    p_game.add_argument("--interval", type=float, default=0.0, help="Override watch interval seconds")
    p_game.add_argument("--force", action="store_true", help="Ignore age/cooldown checks for one nudge attempt")
    p_game.add_argument("--dry-run", action="store_true", help="Evaluate and record status without keypresses")
    p_game.add_argument("--status-output", default="", help="Override game_input.status_file")
    p_game.set_defaults(func=cmd_game_input)

    p_safety = sub.add_parser("game-input-safety", help="Arm/disarm/status for input safety switch")
    p_safety.add_argument("safety_action", choices=["status", "arm", "disarm"])
    p_safety.add_argument("--minutes", type=float, default=15.0, help="Arm duration in minutes")
    p_safety.add_argument("--reason", default="manual")
    p_safety.add_argument("--menu-only", action="store_true", help="Allow only menu actions while armed")
    p_safety.set_defaults(func=cmd_game_input_safety)

    p_control = sub.add_parser("control", help="Send local control commands")
    p_control.add_argument("control_action", choices=["pause", "resume", "stop", "health", "latest-summary"])
    p_control.add_argument("--host", default="127.0.0.1")
    p_control.add_argument("--port", type=int, default=8787)
    p_control.add_argument("--reason", default="manual_pause")
    p_control.set_defaults(func=cmd_control)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
