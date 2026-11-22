# Deploy notes — combo index

Honest scope: **there is no live host.** Nothing in this repo has been deployed; no domain
has been bought (that is an explicit open question for the project owner, and O's standing
rule is no bulk domain lookups). These are the notes for whoever does it.

The API is one Python process, stdlib only, reading a few JSON files. It runs on the
cheapest box that has a public IP. A $5–9/month VPS is generous; a free tier with
persistent disk works too.

---

## What has to survive

| path | what | who writes | backup |
|---|---|---|---|
| `data/votes.json` | the only irreplaceable write. Votes cannot be reconstructed. | the API | **yes, every hour** |
| `data/misses.jsonl` | append-only miss log. Losing it loses nothing critical but it is demand signal. | the API | daily |
| `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl` | the corpus, rebuildable from `scrapers/out` + `pipeline/build.py` | the pipeline | git (it is committed) |
| `data/taxonomy.json` | vocabulary | a human (lead) | git |

That asymmetry is the whole deployment risk: **the API is disposable, `votes.json` is not.**
The corpus lives in git and can be rebuilt; a vote tally cannot.

## The layout on the box

```
/srv/combo-index/                # the git checkout
├── api/server.py                # the service (systemd ExecStart)
├── web/                         # static site
├── data/                        # dataset + the two write files (ReadWritePaths)
└── pipeline/                    # rebuild tooling, run by cron/timer, not by the web process
```

One user (`combo`), no shell, owning `/srv/combo-index/data`.

## Install

```bash
# 1. code (no build step, no venv needed — stdlib only, Python >= 3.11)
sudo useradd --system --home /srv/combo-index --shell /usr/sbin/nologin combo
sudo git clone <your-repo> /srv/combo-index
sudo chown -R combo:combo /srv/combo-index

# 2. build the first dataset (as the service user, so file ownership is right)
sudo -u combo python3 /srv/combo-index/pipeline/build.py

# 3. the service
sudo cp /srv/combo-index/api/systemd/solve-run.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now solve-run.service
systemctl status solve-run.service --no-pager
curl -s localhost:8787/api/health | python3 -m json.tool

# 4. TLS front door
sudo apt install -y caddy        # or the upstream Caddy repo
sudo cp /srv/combo-index/api/Caddyfile /etc/caddy/Caddyfile   # then edit <YOUR_HOST>
sudo systemctl reload caddy

# 5. verify from the outside
curl -s https://<YOUR_HOST>/api/health | python3 -m json.tool
curl -sI https://<YOUR_HOST>/api/export.jsonl | grep -i etag
```

## Backups (the part that matters)

`votes.json` is small, append-mostly, and rewritten atomically (tmp + `os.replace`), so a
plain copy is safe to take at any time — it is never observed half-written.

```bash
# /etc/cron.d/combo-index-backup
0 * * * *  combo  cp /srv/combo-index/data/votes.json /srv/backups/votes-$(date +\%Y\%m\%d-\%H).json
5 * * * *  combo  rsync -a --remove-source-files /srv/backups/ remote:combo-index-backups/
```

Restore is `cp` back into place and `systemctl restart solve-run`. Keep the hourly copies
in git (a commit per hour is fine here) if you want the cheapest possible durable backup.

## Rebuilding the dataset

Do **not** rebuild from a web request — a request must never trigger a corpus rebuild. The
API triggers `pipeline.build.build()` only when the wanted threshold is crossed, and it
degrades gracefully if that fails. For everything else, use a timer:

```bash
# /etc/systemd/system/combo-build.service  (Type=oneshot, User=combo, same hardening)
ExecStart=/usr/bin/python3 /srv/combo-index/pipeline/build.py

# /etc/systemd/system/combo-build.timer
[Timer]
OnCalendar=*-*-* 04:17:00     # nightly, off-peak, deterministic minute
Persistent=true
```

Scrapers are a separate, slower job (`python3 scrapers/run_all.py`) that writes
`scrapers/out/*.jsonl`; the build reads them. Keep scrape and build as two timers so a
flaky upstream does not block a publish.

## Monitoring (three things worth alerting on)

1. **`/api/health` returns non-200** → the dataset is missing or empty. The site will render
   its "no data yet" state; that is not an outage of the service but it is of the product.
2. **`stale_days` > 7** → the corpus has stopped being refreshed. Staleness is failure mode #1.
3. **`write_path.recent_errors` non-empty** → the vote/miss writes or the threshold rebuild
   are failing. Votes are still durable (they are on disk) but the wanted list is not folding.

```bash
curl -fsS https://<YOUR_HOST>/api/health | python3 -c \
  'import json,sys; d=json.load(sys.stdin); s=d["stale_days"] or 0; e=d["write_path"]["recent_errors"]; \
   print(f"rows={d[\"dataset\"][\"rows\"]} stale={s}d errors={len(e)}"); sys.exit(1 if s>7 or e else 0)'
```

## Resource notes

- Memory: the API loads `combos.json` into a dict; at 25 rows that is KBs, at 50k rows it
  would be ~100 MB. The unit caps at 512 MB, which leaves years of headroom.
- The rate limiter is **in-process** (20 writes/min/IP). Behind Caddy it reads
  `X-Forwarded-For`. Two app processes behind a load balancer would each allow 20 — for v1's
  traffic that is fine; do not pretend it is a distributed limiter.
- Threading: `ThreadingHTTPServer`, one thread per request, writes serialized by a
  `threading.Lock` + atomic rename. No SQLite, no migrations, no connection pool.

## What is deliberately not here

- No CDN, no container, no Kubernetes. One process, one Caddy, one cron line.
- No account system, no OAuth. A "voter" is whatever stable string the client sends
  (`gh:handle`, `agent:<tool-id>`, or an anonymous per-client hash derived from IP+UA).
  Vote weight is 1. Account identity is a v2 question and the open decision in the blueprint.
- No signing/verification of pointers. The poisoning mitigation in v1 is *display*: the UI
  shows `source_kind` and the pointer's domain, and nothing on the index is executed.
