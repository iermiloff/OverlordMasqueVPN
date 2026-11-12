import os
import json
import subprocess
import threading
import sys
import socket
import base64
import ctypes
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import customtkinter as ctk

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


# ==================== ПРОСТАЯ ОБФУСКАЦИЯ ПАРОЛЕЙ ====================

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


# ==================== UAC-ЭЛЕВАЦИЯ ====================

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


# ==================== ОСНОВНОЕ ПРИЛОЖЕНИЕ ====================

class OverlordMasqueApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("OverlordMasque")
        self.geometry("780x520")
        self.resizable(False, False)

        self.accent_color = "#990000"
        self.hover_color = "#cc0000"
        self.bg_frame_color = "#1e1e1e"

        self.xray_process = None
        self.is_connected = False
        self.h2_fallback_attempted = False
        self.server_ip = None

        # ==================== ЛЕВАЯ ПАНЕЛЬ ====================
        self.left_frame = ctk.CTkFrame(self, width=390, corner_radius=15, fg_color=self.bg_frame_color)
        self.left_frame.pack(side="left", fill="y", padx=15, pady=15)

        self.label_title = ctk.CTkLabel(
            self.left_frame, text="OVERLORD MASQUE",
            font=ctk.CTkFont(family="Impact", size=24, weight="bold"),
            text_color=self.accent_color
        )
        self.label_title.pack(pady=15)

        self.profile_var = ctk.StringVar(value="Выбрать профиль...")
        self.profile_menu = ctk.CTkOptionMenu(
            self.left_frame, values=self.load_profile_names(),
            variable=self.profile_var, command=self.on_profile_select,
            width=330, fg_color="#333333",
            button_color=self.accent_color, button_hover_color=self.hover_color
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

        # Привязка буфера обмена и контекстного меню ко всем полям
        for entry in (self.entry_domain, self.entry_port, self.entry_user, self.entry_pass):
            self._bind_clipboard(entry)

        self.button_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.button_frame.pack(pady=(10, 0))

        self.btn_save_profile = ctk.CTkButton(
            self.button_frame, text="💾 Сохранить профиль", command=self.save_profile,
            width=160, height=32, fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=12)
        )
        self.btn_save_profile.pack(side="left", padx=5)

        self.btn_save_logs = ctk.CTkButton(
            self.button_frame, text="📄 Сохранить логи", command=self.save_logs,
            width=160, height=32, fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=12)
        )
        self.btn_save_logs.pack(side="left", padx=5)

        self.btn_connect = ctk.CTkButton(
            self.left_frame, text="АКТИВИРОВАТЬ VPN", command=self.toggle_connection,
            width=220, height=40, fg_color=self.accent_color, hover_color=self.hover_color,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.btn_connect.pack(pady=15)

        self.status_label = ctk.CTkLabel(
            self.left_frame, text="СТАТУС: СИСТЕМА ДЕАКТИВИРОВАНА",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="gray"
        )
        self.status_label.pack(side="bottom", pady=10)

        # ==================== ПРАВАЯ ПАНЕЛЬ (ЛОГИ) ====================
        self.right_frame = ctk.CTkFrame(self, width=350, corner_radius=15, fg_color=self.bg_frame_color)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=15, pady=15)

        self.log_label = ctk.CTkLabel(
            self.right_frame, text="ЛОГИ СЕТЕВОГО ЯДРА:",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#aaaaaa"
        )
        self.log_label.pack(pady=10)

        self.log_textbox = ctk.CTkTextbox(
            self.right_frame, width=330, height=390,
            fg_color="#121212", text_color="#00ff00",
            font=ctk.CTkFont(family="Consolas", size=10)
        )
        self.log_textbox.pack(padx=10, pady=10, fill="both", expand=True)

        # ==================== ПРОВЕРКА РЕСУРСОВ ====================
        self.xray_path = get_resource_path("xray.exe")
        self.wintun_path = get_resource_path("wintun.dll")

        if not os.path.exists(self.xray_path) or not os.path.exists(self.wintun_path):
            self.log_print("КРИТИЧЕСКАЯ ОШИБКА: Компоненты ядра (xray.exe / wintun.dll) не интегрированы!")
            self.btn_connect.configure(state="disabled")

        icon_path = get_resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.load_saved_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ==================== БУФЕР ОБМЕНА + КОНТЕКСТНОЕ МЕНЮ ====================

    def _bind_clipboard(self, entry_widget):
        inner_entry = getattr(entry_widget, "_entry", None) or getattr(entry_widget, "entry", None)
        if inner_entry is None:
            return

        def paste_text(event=None):
            try:
                text = inner_entry.clipboard_get()
                if inner_entry.selection_present():
                    inner_entry.delete("sel.first", "sel.last")
                inner_entry.insert("insert", text)
            except tk.TclError:
                pass
            return "break"

        def copy_text(event=None):
            try:
                if inner_entry.selection_present():
                    inner_entry.clipboard_clear()
                    inner_entry.clipboard_append(inner_entry.selection_get())
            except tk.TclError:
                pass
            return "break"

        def cut_text(event=None):
            copy_text()
            try:
                if inner_entry.selection_present():
                    inner_entry.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            return "break"

        def select_all(event=None):
            inner_entry.select_range(0, "end")
            return "break"

        # Стандартные привязки (работают при английской раскладке)
        inner_entry.bind("<Control-v>", paste_text)
        inner_entry.bind("<Control-c>", copy_text)
        inner_entry.bind("<Control-x>", cut_text)
        inner_entry.bind("<Control-a>", select_all)
        inner_entry.bind("<Shift-Insert>", paste_text)
        inner_entry.bind("<Control-Insert>", copy_text)

        # Дополнительная обработка по keycode для не-английских раскладок
        def on_ctrl_key(event):
            if not (event.state & 0x4):
                return None
            keysym = (event.keysym or "").lower()
            if event.keycode == 86 and keysym != "v":
                return paste_text()
            if event.keycode == 67 and keysym != "c":
                return copy_text()
            if event.keycode == 88 and keysym != "x":
                return cut_text()
            if event.keycode == 65 and keysym != "a":
                return select_all()
            return None

        inner_entry.bind("<Control-KeyPress>", on_ctrl_key)

        # Контекстное меню
        context_menu = tk.Menu(inner_entry, tearoff=0)
        context_menu.add_command(label="Копировать", command=copy_text)
        context_menu.add_command(label="Вставить", command=paste_text)
        context_menu.add_command(label="Вырезать", command=cut_text)
        context_menu.add_separator()
        context_menu.add_command(label="Выделить всё", command=select_all)

        def show_context_menu(event):
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

        inner_entry.bind("<Button-3>", show_context_menu)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ ====================

    def log_print(self, text):
        self.log_textbox.insert("end", text + "\n")
        self.log_textbox.see("end")

    def get_hidden_startupinfo(self):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo

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
            self.status_label.configure(text="ЗАПОЛНИТЕ ВСЕ ПОЛЯ ДЛЯ СОХРАНЕНИЯ!", text_color="orange")
            return

        if not port.isdigit() or not (1 <= int(port) <= 65535):
            self.status_label.configure(text="ПОРТ ДОЛЖЕН БЫТЬ ЧИСЛОМ ОТ 1 ДО 65535", text_color="orange")
            return

        profile_name = simpledialog.askstring("Имя профиля", "Введите название для сохранения:", initialvalue=domain)
        if not profile_name:
            return

        profiles = {}
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                pass

        profiles[profile_name] = {
            "domain": domain,
            "port": port,
            "user": user,
            "password": obfuscate(password)
        }

        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
            self.log_print(f"[СИСТЕМА] Профиль '{profile_name}' сохранён.")
            self.profile_menu.configure(values=list(profiles.keys()))
            self.profile_var.set(profile_name)
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка сохранения профиля: {e}")

    def on_profile_select(self, choice):
        if choice in ("Нет сохранённых профилей", "Ошибка загрузки"):
            return
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                profiles = json.load(f)
            if choice in profiles:
                data = profiles[choice]
                self.entry_domain.delete(0, "end")
                self.entry_domain.insert(0, data.get("domain", ""))
                self.entry_port.delete(0, "end")
                self.entry_port.insert(0, data.get("port", ""))
                self.entry_user.delete(0, "end")
                self.entry_user.insert(0, data.get("user", ""))
                self.entry_pass.delete(0, "end")
                self.entry_pass.insert(0, deobfuscate(data.get("password", "")))
                self.log_print(f"[СИСТЕМА] Загружен профиль: {choice}")
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка загрузки профиля: {e}")

    def save_logs(self):
        log_content = self.log_textbox.get("1.0", "end-1c")
        if not log_content.strip():
            self.log_print("[СИСТЕМА] Логи пусты, сохранять нечего.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
            initialfile="masque_session_log.txt"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(log_content)
                self.log_print(f"[СИСТЕМА] Логи сохранены в: {file_path}")
            except Exception as e:
                self.log_print(f"[СИСТЕМА] Ошибка сохранения логов: {e}")

    # ==================== НАСТРОЙКИ ПОСЛЕДНЕЙ СЕССИИ ====================

    def load_saved_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entry_domain.insert(0, data.get("domain", ""))
                self.entry_port.insert(0, data.get("port", ""))
                self.entry_user.insert(0, data.get("user", ""))
                self.entry_pass.insert(0, deobfuscate(data.get("password", "")))
                self.log_print("[СИСТЕМА] Предыдущая конфигурация успешно импортирована!")
            except Exception as e:
                self.log_print(f"[СИСТЕМА] Не удалось прочесть файл автосохранения: {e}")

    def save_settings(self, domain, port, user, password):
        try:
            data = {
                "domain": domain,
                "port": port,
                "user": user,
                "password": obfuscate(password)
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_print(f"[СИСТЕМА] Ошибка автосохранения настроек: {e}")

    # ==================== КОНФИГУРАЦИЯ XRAY ====================

    def generate_tun_config(self, domain, port, user, password, server_ip, force_h2=False):
        alpn = ["h2"] if force_h2 else ["h3", "h2"]

        config = {
            "log": {"loglevel": "info"},
            "dns": {"servers": ["1.1.1.1", "8.8.8.8"]},
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [{
                    "type": "field",
                    "inboundTag": ["tun-in"],
                    "outboundTag": "proxy"
                }]
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
                    "stack": "gvisor"
                }
            }],
            "outbounds": [{
                "protocol": "masque",
                "settings": {
                    "address": server_ip,
                    "port": int(port),
                    "remoteDNS": ["1.1.1.1", "8.8.8.8"]
                },
                "tag": "proxy",
                "streamSettings": {
                    "method": "masque",
                    "masqueSettings": {
                        "host": domain,
                        "path": "/.well-known/masque/ip/{target}/{ipproto}/",
                        "user": user,
                        "pass": password
                    },
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": domain,
                        "alpn": alpn
                    }
                }
            }, {
                "protocol": "freedom",
                "tag": "direct"
            }]
        }
        with open(CONFIG_TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ==================== ЗАПУСК / ОСТАНОВКА ====================

    def run_xray(self):
        try:
            self.xray_process = subprocess.Popen(
                [self.xray_path, "run", "-c", CONFIG_TEMP_FILE],
                startupinfo=self.get_hidden_startupinfo(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8"
            )

            while self.xray_process and self.xray_process.poll() is None:
                line = self.xray_process.stdout.readline()
                if not line:
                    continue
                stripped = line.strip()
                self.log_print(stripped)

                lower = stripped.lower()

                if ("failed to open quic" in lower or "quic connection" in lower) and not self.h2_fallback_attempted:
                    self.h2_fallback_attempted = True
                    self.log_print("[СИСТЕМА] Обнаружен сбой QUIC. Переключаюсь на HTTP/2 (h2)...")
                    self.after(0, self.perform_h2_fallback)

                elif "level=error" in lower or ("error" in lower and "failed" in lower):
                    self.after(0, lambda: self.status_label.configure(
                        text="СТАТУС: ОШИБКА ЯДРА (см. логи)", text_color="red"
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

        if self.xray_process:
            self.xray_process.terminate()
            try:
                self.xray_process.wait(timeout=3)
            except Exception:
                self.xray_process.kill()
            self.xray_process = None

        # Переиспользуем ранее разрешённый IP; если его нет — резолвим заново
        server_ip = self.server_ip
        if not server_ip:
            try:
                server_ip = socket.gethostbyname(domain)
                self.server_ip = server_ip
            except socket.gaierror as e:
                self.log_print(f"[СИСТЕМА] Fallback: DNS-ошибка: {e}")
                return

        self.generate_tun_config(domain, port, user, password, server_ip, force_h2=True)
        self.status_label.configure(text="СТАТУС: ПЕРЕКЛЮЧЕНИЕ НА HTTP/2...", text_color="yellow")

        self.xray_thread = threading.Thread(target=self.run_xray, daemon=True)
        self.xray_thread.start()

        self.log_print("[СИСТЕМА] Ядро перезапущено с ALPN h2.")

    def toggle_connection(self):
        if not self.is_connected:
            domain = self.entry_domain.get().strip()
            port = self.entry_port.get().strip()
            user = self.entry_user.get().strip()
            password = self.entry_pass.get().strip()

            if not all([domain, port, user, password]):
                self.status_label.configure(text="ЗАПОЛНИТЕ ВСЕ ПОЛЯ ВВОДА!", text_color="orange")
                return

            if not port.isdigit() or not (1 <= int(port) <= 65535):
                self.status_label.configure(text="ПОРТ ДОЛЖЕН БЫТЬ ЧИСЛОМ ОТ 1 ДО 65535", text_color="orange")
                return

            self.log_textbox.delete("1.0", "end")
            self.h2_fallback_attempted = False

            # Резолвим домен ДО запуска Xray — иначе WFP заблокирует системный DNS
            self.status_label.configure(text="РАЗРЕШЕНИЕ ДОМЕНА СЕРВЕРА...", text_color="yellow")
            try:
                server_ip = socket.gethostbyname(domain)
            except socket.gaierror as e:
                self.log_print(f"[СИСТЕМА] Ошибка DNS: не удалось разрешить {domain}: {e}")
                self.status_label.configure(
                    text="ОШИБКА: НЕ УДАЛОСЬ РАЗРЕШИТЬ ДОМЕН СЕРВЕРА",
                    text_color="red"
                )
                return

            self.server_ip = server_ip
            self.log_print(f"[СИСТЕМА] Домен {domain} разрешён в {server_ip}")

            self.generate_tun_config(domain, port, user, password, server_ip, force_h2=False)
            self.save_settings(domain, port, user, password)

            self.status_label.configure(text="ИНИЦИАЛИЗАЦИЯ ЯДРА...", text_color="yellow")

            self.xray_thread = threading.Thread(target=self.run_xray, daemon=True)
            self.xray_thread.start()

            self.is_connected = True
            self.btn_connect.configure(text="ОТКЛЮЧИТЬ VPN", fg_color="#440000", hover_color="#660000")
            self.status_label.configure(text="СТАТУС: ТУННЕЛЬ УСПЕШНО АКТИВИРОВАН", text_color="green")
        else:
            self.disconnect()

    def disconnect(self):
        if self.xray_process:
            self.xray_process.terminate()
            try:
                self.xray_process.wait(timeout=3)
            except Exception:
                self.xray_process.kill()
            self.xray_process = None

        if os.path.exists(CONFIG_TEMP_FILE):
            try:
                os.remove(CONFIG_TEMP_FILE)
            except Exception:
                pass

        self.is_connected = False
        self.h2_fallback_attempted = False
        self.server_ip = None
        self.btn_connect.configure(text="АКТИВИРОВАТЬ VPN", fg_color=self.accent_color, hover_color=self.hover_color)
        self.status_label.configure(text="СТАТУС: СИСТЕМА ДЕАКТИВИРОВАНА", text_color="gray")

    def on_closing(self):
        self.disconnect()
        self.destroy()


# ==================== ТОЧКА ВХОДА С ПРОВЕРКОЙ UAC ====================

if __name__ == "__main__":
    if not is_admin():
        if relaunch_as_admin():
            sys.exit(0)
        else:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Требуются права администратора",
                "OverlordMasque требует прав администратора для создания "
                "TUN-адаптера и настройки маршрутов Windows.\n\n"
                "Пожалуйста, запустите приложение и подтвердите запрос UAC."
            )
            root.destroy()
            sys.exit(1)

    app = OverlordMasqueApp()
    app.mainloop()