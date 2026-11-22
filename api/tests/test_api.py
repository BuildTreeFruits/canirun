#!/usr/bin/env python3
"""api/tests/test_api.py -- the API's acceptance tests. Plain python, no pytest, no deps.

    python3 api/tests/test_api.py             # full suite
    RUN_SLOW=1 python3 api/tests/test_api.py  # also exercise the vote rate limiter

Runs the real ThreadingHTTPServer on an ephemeral port against a throw-away copy of
api/tests/fixtures/ -- the point is to test the HTTP surface an agent actually sees,
not a mock of it. Nothing here writes to the project's data/ directory.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(API_DIR)
for _p in (API_DIR, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server as server_mod  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
if not os.path.isdir(FIXTURES):  # self-heal on a fresh checkout
    import make_fixtures  # noqa: E402
    make_fixtures.main()

# CONTRACT §4, frozen. A contract drift fails a test rather than silently shipping.
RESPONSE_KEYS = {"query", "rows", "context", "miss", "query_id", "generated_at", "dataset"}
QUERY_KEYS = {"hw", "model", "runtime", "status", "kind", "q", "limit"}
MISS_KEYS = {"is_miss", "reason", "partial", "hint", "known_wanted", "wanted_votes",
             "last_checked", "counts"}
MISS_REASONS = {"no-claim", "wanted-only", "rejected-only", "partial-context", "no-match"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class APITestCase(unittest.TestCase):
    """Each test gets a private data dir + static dir and its own server."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="solve-run-api-test-")
        self.data = os.path.join(self.tmp, "data")
        shutil.copytree(FIXTURES, self.data)
        self.static = os.path.join(self.tmp, "web")
        os.makedirs(self.static)
        with open(os.path.join(self.static, "index.html"), "w") as fh:
            fh.write("<!doctype html><title>fixture site</title>")
        with open(os.path.join(self.tmp, "secret.txt"), "w") as fh:
            fh.write("TOP-SECRET")

        self.port = free_port()
        self.srv = server_mod.make_server("127.0.0.1", self.port, data_dir=self.data,
                                          static_dir=self.static, quiet=True)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"
        self._wait_ready()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait_ready(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.request("/api/health")
                return
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.05)
        self.fail("server did not start")

    # -- http helpers ------------------------------------------------------

    def request(self, path, method="GET", body=None, headers=None):
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read()

    def get(self, path, **kw):
        return self.request(path, **kw)

    def getjson(self, path):
        status, _headers, raw = self.get(path)
        self.assertEqual(status, 200, f"{path} -> {status}: {raw[:400]!r}")
        return json.loads(raw)

    def postjson(self, path, body):
        status, _headers, raw = self.request(path, "POST", body)
        return status, (json.loads(raw) if raw else None)

    def deletejson(self, path, body):
        status, _headers, raw = self.request(path, "DELETE", body)
        return status, (json.loads(raw) if raw else None)

    def count_misses(self) -> int:
        path = os.path.join(self.data, "misses.jsonl")
        if not os.path.exists(path):
            return 0
        with open(path) as fh:
            return sum(1 for line in fh if line.strip())


# ==========================================================================
# CONTRACT §4 — response shape and the miss object
# ==========================================================================

class TestLookupShape(APITestCase):
    def test_hit_has_every_contract_key(self):
        body = self.getjson("/api/lookup?hw=sm_86&model=qwen3")
        self.assertEqual(set(body) - {"error"}, RESPONSE_KEYS,
                         f"key drift: extra={set(body) - RESPONSE_KEYS} missing={RESPONSE_KEYS - set(body)}")
        self.assertEqual(set(body["query"]), QUERY_KEYS)
        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(body["rows"][0]["id"], "nvidia/sm_86/qwen3/llama_cpp")
        self.assertEqual(body["miss"], {"is_miss": False})
        self.assertRegex(body["query_id"], r"^[0-9a-f]{8}$")
        self.assertEqual(set(body["dataset"]), {"rows", "as_of", "version"})
        self.assertRegex(body["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_miss_has_every_miss_key_and_valid_reason(self):
        miss = self.getjson("/api/lookup?hw=sm_86&model=gemma-4")["miss"]
        self.assertTrue(miss["is_miss"])
        self.assertEqual(set(miss), MISS_KEYS,
                         f"miss key drift: extra={set(miss) - MISS_KEYS} missing={MISS_KEYS - set(miss)}")
        self.assertIn(miss["reason"], MISS_REASONS)
        self.assertIsInstance(miss["partial"], bool)
        self.assertIsInstance(miss["known_wanted"], bool)
        self.assertIsInstance(miss["wanted_votes"], int)
        self.assertIsInstance(miss["hint"], str)
        self.assertTrue(miss["hint"])
        self.assertEqual(set(miss["counts"]), {"exact", "context"})
        self.assertIsInstance(miss["counts"]["exact"], int)
        self.assertIsInstance(miss["counts"]["context"], int)
        self.assertTrue(miss["last_checked"] is None or isinstance(miss["last_checked"], str))

    def test_miss_is_miss_iff_rows_empty(self):
        for path in ("/api/lookup?hw=sm_86&model=qwen3", "/api/lookup?hw=zzz-9",
                     "/api/lookup?model=qwen3", "/api/lookup",
                     "/api/lookup?hw=sm_120&model=deepseek-v4"):
            body = self.getjson(path)
            self.assertEqual(body["miss"]["is_miss"], len(body["rows"]) == 0, path)

    def test_star_rows_are_context_never_an_answer(self):
        """CONTRACT §3: model_family '*' is hardware context, never an answer to a model query."""
        body = self.getjson("/api/lookup?hw=sm_86&model=brand-new-model")
        self.assertEqual(body["rows"], [])
        self.assertTrue(body["miss"]["is_miss"])
        self.assertTrue(body["miss"]["partial"])
        self.assertEqual(body["miss"]["reason"], "partial-context")
        self.assertEqual(body["miss"]["counts"]["exact"], 0)
        self.assertGreaterEqual(len(body["context"]), 1)
        for row in body["context"]:
            self.assertEqual(row["model_family"], "*")

    def test_free_text_that_matches_nothing_is_no_match(self):
        """Regression: a q matching nothing must be no-match/0 votes, never wanted-only.
        (A vote-only row once leaked into every text query, making the index claim
        demand for text that matched no row at all.)"""
        miss = self.getjson("/api/lookup?q=nonexistentword")["miss"]
        self.assertTrue(miss["is_miss"])
        self.assertEqual(miss["reason"], "no-match")
        self.assertEqual(miss["wanted_votes"], 0)
        self.assertFalse(miss["known_wanted"])
        self.assertEqual(miss["counts"], {"exact": 0, "context": 0})

    def test_free_text_hit_still_works(self):
        body = self.getjson("/api/lookup?q=gfx1100")
        self.assertFalse(body["miss"]["is_miss"])
        self.assertGreaterEqual(len(body["rows"]), 1)

    def test_vote_only_row_does_not_leak_into_unrelated_text_queries(self):
        self.postjson("/api/want/nvidia/sm_120/qwen3/llama_cpp", {"voter": "t:leak"})
        miss = self.getjson("/api/lookup?q=nonexistentword")["miss"]
        self.assertEqual(miss["reason"], "no-match", miss)
        self.assertEqual(miss["wanted_votes"], 0, miss)
        # the vote is not lost -- it is discoverable where it belongs
        self.assertIn("nvidia/sm_120/qwen3/llama_cpp",
                      [r["id"] for r in self.getjson("/api/wanted")["rows"]])

    def test_no_match_when_nothing_at_all(self):
        miss = self.getjson("/api/lookup?hw=sm_126&model=qwen3")["miss"]
        self.assertEqual(miss["reason"], "no-match")
        self.assertFalse(miss["partial"])
        self.assertEqual(miss["counts"], {"exact": 0, "context": 0})

    def test_wanted_only_reason(self):
        # the fixture wanted row matches sm_120 x deepseek-v4; filtering to solved
        # leaves nothing but the wanted row, which must be named as the reason
        body = self.getjson("/api/lookup?hw=sm_120&model=deepseek-v4&status=solved")
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["miss"]["reason"], "wanted-only")
        self.assertTrue(body["miss"]["known_wanted"])
        self.assertGreaterEqual(body["miss"]["wanted_votes"], 1)

    def test_rejected_only_reason(self):
        body = self.getjson("/api/lookup?hw=sm_75&model=gemma-4&status=solved")
        self.assertEqual(body["rows"], [])
        self.assertEqual(body["miss"]["reason"], "rejected-only")

    def test_query_id_stable_across_requests_and_differs_by_query(self):
        a = self.getjson("/api/lookup?hw=sm_86&model=qwen3")["query_id"]
        b = self.getjson("/api/lookup?hw=sm_86&model=qwen3")["query_id"]
        c = self.getjson("/api/lookup?hw=sm_89&model=qwen3")["query_id"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_unknown_params_ignored_and_limit_clamped(self):
        body = self.getjson("/api/lookup?hw=sm_86&named=1&limit=9999&whatever=x")
        self.assertEqual(body["query"]["limit"], 500)
        self.assertEqual(body["query"]["hw"], "sm_86")
        self.assertEqual(set(body["query"]), QUERY_KEYS)

    def test_query_echo_normalised_when_empty(self):
        query = self.getjson("/api/lookup")["query"]
        self.assertEqual(set(query), QUERY_KEYS)
        self.assertEqual(query["limit"], 50)
        for key in ("hw", "model", "runtime", "status", "kind", "q"):
            self.assertIsNone(query[key], key)


class TestLookupMatching(APITestCase):
    def test_hw_matches_arch_then_vendor_then_prefix(self):
        self.assertGreaterEqual(len(self.getjson("/api/lookup?hw=sm_86")["rows"]), 2)
        self.assertGreaterEqual(len(self.getjson("/api/lookup?hw=nvidia")["rows"]), 2)
        self.assertGreaterEqual(len(self.getjson("/api/lookup?hw=sm_")["rows"]), 2)

    def test_runtime_matches_slug(self):
        rows = self.getjson("/api/lookup?hw=gfx1100&runtime=vllm")["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["runtime"], "vllm")

    def test_q_free_text(self):
        self.assertGreaterEqual(len(self.getjson("/api/lookup?q=gfx1100")["rows"]), 1)


# ==========================================================================
# votes
# ==========================================================================

class TestVotes(APITestCase):
    RID = "nvidia/sm_86/qwen3/llama_cpp"

    def test_same_voter_twice_is_one_vote(self):
        st1, r1 = self.postjson(f"/api/want/{self.RID}", {"voter": "gh:alice"})
        st2, r2 = self.postjson(f"/api/want/{self.RID}", {"voter": "gh:alice"})
        self.assertEqual((st1, st2), (201, 201))
        self.assertEqual(r1["want_votes"], 1)
        self.assertEqual(r2["want_votes"], 1, "idempotency violated: double vote counted twice")
        for r in (r1, r2):
            self.assertTrue({"id", "want_votes", "want_first", "voted"} <= set(r))
            self.assertEqual(r["id"], self.RID)
            self.assertTrue(r["voted"])
        self.assertRegex(r1["want_first"], r"^\d{4}-\d{2}-\d{2}$")

    def test_distinct_voters_accumulate(self):
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        _, r2 = self.postjson(f"/api/want/{self.RID}", {"voter": "gh:b"})
        self.assertEqual(r2["want_votes"], 2)

    def test_retract(self):
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        st, r = self.deletejson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        self.assertEqual(st, 200)
        self.assertEqual(r["want_votes"], 0)
        self.assertFalse(r["voted"])
        _, r2 = self.deletejson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        self.assertEqual(r2["want_votes"], 0, "retracting twice must stay at 0")

    def test_retract_leaves_other_voters_alone(self):
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:b"})
        _, r = self.deletejson(f"/api/want/{self.RID}", {"voter": "gh:a"})
        self.assertEqual(r["want_votes"], 1)
        self.assertFalse(r["voted"])

    def test_votes_persist_atomically_with_no_temp_files(self):
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:persist"})
        path = os.path.join(self.data, "votes.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            blob = json.load(fh)
        self.assertEqual(blob[self.RID]["count"], 1)
        leftovers = [n for n in os.listdir(self.data) if ".tmp." in n]
        self.assertEqual(leftovers, [], f"atomic write left temp files: {leftovers}")

    def test_vote_visible_in_lookup_without_a_pipeline_rebuild(self):
        self.postjson(f"/api/want/{self.RID}", {"voter": "gh:instant"})
        self.assertEqual(self.getjson("/api/lookup?hw=sm_86&model=qwen3")["rows"][0]["want_votes"], 1)

    def test_vote_for_unexported_id_still_works(self):
        rid = "nvidia/sm_120/qwen3/llama_cpp"
        st, r = self.postjson(f"/api/want/{rid}", {"voter": "gh:future"})
        self.assertIn(st, (200, 201))
        self.assertEqual(r["want_votes"], 1)
        self.assertFalse(r["row_known"])
        self.assertIn(rid, [x["id"] for x in self.getjson("/api/wanted")["rows"]])

    def test_runtime_matches_both_dotted_and_underscored_forms(self):
        """Ids cannot contain dots (CONTRACT §2), so a materialised row carries the id
        segment `llama_cpp` while clients ask for the taxonomy slug `llama.cpp`."""
        for spelling in ("llama.cpp", "llama_cpp", "LLAMA.CPP", "llama-cpp"):
            body = self.getjson(f"/api/lookup?hw=sm_86&model=qwen3&runtime={spelling}")
            self.assertEqual(len(body["rows"]), 1, f"runtime={spelling} should match")
            self.assertEqual(body["rows"][0]["id"], "nvidia/sm_86/qwen3/llama_cpp")

    def test_runtime_alias_map_is_exposed(self):
        doc = self.getjson("/api/taxonomy")
        self.assertIn("runtime_id_aliases", doc)
        self.assertEqual(doc["runtime_id_aliases"].get("llama_cpp"), "llama.cpp")

    def test_dotted_runtime_is_mapped_not_rejected(self):
        """A dotted runtime segment is a spelling difference, not an error: it maps to
        the taxonomy slug and stores the canonical dot-free id."""
        st, r = self.postjson("/api/want/nvidia/sm_86/qwen3/llama.cpp", {"voter": "gh:x"})
        self.assertEqual(st, 201)
        self.assertEqual(r["id"], "nvidia/sm_86/qwen3/llama_cpp")
        self.assertEqual(r["runtime"], "llama.cpp")
        self.assertEqual(r["id_requested"], "nvidia/sm_86/qwen3/llama.cpp")

    def test_non_canonical_case_is_rejected_with_a_suggestion(self):
        st, r = self.postjson("/api/want/NVIDIA/sm_86/qwen3/vllm", {"voter": "gh:x"})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"]["code"], "bad-id")
        self.assertEqual(r["error"]["did_you_mean"], "nvidia/sm_86/qwen3/vllm")

    def test_uppercase_and_short_ids_rejected(self):
        for bad in ("not-an-id", "nvidia/sm_86/qwen3/",
                    "nvidia/sm_86/qwen3/llama_cpp/extra"):
            st, r = self.postjson(f"/api/want/{bad}", {"voter": "gh:x"})
            self.assertEqual(st, 400, bad)
            self.assertEqual(r["error"]["code"], "bad-id", bad)

    def test_vote_runtime_segment_resolves_to_taxonomy_slug(self):
        """A dot-free id segment must map back to the taxonomy slug on the write path."""
        dotted, underscored = "/api/want/nvidia/sm_86/qwen3/llama.cpp", "/api/want/nvidia/sm_86/qwen3/llama_cpp"
        _st, r1 = self.postjson(dotted, {"voter": "t:a"})
        self.assertEqual(r1["runtime"], "llama.cpp")
        self.assertEqual(r1["id"], "nvidia/sm_86/qwen3/llama_cpp")
        # both spellings are the same vote target, so the count does not double
        _st, r2 = self.postjson(underscored, {"voter": "t:a"})
        self.assertEqual(r2["want_votes"], 1)
        self.assertEqual(r2["id"], "nvidia/sm_86/qwen3/llama_cpp")
        with open(os.path.join(self.data, "votes.json")) as fh:
            self.assertEqual(list(json.load(fh)), ["nvidia/sm_86/qwen3/llama_cpp"])

    def test_unknown_runtime_rejected_with_the_list(self):
        st, r = self.postjson("/api/want/nvidia/sm_86/qwen3/bogus-rt", {"voter": "t:a"})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"]["code"], "unknown-runtime")
        self.assertIn("llama.cpp", r["error"]["known_runtimes"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "votes.json")) and
                         json.load(open(os.path.join(self.data, "votes.json"))))

    def test_wanted_sorted_votes_desc_then_want_first_asc(self):
        rows = self.getjson("/api/wanted")["rows"]
        keys = [(-int(r["want_votes"]), str(r.get("want_first") or "\uffff")) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_bad_voter_rejected_cleanly(self):
        st, r = self.postjson(f"/api/want/{self.RID}", {"voter": "x" * 200})
        self.assertEqual(st, 400)
        self.assertIn("error", r)

    def test_bad_id_rejected_not_500(self):
        st, r = self.postjson("/api/want/not-an-id", {"voter": "gh:x"})
        self.assertEqual(st, 400)
        self.assertIn("error", r)


# ==========================================================================
# miss log
# ==========================================================================

class TestMiss(APITestCase):
    QUERY = {"hw": "sm_86", "model": "brand-new-model"}

    def test_distinct_searcher_counting(self):
        seen = []
        for key in ("agent:t-1", "agent:t-1", "agent:t-2", "agent:t-3"):
            st, r = self.postjson("/api/miss", {"query": self.QUERY, "searcher_key": key})
            self.assertEqual(st, 200)
            self.assertTrue(r["logged"])
            self.assertEqual(r["creates_wanted_at"], 3)
            seen.append(r["distinct_searchers"])
        self.assertEqual(seen, [1, 1, 2, 3],
                         f"a repeated searcher must not count twice: {seen}")

    def test_miss_record_has_every_field(self):
        self.postjson("/api/miss", {"query": self.QUERY, "searcher_key": "agent:t-1"})
        with open(os.path.join(self.data, "misses.jsonl")) as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]), {"ts", "query", "query_id", "searcher_key", "user_agent"})
        self.assertEqual(records[0]["searcher_key"], "agent:t-1")
        self.assertEqual(records[0]["query"]["model"], "brand-new-model")

    def test_get_lookup_is_side_effect_free_by_default(self):
        before = self.count_misses()
        for _ in range(3):
            self.getjson("/api/lookup?hw=sm_86&model=brand-new-model")
        self.assertEqual(self.count_misses(), before, "a plain GET logged a miss; agents poll GET")

    def test_get_lookup_log_1_logs_the_miss(self):
        before = self.count_misses()
        body = self.getjson("/api/lookup?hw=sm_86&model=brand-new-model&log=1")
        self.assertTrue(body["miss"]["is_miss"])
        self.assertTrue(body["miss_logged"]["logged"])
        self.assertEqual(self.count_misses(), before + 1)

    def test_get_lookup_log_1_on_a_hit_logs_nothing(self):
        before = self.count_misses()
        body = self.getjson("/api/lookup?hw=sm_86&model=qwen3&log=1")
        self.assertFalse(body["miss"]["is_miss"])
        self.assertEqual(self.count_misses(), before)

    def test_bad_body_rejected(self):
        st, r = self.postjson("/api/miss", {"searcher_key": "x"})
        self.assertEqual(st, 400)
        self.assertIn("error", r)
        st2, _ = self.postjson("/api/miss", {"query": {"nonsense": "1"}})
        self.assertEqual(st2, 400)

    def test_three_distinct_searchers_create_a_wanted_row(self):
        """The loop the whole write path exists for (blueprint §Write path)."""
        # gfx1200 has no '*' row in the fixture, so this is a true miss, not partial-context
        query = {"hw": "gfx1200", "model": "brand-new-model"}
        for i in range(1, 4):
            st, r = self.postjson("/api/miss",
                                  {"query": query, "searcher_key": f"agent:tool-{i}"})
            self.assertEqual(st, 200)
        self.assertEqual(r["distinct_searchers"], 3)
        self.assertTrue(r["would_create_wanted"])
        wanted = [x["id"] for x in self.getjson("/api/wanted")["rows"]]
        self.assertIn("amd/gfx1200/brand-new-model/unknown", wanted)
        # and the lookup that used to miss now answers
        body = self.getjson("/api/lookup?hw=gfx1200&model=brand-new-model")
        self.assertFalse(body["miss"]["is_miss"])
        self.assertEqual(body["rows"][0]["status"], "wanted")


# ==========================================================================
# export, ETag, 304
# ==========================================================================

class TestExportETag(APITestCase):
    def test_export_jsonl_has_etag_and_cache_control(self):
        st, hd, body = self.get("/api/export.jsonl")
        self.assertEqual(st, 200)
        self.assertIn("etag", hd)
        self.assertIn("cache-control", hd)
        lines = [ln for ln in body.decode().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 8)
        for line in lines:
            json.loads(line)

    def test_304_on_if_none_match(self):
        _, hd, _ = self.get("/api/export.jsonl")
        etag = hd["etag"]
        st, hd2, body = self.get("/api/export.jsonl", headers={"If-None-Match": etag})
        self.assertEqual(st, 304)
        self.assertEqual(body, b"", "a 304 must carry no body")
        self.assertEqual(hd2["etag"], etag)

    def test_etag_moves_when_data_changes(self):
        _, hd1, _ = self.get("/api/export.jsonl")
        with open(os.path.join(self.data, "export.jsonl"), "a") as fh:
            fh.write(json.dumps({"id": "nvidia/sm_86/zzz/llama.cpp"}) + "\n")
        _, hd2, _ = self.get("/api/export.jsonl")
        self.assertNotEqual(hd2["etag"], hd1["etag"])

    def test_combos_json_etag_and_304(self):
        st, hd, body = self.get("/api/combos.json")
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(body)["rows"]), 8)
        st2, _, body2 = self.get("/api/combos.json", headers={"If-None-Match": hd["etag"]})
        self.assertEqual(st2, 304)
        self.assertEqual(body2, b"")


# ==========================================================================
# static serving + traversal
# ==========================================================================

class TestStaticSafety(APITestCase):
    def test_index_served(self):
        st, hd, body = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", hd["content-type"])
        self.assertIn(b"fixture site", body)

    def test_content_type_by_extension(self):
        with open(os.path.join(self.static, "app.js"), "w") as fh:
            fh.write("export const x = 1;")
        st, hd, _ = self.get("/app.js")
        self.assertEqual(st, 200)
        self.assertIn("javascript", hd["content-type"].lower())

    def test_traversal_blocked(self):
        for path in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt",
                     "/subdir/../../secret.txt", "/....//secret.txt"):
            st, _hd, body = self.get(path)
            self.assertNotIn(b"TOP-SECRET", body, f"SECRET LEAKED via {path}")

    def test_unknown_asset_is_json_404(self):
        st, hd, body = self.get("/nope/missing.png")
        self.assertEqual(st, 404)
        self.assertIn("application/json", hd["content-type"])
        self.assertIn("error", json.loads(body))


# ==========================================================================
# degraded states — a missing dataset must be a clean answer, not a traceback
# ==========================================================================

class TestMissingData(APITestCase):
    def _delete_dataset(self):
        for name in ("combos.json", "export.jsonl"):
            p = os.path.join(self.data, name)
            if os.path.exists(p):
                os.remove(p)
        rows_dir = os.path.join(self.data, "rows")
        for name in os.listdir(rows_dir):
            os.remove(os.path.join(rows_dir, name))

    def test_lookup_with_no_dataset_is_a_wellformed_miss(self):
        self._delete_dataset()
        st, _hd, body = self.get("/api/lookup?hw=sm_86&model=qwen3")
        self.assertEqual(st, 200, "a missing dataset is a miss, not a 500")
        doc = json.loads(body)
        self.assertEqual(set(doc), RESPONSE_KEYS)
        self.assertTrue(doc["miss"]["is_miss"])
        self.assertIn(doc["miss"]["reason"], MISS_REASONS)
        self.assertEqual(set(doc["miss"]), MISS_KEYS)
        self.assertNotIn("Traceback", body.decode())

    def test_export_with_no_dataset_returns_clean_json_error(self):
        self._delete_dataset()
        st, hd, body = self.get("/api/export.jsonl")
        self.assertEqual(st, 503)
        self.assertIn("application/json", hd["content-type"])
        doc = json.loads(body)
        self.assertIn("error", doc)
        self.assertNotEqual(doc["error"]["code"], "internal")
        for bad in ("Traceback", "FileNotFoundError", "<html"):
            self.assertNotIn(bad, body.decode())

    def test_health_reports_unhealthy_with_reason(self):
        self._delete_dataset()
        st, _hd, body = self.get("/api/health")
        self.assertEqual(st, 503)
        doc = json.loads(body)
        self.assertFalse(doc["ok"])
        self.assertIsInstance(doc["dataset_error"], str)

    def test_corrupt_export_falls_back_to_rows(self):
        with open(os.path.join(self.data, "combos.json"), "w") as fh:
            fh.write("{not json at all")
        body = self.getjson("/api/lookup?hw=sm_86&model=qwen3")
        self.assertEqual(len(body["rows"]), 1, "should have fallen back to data/rows/*.jsonl")


# ==========================================================================
# the rest of the surface
# ==========================================================================

class TestOtherRoutes(APITestCase):
    def test_taxonomy(self):
        doc = self.getjson("/api/taxonomy")
        for key in ("hw_vendors", "runtimes", "models"):
            self.assertIn(key, doc)

    def test_rows_counts_pagination(self):
        doc = self.getjson("/api/rows?limit=2")
        self.assertEqual(len(doc["rows"]), 2)
        self.assertEqual(doc["counts"]["total"], 8)
        self.assertIn("solved", doc["counts"]["by_status"])
        page2 = self.getjson("/api/rows?limit=2&offset=2")
        self.assertNotEqual([r["id"] for r in doc["rows"]], [r["id"] for r in page2["rows"]])

    def test_rows_filters(self):
        rejected = self.getjson("/api/rows?status=rejected")["rows"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["status"], "rejected")
        derived = self.getjson("/api/rows?kind=derived")["rows"]
        self.assertTrue(derived)
        for row in derived:
            self.assertEqual(row["source_kind"], "derived")

    def test_health_ok(self):
        doc = self.getjson("/api/health")
        self.assertTrue(doc["ok"])
        self.assertIn("dataset", doc)
        self.assertIn("write_path", doc)
        self.assertIn("stale_days", doc)

    def test_docs_page_is_a_real_deliverable(self):
        st, hd, body = self.get("/api/docs")
        self.assertEqual(st, 200)
        self.assertIn("text/html", hd["content-type"])
        text = body.decode()
        self.assertIn("Before building a hardware-specific kernel or runtime workaround, call", text)
        self.assertIn("lookup_combo", text)
        self.assertIn("curl", text)
        for route in ("/api/lookup", "/api/want", "/api/miss", "/api/export.jsonl"):
            self.assertIn(route, text)
        for reason in sorted(MISS_REASONS):
            self.assertIn(reason, text, f"docs do not explain miss.reason {reason}")
        self.assertIn("304", text)

    def test_openapi_parses_and_documents_lookup(self):
        doc = self.getjson("/api/openapi.json")
        self.assertIn("openapi", doc)
        self.assertIn("/api/lookup", doc["paths"])
        self.assertEqual(doc["paths"]["/api/lookup"]["get"]["operationId"], "lookup_combo")
        for schema in ("Row", "Miss", "Query"):
            self.assertIn(schema, doc["components"]["schemas"])
        self.assertEqual(set(doc["components"]["schemas"]["Miss"]["properties"]), MISS_KEYS)

    def test_json_404_for_api_paths(self):
        st, hd, body = self.get("/api/nonsense")
        self.assertEqual(st, 404)
        self.assertIn("error", json.loads(body))

    def test_legacy_blueprint_aliases_work(self):
        """The blueprint advertises /v1/lookup, /combo.json and /v1/export.jsonl."""
        for path in ("/v1/lookup?hw=sm_86", "/combo.json?hw=sm_86"):
            body = self.getjson(path)
            self.assertEqual(set(body) - {"error", "miss_logged"}, RESPONSE_KEYS, path)
            self.assertIn("miss", body)
        st, _hd, body = self.get("/v1/export.jsonl")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(body.decode().splitlines()), 1)

    def test_star_row_not_duplicated_between_rows_and_context(self):
        """A '*' row is an answer when no model is asked, context only when one is."""
        no_model = self.getjson("/api/lookup?hw=sm_86")
        self.assertIn("nvidia/sm_86/*/llama_cpp", [r["id"] for r in no_model["rows"]])
        self.assertEqual(no_model["context"], [])
        with_model = self.getjson("/api/lookup?hw=sm_86&model=does-not-exist")
        self.assertEqual(with_model["rows"], [])
        self.assertIn("nvidia/sm_86/*/llama_cpp", [r["id"] for r in with_model["context"]])
        overlap = set(r["id"] for r in with_model["rows"]) & set(r["id"] for r in with_model["context"])
        self.assertEqual(overlap, set())

    def test_cors_preflight(self):
        st, hd, _ = self.request("/api/lookup", method="OPTIONS")
        self.assertIn(st, (200, 204))
        self.assertEqual(hd["access-control-allow-origin"], "*")


@unittest.skipUnless(os.environ.get("RUN_SLOW") == "1", "set RUN_SLOW=1 to test the rate limiter")
class TestRateLimit(APITestCase):
    def test_vote_rate_limit_20_per_minute(self):
        codes = []
        for i in range(24):
            st, _ = self.postjson("/api/want/nvidia/sm_86/qwen3/llama_cpp",
                                  {"voter": f"gh:spam-{i}"})
            codes.append(st)
        self.assertIn(429, codes, "the 20/min limit never fired")
        self.assertEqual(codes[:20], [201] * 20)
        self.assertEqual(self.get("/api/health")[0], 200, "rate limiting took the server down")


if __name__ == "__main__":
    unittest.main(verbosity=2)
