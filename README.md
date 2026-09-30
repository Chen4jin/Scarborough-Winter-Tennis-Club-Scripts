# Scarborough Winter Tennis Club Scripts

Small helper scripts for the SWTC members site (`members.swtc.ca`).

| Script | What it does |
| --- | --- |
| `swtc_register.py` | Waits until a scheduled time, then sends the membership registration request (parallel workers, bounded retries) until it succeeds. |
| `cookie_check.py` | Checks that your login cookie works and (optionally) monitors how long it stays valid. |

Both scripts use only Python's standard library, so there is nothing to `pip install`.

> **Security:** your `gameupper_token` is a login session. Anyone who has it can act as you on the site.
> Never commit it, paste it in a public place, or share a command/exe that contains it.
> The scripts ask for the token when you run them and never store it.

---

## 1. Requirements

- Windows PC (also works on Mac/Linux with Python)
- [Python 3.9+](https://www.python.org/downloads/) (tick **Add python.exe to PATH** when installing)
- A member account on `members.swtc.ca`

Check Python works:

```
python --version
```

## 2. Get the code

```
cd %USERPROFILE%\Downloads
git clone https://github.com/Chen4jin/Scarborough-Winter-Tennis-Club-Scripts.git
cd Scarborough-Winter-Tennis-Club-Scripts
```

(Or click **Code → Download ZIP** on GitHub and unzip it.)

## 3. Get your token and IDs

1. Log in at <https://members.swtc.ca/> in Chrome.
2. Press **F12** → **Application** tab → **Cookies** → `https://members.swtc.ca`.
3. Copy the **Value** of `gameupper_token`.
4. Get the IDs by going through the registration page once with **F12 → Network** open. Click the `register` request and look at **Payload**:
   - `membership_type_id` (example: `5001`, also the number at the end of the register page URL)
   - `payment_method_id` (example: `5`)
   - `registrant_ids` (your member ID(s), comma separated if more than one)

Get a **fresh token shortly before you run the script**, and don't log out afterwards (logging out invalidates it).

## 4. Check your cookie works (recommended)

```
python cookie_check.py
```

- Paste your token and press Enter to accept the default test page (`https://members.swtc.ca/booking`).
- It compares a request **without** and **with** your cookie:
  - `VERIFIED` - the cookie logs you in.
  - `COOKIE REJECTED` - get a fresh token.
  - `INCONCLUSIVE` - the page looks the same either way; use a JSON GET URL from DevTools instead.
- Answer `y` at the end to monitor how long the cookie keeps working. Results are logged to `cookie_check_log.txt`.

## 5. Run the scheduled registration

```
python swtc_register.py
```

You will be asked for:

| Prompt | Default | Notes |
| --- | --- | --- |
| `gameupper_token` | - | Your cookie value |
| `membership_type_id` | `5001` | |
| `payment_method_id` | `5` | |
| `registrant_ids` | - | Comma separated |
| Run at (Eastern Time) | `2026-10-01 08:00:00` | Format `YYYY-MM-DD HH:MM:SS` |
| Parallel workers | `3` | Max 5 |
| Seconds between retries per worker | `0.5` | Min 0.2 |
| Give up after (seconds) | `120` | |

Then leave the window open. At the scheduled time all workers fire together and keep retrying until:

- a request succeeds (2xx), or
- the server returns `401` (bad/expired token) or `409` (probably already registered), or
- the give-up time is reached, or
- you press **Ctrl+C**.

If the server replies `429`, the script slows down and honors `Retry-After`.

### Tips for the day

- Keep the PC **plugged in and awake** (turn off sleep) and the window open.
- Sync your clock: **Settings → Time & language → Sync now**.
- Use a fresh token from the day before, and stay logged in.
- Do a dry run a few minutes ahead of time to see the countdown and the responses.

## 6. Build a standalone .exe (optional)

Run this on Windows:

```
pip install pyinstaller
pyinstaller --onefile --name swtc_register swtc_register.py
pyinstaller --onefile --name cookie_check cookie_check.py
```

The executables appear in the `dist` folder. Rebuild after every code change.
Windows SmartScreen may warn about an unsigned exe: click **More info → Run anyway**.
Do not commit `dist/`, `build/`, or `*.spec` files (see `.gitignore`).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `python` is not recognized | Reinstall Python with **Add to PATH** ticked, or use `py` instead of `python`. |
| `401` | Token expired or you logged out. Copy a new `gameupper_token`. |
| `409` | Likely already registered. Check your account on the site. |
| `429` | Rate limited. Increase the retry interval or lower the worker count. |
| Nothing succeeds before give-up time | Read the last responses printed; they show what the server said. |

## Please be considerate

These scripts are for registering your own membership. Keep the request rate low, don't share your token, and don't touch other members' data.
