# Deploy notes — canirun

Honest scope: **the static frontend runs anywhere (including GitHub Pages), and the live write API is a single stdlib-only Python process.** These are the production deployment notes for running the live API + vote/miss store on a lightweight Linux VPS.

The API uses Python 3.11+ standard library only, reading and writing JSON/JSONL files on disk. A $5/month VPS (or any free-tier instance with persistent storage) is more than enough.

---

## What has to survive

| path | what | who writes | backup |
|---|---|---|---|
| `data/votes.json` | the only irreplaceable write. Votes cannot be reconstructed. | the API | **yes, every hour** |
| `data/misses.jsonl` | append-only miss log. Losing it loses nothing critical, but it is the demand signal. | the API | daily |
| `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl` | the corpus, rebuildable from `scrapers/out` + `pipeline/build.py` | the pipeline | git (committed) |
| `data/taxonomy.json` | canonical vocabulary and aliases | maintainers | git (committed) |

That asymmetry is the whole deployment model: **the API process is disposable, `votes.json` is not.**
The corpus lives in git and can be rebuilt at any time; a vote tally cannot.

## The layout on the box

```text
/srv/combo-index/                # git checkout (matches api/systemd/canirun.service)
├── api/server.py                # the service (systemd ExecStart)
├── web/                         # static site
├── data/                        # dataset + the two write files (ReadWritePaths)
└── pipeline/                    # rebuild tooling, run by cron/timer, not by the web process
```

One dedicated system user (`combo`), no login shell, owning `/srv/combo-index/data`.

## Install

```bash
# 1. code (no build step, no venv needed — stdlib only, Python >= 3.11)
sudo useradd --system --home /srv/combo-index --shell /usr/sbin/nologin combo
sudo git clone https://github.com/BuildTreeFruits/canirun.git /srv/combo-index
sudo chown -R combo:combo /srv/combo-index

# 2. verify/build the dataset (as the service user, so file ownership stays clean)
sudo -u combo python3 /srv/combo-index/pipeline/build.py --check

# 3. install and start the systemd service
sudo cp /srv/combo-index/api/systemd/canirun.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now canirun.service
systemctl status canirun.service --no-pager
curl -s localhost:8787/api/health | python3 -m json.tool

# 4. TLS front door via Caddy
sudo apt install -y caddy
sudo cp /srv/combo-index/api/Caddyfile /etc/caddy/Caddyfile   # edit <YOUR_HOST>
sudo systemctl reload caddy

# 5. verify from the outside
curl -s https://<YOUR_HOST>/api/health | python3 -m json.tool
curl -sI https://<YOUR_HOST>/api/export.jsonl | grep -i etag
```

## Backups (the part that matters)

`votes.json` is small, append-mostly, and rewritten atomically (temp file + `os.replace`), so a
plain file copy is safe to take at any time — it is never observed half-written.

```bash
# /etc/cron.d/canirun-backup
0 * * * *  combo  cp /srv/combo-index/data/votes.json /srv/backups/votes-$(date +\%Y\%m\%d-\%H).json
5 * * * *  combo  rsync -a --remove-source-files /srv/backups/ remote:canirun-backups/
```

Restore is `cp` back into place and `systemctl restart canirun`.

## Rebuilding the dataset

The API schedules a background `pipeline.build.build()` only when a vote/miss threshold is crossed, coalescing concurrent triggers behind a lock. For periodic dataset refreshes, use a systemd timer:

```ini
# /etc/systemd/system/canirun-build.service (Type=oneshot, User=combo)
ExecStart=/usr/bin/python3 /srv/combo-index/pipeline/build.py

# /etc/systemd/system/canirun-build.timer
[Timer]
OnCalendar=*-*-* 04:17:00
Persistent=true
```

Scrapers are a separate job (`python3 scrapers/run_all.py`) that writes `scrapers/out/*.jsonl`; the build reads them. Keep scrape and build on separate timers so a slow upstream never blocks a publish.

## Monitoring (three things worth alerting on)

1. **`/api/health` returns non-200** → the dataset is missing or empty.
2. **`stale_days` > 7** → the corpus has stopped being refreshed.
3. **`write_path.recent_errors` non-empty** → the vote/miss writes or background threshold rebuilds are failing.

```bash
curl -fsS https://<YOUR_HOST>/api/health | python3 -c \
  'import json,sys; d=json.load(sys.stdin); s=d["stale_days"] or 0; e=d["write_path"]["recent_errors"]; \
   print(f"rows={d[\"dataset\"][\"rows\"]} stale={s}d errors={len(e)}"); sys.exit(1 if s>7 or e else 0)'
```

## Resource notes

- **Memory:** the API loads `combos.json` into memory; at ~320 rows that is under 1 MB, and at 50k rows it would be ~100 MB. The systemd unit caps memory at 512 MB.
- **Rate limiting:** in-process token bucket (20 writes/min/IP). Behind Caddy it reads `X-Forwarded-For`.
- **Concurrency:** `ThreadingHTTPServer`, one thread per request, writes serialized by a `threading.Lock` + atomic rename. No external database, no migrations, no connection pool.

## What is deliberately not here

- **No container or orchestrator required:** one Python process, one Caddy reverse proxy, one cron line.
- **No account system or OAuth:** a voter is whatever stable identifier the client sends (`gh:handle`, `agent:<tool-id>`, or an anonymous per-client hash derived from IP + User-Agent). Vote weight is 1.
- **No remote code execution:** pointers are documentation/evidence URLs displayed with their `source_kind` and domain; nothing in the index is executed.
