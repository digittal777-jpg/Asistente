import argparse
import sys
import time

from core.assistant import RaphelAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Raphel: asistente de escritorio modular con automation y vision."
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Inicia una interfaz simple con tkinter en lugar del modo consola.",
    )
    parser.add_argument(
        "--command",
        type=str,
        help="Ejecuta un comando una sola vez y termina.",
    )
    parser.add_argument(
        "--remote-console",
        nargs="?",
        const=8765,
        type=int,
        help="Inicia solo la consola remota local y se queda sirviendo hasta Ctrl+C.",
    )
    parser.add_argument(
        "--remote-console-online",
        nargs="?",
        const=8765,
        type=int,
        help="Inicia la consola remota visible por LAN y se queda sirviendo hasta Ctrl+C.",
    )
    return parser


def _should_hold_after_command(command: str) -> bool:
    normalized = str(command or "").strip().lower()
    return normalized.startswith("remote-console-start") or normalized.startswith("remote-console-online")


def _serve_remote_console_until_interrupt(assistant: RaphelAssistant) -> int:
    print("Consola remota activa. Presiona Ctrl+C para detener.", flush=True)
    try:
        while assistant.remote_console.is_running():
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nDeteniendo consola remota...", flush=True)
    finally:
        assistant.shutdown()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    assistant = RaphelAssistant()

    if args.remote_console_online is not None:
        print(assistant.start_remote_console(port=args.remote_console_online, expose_online=True), flush=True)
        return _serve_remote_console_until_interrupt(assistant)

    if args.remote_console is not None:
        print(assistant.start_remote_console(port=args.remote_console, expose_online=False), flush=True)
        return _serve_remote_console_until_interrupt(assistant)

    if args.command:
        result = assistant.handle_command(args.command)
        print(result, flush=True)
        if _should_hold_after_command(args.command):
            return _serve_remote_console_until_interrupt(assistant)
        return 0

    if args.gui:
        assistant.run_gui()
        return 0

    assistant.run_console()
    return 0


if __name__ == "__main__":
    sys.exit(main())
