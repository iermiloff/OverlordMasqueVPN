import os
import json
import subprocess
import threading
import sys
import socket
import base64
import ctypes
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import customtkinter as ctk

from routing import (
    PRESETS,
    PRESET_RU,
    PRESET_CINEMA,
    PRESET_BITTORRENT,
    PRESET_GAMES,
    PRESET_ADS,
    build_routing_rules,
    build_direct_lists,
    build_dns_config,
)
from updater import check_and_update_geodata, get_effective_geodata_paths

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ==================== ПУТИ К ПОЛЬЗОВАТЕЛЬСКИМ ДАННЫМ ====================

def get_user_data_dir():
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    data_dir = os.path.join(appdata, "OverlordMasque")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        import tempfile
        data_dir = os.path.join(tempfile.gettempdir(), "OverlordMasque")
        os.makedirs(data_dir, exist_ok=True)
    return data_dir


USER_DATA_DIR = get_user_data_dir()
SETTINGS_FILE = os.path.join(USER_DATA_DIR, "user_saved_config.json")
PROFILES_FILE = os.path.join(USER_DATA_DIR, "saved_profiles.json")
CONFIG_TEMP_FILE = os.path.join(USER_DATA_DIR, "config_temp.json")


def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ==================== ОБФУСКАЦИЯ ПАРОЛЕЙ ====================

def obfuscate(text: str) -> str:
    if not text:
        return ""
    return "b64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def deobfuscate(text: str) -> str:
    if not text:
        return ""
    if text.startswith("b64:"):
        try:
            return base64.b64decode(text[4:]).decode("utf-8")
        except Exception:
            return text
    return text


# ==================== UAC ====================

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = ""
    else:
        exe = sys.executable
        params = " ".join(f'"{arg}"' for arg in sys.argv)
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return ret > 32
    except Exception:
        return False


# ==================== ДИАЛОГ ПРАВИЛ МАРШРУТИЗАЦИИ ====================

class RoutingRulesDialog(ctk.CTkToplevel):
    def __init__(self, parent, current_presets: set, current_custom: list,
                 use_ru_blocked_filter: bool, use_ru_dns: bool,
                 bypass_ru_tld: bool, on_save):
        super().__init__(parent)
        self.title("Правила маршрутизации")
        self.geometry("520x900")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.on_save = on_save
        self.preset_vars = {}
        self.use_ru_blocked_filter_var = ctk.BooleanVar(value=use_ru_blocked_filter)
        self.use_ru_dns_var = ctk.BooleanVar(value=use_ru_dns)
        self.bypass_ru_tld_var = ctk.BooleanVar(value=bypass_ru_tld)

        ctk.CTkLabel(
            self, text="ПРАВИЛА МАРШРУТИЗАЦИИ",
            font=ctk.CTkFont(family="Impact", size=20, weight="bold"),
            text_color="#990000",
        ).pack(pady=(20, 5))

        ctk.CTkLabel(
            self, text="Выберите, что пускать напрямую, минуя туннель",
            font=ctk.CTkFont(size=12), text_color="#aaaaaa",
        ).pack(pady=(0, 15))

        presets_frame = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        presets_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(
            presets_frame, text="Пресеты:",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#cccccc",
        ).pack(anchor="w", padx=15, pady=(10, 5))

        for preset_id, preset_data in PRESETS.items():
            var = ctk.BooleanVar(value=preset_id in current_presets)
            self.preset_vars[preset_id] = var
            ctk.CTkCheckBox(
                presets_frame, text=preset_data["label"], variable=var,
                font=ctk.CTkFont(size=12), checkbox_width=18, checkbox_height=18,
                fg_color="#990000", hover_color="#cc0000",
            ).pack(anchor="w", padx=25, pady=3)
        ctk.CTkLabel(presets_frame, text="", height=5).pack()

        tld_frame = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        tld_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkCheckBox(
            tld_frame,
            text="Все .ru и .рф домены — напрямую\n"
                 "(до geoip/geosite, закрывает 90% российских сайтов)",
            variable=self.bypass_ru_tld_var,
            font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            fg_color="#990000", hover_color="#cc0000",
        ).pack(anchor="w", padx=15, pady=10)

        ctk.CTkLabel(
            tld_frame,
            text="Простейший способ ускорить российские сайты без больших списков.",
            font=ctk.CTkFont(size=9), text_color="#777777",
        ).pack(anchor="w", padx=15, pady=(0, 8))

        ru_blocked_frame = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        ru_blocked_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkCheckBox(
            ru_blocked_frame,
            text="Учитывать блокировки РФ\n"
                 "(российские сайты, заблокированные в РФ → через туннель)",
            variable=self.use_ru_blocked_filter_var,
            font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            fg_color="#990000", hover_color="#cc0000",
        ).pack(anchor="w", padx=15, pady=10)

        ctk.CTkLabel(
            ru_blocked_frame,
            text="Требует свежих geosite.dat/geoip.dat (обновляются автоматически).",
            font=ctk.CTkFont(size=9), text_color="#777777",
        ).pack(anchor="w", padx=15, pady=(0, 8))

        ru_dns_frame = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        ru_dns_frame.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkCheckBox(
            ru_dns_frame,
            text="Российский DNS для прямых соединений\n"
                 "(Яндекс 77.88.8.8 вместо Cloudflare)",
            variable=self.use_ru_dns_var,
            font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            fg_color="#990000", hover_color="#cc0000",
        ).pack(anchor="w", padx=15, pady=10)

        ctk.CTkLabel(
            ru_dns_frame,
            text="Снижает несовпадение DNS и IP при работе с российскими сайтами.",
            font=ctk.CTkFont(size=9), text_color="#777777",
        ).pack(anchor="w", padx=15, pady=(0, 8))

        ctk.CTkLabel(
            self, text="Свои домены и IP (по одному на строку):",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#cccccc",
        ).pack(anchor="w", padx=20, pady=(10, 5))

        self.custom_textbox = ctk.CTkTextbox(
            self, width=480, height=100,
            fg_color="#121212", text_color="#00ff00",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.custom_textbox.pack(padx=20, pady=(0, 5))
        if current_custom:
            self.custom_textbox.insert("1.0", "\n".join(current_custom))

        ctk.CTkLabel(
            self,
            text="Поддерживаются: domain, geosite:, geoip:, IP, CIDR, regexp:.\n"
                 "Строки, начинающиеся с #, игнорируются.",
            font=ctk.CTkFont(size=10), text_color="#777777", justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 15))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))

        ctk.CTkButton(
            btn_frame, text="Сохранить", command=self._save,
            width=160, height=38, fg_color="#990000", hover_color="#cc0000",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="Отмена", command=self.destroy,
            width=160, height=38, fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=10)

    def _save(self):
        try:
            selected_presets = {pid for pid, var in self.preset_vars.items() if var.get()}
            custom_lines = self.custom_textbox.get("1.0", "end-1c").splitlines()
            custom_lines = [line for line in custom_lines if line.strip()]
            self.on_save(
                selected_presets,
                custom_lines,
                self.use_ru_blocked_filter_var.get(),
                self.use_ru_dns_var.get(),
                self.bypass_ru_tld_var.get(),
            )
        except Exception as e:
            print(f"[RoutingDialog] Save error: {e}")
        finally:
            try:
                self.grab_release()
            except Exception:
                pass
            self.after(10, self.destroy)


# ==================== ОСНОВНОЕ ПРИЛОЖЕНИЕ ====================

class OverlordMasqueApp(ctk.CTk):
    ERROR_TIMEOUT_SEC = 10
    WATCHDOG_INTERVAL_SEC = 5
    WATCHDOG_MAX_RESTARTS = 3
    WATCHDOG_STABLE_RESET_SEC = 60

    def __init__(self):
        super().__init__()

        self.title("OverlordMasque")
        self.geometry("780x600")
        self.resizable(False, False)

        self.accent_color = "#990000"
        self.hover_color = "#cc0000"
        self.bg_frame_color = "#1e1e1e"

        self.xray_process = None
        self.is_connected = False
        self.h2_fallback_attempted = False
        self.server_ip = None
        self.last_error_ts = 0.0

        # Watchdog
        self.watchdog_thread = None
        self.watchdog_restart_count = 0
        self._watchdog_paused = False
        self.xray_start_time = 0.0

        self.routing_presets = set()
        self.routing_custom = []
        self.use_ru_blocked_filter = False
        self.use_ru_dns = True
        self.bypass_ru_tld = False

        # ==================== ЛЕВАЯ ПАНЕЛЬ ====================
        self.left_frame = ctk.CTkFrame(self, width=390, corner_radius=15, fg_color=self.bg_frame_color)
        self.left_frame.pack(side="left", fill="y", padx=15, pady=15)

        ctk.CTkLabel(
            self.left_frame, text="OVERLORD MASQUE",
            font=ctk.CTkFont(family="Impact", size=24, weight="bold"),
            text_color=self.accent_color,
        ).pack(pady=15)

        self.profile_var = ctk.StringVar(value="Выбрать профиль...")
        self.profile_menu = ctk.CTkOptionMenu(
            self.left_frame, values=self.load_profile_names(),
            variable=self.profile_var, command=self.on_profile_select,
            width=330, fg_color="#333333",
            button_color=self.accent_color, button_hover_color=self.hover_color,
        )
        self.profile_menu.pack(pady=(0, 10))

        self.entry_domain = ctk.CTkEntry(self.left_frame, placeholder_text="Домен сервера (напр., server.com)", width=330, height=35)
        self.entry_domain.pack(pady=5)

        self.entry_port = ctk.CTkEntry(self.left_frame, placeholder_text="Порт (напр., 8080)", width=330, height=35)
        self.entry_port.pack(pady=5)

        self.entry_user = ctk.CTkEntry(self.left_frame, placeholder_text="Имя пользователя (Логин)", width=330, height=35)
        self.entry_user.pack(pady=5)

        self.entry_pass = ctk.CTkEntry(self.left_frame, placeholder_text="Пароль пользователя", width=330, height=35, show="*")
        self.entry_pass.pack(pady=5)

        for entry in (self.entry_domain, self.entry_port, self.entry_user, self.entry_pass):
            self._bind_clipboard(entry)

        self.button_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.button_frame.pack(pady=(10, 0))

        ctk.CTkButton(
            self.button_frame, text="Сохранить профиль", command=self.save_profile,
            width=160, height=32, fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            self.button_frame, text="Сохранить логи", command=self.save_logs,
            width=160, height=32, fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=3)

        self.btn_routing = ctk.CTkButton(
            self.left_frame,
            text="⚙  РАЗДЕЛЬНАЯ МАРШРУТИЗАЦИЯ",
            command=self.open_routing_dialog,
            width=330, height=36,
            fg_color="#5a5a5a", hover_color="#707070",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.btn_routing.pack(pady=(8, 0))

        self.routing_summary_label = ctk.CTkLabel(
            self.left_frame, text="Маршрутизация: по умолчанию",
            font=ctk.CTkFont(size=10), text_color="#888888",
        )
        self.routing_summary_label.pack(pady=(3, 0))

        self.btn_connect = ctk.CTkButton(
            self.left_frame, text="АКТИВИРОВАТЬ VPN", command=self.toggle_connection,
            width=220, height=42, fg_color=self.accent_color, hover_color=self.hover_color,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.btn_connect.pack(pady=15)

        self.status_label = ctk.CTkLabel(
            self.left_frame, text="СТАТУС: СИСТЕМА ДЕАКТИВИРОВАНА",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="gray",
        )
        self.status_label.pack(side="bottom", pady=10)

        # ==================== ПРАВАЯ ПАНЕЛЬ ====================
        self.right_frame = ctk.CTkFrame(self, width=350, corner_radius=15, fg_color=self.bg_frame_color)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=15, pady=15)

        ctk.CTkLabel(
            self.right_frame, text="ЛОГИ СЕТЕВОГО ЯДРА:",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#aaaaaa",
        ).pack(pady=10)

        self.log_textbox = ctk.CTkTextbox(
            self.right_frame, width=330, height=470,
            fg_color="#121212", text_color="#00ff00",
            font=ctk.CTkFont(family="Consolas", size=10),
        )
        self.log_textbox.pack(padx=10, pady=10, fill="both", expand=True)

        # ==================== РЕСУРСЫ ====================
        self.xray_path = get_resource_path("xray.exe")
        self.wintun_path = get_resource_path("wintun.dll")

        if not os.path.exists(self.xray_path) or not os.path.exists(self.wintun_path):
            self.log_print("КРИТИЧЕСКАЯ ОШИБКА: Компоненты ядра не интегрированы!")
            self.btn_connect.configure(state="disabled")

        self.geosite_path = get_resource_path("geosite.dat")
        self.geoip_path = get_resource_path("geoip.dat")
        if not os.path.exists(self.geosite_path) or not os.path.exists(self.geoip_path):
            self.log_print(
                "ВНИМАНИЕ: geosite.dat / geoip.dat не найдены в сборке. "
                "Правила с geosite: и geoip: работать не будут. "
                "Будут использоваться скачанные версии (при наличии интернета)."
            )

        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.load_saved_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.after(2000, self._check_error_timeout)

        threading.Thread(target=self._background_geodata_update, daemon=True).start()

    # ==================== WATCHDOG ====================

    def _start_watchdog(self):
        self.watchdog_restart_count = 0
        self._watchdog_paused = False
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog_thread.start()

    def _watchdog_loop(self):
        while self.is_connected:
            time.sleep(self.WATCHDOG_INTERVAL_SEC)
            if not self.is_connected:
                break
            if self._watchdog_paused:
                continue
            if self.xray_process is None:
                continue

            if self.xray_process.poll() is None:
                # Процесс жив. Сбрасываем счётчик, если он стабильно прожил N секунд
                if (self.xray_start_time > 0
                        and time.time() - self.xray_start_time > self.WATCHDOG_STABLE_RESET_SEC):
                    self.watchdog_restart_count = 0
                continue

            self.watchdog_restart_count += 1
            if self.watchdog_restart_count > self.WATCHDOG_MAX_RESTARTS:
                self.after(0, self._on_watchdog_give_up)
                return

            n = self.watchdog_restart_count
            self.after(0, lambda n=n: self._on_watchdog_restart(n))
            self.after(0, self._restart_xray_only)

    def _on_watchdog_restart(self, attempt: int):
        self._force_window_attention()
        self.status_label.configure(
            text=f"ВНИМАНИЕ: ЯДРО УПАЛО, ПЕРЕЗАПУСК {attempt}/{self.WATCHDOG_MAX_RESTARTS}",
            text_color="orange",
        )
        self.log_print(f"[WATCHDOG] Ядро упало, попытка перезапуска {attempt}/{self.WATCHDOG_MAX_RESTARTS}")

    def _on_watchdog_give_up(self):
        self._force_window_attention()
        self.status_label.configure(
            text="СТАТУС: ЯДРО ПАДАЕТ, АВТОПЕРЕЗАПУСК ОСТАНОВЛЕН",
            text_color="red",
        )
        self.log_print(
            f"[WATCHDOG] Превышено число попыток ({self.WATCHDOG_MAX_RESTARTS}). "
            "Автоперезапуск остановлен. Проверьте конфигурацию или связь с сервером."
        )
        self.after(500, self.disconnect)

    def _restart_xray_only(self):
        if self.xray_process:
            try:
                self.xray_process.terminate()
                self.xray_process.wait(timeout=3)
            except Exception:
                try:
                    self.xray_process.kill()
                except Exception:
                    pass
        self.xray_process = None
        self.xray_start_time = 0.0
        self.xray_thread = threading.Thread(target=self.run_xray, daemon=True)
        self.xray_thread.start()
        self.log_print("[WATCHDOG] Ядро перезапущено.")

    def _force_window_attention(self):

        try:
            if self.state() == "iconic":
                self.deiconify()
                self.lift()

            self._flash_taskbar()
        except Exception:
            pass

    def _flash_taskbar(self):
        try:
            from ctypes import wintypes

            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                ]

            FLASHW_ALL = 3
            FLASHW_TIMERNOFG = 12

            fi = FLASHWINFO(
                cbSize=ctypes.sizeof(FLASHWINFO),
                hwnd=hwnd,
                dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,
                uCount=3,
                dwTimeout=0,
            )
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        except Exception:
            pass

    # ==================== МОНИТОР СТАТУСА ОШИБКИ ====================

    def _check_error_timeout(self):
        try:
            if (self.is_connected
                    and self.last_error_ts > 0
                    and time.time() - self.last_error_ts >= self.ERROR_TIMEOUT_SEC):
                self.last_error_ts = 0.0
                # Не перебиваем статус watchdog'а, если он уже что-то показал
                if self.status_label.cget("text").startswith("ВНИМАНИЕ"):
                    self.status_label.configure(
                        text="СТАТУС: ТУННЕЛЬ АКТИВЕН", text_color="green"
                    )
                self.log_print(
                    f"[СИСТЕМА] Ошибки в логах прекратились "
                    f"({self.ERROR_TIMEOUT_SEC}с без новых сбоев), статус восстановлен."
                )
        except Exception:
            pass
        finally:
            self.after(2000, self._check_error_timeout)

    # ==================== ФОНОВОЕ ОБНОВЛЕНИЕ GEODATA ====================

    def _background_geodata_update(self):
        def safe_log(msg):
            self.after(0, lambda: self.log_print(msg))

        try:
            result = check_and_update_geodata(USER_DATA_DIR, log_callback=safe_log)
            updated = [k for k, v in result.items() if v == "updated"]
            if updated:
                self.after(0, lambda: self.log_print(
                    f"[СИСТЕМА] Geodata обновлена: {', '.join(updated)}"
                ))
            else:
                self.after(0, lambda: self.log_print(
                    "[СИСТЕМА] Geodata актуальна, скачивание не требуется."
                ))
        except Exception as e:
            self.after(0, lambda: self.log_print(f"[UPDATER] Ошибка фоновой проверки: {e}"))

    # ==================== БУФЕР ОБМЕНА ====================

    def _bind_clipboard(self, entry_widget):
        inner_entry = getattr(entry_widget, "_entry", None) or getattr(entry_widget, "entry", None)
        if inner_entry is None:
            return

        def paste(event=None):
            try:
                text = inner_entry.clipboard_get()
                if inner_entry.selection_present():
                    inner_entry.delete("sel.first", "sel.last")
                inner_entry.insert("insert", text)
            except tk.TclError:
                pass
            return "break"

        def copy(event=None):
            try:
                if inner_entry.selection_present():
                    inner_entry.clipboard_clear()
                    inner_entry.clipboard_append(inner_entry.selection_get())
            except tk.TclError:
                pass
            return "break"

        def cut(event=None):
            copy()
            try:
                if inner_entry.selection_present():
                    inner_entry.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            return "break"

        def select_all(event=None):
            inner_entry.select_range(0, "end")
            return "break"

        inner_entry.bind("<Control-v>", paste)
        inner_entry.bind("<Control-c>", copy)
        inner_entry.bind("<Control-x>", cut)
        inner_entry.bind("<Control-a>", select_all)
        inner_entry.bind("<Shift-Insert>", paste)
        inner_entry.bind("<Control-Insert>", copy)

        def on_ctrl(event):
            if not (event.state & 0x4):
                return None
            ks = (event.keysym or "").lower()
            if event.keycode == 86 and ks != "v": return paste()
            if event.keycode == 67 and ks != "c": return copy()
            if event.keycode == 88 and ks != "x": return cut()
            if event.keycode == 65 and ks != "a": return select_all()
            return None

        inner_entry.bind("<Control-KeyPress>", on_ctrl)

        menu = tk.Menu(inner_entry, tearoff=0)
        menu.add_command(label="Копировать", command=copy)
        menu.add_command(label="Вставить", command=paste)
        menu.add_command(label="Вырезать", command=cut)
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=select_all)

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        inner_entry.bind("<Button-3>", show_menu)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ ====================

    def log_print(self, text):
        self.log_textbox.insert("end", text + "\n")
        self.log_textbox.see("end")

    def get_hidden_startupinfo(self):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si

    def _update_routing_summary(self):
        parts = []
        preset_count = len(self.routing_presets)
        custom_count = len([l for l in self.routing_custom if l.strip()])
        if preset_count:
            parts.append(f"пресетов: {preset_count}")
        if custom_count:
            parts.append(f"правил: {custom_count}")
        if self.bypass_ru_tld:
            parts.append(".ru/.рф: вкл")
        if self.use_ru_blocked_filter:
            parts.append("фильтр РФ: вкл")
        if not self.use_ru_dns:
            parts.append("RU-DNS: выкл")
        text = "Маршрутизация: " + (", ".join(parts) if parts else "по умолчанию")
        self.routing_summary_label.configure(text=text)

    # ==================== ДИАЛОГ МАРШРУТИЗАЦИИ ====================

    def open_routing_dialog(self):
        RoutingRulesDialog(
            self, self.routing_presets, self.routing_custom,
            self.use_ru_blocked_filter, self.use_ru_dns,
            self.bypass_ru_tld,
            on_save=self._on_routing_saved,
        )

    def _on_routing_saved(self, presets: set, custom: list,
                          use_ru_blocked_filter: bool, use_ru_dns: bool,
                          bypass_ru_tld: bool):
        self.routing_presets = presets
        self.routing_custom = custom
        self.use_ru_blocked_filter = use_ru_blocked_filter
        self.use_ru_dns = use_ru_dns
        self.bypass_ru_tld = bypass_ru_tld
        self._update_routing_summary()
        self.log_print(
            f"[СИСТЕМА] Маршрутизация обновлена: пресетов {len(presets)}, "
            f"кастомных строк {len([l for l in custom if l.strip()])}, "
            f".ru/.рф: {'вкл' if bypass_ru_tld else 'выкл'}, "
            f"фильтр РФ: {'вкл' if use_ru_blocked_filter else 'выкл'}, "
            f"RU-DNS: {'вкл' if use_ru_dns else 'выкл'}"
        )
        if self.is_connected:
            self.log_print("[СИСТЕМА] Перезапуск туннеля для применения правил...")
            self.after(150, self._restart_tunnel)

    def _restart_tunnel(self):
        try:
            self.disconnect()
        finally:
            self.after(500, self.toggle_connection)

    # ==================== ПРОФИЛИ ====================

    def load_profile_names(self):
        if not os.path.exists(PROFILES_FILE):
            return ["Нет сохранённых профилей"]
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            return list(profiles.keys()) if profiles else ["Нет сохранённых профилей"]
        except Exception:
            return ["Ошибка загрузки"]

    def save_profile(self):
        domain = self.entry_domain.get().strip()
        port = self.entry_port.get().strip()
        user = self.entry_user.get().strip()
        password = self.entry_pass.get().strip()

        if not all([domain, port, user, password]):
            self.status_label.configure(text="ЗАПОЛНИТЕ ВСЕ ПОЛЯ!", text_color="orange")
            return
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            self.status_label.configure(text="ПОРТ: 1-65535", text_color="orange")
            return

        name = simpledialog.askstring("Имя профиля", "Название:", initialvalue=domain)
        if not name:
            return

        profiles = {}
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                pass

        profiles[name] = {
            "domain": domain,
            "port": port,
            "user": user,
            "password": obfuscate(password),
            "routing_presets": list(self.routing_presets),
            "routing_custom": list(self.routing_custom),
            "use_ru_blocked_filter": self.use_ru_blocked_filter,
            "use_ru_dns": self.use_ru_dns,
            "bypass_ru_tld": self.bypass_ru_tld,
        }

        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
            self.log_print(f"[СИСТЕМА] Профиль '{name}' сохранён.")
            self.profile_menu.configure(values=list(profiles.keys()))
            self.profile_var.set(name)
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка сохранения профиля: {e}")

    def on_profile_select(self, choice):
        if choice in ("Нет сохранённых профилей", "Ошибка загрузки"):
            return
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            if choice not in profiles:
                return
            data = profiles[choice]
            self.entry_domain.delete(0, "end"); self.entry_domain.insert(0, data.get("domain", ""))
            self.entry_port.delete(0, "end");   self.entry_port.insert(0, data.get("port", ""))
            self.entry_user.delete(0, "end");   self.entry_user.insert(0, data.get("user", ""))
            self.entry_pass.delete(0, "end");   self.entry_pass.insert(0, deobfuscate(data.get("password", "")))
            self.routing_presets = set(data.get("routing_presets", []))
            self.routing_custom = list(data.get("routing_custom", []))
            self.use_ru_blocked_filter = bool(data.get("use_ru_blocked_filter", False))
            self.use_ru_dns = bool(data.get("use_ru_dns", True))
            self.bypass_ru_tld = bool(data.get("bypass_ru_tld", False))
            self._update_routing_summary()
            self.log_print(f"[СИСТЕМА] Профиль '{choice}' загружен.")
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка загрузки профиля: {e}")

    def save_logs(self):
        content = self.log_textbox.get("1.0", "end-1c")
        if not content.strip():
            self.log_print("[СИСТЕМА] Логи пусты.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            initialfile="masque_session_log.txt",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log_print(f"[СИСТЕМА] Логи сохранены: {path}")
            except Exception as e:
                self.log_print(f"[СИСТЕМА] Ошибка: {e}")

    # ==================== НАСТРОЙКИ СЕССИИ ====================

    def load_saved_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entry_domain.insert(0, data.get("domain", ""))
                self.entry_port.insert(0, data.get("port", ""))
                self.entry_user.insert(0, data.get("user", ""))
                self.entry_pass.insert(0, deobfuscate(data.get("password", "")))
                self.routing_presets = set(data.get("routing_presets", []))
                self.routing_custom = list(data.get("routing_custom", []))
                self.use_ru_blocked_filter = bool(data.get("use_ru_blocked_filter", False))
                self.use_ru_dns = bool(data.get("use_ru_dns", True))
                self.bypass_ru_tld = bool(data.get("bypass_ru_tld", False))
                self._update_routing_summary()
                self.log_print("[СИСТЕМА] Предыдущая конфигурация импортирована.")
            except Exception as e:
                self.log_print(f"[СИСТЕМА] Ошибка чтения настроек: {e}")

    def save_settings(self, domain, port, user, password):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "domain": domain, "port": port, "user": user,
                    "password": obfuscate(password),
                    "routing_presets": list(self.routing_presets),
                    "routing_custom": list(self.routing_custom),
                    "use_ru_blocked_filter": self.use_ru_blocked_filter,
                    "use_ru_dns": self.use_ru_dns,
                    "bypass_ru_tld": self.bypass_ru_tld,
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка сохранения: {e}")

    # ==================== КОНФИГ XRAY ====================

    def generate_tun_config(self, domain, port, user, password, server_ip, force_h2=False):
        alpn = ["h2"] if force_h2 else ["h3", "h2"]

        bypass_bittorrent = PRESET_BITTORRENT in self.routing_presets
        rules = build_routing_rules(
            self.routing_presets, self.routing_custom, bypass_bittorrent,
            use_ru_blocked_filter=self.use_ru_blocked_filter,
            bypass_ru_tld=self.bypass_ru_tld,
        )

        direct_domains, direct_ips, _, _ = build_direct_lists(
            self.routing_presets, self.routing_custom
        )
        dns_config = build_dns_config(direct_domains, self.use_ru_dns)

        domain_strategy = "IPIfNonMatch" if self.use_ru_blocked_filter else "AsIs"

        bundled_dir = os.path.dirname(get_resource_path("xray.exe"))
        geosite_path, geoip_path = get_effective_geodata_paths(USER_DATA_DIR, bundled_dir)

        config = {
            "log": {"loglevel": "info"},
            "dns": dns_config,
            "routing": {
                "domainStrategy": domain_strategy,
                "rules": rules,
            },
            "inbounds": [{
                "protocol": "tun",
                "tag": "tun-in",
                "settings": {
                    "name": "masque-tun0",
                    "desc": "Wintun",
                    "mtu": 1350,
                    "gateway": ["172.19.0.1/30"],
                    "autoSystemRoutingTable": ["0.0.0.0/0", "::/0"],
                    "autoOutboundsInterface": "auto",
                    "autoSystemWfpBlockLeak": ["dns", "misconfigtun"],
                    "dns": ["1.1.1.1", "8.8.8.8"],
                    "stack": "gvisor",
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                },
            }],
            "outbounds": [{
                "protocol": "masque",
                "settings": {
                    "address": server_ip,
                    "port": int(port),
                    "remoteDNS": ["1.1.1.1", "8.8.8.8"],
                },
                "tag": "proxy",
                "streamSettings": {
                    "method": "masque",
                    "masqueSettings": {
                        "host": domain,
                        "path": "/.well-known/masque/ip/{target}/{ipproto}/",
                        "user": user,
                        "pass": password,
                    },
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": domain,
                        "alpn": alpn,
                    },
                },
            }, {
                "protocol": "freedom",
                "tag": "direct",
                "settings": {
                    # Резолвим домены через внутренний DNS Xray (77.88.8.8 для direct),
                    # а не через системный, который завёрнут в туннель.
                    "domainStrategy": "UseIP",
                },
            }, {
                "protocol": "blackhole",
                "tag": "block",
            }],
        }

        if geosite_path or geoip_path:
            config["geodata"] = {}
            if geosite_path:
                config["geodata"]["geosite"] = geosite_path
            if geoip_path:
                config["geodata"]["geoip"] = geoip_path

        with open(CONFIG_TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ==================== ЗАПУСК XRAY ====================

    def run_xray(self):
        try:
            self.xray_process = subprocess.Popen(
                [self.xray_path, "run", "-c", CONFIG_TEMP_FILE],
                startupinfo=self.get_hidden_startupinfo(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8",
            )
            self.xray_start_time = time.time()
            while self.xray_process and self.xray_process.poll() is None:
                line = self.xray_process.stdout.readline()
                if not line:
                    continue
                s = line.strip()
                self.log_print(s)
                low = s.lower()

                if ("failed to open quic" in low or "quic connection" in low) and not self.h2_fallback_attempted:
                    self.h2_fallback_attempted = True
                    self.log_print("[СИСТЕМА] Сбой QUIC. Переключаюсь на HTTP/2...")
                    self.after(0, self.perform_h2_fallback)
                    continue

                if "level=error" in low or ("error" in low and "failed" in low):
                    self.last_error_ts = time.time()
                    self.after(0, lambda: self.status_label.configure(
                        text="ВНИМАНИЕ: СБОИ В ЛОГАХ", text_color="orange"
                    ))
        except Exception as e:
            self.log_print(f"Ошибка ядра: {e}")

    def perform_h2_fallback(self):
        domain = self.entry_domain.get().strip()
        port = self.entry_port.get().strip()
        user = self.entry_user.get().strip()
        password = self.entry_pass.get().strip()
        if not all([domain, port, user, password]):
            return

        # Ставим watchdog на паузу, чтобы он не вмешался в контролируемый перезапуск
        self._watchdog_paused = True
        try:
            if self.xray_process:
                self.xray_process.terminate()
                try: self.xray_process.wait(timeout=3)
                except Exception: self.xray_process.kill()
                self.xray_process = None

            server_ip = self.server_ip
            if not server_ip:
                try:
                    server_ip = socket.gethostbyname(domain)
                    self.server_ip = server_ip
                except socket.gaierror as e:
                    self.log_print(f"[СИСТЕМА] Fallback DNS: {e}")
                    return

            self.generate_tun_config(domain, port, user, password, server_ip, force_h2=True)
            self.status_label.configure(text="СТАТУС: ПЕРЕКЛЮЧЕНИЕ НА HTTP/2...", text_color="yellow")
            self.xray_thread = threading.Thread(target=self.run_xray, daemon=True)
            self.xray_thread.start()
            self.log_print("[СИСТЕМА] Ядро перезапущено с ALPN h2.")
        finally:
            self.after(1000, lambda: setattr(self, "_watchdog_paused", False))

    def toggle_connection(self):
        if not self.is_connected:
            domain = self.entry_domain.get().strip()
            port = self.entry_port.get().strip()
            user = self.entry_user.get().strip()
            password = self.entry_pass.get().strip()

            if not all([domain, port, user, password]):
                self.status_label.configure(text="ЗАПОЛНИТЕ ВСЕ ПОЛЯ!", text_color="orange")
                return
            if not port.isdigit() or not (1 <= int(port) <= 65535):
                self.status_label.configure(text="ПОРТ: 1-65535", text_color="orange")
                return

            self.log_textbox.delete("1.0", "end")
            self.h2_fallback_attempted = False
            self.last_error_ts = 0.0

            self.status_label.configure(text="РАЗРЕШЕНИЕ ДОМЕНА...", text_color="yellow")
            try:
                server_ip = socket.gethostbyname(domain)
            except socket.gaierror as e:
                self.log_print(f"[СИСТЕМА] DNS-ошибка: {e}")
                self.status_label.configure(text="ОШИБКА DNS", text_color="red")
                return

            self.server_ip = server_ip
            self.log_print(f"[СИСТЕМА] {domain} → {server_ip}")

            self.generate_tun_config(domain, port, user, password, server_ip)
            self.save_settings(domain, port, user, password)

            self.status_label.configure(text="ИНИЦИАЛИЗАЦИЯ...", text_color="yellow")
            self.xray_thread = threading.Thread(target=self.run_xray, daemon=True)
            self.xray_thread.start()

            self.is_connected = True
            self._start_watchdog()

            self.btn_connect.configure(text="ОТКЛЮЧИТЬ VPN", fg_color="#440000", hover_color="#660000")
            self.status_label.configure(text="СТАТУС: ТУННЕЛЬ АКТИВЕН", text_color="green")
        else:
            self.disconnect()

    def disconnect(self):
        if self.xray_process:
            self.xray_process.terminate()
            try: self.xray_process.wait(timeout=3)
            except Exception: self.xray_process.kill()
            self.xray_process = None
        if os.path.exists(CONFIG_TEMP_FILE):
            try: os.remove(CONFIG_TEMP_FILE)
            except Exception: pass
        self.is_connected = False
        self.h2_fallback_attempted = False
        self.server_ip = None
        self.last_error_ts = 0.0
        self.watchdog_restart_count = 0
        self._watchdog_paused = False
        self.xray_start_time = 0.0
        self.btn_connect.configure(text="АКТИВИРОВАТЬ VPN", fg_color=self.accent_color, hover_color=self.hover_color)
        self.status_label.configure(text="СТАТУС: СИСТЕМА ДЕАКТИВИРОВАНА", text_color="gray")

    def on_closing(self):
        self.disconnect()
        self.destroy()


if __name__ == "__main__":
    if not is_admin():
        if relaunch_as_admin():
            sys.exit(0)
        else:
            root = tk.Tk(); root.withdraw()
            messagebox.showerror(
                "Требуются права администратора",
                "OverlordMasque требует прав администратора для создания TUN-адаптера "
                "и настройки маршрутов Windows.\n\nЗапустите приложение и подтвердите UAC.",
            )
            root.destroy()
            sys.exit(1)

    app = OverlordMasqueApp()
    app.mainloop()
