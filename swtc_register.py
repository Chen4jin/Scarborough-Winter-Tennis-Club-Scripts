import json
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

URL = "https://members.swtc.ca/api/v1/memberships/register"
DEFAULT_TIME = "2026-10-01 08:00:00"

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/Toronto")
except Exception:
    ET = timezone(timedelta(hours=-4))  # EDT fallback (valid for Oct 1)

go = threading.Event()      # set at the scheduled time
stop = threading.Event()    # set on success / fatal error / timeout
print_lock = threading.Lock()
result = {"status": None, "body": None}
counter = {"n": 0}


def ask(prompt, default=None):
    text = f"{prompt}" + (f" [{default}]" if default else "") + ": "
    return input(text).strip() or default


def now_str():
    return datetime.now(ET).strftime("%H:%M:%S.%f")[:-3]


def say(msg):
    with print_lock:
        print(msg, flush=True)


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


def worker(wid, token, payload, membership_type_id, interval):
    go.wait()
    last_seen = None
    while not stop.is_set():
        status, body, retry_after = send(token, payload, membership_type_id)
        with print_lock:
            counter["n"] += 1
            n = counter["n"]
        sig = (status, body[:200])
        if sig != last_seen:  # only print when the response changes, to avoid flooding
            say(f"[{now_str()}] #{n} worker {wid}: status {status} {body[:300]}")
            last_seen = sig

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

        delay = interval
        if status == 429:  # server asks us to slow down
            try:
                delay = max(float(retry_after), interval)
            except (TypeError, ValueError):
                delay = 2.0
        stop.wait(delay)


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
    print("SWTC membership register (scheduled, parallel retry)\n")
    token = ask("gameupper_token (cookie value from your browser)")
    membership_type_id = int(ask("membership_type_id", "5001"))
    payment_method_id = int(ask("payment_method_id", "5"))
    ids = ask("registrant_ids (comma separated)")
    registrant_ids = [int(x) for x in ids.split(",") if x.strip()]
    when = ask("Run at (Eastern Time, YYYY-MM-DD HH:MM:SS)", DEFAULT_TIME)
    workers = min(int(ask("Parallel workers (max 5)", "3")), 5)
    interval = max(float(ask("Seconds between retries per worker (min 0.2)", "0.5")), 0.2)
    max_seconds = int(ask("Give up after how many seconds", "120"))
    target = datetime.strptime(when, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)

    payload = {
        "membership_type_id": membership_type_id,
        "payment_method_id": payment_method_id,
        "registrant_ids": registrant_ids,
        "agreement_accepted": True,
    }

    threads = [
        threading.Thread(target=worker, args=(i + 1, token, payload, membership_type_id, interval), daemon=True)
        for i in range(workers)
    ]
    for t in threads:
        t.start()

    print(f"\nWill fire at {target.strftime('%Y-%m-%d %H:%M:%S %Z')} with {workers} workers "
          f"(~{workers / interval:.0f} req/s max), giving up after {max_seconds}s.")
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
