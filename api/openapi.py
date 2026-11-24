"""GET /api/openapi.json — machine-readable spec for the combo index API.

Kept hand-written and deliberately small: one lookup operation an agent tool can be
generated from, plus the write surface. Schemas are permissive (`additionalProperties`)
because CONTRACT §1 rows carry optional/nullable fields and the index must be able to
grow without breaking consumers.
"""

from __future__ import annotations

ROW_SCHEMA = {
    "type": "object",
    # `evidence` is optional (CONTRACT §1 amendment): vote- and miss-created rows carry
    # demand/gap metadata and no quote, and no quote is ever synthesised.
    "required": ["id", "status", "source_kind", "hw_vendor", "hw_arch", "model_family",
                 "runtime", "as_of", "reported_by", "pointer_alive", "want_votes"],
    "properties": {
        "id": {"type": "string", "example": "nvidia/sm_86/qwen3/llama_cpp",
               "description": "canonical id: {hw_vendor}/{hw_arch}/{model_family}/{runtime} (CONTRACT §2)"},
        "status": {"type": "string", "enum": ["solved", "untested", "rejected"]},
        "basis": {"type": ["string", "null"], "enum": ["docs-claim", "analogy", "author-says", "mine", None]},
        "basis_note": {"type": ["string", "null"]},
        "parent": {"type": ["string", "null"], "description": "parent base row id for variant rows"},
        "parent_untested": {"type": "boolean", "description": "true when a variant's parent row has status == 'untested'"},
        "source_kind": {"type": "string", "enum": ["scraped", "derived", "hand", "author-claim"]},
        "provisional": {"type": "boolean"},
        "hw_vendor": {"type": "string", "enum": ["nvidia", "amd", "intel", "apple", "qualcomm",
                                                 "arm-cpu", "x86-cpu", "other"]},
        "hw_arch": {"type": "string", "example": "sm_86"},
        "hw_name": {"type": ["string", "null"]},
        "hw_extra": {"type": "object"},
        "model_family": {"type": "string", "description": "snake_case, or '*' for hardware claims (CONTRACT §3)"},
        "model_rev": {"type": ["string", "null"]},
        "quant": {"type": ["string", "null"]},
        "context_length": {"type": ["integer", "null"], "minimum": 1},
        "offload": {"type": ["string", "null"]},
        "runtime_version": {"type": ["string", "null"]},
        "driver_version": {"type": ["string", "null"]},
        "flags": {"type": ["string", "null"]},
        "fits": {"type": ["string", "null"], "enum": ["writing", "coding", "tools", "long-context", "multimodal", "speed", None]},
        "runtime": {"type": "string", "description": "slug from /api/taxonomy runtimes[]"},
        "runtime_rev": {"type": ["string", "null"]},
        "pointer": {"type": ["string", "null"], "format": "uri",
                    "description": "evidence URL to READ, never code to run"},
        "notes": {"type": ["string", "null"]},
        "measurement": {"type": ["object", "null"]},
        "pointer_alive": {"type": "boolean"},
        "as_of": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "reported_by": {"type": "string"},
        "first_seen": {"type": ["string", "null"]},
        "updated": {"type": ["string", "null"]},
        "want_votes": {"type": "integer", "minimum": 0},
        "want_first": {"type": ["string", "null"]},
        "want_requesters": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "description": "optional; absent on vote/miss-created rows",
                     "items": {
            "type": "object",
            "required": ["url", "quote", "kind"],
            "properties": {"url": {"type": "string"}, "quote": {"type": "string"},
                           "kind": {"type": "string", "enum": ["upstream-doc", "package-table",
                                                              "model-repo", "release", "issue",
                                                              "community"]}}}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "created_by": {"type": "string", "enum": ["scraper", "derived", "hand", "vote", "miss"]},
    },
    "additionalProperties": True,
}

MISS_SCHEMA = {
    "type": "object",
    "description": "Always present in a lookup response. On a hit: {\"is_miss\": false}.",
    "properties": {
        "is_miss": {"type": "boolean", "description": "true iff rows == []; context rows never count"},
        "reason": {"type": "string", "enum": ["no-claim", "untested-only", "rejected-only",
                                              "partial-context", "no-match"]},
        "partial": {"type": "boolean", "description": "hardware-level '*' rows exist, no model-specific claim"},
        "hint": {"type": "string"},
        "known_untested": {"type": "boolean"},
        "known_wanted": {"type": "boolean"},
        "wanted_votes": {"type": "integer"},
        "untested_basis": {"type": "array", "items": {"type": "string"}},
        "last_checked": {"type": ["string", "null"], "format": "date"},
        "counts": {"type": "object",
                   "properties": {"exact": {"type": "integer"}, "context": {"type": "integer"}}},
    },
    "additionalProperties": True,
}

QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "hw": {"type": ["string", "null"]},
        "model": {"type": ["string", "null"]},
        "runtime": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"]},
        "q": {"type": ["string", "null"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
    },
    "additionalProperties": False,
}

LOOKUP_RESPONSE = {
    "type": "object",
    "required": ["query", "rows", "context", "miss", "query_id", "generated_at", "dataset"],
    "properties": {
        "query": {"$ref": "#/components/schemas/Query"},
        "rows": {"type": "array", "items": {"$ref": "#/components/schemas/Row"}},
        "context": {"type": "array", "items": {"$ref": "#/components/schemas/Row"},
                    "description": "model_family '*' rows: hardware-level support, applies to all models"},
        "miss": {"$ref": "#/components/schemas/Miss"},
        "query_id": {"type": "string", "example": "ab12cd34"},
        "generated_at": {"type": "string", "format": "date-time"},
        "dataset": {"type": "object",
                    "properties": {"rows": {"type": "integer"},
                                   "as_of": {"type": ["string", "null"], "format": "date"},
                                   "version": {"type": ["string", "null"]}}},
        "miss_logged": {"type": "object", "description": "only when ?log=1 or when called via POST"},
    },
    "additionalProperties": True,
}

ERROR_SCHEMA = {
    "type": "object",
    "required": ["error"],
    "properties": {"error": {"type": "object",
                             "required": ["code", "status", "message"],
                             "properties": {"code": {"type": "string"},
                                            "status": {"type": "integer"},
                                            "message": {"type": "string"}}}},
}

LOOKUP_PARAMS = [
    {"name": "hw", "in": "query", "schema": {"type": "string"},
     "description": "hw_arch exactly, else hw_vendor, else prefix (e.g. sm_86, sm_, nvidia)"},
    {"name": "model", "in": "query", "schema": {"type": "string"},
     "description": "model_family exactly, else contains. '*' rows are context only"},
    {"name": "runtime", "in": "query", "schema": {"type": "string"},
     "description": "runtime slug in either spelling -- llama.cpp or llama_cpp -- then display name"},
    {"name": "status", "in": "query", "schema": {"type": "string",
                                                 "enum": ["solved", "untested", "rejected"]}},
    {"name": "kind", "in": "query", "schema": {"type": "string",
                                               "enum": ["scraped", "derived", "hand", "author-claim"]},
     "description": "source_kind filter"},
    {"name": "q", "in": "query", "schema": {"type": "string"}, "description": "free text"},
    {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500,
                                                "default": 50}},
    {"name": "log", "in": "query", "schema": {"type": "string", "enum": ["1"]},
     "description": "log the miss if this lookup is a miss (GET is otherwise side-effect free)"},
    {"name": "searcher", "in": "query", "schema": {"type": "string"},
     "description": "stable searcher key used with log=1; anonymous key derived per client if absent"},
]


def spec(base_url: str = "http://127.0.0.1:8787") -> dict:
    base = base_url.rstrip("/")
    want_path = {
        "parameters": [{"name": "id", "in": "path", "required": True,
                        "schema": {"type": "string"},
                        "description": "{hw_vendor}/{hw_arch}/{model_family}/{runtime}; slashes must be encoded or sent literally"}],
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "canirun combo index",
            "version": "0.1.0",
            "description": (
                "Combination index for local inference: does (hardware × model × runtime) have a "
                "known working path? Before building a hardware-specific kernel or runtime "
                "workaround, call lookup; if it returns a miss, report the miss. "
                "Rows are claims with evidence pointers. Nothing is executed or endorsed."
            ),
            "license": {"name": "see project root"},
        },
        "servers": [{"url": base}],
        "paths": {
            "/api/lookup": {
                "get": {
                    "operationId": "lookup_combo",
                    "summary": "Look up a hardware/model/runtime combination. Returns rows, "
                               "'*' context rows, and a miss object.",
                    "parameters": LOOKUP_PARAMS,
                    "responses": {
                        "200": {"description": "Lookup result (a miss is 200 — read miss.is_miss)",
                                "content": {"application/json": {"schema": LOOKUP_RESPONSE}}},
                        "429": {"description": "Rate limited (only for log=1)"},
                    },
                },
                "post": {
                    "operationId": "lookup_combo_logging",
                    "summary": "Same as GET, but logs the miss when it is one.",
                    "requestBody": {"content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"query": {"$ref": "#/components/schemas/Query"}}}}}},
                    "responses": {"200": {"description": "Lookup result",
                                          "content": {"application/json": {"schema": LOOKUP_RESPONSE}}}},
                },
            },
            "/api/rows": {
                "get": {"operationId": "browse_rows", "summary": "Filtered browse with counts",
                        "parameters": LOOKUP_PARAMS + [
                            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}}],
                        "responses": {"200": {"description": "Rows + counts"}}},
            },
            "/api/wanted": {
                "get": {"operationId": "wanted_list",
                        "summary": "Untested / wanted rows, sorted want_votes desc then want_first asc",
                        "responses": {"200": {"description": "Untested / wanted rows"}}},
            },
            "/api/untested": {
                "get": {"operationId": "untested_list",
                        "summary": "Untested rows (alias of /api/wanted), sorted want_votes desc then want_first asc",
                        "responses": {"200": {"description": "Untested rows"}}},
            },
            "/llms.txt": {
                "get": {"operationId": "llms_txt",
                        "summary": "Plain-text summary for LLMs and agents",
                        "responses": {"200": {"description": "text/plain; charset=utf-8"}}},
            },
            "/api/want/{id}": {
                **want_path,
                "post": {
                    "operationId": "want_combo",
                    "summary": "Vote for a combination. Idempotent per (id, voter).",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object", "properties": {"voter": {"type": "string",
                                                                   "description": "stable key, e.g. gh:handle"}},
                        "required": ["voter"]}}}},
                    "responses": {
                        "201": {"description": "Vote recorded", "content": {"application/json": {"schema": {
                            "type": "object", "properties": {
                                "id": {"type": "string"}, "want_votes": {"type": "integer"},
                                "want_first": {"type": ["string", "null"]}, "voted": {"type": "boolean"}}}}}},
                        "400": {"description": "Bad id or voter", "content": {"application/json": {"schema": ERROR_SCHEMA}}},
                        "429": {"description": "Rate limited (20/min/IP)"},
                    },
                },
                "delete": {
                    "operationId": "unwant_combo",
                    "summary": "Retract a vote. Same body as POST.",
                    "responses": {"200": {"description": "Vote retracted"}},
                },
            },
            "/api/miss": {
                "post": {
                    "operationId": "report_miss",
                    "summary": "Report a searched combination that found nothing. "
                               "3 distinct searchers create a provisional wanted row.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"$ref": "#/components/schemas/Query"},
                                       "searcher_key": {"type": "string"}}}}}},
                    "responses": {
                        "200": {"description": "Logged", "content": {"application/json": {"schema": {
                            "type": "object", "properties": {
                                "logged": {"type": "boolean"}, "query_id": {"type": "string"},
                                "distinct_searchers": {"type": "integer"},
                                "creates_wanted_at": {"type": "integer", "const": 3}}}}}},
                        "400": {"description": "Bad body", "content": {"application/json": {"schema": ERROR_SCHEMA}}},
                        "429": {"description": "Rate limited"},
                    },
                }
            },
            "/api/combos.json": {
                "get": {"operationId": "export_combos",
                        "summary": "The export (ETag, Cache-Control, 304)",
                        "responses": {"200": {"description": "combos.json"},
                                      "304": {"description": "Not modified"},
                                      "503": {"description": "No dataset built yet"}}},
            },
            "/api/export.jsonl": {
                "get": {"operationId": "export_jsonl",
                        "summary": "Full dump, one row per line (ETag, 304)",
                        "responses": {"200": {"description": "JSONL"}, "304": {"description": "Not modified"},
                                      "503": {"description": "No dataset built yet"}}},
            },
            "/api/taxonomy": {
                "get": {"operationId": "taxonomy", "summary": "Vendors, runtimes, models, hw_archs",
                        "responses": {"200": {"description": "Taxonomy"}}},
            },
            "/api/health": {
                "get": {"operationId": "health", "summary": "Liveness + dataset freshness",
                        "responses": {"200": {"description": "Healthy"},
                                      "503": {"description": "Dataset missing/empty"}}},
            },
            "/api/openapi.json": {
                "get": {"operationId": "openapi", "summary": "This document",
                        "responses": {"200": {"description": "OpenAPI 3.1"}}},
            },
        },
        "components": {
            "schemas": {"Row": ROW_SCHEMA, "Miss": MISS_SCHEMA, "Query": QUERY_SCHEMA,
                        "Error": ERROR_SCHEMA},
        },
    }
