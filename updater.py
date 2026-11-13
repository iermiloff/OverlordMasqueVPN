import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


GEODATA_URLS = {
    "geosite.dat": "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geosite.dat",
    "geoip.dat":   "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geoip.dat",
}

GEODATA_DIR_NAME = "geodata"
METADATA_FILE_NAME = "metadata.json"
USER_AGENT = "OverlordMasque/1.1.1"
MIN_FILE_SIZE = 1024


def get_geodata_dir(user_data_dir):
    d = os.path.join(user_data_dir, GEODATA_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _load_metadata(geodata_dir):
    path = os.path.join(geodata_dir, METADATA_FILE_NAME)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_metadata(geodata_dir, metadata):
    path = os.path.join(geodata_dir, METADATA_FILE_NAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception:
        pass


def _remote_info(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {
                "last_modified": resp.headers.get("Last-Modified", ""),
                "etag": resp.headers.get("ETag", ""),
                "size": int(resp.headers.get("Content-Length", "0") or 0),
            }
    except Exception:
        return None


def _download_file(url, dest_path, log_callback=None):

    tmp_path = dest_path + ".tmp"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        if os.path.getsize(tmp_path) < MIN_FILE_SIZE:
            raise ValueError(f"Файл слишком мал: {os.path.getsize(tmp_path)} байт")
        os.replace(tmp_path, dest_path)
        return True
    except Exception as e:
        if log_callback:
            log_callback(f"[UPDATER] Ошибка скачивания {os.path.basename(dest_path)}: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def check_and_update_geodata(user_data_dir, log_callback=None, force=False):

    geodata_dir = get_geodata_dir(user_data_dir)
    metadata = _load_metadata(geodata_dir)
    result = {}

    for filename, url in GEODATA_URLS.items():
        dest = os.path.join(geodata_dir, filename)
        remote = _remote_info(url)

        if remote is None:
            if log_callback:
                log_callback(f"[UPDATER] Не удалось проверить {filename} (нет связи)")
            result[filename] = "failed"
            continue

        local = metadata.get(filename, {})
        need_update = force or not os.path.exists(dest)

        if not need_update and remote.get("last_modified") and local.get("last_modified"):
            if remote["last_modified"] != local["last_modified"]:
                need_update = True

        if not need_update:
            result[filename] = "skipped"
            continue

        if log_callback:
            log_callback(f"[UPDATER] Обновление {filename}...")

        if _download_file(url, dest, log_callback):
            metadata[filename] = {
                "last_modified": remote["last_modified"],
                "etag": remote["etag"],
                "size": remote["size"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            result[filename] = "updated"
            if log_callback:
                log_callback(f"[UPDATER] {filename} обновлён ({remote['size']} байт)")
        else:
            result[filename] = "failed"

    _save_metadata(geodata_dir, metadata)
    return result


def get_effective_geodata_paths(user_data_dir, bundled_dir):

    geodata_dir = get_geodata_dir(user_data_dir)
    paths = {}
    for filename in GEODATA_URLS.keys():
        downloaded = os.path.join(geodata_dir, filename)
        if os.path.exists(downloaded) and os.path.getsize(downloaded) >= MIN_FILE_SIZE:
            paths[filename] = downloaded
        else:
            bundled = os.path.join(bundled_dir, filename)
            if os.path.exists(bundled):
                paths[filename] = bundled
            else:
                paths[filename] = None
    return paths["geosite.dat"], paths["geoip.dat"]