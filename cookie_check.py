import base64
import hashlib
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/Toronto")
except Exception:
    ET = timezone(timedelta(hours=-4))

LOG_FILE = "cookie_check_log.txt"
DEFAULT_URL = "https://members.swtc.ca/booking"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def ask(prompt, default=None):
    text = f"{prompt}" + (f" [{default}]" if default else "") + ": "
    return input(text).strip() or default


def decode_jwt(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return None


def fmt(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M:%S %Z")


def log(msg):
    line = f"[{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch(url, token=None):
    """Returns dict: status, location, body_hash, set_cookie. Does not follow redirects."""
    headers = {
        "accept": "text/html,application/json,*/*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0 Safari/537.36",
    }
    if token:
        headers["cookie"] = f"gameupper_token={token}"
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        resp = OPENER.open(req, timeout=30)
        status, hdrs, body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, e.headers, e.read()
    except Exception as e:
        return {"status": 0, "location": "", "body_hash": "", "set_cookie": [], "error": str(e)}
    return {
        "status": status,
        "location": hdrs.get("Location", "") or "",
        "body_hash": hashlib.md5(body).hexdigest(),
        "set_cookie": hdrs.get_all("Set-Cookie") or [],
    }


def is_logged_out(r):
    if r["status"] in (401, 403):
        return True
    if 300 <= r["status"] < 400 and "login" in r["location"].lower():
        return True
    return False


def describe(r):
    if r["status"] == 0:
        return f"error: {r.get('error')}"
    s = f"status {r['status']}"
    if r["location"]:
        s += f" -> {r['location']}"
    return s


def main():
    print("Cookie checker\n")
    token = ask("gameupper_token")

    data = decode_jwt(token)
    exp = None
    if data:
        exp = data.get("exp")
        print("\nToken claims (what the token SAYS):")
        if data.get("iat"):
            print("  Issued :", fmt(data["iat"]))
        if exp:
            print("  Expires:", fmt(exp))
            left = exp - time.time()
            print(f"  Time left: {left / 86400:.2f} days" if left > 0 else "  Already expired per token")
    else:
        print("Could not decode token as JWT.")

    url = ask("\nProtected page/URL to test", DEFAULT_URL)

    print("\n--- Control test ---")
    no_cookie = fetch(url)
    with_cookie = fetch(url, token)
    print("Without cookie:", describe(no_cookie))
    print("With cookie   :", describe(with_cookie))

    if is_logged_out(no_cookie) and not is_logged_out(with_cookie) and with_cookie["status"] == 200:
        print("\nRESULT: VERIFIED. Server redirects you to login without the cookie and lets you in with it.")
    elif is_logged_out(with_cookie):
        print("\nRESULT: COOKIE REJECTED. The server treats you as logged out.")
    elif no_cookie["status"] == with_cookie["status"] and no_cookie["body_hash"] == with_cookie["body_hash"]:
        print("\nRESULT: INCONCLUSIVE. The page looks the same with and without the cookie,")
        print("so login is probably checked in the browser (JavaScript), not on the server.")
        print("Use a JSON/API GET URL from DevTools > Network that returns your account data instead.")
    else:
        print("\nRESULT: Responses differ but not clearly a login redirect. Check the details above.")

    if with_cookie["set_cookie"] and any("gameupper_token" in c for c in with_cookie["set_cookie"]):
        print("Note: server sent a NEW gameupper_token (sliding expiry?).")

    if ask("\nMonitor how long the cookie keeps working? (y/n)", "n").lower() != "y":
        return
    minutes = float(ask("Check every N minutes", "30"))

    log(f"Started monitoring {url}")
    while True:
        r = fetch(url, token)
        note = ""
        if any("gameupper_token" in c for c in r["set_cookie"]):
            note = "  ** NEW gameupper_token issued **"
        log(describe(r) + note)
        if is_logged_out(r):
            log("Cookie no longer accepted. Session ended.")
            if exp:
                log(f"Token's own exp was {fmt(exp)}")
            break
        if exp and time.time() > exp + 3600:
            log("Still accepted 1 hour past exp; server ignores exp.")
            break
        time.sleep(minutes * 60)

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
