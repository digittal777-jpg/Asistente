from __future__ import annotations

import threading
from datetime import datetime
from tkinter import END, messagebox
from typing import Any, Callable

try:
    import customtkinter as ctk

    CUSTOM_TK_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback local
    CUSTOM_TK_AVAILABLE = False
    import tkinter as tk
    from tkinter import ttk


class RaphelGUI:
    def __init__(self, assistant: Any) -> None:
        self.assistant = assistant
        self.status_text = "Listo"
        self.context_text = "Sin contexto todavia"
        self.root: Any = None

    def run(self) -> None:
        if CUSTOM_TK_AVAILABLE:
            self._run_customtkinter()
        else:
            self._run_tkinter_fallback()

    def _run_customtkinter(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        root = ctk.CTk()
        self.root = root
        root.title("Raphel")
        root.geometry("980x700")
        root.minsize(820, 620)
        root.attributes("-topmost", bool(self.assistant.config.get("gui", {}).get("always_on_top", True)))
        root.attributes("-alpha", float(self.assistant.config.get("gui", {}).get("alpha", 0.96)))

        self.assistant.set_confirmation_provider(
            lambda prompt: bool(messagebox.askyesno("Confirmacion requerida", prompt, parent=root))
        )
        self.assistant.add_status_listener(lambda msg, level="info": root.after(0, self._append_log, msg, level))
        self.assistant.add_context_listener(lambda context: root.after(0, self._update_context, context))
        if existing_context := self.assistant.get_context_payload():
            self._update_context(existing_context)

        outer = ctk.CTkFrame(root, corner_radius=18)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        top = ctk.CTkFrame(outer, corner_radius=14, fg_color="#1f2937")
        top.pack(fill="x", padx=14, pady=(14, 10))

        title = ctk.CTkLabel(
            top,
            text="Raphel",
            font=ctk.CTkFont("Segoe UI", 28, "bold"),
        )
        title.pack(anchor="w", padx=18, pady=(16, 2))

        subtitle = ctk.CTkLabel(
            top,
            text="Asistente de escritorio con automation, vision y skills activables por lenguaje natural.",
            font=ctk.CTkFont("Segoe UI", 13),
            text_color="#d1d5db",
        )
        subtitle.pack(anchor="w", padx=18, pady=(0, 16))

        status_bar = ctk.CTkFrame(outer, corner_radius=12, fg_color="#0f172a")
        status_bar.pack(fill="x", padx=14, pady=(0, 10))

        self.status_label = ctk.CTkLabel(
            status_bar,
            text="Estado: listo",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color="#93c5fd",
        )
        self.status_label.pack(anchor="w", padx=14, pady=(10, 4))

        self.context_label = ctk.CTkLabel(
            status_bar,
            text="Contexto: esperando snapshot...",
            font=ctk.CTkFont("Segoe UI", 12),
            text_color="#cbd5e1",
            justify="left",
            wraplength=760,
        )
        self.context_label.pack(anchor="w", padx=14, pady=(0, 8))

        controls = ctk.CTkFrame(status_bar, fg_color="transparent")
        controls.pack(fill="x", padx=14, pady=(0, 10))

        self.vision_button = ctk.CTkButton(
            controls,
            text="Detener vision" if self.assistant.vision.is_monitoring else "Activar vision",
            width=150,
            command=self._toggle_vision,
        )
        self.vision_button.pack(side="left")

        memory_button = ctk.CTkButton(
            controls,
            text="Memoria",
            width=120,
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._append_log(self.assistant.read_recent_history(limit=8), "info"),
        )
        memory_button.pack(side="left", padx=10)

        calibrate_button = ctk.CTkButton(
            controls,
            text="Calibrar UI",
            width=130,
            fg_color="#065f46",
            hover_color="#047857",
            command=self._calibrate_ui,
        )
        calibrate_button.pack(side="left")

        command_frame = ctk.CTkFrame(outer, corner_radius=14)
        command_frame.pack(fill="x", padx=14, pady=(0, 10))

        command_label = ctk.CTkLabel(
            command_frame,
            text="Comando",
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
        )
        command_label.pack(anchor="w", padx=16, pady=(14, 6))

        self.command_box = ctk.CTkTextbox(command_frame, height=140, font=("Segoe UI", 16))
        self.command_box.pack(fill="x", padx=16, pady=(0, 12))
        self.command_box.insert("1.0", "Abre Brave y pon YouTube")
        self.command_box.focus_set()
        self.command_box.bind("<Return>", self._on_enter_custom)
        self.command_box.bind("<Shift-Return>", self._allow_newline)

        buttons = ctk.CTkFrame(command_frame, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=(0, 14))

        execute_button = ctk.CTkButton(buttons, text="Ejecutar", width=140, command=self._submit_async)
        execute_button.pack(side="left")

        clear_button = ctk.CTkButton(
            buttons,
            text="Limpiar",
            width=120,
            fg_color="#374151",
            hover_color="#4b5563",
            command=lambda: self.command_box.delete("1.0", END),
        )
        clear_button.pack(side="left", padx=10)

        help_button = ctk.CTkButton(
            buttons,
            text="Skills",
            width=120,
            fg_color="#1d4ed8",
            hover_color="#2563eb",
            command=lambda: self._append_log(self.assistant._list_skills(), "info"),
        )
        help_button.pack(side="left")

        log_frame = ctk.CTkFrame(outer, corner_radius=14)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        log_label = ctk.CTkLabel(
            log_frame,
            text="Actividad en tiempo real",
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
        )
        log_label.pack(anchor="w", padx=16, pady=(14, 6))

        self.log_box = ctk.CTkTextbox(log_frame, font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.log_box.insert("1.0", "Raphel listo. Puedes escribir comandos naturales o directos.\n")
        self.log_box.configure(state="disabled")

        root.protocol("WM_DELETE_WINDOW", lambda: self._shutdown(root))
        root.mainloop()

    def _run_tkinter_fallback(self) -> None:
        root = tk.Tk()
        self.root = root
        root.title("Raphel")
        root.geometry("920x640")
        root.minsize(760, 560)
        root.attributes("-topmost", bool(self.assistant.config.get("gui", {}).get("always_on_top", True)))
        root.attributes("-alpha", float(self.assistant.config.get("gui", {}).get("alpha", 0.96)))

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Raphel.TFrame", background="#0f172a")
        style.configure("Raphel.TLabel", background="#0f172a", foreground="#e5e7eb", font=("Segoe UI", 11))
        style.configure("RaphelTitle.TLabel", background="#0f172a", foreground="#f8fafc", font=("Segoe UI", 22, "bold"))
        style.configure("Raphel.TButton", font=("Segoe UI", 11, "bold"))

        self.assistant.set_confirmation_provider(
            lambda prompt: bool(messagebox.askyesno("Confirmacion requerida", prompt, parent=root))
        )
        self.assistant.add_status_listener(lambda msg, level="info": root.after(0, self._append_log, msg, level))
        self.assistant.add_context_listener(lambda context: root.after(0, self._update_context, context))
        if existing_context := self.assistant.get_context_payload():
            self._update_context(existing_context)

        wrapper = ttk.Frame(root, style="Raphel.TFrame", padding=16)
        wrapper.pack(fill="both", expand=True)

        ttk.Label(wrapper, text="Raphel", style="RaphelTitle.TLabel").pack(anchor="w")
        ttk.Label(
            wrapper,
            text="Asistente de escritorio con control, vision y skills.",
            style="Raphel.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        self.status_label = ttk.Label(wrapper, text="Estado: listo", style="Raphel.TLabel")
        self.status_label.pack(anchor="w", pady=(0, 8))

        self.context_label = ttk.Label(
            wrapper,
            text="Contexto: esperando snapshot...",
            style="Raphel.TLabel",
            wraplength=760,
        )
        self.context_label.pack(anchor="w", pady=(0, 8))

        controls = ttk.Frame(wrapper)
        controls.pack(fill="x", pady=(0, 8))
        self.vision_button = ttk.Button(
            controls,
            text="Detener vision" if self.assistant.vision.is_monitoring else "Activar vision",
            style="Raphel.TButton",
            command=self._toggle_vision,
        )
        self.vision_button.pack(side="left")
        ttk.Button(
            controls,
            text="Memoria",
            style="Raphel.TButton",
            command=lambda: self._append_log(self.assistant.read_recent_history(limit=8), "info"),
        ).pack(side="left", padx=8)
        ttk.Button(
            controls,
            text="Calibrar UI",
            style="Raphel.TButton",
            command=self._calibrate_ui,
        ).pack(side="left", padx=8)

        ttk.Label(wrapper, text="Comando", style="Raphel.TLabel").pack(anchor="w")
        self.command_box = tk.Text(wrapper, height=6, font=("Segoe UI", 14), wrap="word")
        self.command_box.pack(fill="x", pady=(4, 8))
        self.command_box.insert("1.0", "Abre Brave y pon YouTube")
        self.command_box.bind("<Return>", self._on_enter_tk)
        self.command_box.bind("<Shift-Return>", self._allow_newline)

        buttons = ttk.Frame(wrapper)
        buttons.pack(fill="x", pady=(0, 10))
        ttk.Button(buttons, text="Ejecutar", style="Raphel.TButton", command=self._submit_async).pack(side="left")
        ttk.Button(buttons, text="Limpiar", style="Raphel.TButton", command=lambda: self.command_box.delete("1.0", END)).pack(side="left", padx=8)
        ttk.Button(buttons, text="Skills", style="Raphel.TButton", command=lambda: self._append_log(self.assistant._list_skills(), "info")).pack(side="left")

        ttk.Label(wrapper, text="Actividad en tiempo real", style="Raphel.TLabel").pack(anchor="w")
        self.log_box = tk.Text(wrapper, font=("Consolas", 11), wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))
        self.log_box.insert("1.0", "Raphel listo. Puedes escribir comandos naturales o directos.\n")
        self.log_box.configure(state="disabled")

        root.protocol("WM_DELETE_WINDOW", lambda: self._shutdown(root))
        root.mainloop()

    def _submit_async(self) -> None:
        command = self.command_box.get("1.0", END).strip()
        if not command:
            return
        self._set_status("Procesando comando...")
        self._append_log(f"> {command}", "command")
        plan = self.assistant.describe_command_plan(command)
        if plan:
            self._append_log(plan, "info")

        thread = threading.Thread(target=self._run_command, args=(command,), daemon=True)
        thread.start()

    def _run_command(self, command: str) -> None:
        try:
            result = self.assistant.handle_command(command)
            if self.root:
                self.root.after(0, self._append_log, result, "result")
                self.root.after(0, self._set_status, "Listo")
        except Exception as exc:  # pragma: no cover - defensa final
            if self.root:
                self.root.after(0, self._append_log, f"Error inesperado: {exc}", "error")
                self.root.after(0, self._set_status, "Error")

    def _append_log(self, message: str, level: str = "info") -> None:
        if not getattr(self, "log_box", None):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "command": "CMD",
            "result": "OK",
            "error": "ERR",
            "context": "CTX",
        }.get(level, "LOG")
        line = f"[{timestamp}] {prefix} | {message}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert(END, line)
        self.log_box.see(END)
        self.log_box.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status_text = text
        if getattr(self, "status_label", None):
            self.status_label.configure(text=f"Estado: {text}")

    def _update_context(self, context: dict[str, Any]) -> None:
        active_window = context.get("active_window") or "ninguna"
        active_app = context.get("active_app") or "desconocida"
        active_site = context.get("active_site") or "desconocido"
        browser_count = len(context.get("browsers_open", []))
        self.context_text = (
            f"Contexto: ventana={active_window} | app={active_app} | sitio={active_site} | "
            f"navegadores={browser_count}"
        )
        if getattr(self, "context_label", None):
            self.context_label.configure(text=self.context_text)

    def _toggle_vision(self) -> None:
        if self.assistant.vision.is_monitoring:
            result = self.assistant.stop_vision_monitor()
            button_text = "Activar vision"
        else:
            result = self.assistant.start_vision_monitor()
            button_text = "Detener vision"
        self._append_log(result, "info")
        if getattr(self, "vision_button", None):
            self.vision_button.configure(text=button_text)

    def _calibrate_ui(self) -> None:
        targets = self.assistant.ui_calibration_targets()
        self._append_log("Iniciando calibracion guiada de UI...", "info")
        for item in targets:
            target_name = item["name"]
            app_name = item["app"]
            should_capture = messagebox.askokcancel(
                "Calibrar UI",
                (
                    f"Coloca el cursor sobre '{target_name}' ({app_name}) y presiona OK.\n\n"
                    "Si ese elemento no esta visible ahora, presiona Cancel para omitirlo."
                ),
                parent=self.root,
            )
            if not should_capture:
                self._append_log(f"Calibracion omitida: {target_name}", "info")
                continue
            try:
                path = self.assistant.calibrate_ui_target(target_name, app_name)
                self._append_log(f"Template guardado: {target_name} -> {path}", "result")
            except Exception as exc:
                self._append_log(f"No se pudo calibrar {target_name}: {exc}", "error")
        self._append_log(self.assistant.calibration_status(), "info")

    def _shutdown(self, root: Any) -> None:
        self.assistant.shutdown()
        root.destroy()

    def _on_enter_custom(self, event: Any) -> str:
        if getattr(event, "state", 0) & 0x1:
            return ""
        self._submit_async()
        return "break"

    def _on_enter_tk(self, event: Any) -> str:
        if getattr(event, "state", 0) & 0x1:
            return ""
        self._submit_async()
        return "break"

    @staticmethod
    def _allow_newline(event: Any) -> None:
        return None
