import os
import sys
import time
import calendar
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from tqdm import tqdm
import requests

from pyicloud import PyiCloudService
from pyicloud.exceptions import PyiCloudFailedLoginException

# ---------------- Configuration ----------------
APPLE_ID_EMAIL = os.environ.get("ICLOUD_USER") or ""
OUTPUT_DIR = os.environ.get("ICLOUD_OUT") or "Downloads/Photos"

START_MONTH = "2026-01"
END_MONTH   = "2026-01"

SLEEP_BETWEEN_DOWNLOADS = 0.3
SKIP_VIDEOS = False
# ------------------------------------------------


def parse_month(month_str):
    return datetime.strptime(month_str, "%Y-%m").replace(tzinfo=timezone.utc)


def month_range(start_month_dt, end_month_dt):
    cur = start_month_dt.replace(day=1)
    end_norm = end_month_dt.replace(day=1)
    while cur <= end_norm:
        yield cur
        cur += relativedelta(months=1)


def month_bounds(month_dt):
    first = month_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day = calendar.monthrange(first.year, first.month)
    last = first.replace(day=last_day, hour=23, minute=59, second=59)
    return first, last


def safe_filename(name):
    return "".join(c for c in name if c not in r'<>:"/\|?*').strip()


def login():
    user = APPLE_ID_EMAIL or input("Apple ID (email): ").strip()
    try:
        api = PyiCloudService(user, input(f"Password for {user}: ").strip())
    except PyiCloudFailedLoginException as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    if api.requires_2fa:
        code = input("Enter 2FA code: ").strip()
        if not api.validate_2fa_code(code):
            print("2FA failed")
            sys.exit(1)

    return api


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def asset_timestamp(asset):
    dt = getattr(asset, "created", None)
    if dt:
        return dt
    return None


def is_in_month(asset, start_dt, end_dt):
    ts = asset_timestamp(asset)
    if not ts:
        return False
    return start_dt <= ts <= end_dt


def file_ext(asset):
    name = (asset.filename or "").lower()
    if "." in name:
        return "." + name.split(".")[-1]
    if getattr(asset, "item_type", "") == "video":
        return ".mov"
    return ".jpg"


def build_filename(asset):
    ts = asset_timestamp(asset)
    base_time = ts.strftime("%Y%m%d_%H%M%S") if ts else "unknown"
    base = f"{base_time}_{asset.filename or asset.id}"
    return safe_filename(base)


def save_stream_to_file(resp, target_path):
    if isinstance(resp, requests.Response):
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
    else:
        with open(target_path, "wb") as f:
            f.write(resp)


def download_asset(asset, out_dir, max_retries=3):
    if SKIP_VIDEOS and getattr(asset, "item_type", "") == "video":
        return None, "skipped_video"

    target_name = build_filename(asset) + file_ext(asset)
    target_path = os.path.join(out_dir, target_name)

    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        return target_path, "skip"

    last_err = None
    attempt = 0

    while attempt < max_retries:
        try:
            resp = asset.download()   # ✅ FIXED (no original=True)
            save_stream_to_file(resp, target_path)
            return target_path, "ok"
        except Exception as e:
            last_err = e
            attempt += 1
            time.sleep(1.5 * attempt)

    return f"{type(last_err).__name__}: {last_err}", "error"


def main():
    start_dt = parse_month(START_MONTH)
    end_dt = parse_month(END_MONTH)

    api = login()
    print("Fetching iCloud photos (first time may be slow)...")
    photos = api.photos.all

    base_out = os.path.abspath(OUTPUT_DIR)
    ensure_dir(base_out)

    for month_dt in month_range(start_dt, end_dt):
        mstart, mend = month_bounds(month_dt)
        month_tag = month_dt.strftime("%Y-%m")
        out_dir = os.path.join(base_out, month_tag)
        ensure_dir(out_dir)

        matched = [a for a in photos if is_in_month(a, mstart, mend)]
        print(f"\n{month_tag}: {len(matched)} item(s)")

        for asset in tqdm(matched, desc=f"Downloading {month_tag}", unit="file"):
            path, status = download_asset(asset, out_dir)
            if status == "ok":
                time.sleep(SLEEP_BETWEEN_DOWNLOADS)
            elif status == "error":
                print("Error:", path)

    print("\nDone ✅ Files saved to:", base_out)


if __name__ == "__main__":
    main()
