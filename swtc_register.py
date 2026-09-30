import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime, timedelta, timezone

URL = "https://members.swtc.ca/api/v1/memberships/register"
CONFIG_FILE = "swtc_config.json"   # optional, lives next to the script/exe

DEFAULTS = {
    "membership_type_id": "5001",
    "payment_method_id": "5",
    "run_at": "2026-10-01 08:00:00",
    "workers": "2",
    "max_per_minute": "12",
    "interval": "0.5",
    "give_up_seconds": "300",
}

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/Toronto")
except Exception:
    ET = timezone(timedelta(hours=-4))  # EDT fallback (valid for Oct 1)

go = threading.Event()
stop = threading.Event()
print_lock = threading.Lock()
result = {"status": None, "body": None}
counter = {"n": 0}


# ---------- config / prompts ----------
def load_config():
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    path = os.path.join(base, CONFIG_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ask(prompt, default=None, cast=str, required=False, secret=False):
    """Blank input -> default. Re-asks on invalid input or blank required field."""
    shown = None
    if default not in (None, ""):
        shown = (str(default)[:6] + "..." + str(default)[-4:]) if secret and len(str(default)) > 12 else str(default)
    while True:
        value = input(f"{prompt}" + (f" [{shown}]" if shown else "") + ": ").strip()
        if not value:
            if default in (None, ""):
                if required:
                    print("  This one is required.")
                    continue
                return None
            value = str(default)
        try:
            return cast(value)
        except Exception:
            print("  Invalid value, try again.")


def parse_ids(s):
    ids = [int(x) for x in s.split(",") if x.strip()]
    if not ids:
        raise ValueError
    return ids


def parse_time(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)


# ---------- helpers ----------
def now_str():
    return datetime.now(ET).strftime("%H:%M:%S.%f")[:-3]


def say(msg):
    with print_lock:
        print(msg, flush=True)


class Limiter:
    """Shared across workers: max N attempts per rolling minute + server-imposed cooldown."""

    def __init__(self, max_per_min):
        self.max = max_per_min
        self.lock = threading.Lock()
        self.times = deque()
        self.cooldown_until = 0.0

    def set_cooldown(self, seconds):
        with self.lock:
            self.cooldown_until = max(self.cooldown_until, time.time() + seconds)
            self.times.clear()

    def acquire(self):
        while not stop.is_set():
            with self.lock:
                now = time.time()
                if now < self.cooldown_until:
                    wait = self.cooldown_until - now
                else:
                    while self.times and now - self.times[0] >= 60:
                        self.times.popleft()
                    if len(self.times) < self.max:
                        self.times.append(now)
                        return True
                    wait = 60 - (now - self.times[0])
            stop.wait(min(max(wait, 0.05), 1.0))
        return False


def send(token, payload, membership_type_id):
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://members.swtc.ca",
            "referer": f"https://members.swtc.ca/membership/register/{membership_type_id}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0 Safari/537.36",
            "cookie": f"gameupper_token={token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), e.headers.get("Retry-After")
    except Exception as e:
        return 0, str(e), None


def worker(wid, token, payload, membership_type_id, interval, limiter):
    go.wait()
    last_sig = None
    while not stop.is_set():
        if not limiter.acquire():
            return
        status, body, retry_after = send(token, payload, membership_type_id)
        with print_lock:
            counter["n"] += 1
            n = counter["n"]
        sig = (status, re.sub(r"\d+", "#", body[:200]))  # ignore changing numbers
        if sig != last_sig:
            say(f"[{now_str()}] #{n} worker {wid}: status {status} {body[:300]}")
            last_sig = sig

        if 200 <= status < 300:
            with print_lock:
                if result["status"] is None:
                    result["status"], result["body"] = status, body
            stop.set()
            return
        if status == 401:
            say("Token rejected (401). Get a fresh gameupper_token. Stopping.")
            stop.set()
            return
        if status == 409:
            say("409 conflict: probably already registered. Stopping.")
            stop.set()
            return
        if status == 429:
            m = re.search(r"wait (\d+) second", body)
            try:
                secs = float(m.group(1)) if m else float(retry_after)
            except (TypeError, ValueError):
                secs = 60.0
            say(f"[{now_str()}] Rate limited. All workers pausing {secs + 1:.0f}s.")
            limiter.set_cooldown(secs + 1)
            continue

        stop.wait(interval)


def wait_until(target):
    while True:
        remaining = (target - datetime.now(ET)).total_seconds()
        if remaining <= 0:
            return
        if remaining > 60:
            print(f"\rWaiting... {int(remaining // 3600)}h {int(remaining % 3600 // 60)}m left   ", end="", flush=True)
            time.sleep(30)
        elif remaining > 2:
            print(f"\rWaiting... {int(remaining)}s left        ", end="", flush=True)
            time.sleep(1)
        else:
            time.sleep(0.005)


def main():
    cfg = load_config()
    print("SWTC membership register (scheduled)")
    print("Press Enter on any question to accept the value in [brackets].\n")

    token = ask("gameupper_token", cfg.get("token") or os.environ.get("SWTC_TOKEN"), required=True, secret=True)
    membership_type_id = ask("membership_type_id", cfg.get("membership_type_id", DEFAULTS["membership_type_id"]), int)
    payment_method_id = ask("payment_method_id", cfg.get("payment_method_id", DEFAULTS["payment_method_id"]), int)
    registrant_ids = ask("registrant_ids (comma separated)", cfg.get("registrant_ids"), parse_ids, required=True)
    target = ask("Run at (Eastern Time, YYYY-MM-DD HH:MM:SS)", cfg.get("run_at", DEFAULTS["run_at"]), parse_time)
    workers = min(ask("Parallel workers (max 5)", cfg.get("workers", DEFAULTS["workers"]), int), 5)
    max_per_min = min(ask("Max attempts per minute, all workers (server limit is ~20)",
                          cfg.get("max_per_minute", DEFAULTS["max_per_minute"]), int), 18)
    interval = max(ask("Seconds between retries per worker (min 0.2)", cfg.get("interval", DEFAULTS["interval"]), float), 0.2)
    max_seconds = ask("Give up after how many seconds", cfg.get("give_up_seconds", DEFAULTS["give_up_seconds"]), int)

    payload = {
        "membership_type_id": membership_type_id,
        "payment_method_id": payment_method_id,
        "registrant_ids": registrant_ids,
        "agreement_accepted": True,
    }

    limiter = Limiter(max_per_min)
    threads = [
        threading.Thread(target=worker, args=(i + 1, token, payload, membership_type_id, interval, limiter), daemon=True)
        for i in range(workers)
    ]
    for t in threads:
        t.start()

    print(f"\nWill fire at {target.strftime('%Y-%m-%d %H:%M:%S %Z')} with {workers} workers, "
          f"max {max_per_min} attempts/min, giving up after {max_seconds}s.")
    print("Keep this window open and the PC awake. Ctrl+C to abort.\n")

    try:
        wait_until(target)
        say(f"\n[{now_str()}] GO")
        go.set()
        deadline = time.time() + max_seconds
        while not stop.is_set() and time.time() < deadline:
            time.sleep(0.05)
        if not stop.is_set():
            say(f"\nGave up after {max_seconds}s.")
            stop.set()
    except KeyboardInterrupt:
        stop.set()
        say("\nAborted.")

    for t in threads:
        t.join(timeout=20)

    print(f"\nTotal requests sent: {counter['n']}")
    if result["status"]:
        print(f"SUCCESS: status {result['status']}\n{result['body']}")
    else:
        print("No successful registration.")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
