"""Autopost Reels ke Instagram/Facebook Page via Meta Graph API (jalan di GitHub Actions).
Memposting setiap baris schedule.csv yang waktunya (WIB) sudah lewat dan belum ada di posted.txt.
Token Page dibaca dari secrets: TOKEN_RUNI, TOKEN_THEO, TOKEN_IMANI.
"""
import csv, json, os, sys, time, datetime, urllib.request, urllib.parse, urllib.error

G = "https://graph.facebook.com/v21.0"
WIB = datetime.timezone(datetime.timedelta(hours=7))
DONE = "posted.txt"
MAX_LATE_HOURS = 48  # jangan posting video yang sudah telat lebih dari 2 hari


def log(m):
    print(f"[{datetime.datetime.now(WIB):%Y-%m-%d %H:%M} WIB] {m}", flush=True)


def http(method, url, params=None, data=None, headers=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:400]}")


def upload(url, tok, path):
    with open(path, "rb") as f:
        data = f.read()
    return http("POST", url, data=data, headers={
        "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))})


def account(tok):
    me = http("GET", f"{G}/me", {"fields": "id,name,instagram_business_account", "access_token": tok})
    return me["id"], (me.get("instagram_business_account") or {}).get("id"), me.get("name")


def post_ig(tok, ig, path, cap):
    c = http("POST", f"{G}/{ig}/media", {"media_type": "REELS", "upload_type": "resumable",
             "caption": cap, "share_to_feed": "true", "access_token": tok})
    upload(c["uri"], tok, path)
    for _ in range(60):
        time.sleep(10)
        s = http("GET", f"{G}/{c['id']}", {"fields": "status_code,status", "access_token": tok})
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
    else:
        raise RuntimeError("IG processing timeout")
    return http("POST", f"{G}/{ig}/media_publish", {"creation_id": c["id"], "access_token": tok})["id"]


def post_fb(tok, pid, path, cap):
    s = http("POST", f"{G}/{pid}/video_reels", {"upload_phase": "start", "access_token": tok})
    upload(s["upload_url"], tok, path)
    http("POST", f"{G}/{pid}/video_reels", {"upload_phase": "finish", "video_id": s["video_id"],
         "video_state": "PUBLISHED", "description": cap, "access_token": tok})
    return s["video_id"]


def check():
    ok = True
    for ch in ("RUNI", "THEO", "IMANI"):
        tok = os.environ.get(f"TOKEN_{ch}", "").strip()
        try:
            pid, ig, name = account(tok)
            d = http("GET", f"{G}/debug_token", {"input_token": tok, "access_token": tok})["data"]
            exp = d.get("expires_at", 0)
            log(f"{ch}: Page '{name}' | IG id {ig or 'TIDAK ADA'} | kedaluwarsa: {'tidak pernah' if not exp else datetime.datetime.fromtimestamp(exp, WIB)}")
            ok = ok and bool(ig)
        except Exception as e:
            ok = False
            log(f"{ch}: GAGAL {e}")
    sys.exit(0 if ok else 1)


def main():
    if os.environ.get("MODE") == "check":
        return check()
    dry = "--test" in sys.argv
    now = datetime.datetime.now(WIB)
    done = set(open(DONE).read().split()) if os.path.exists(DONE) else set()
    accs, failed = {}, False
    for r in csv.DictReader(open("schedule.csv", encoding="utf-8")):
        when = datetime.datetime.strptime(f"{r['date']} {r['time_wib']}", "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
        if when > now:
            continue
        for t in r["targets"].split("+"):
            key = f"{r['video']}:{t}"
            if key in done:
                continue
            if now - when > datetime.timedelta(hours=MAX_LATE_HOURS):
                log(f"LEWATI {key} (sudah telat > {MAX_LATE_HOURS} jam)")
                continue
            if dry:
                log(f"[TEST] akan posting {key}")
                continue
            ch = r["character"]
            tok = os.environ.get(f"TOKEN_{ch.upper()}", "").strip()
            if not tok:
                log(f"!! secret TOKEN_{ch.upper()} belum diisi")
                failed = True
                continue
            try:
                if ch not in accs:
                    accs[ch] = account(tok)
                pid, ig, name = accs[ch]
                path = os.path.join("videos", r["video"] + ".mp4")
                if t == "instagram":
                    if not ig:
                        raise RuntimeError(f"Instagram belum terhubung ke Page {name}")
                    rid = post_ig(tok, ig, path, r["caption"])
                else:
                    rid = post_fb(tok, pid, path, r["caption"])
                with open(DONE, "a") as f:
                    f.write(key + "\n")
                done.add(key)
                log(f"OK {key} -> {rid}")
            except Exception as e:
                failed = True
                log(f"GAGAL {key}: {e}")
    if failed:
        sys.exit(1)  # supaya GitHub mengirim email notifikasi gagal


if __name__ == "__main__":
    main()
