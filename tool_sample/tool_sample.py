"""ToolHub: turn the long-format documentation CSVs into agent tools.

This module is the "loop that turns a DB into tools". It reads the parsed
documentation CSVs (scipy / sklearn / lifelines / plotly / matplotlib),
reconstructs a Biomni-compatible tool schema for every documented callable,
and can dynamically resolve + invoke the real library callable at runtime.

Nothing here is generated tool-by-tool: every tool description and every
callable is produced from data in a single loop.

Layout (root-level):
    tool/       -> this hub (loader + dynamic dispatch)
    tool_desc/  -> generated Biomni-style `description = [...]` per library
    tool_env/   -> library install list (like biomni_env)
"""

from __future__ import annotations

import csv
import importlib
import re
from collections import defaultdict, OrderedDict
from pathlib import Path

# ==========================================================================
# [DISABLED] officialdocs-based ToolHub loader.
#
# The SEER agent does not read tools from ``officialdocs_parsing`` nor invoke
# them dynamically at runtime; only the merged SEER substrate further below is
# used by ``graphs.py``. The whole doc-loading region is parked inside a raw
# string literal so it is still parsed (kept for reference) but never executed.
# Re-enable by removing the surrounding ``_OFFICIALDOCS_LOADER_DISABLED`` quotes.
# ==========================================================================
_OFFICIALDOCS_LOADER_DISABLED = r'''
# --------------------------------------------------------------------------
# Sources: library name -> long-format CSV produced by officialdocs_parsing
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "officialdocs_parsing"

SOURCES: "OrderedDict[str, Path]" = OrderedDict(
    [
        ("scipy", DOCS / "scipy" / "scipy_stats_all.csv"),
        ("sklearn", DOCS / "sklearn" / "analysis_details_all.csv"),
        ("lifelines", DOCS / "lifelines" / "analysis_details_all.csv"),
        ("plotly", DOCS / "plotly" / "analysis_details_all.csv"),
        ("matplotlib", DOCS / "matplotlib" / "analysis_details_all.csv"),
    ]
)

_NO_DEFAULT = object()  # sentinel: parameter has no default => required


# --------------------------------------------------------------------------
# Low-level text helpers
# --------------------------------------------------------------------------
def split_top_level(s: str) -> "list[str]":
    """Split on commas that are not nested inside (), [], {} or quotes."""
    parts, depth, cur, quote = [], 0, "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur += ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def arg_string(signature: str) -> str:
    """Return the content of the first balanced (...) group in a signature."""
    if not signature:
        return ""
    i = signature.find("(")
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(signature)):
        if signature[j] == "(":
            depth += 1
        elif signature[j] == ")":
            depth -= 1
            if depth == 0:
                return signature[i + 1 : j]
    return signature[i + 1 :]


def split_names(arg_name: str) -> "list[str]":
    """`a, b` -> ['a', 'b'];  `*args` -> ['args']."""
    out = []
    for tok in arg_name.split(","):
        tok = tok.strip().lstrip("*").strip()
        if tok:
            out.append(tok)
    return out


def split_module_qual(full_name: str) -> "tuple[str, str]":
    """Split a dotted path into (import_module, qualname).

    The qualname starts at the first Capitalized segment (a class); if there
    is none, the last segment is the callable and the rest is the module.
        scipy.stats.ttest_ind          -> ("scipy.stats", "ttest_ind")
        sklearn.cluster.KMeans         -> ("sklearn.cluster", "KMeans")
        matplotlib.axes.Axes.scatter   -> ("matplotlib.axes", "Axes.scatter")
    """
    parts = full_name.split(".")
    for i, p in enumerate(parts):
        if p[:1].isupper():
            module = ".".join(parts[:i]) or full_name
            return module, ".".join(parts[i:])
    return ".".join(parts[:-1]) or full_name, parts[-1]


_DEFAULT_RE = re.compile(r"default\s*[:=]?\s*([^,\)\]]+)", re.I)


def parse_type_and_default(arg_type: str) -> "tuple[str, str, bool]":
    """From a documented type string return (clean_type, default_or_None, optional).

    Handles: 'int, optional', 'int, default=100', 'float, option (default=0.05)',
    '{None, int}', etc.
    """
    t = (arg_type or "").strip()
    if not t:
        return "", None, False
    optional = bool(re.search(r"\b(optional|option)\b", t, re.I)) or "default" in t.lower()
    default = None
    m = _DEFAULT_RE.search(t)
    if m:
        default = m.group(1).strip().rstrip(").").strip() or None
    # strip the optional/default annotations from the type itself
    t = re.sub(r"\(default[^)]*\)", "", t, flags=re.I)
    t = re.sub(r",?\s*default\s*[:=].*$", "", t, flags=re.I)
    t = re.sub(r",?\s*\boptional\b.*$", "", t, flags=re.I)
    t = re.sub(r",?\s*\boption\b.*$", "", t, flags=re.I)
    t = t.strip().rstrip(",").strip()
    return t, default, optional


# --------------------------------------------------------------------------
# Signature parsing
# --------------------------------------------------------------------------
def parse_signature_params(signature: str) -> "list[tuple[str, str, object]]":
    """Return ordered [(name, kind, default)] from a signature string.

    kind is one of: 'param', 'var_positional', 'var_keyword'.
    default is _NO_DEFAULT when the parameter is required.
    """
    out = []
    for tok in split_top_level(arg_string(signature)):
        tok = tok.strip()
        if tok in ("*", "/"):  # positional/keyword separators
            continue
        if tok.startswith("**"):
            out.append((tok[2:].split(":", 1)[0].strip(), "var_keyword", _NO_DEFAULT))
            continue
        if tok.startswith("*"):
            out.append((tok[1:].split(":", 1)[0].strip(), "var_positional", _NO_DEFAULT))
            continue
        if "=" in tok:
            left, default = tok.split("=", 1)
            default = default.strip()
        else:
            left, default = tok, _NO_DEFAULT
        name = left.split(":", 1)[0].strip()
        if name in ("self", "cls") or not name:
            continue
        out.append((name, "param", default))
    return out


# --------------------------------------------------------------------------
# CSV -> grouped rows -> schema
# --------------------------------------------------------------------------
def read_rows(csv_path: Path) -> "list[dict]":
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def group_by_tool(rows: "list[dict]") -> "OrderedDict[str, list[dict]]":
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in rows:
        grouped.setdefault(r["function"], []).append(r)
    return grouped


def _build_description(summ: dict, rows: "list[dict]", module: str, qual: str,
                       has_var_kw: bool) -> str:
    parts = []
    s = (summ.get("description") or "").strip()
    if s:
        parts.append(s)
    if "." in qual:  # a bound method: Class.method
        cls, meth = qual.split(".", 1)
        parts.append(
            f"[Usage] `from {module} import {cls}`; call `.{meth}(...)` on a {cls} instance."
        )
    else:
        parts.append(f"[Usage] `from {module} import {qual}`; then call `{qual}(...)`.")
    returns = [r for r in rows if r["field"] == "return"]
    rtxt = []
    for r in returns:
        name = (r.get("arg_name") or "").strip()
        desc = (r.get("description") or "").strip()
        chunk = f"{name}: {desc}" if name and desc else (name or desc)
        if chunk:
            rtxt.append(chunk)
    if rtxt:
        parts.append("[Returns] " + "; ".join(rtxt))
    if has_var_kw:
        parts.append("[Note] Also accepts additional keyword arguments.")
    return " ".join(parts).strip()


def build_schema(full_name: str, rows: "list[dict]") -> dict:
    summ = next((r for r in rows if r["field"] == "summary"), {})
    signature = summ.get("signature", "") or ""
    kind = summ.get("kind", "") or ""
    url = summ.get("url", "") or summ.get("source_url", "") or ""
    module, qual = split_module_qual(full_name)
    if "." in qual and kind in ("", "function"):
        kind = "method"

    # documented parameters: name -> (type, default, optional, description)
    docs: "OrderedDict[str, tuple]" = OrderedDict()
    for r in rows:
        if r["field"] != "parameter":
            continue
        ctype, dfault, optional = parse_type_and_default(r.get("arg_type", ""))
        desc = (r.get("description") or "").strip()
        for nm in split_names(r.get("arg_name", "")):
            docs[nm] = (ctype, dfault, optional, desc)

    required, optional_params, seen = [], [], set()
    has_var_kw = False
    sig_params = parse_signature_params(signature)

    for name, pkind, default in sig_params:
        if pkind == "var_keyword":
            has_var_kw = True
            continue
        if pkind == "var_positional":
            continue
        seen.add(name)
        ctype, ddefault, _opt, ddesc = docs.get(name, ("", None, False, ""))
        entry = {
            "name": name,
            "type": ctype or "Any",
            "description": ddesc,
            "default": None if default is _NO_DEFAULT else default,
        }
        (required if default is _NO_DEFAULT else optional_params).append(entry)

    # documented params not present in the signature (or no signature at all)
    for nm, (ctype, dfault, optional, desc) in docs.items():
        if nm in seen:
            continue
        entry = {"name": nm, "type": ctype or "Any", "description": desc, "default": dfault}
        # with no signature we trust the doc's optional flag; else treat as optional
        if signature and arg_string(signature):
            optional_params.append(entry)
        else:
            (optional_params if optional else required).append(entry)

    return {
        "name": qual,
        "description": _build_description(summ, rows, module, qual, has_var_kw),
        "required_parameters": required,
        "optional_parameters": optional_params,
        "module": module,
        "qualname": qual,
        "kind": kind,
        "url": url,
    }


def build_library_schemas(csv_path: Path) -> "list[dict]":
    """Loop a single CSV into a flat list of tool schemas."""
    schemas = []
    for full_name, rows in group_by_tool(read_rows(csv_path)).items():
        if not full_name:
            continue
        schemas.append(build_schema(full_name, rows))
    return schemas


def build_all() -> "OrderedDict[str, list[dict]]":
    """library name -> [schema, ...] for every configured CSV."""
    out: "OrderedDict[str, list[dict]]" = OrderedDict()
    for lib, path in SOURCES.items():
        if path.exists():
            out[lib] = build_library_schemas(path)
    return out


# --------------------------------------------------------------------------
# Biomni-compatible catalog  {real_module: [schema, ...]}
# --------------------------------------------------------------------------
def build_module2api_from_csv() -> "dict[str, list[dict]]":
    m2a: "defaultdict[str, list]" = defaultdict(list)
    for schemas in build_all().values():
        for sc in schemas:
            m2a[sc["module"]].append(sc)
    return dict(m2a)


def load_module2api() -> "dict[str, list[dict]]":
    """Load the generated tool_desc/*.py modules into a module2api dict."""
    m2a: "defaultdict[str, list]" = defaultdict(list)
    for lib in SOURCES:
        try:
            mod = importlib.import_module(f"tool_desc.{lib}")
        except ModuleNotFoundError:
            continue
        for sc in getattr(mod, "description", []):
            m2a[sc.get("module", lib)].append(sc)
    return dict(m2a)


# --------------------------------------------------------------------------
# Dynamic dispatch: schema -> real callable
# --------------------------------------------------------------------------
def resolve_callable(schema: dict):
    """Import the real library object described by a schema.

    Returns the resolved callable/class. For bound methods (qualname
    Class.method) the *unbound* function is returned; the agent is expected to
    build an instance first (see the [Usage] hint in the description).
    """
    module = importlib.import_module(schema["module"])
    obj = module
    for attr in schema["qualname"].split("."):
        obj = getattr(obj, attr)
    return obj


def call_tool(schema: dict, *args, **kwargs):
    return resolve_callable(schema)(*args, **kwargs)


if __name__ == "__main__":
    cat = build_all()
    total = sum(len(v) for v in cat.values())
    for lib, schemas in cat.items():
        print(f"{lib:12s} {len(schemas):5d} tools  -> module2api keys: "
              f"{len({s['module'] for s in schemas})}")
    print(f"{'TOTAL':12s} {total:5d} tools")
'''
# [DISABLED] end of officialdocs-based ToolHub loader.


# ============================================================================
# Merged from tool.py — SEER agent tools + Kedro pipeline execution substrate.
# (DuckDB ops, frozen analysis tools: KM / PSM / Cox, step execute/persist,
#  catalog.yml / parameters.yml rendering.)
# ============================================================================

"""SEER agent tools + Kedro pipeline execution substrate.

The SEER agent's Plan (P) node emits a declarative, Kedro-style pipeline: an
ordered list of *named* operations over the SEER table. This module is the
Execute (E) substrate that runs that pipeline.

Design goals
------------
- **Memory safe for multi-GB parquet.** All operations run as DuckDB SQL over a
  lazy ``read_parquet`` view of the SEER file. Intermediate steps stay as DuckDB
  views (column/row pushdown); only small aggregated deliverables are ever
  materialized into pandas.
- **Helper library.** This module provides the DuckDB connection, schema
  profiling, deliverable materialization and S3 helpers reused by the SEER
  ReAct code-gen engine (``multi_agents.seer_agent.graphs``).

Public surface
--------------
- ``resolve_seer_parquet_uri`` — find the SEER dataset for a user/note.
- ``get_seer_connection``      — cached DuckDB connection with a ``seer`` view.
- ``seer_column_profile``      — column list for the planner prompt.
"""


import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _emit_tool_progress(message: str) -> None:
    """오래 걸리는 툴의 한 줄 진행을 로그 + Dora ``progress_brief`` 로 보낸다.

    분석 그래프가 돌 때는 ``graph_invoke`` 싱크(→ ``an_stage`` → 채팅 헤드라인)를
    쓰고, 싱크가 없으면 오케스트레이터 ``util.progress`` 로 떨어진다. 둘 다 없으면
    로그만 남긴다. emit 실패는 계산을 멈추지 않는다.
    """
    msg = str(message or "").strip()
    if not msg:
        return
    logger.info("[seer] %s", msg)
    sent = False
    try:
        import graph_invoke  # lazy: execute 경로에서만 존재

        if graph_invoke._progress_sink.get() is not None:
            graph_invoke._emit_progress({"kind": "brief", "text": msg[:200]})
            sent = True
    except Exception:
        pass
    if sent:
        return
    try:
        from multi_agents.util import progress as PR

        PR.brief(msg)
    except Exception:
        pass


class _ToolHeartbeat:
    """부트스트랩/루프용 throttle 진행. ``every_n`` 회 또는 ``every_s`` 초마다 emit."""

    def __init__(
        self,
        label: str,
        total: int,
        *,
        every_n: int = 100,
        every_s: float = 15.0,
    ) -> None:
        self.label = str(label or "tool").strip() or "tool"
        self.total = max(0, int(total))
        self.every_n = max(1, int(every_n))
        self.every_s = max(2.0, float(every_s))
        self._t0 = time.monotonic()
        self._last_t = self._t0
        self._last_i = 0

    def start(self) -> None:
        if self.total <= 0:
            _emit_tool_progress(self.label)
            return
        _emit_tool_progress(f"{self.label} — 0/{self.total}")

    def tick(self, done: int) -> None:
        if self.total <= 0:
            return
        i = max(0, int(done))
        now = time.monotonic()
        if (
            i < self.total
            and (i - self._last_i) < self.every_n
            and (now - self._last_t) < self.every_s
        ):
            return
        self._last_t = now
        self._last_i = i
        elapsed = now - self._t0
        rate = (i / elapsed) if (elapsed > 0 and i > 0) else 0.0
        remain = ((self.total - i) / rate) if rate else 0.0
        extra = f", ~{int(remain)}s left" if remain >= 3 else ""
        _emit_tool_progress(
            f"{self.label} — {i}/{self.total} ({elapsed:.0f}s{extra})"
        )

    def done(self) -> None:
        elapsed = time.monotonic() - self._t0
        if self.total <= 0:
            _emit_tool_progress(f"{self.label} — done ({elapsed:.0f}s)")
            return
        _emit_tool_progress(f"{self.label} — {self.total}/{self.total} done ({elapsed:.0f}s)")

# Row cap when materializing a deliverable table into pandas. Aggregated SEER
# outputs are tiny; this guards against the planner accidentally selecting raw
# rows from a 4.8M-row table.
MATERIALIZE_ROW_CAP = 5000


def _max_persist_cells() -> int:
    """Cap (rows × columns) that a verified step will export to S3.

    Intermediate cohorts can be 700+ columns × hundreds of thousands of rows;
    COPYing those to S3 on *every* passing step stalls the whole run. Anything
    above this cap is skipped for S3 export (the DuckDB view still lives on the
    cached connection, so downstream steps keep reading it). Override with env
    ``SEER_MAX_PERSIST_CELLS`` (0 disables persistence entirely).

    The cell count stands in for the size of the written file, which is what
    actually costs time: at the numeric/short-string widths these cohorts carry,
    10M cells compresses to roughly tens of MB, and COPY + upload of that lands
    in seconds. Sizing the cap by that budget rather than by the old 3M keeps
    genuinely wide tables out while letting ordinary multiple-imputation output
    through — m=20 over a 3.4k-row cohort with indicator columns is 3.5M cells,
    a few MB of parquet, and skipping it left the cohort unreadable to any later
    delta run (the DuckDB view that the skip relies on does not outlive the run).
    """
    try:
        return max(0, int(os.getenv("SEER_MAX_PERSIST_CELLS", "10000000")))
    except (TypeError, ValueError):
        return 10_000_000

# Local bind-mount fallback used when S3 httpfs is unavailable in-container.
_DEFAULT_LOCAL_PARQUET = "/app/utils/SEER2025.parquet"

# Canonical SEER database — the registered ``seer_db`` tool
# (``insight_on.agent_tools``). SEER-agent runs are *pinned* to this dataset:
# every user of the SEER agent queries the same fixed SEER DB regardless of
# what dataset is attached to their note. Override with env ``SEER_S3_URI``.
SEER_DB_S3_URI = "s3://insight-on/openaccess_db/SEER2025.parquet"


def seer_db_uri() -> str:
    """Return the fixed SEER DB URI (env ``SEER_S3_URI`` → canonical constant)."""
    return (os.getenv("SEER_S3_URI") or "").strip() or SEER_DB_S3_URI


# ---------------------------------------------------------------------------
# Dataset resolution (source_artifacts)
# ---------------------------------------------------------------------------

def resolve_seer_parquet_uri(
    user_id: Optional[str] = None,
    note_id: Optional[str] = None,
    *,
    explicit_uri: Optional[str] = None,
) -> Optional[str]:
    """Resolve the parquet URI for the SEER dataset.

    The SEER agent is pinned to the canonical ``seer_db`` dataset so every user
    queries the same fixed SEER database. An ``explicit_uri`` (programmatic
    override) still wins; otherwise this always returns the fixed SEER DB URI
    (env ``SEER_S3_URI`` → :data:`SEER_DB_S3_URI`). ``get_seer_connection``
    transparently prefers a local bind-mount when present.
    """
    if explicit_uri:
        return explicit_uri.strip()
    return seer_db_uri()


# ---------------------------------------------------------------------------
# DuckDB connection + lazy SEER view
# ---------------------------------------------------------------------------

# Cache one connection per parquet URI for the process lifetime.
_CONN_CACHE: Dict[str, Any] = {}

# Extra input tables (source name -> parquet path) exposed alongside ``seer`` on
# every connection. A run with several uploads registers them once, in step 1;
# they are process-wide because the connection cache is, and because every stage
# reaches the hub through ``get_seer_connection`` rather than passing them along.
_EXTRA_SOURCES: Dict[str, str] = {}


def register_sources(tables: Dict[str, str]) -> Dict[str, str]:
    """Expose additional input tables as views on the shared connection(s).

    ``tables`` maps a source NAME to its normalized parquet path (see
    ``sources``). Registering here — rather than materializing frames into
    DuckDB — keeps every extra upload lazy and column-pruned, exactly like the
    primary ``seer`` view. Returns the names now registered.
    """
    added = {str(k): str(v) for k, v in (tables or {}).items() if k and v}
    _EXTRA_SOURCES.update(added)
    for con in _CONN_CACHE.values():
        _register_extra_views(con)
    return dict(_EXTRA_SOURCES)


def source_views() -> List[str]:
    """Names of the extra input tables currently registered."""
    return sorted(_EXTRA_SOURCES)


def _register_extra_views(con) -> None:
    """(Re)create one view per extra source; a missing/broken file is skipped."""
    for name, path in _EXTRA_SOURCES.items():
        if not os.path.exists(path):
            logger.warning("[seer] source '%s' not found on disk: %s", name, path)
            continue
        try:
            con.execute(
                f"CREATE OR REPLACE VIEW {_q(name)} AS "
                f"SELECT * FROM read_parquet('{path}')"
            )
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the run
            logger.warning("[seer] source '%s' could not be registered: %s", name, e)


def get_seer_connection(parquet_uri: str):
    """Return a cached DuckDB connection exposing the SEER table as view ``seer``.

    Prefers a local parquet when present (network-restricted deploys read from
    disk, never S3): ``SEER_LOCAL_PARQUET`` (explicit file) > a file named after
    the URI's basename inside ``SEER_LOCAL_DATA_DIR`` (e.g. ``backend/data``
    bind-mounted at ``/app/data``) > the canonical SEER DB bind-mount. Only when
    no local copy exists does it configure httpfs and read directly from S3
    (lazy, no full download).
    """
    import duckdb

    cached = _CONN_CACHE.get(parquet_uri)
    if cached is not None:
        return cached

    con = duckdb.connect(database=":memory:")

    # ``SEER_LOCAL_PARQUET`` (explicit override) always wins and applies to any
    # URI unconditionally.
    local = (os.getenv("SEER_LOCAL_PARQUET") or "").strip()

    # Prefer a locally-mounted copy for ANY dataset so runs never hit S3 when the
    # parquet is available on disk (network-restricted deploys). ``backend/data``
    # is bind-mounted at ``SEER_LOCAL_DATA_DIR`` (docker-compose), so an S3 URI
    # like ``s3://.../SEER_Breast.parquet`` resolves to
    # ``/app/data/SEER_Breast.parquet`` when that file exists.
    if not local:
        data_dir = (os.getenv("SEER_LOCAL_DATA_DIR") or "").strip()
        if data_dir and str(parquet_uri):
            cand = os.path.join(data_dir, os.path.basename(str(parquet_uri)))
            if os.path.exists(cand):
                local = cand

    # Fall back to the canonical SEER DB bind-mount for the fixed seer_db URI.
    if (
        not local
        and os.path.exists(_DEFAULT_LOCAL_PARQUET)
        and str(parquet_uri).startswith("s3://")
        and str(parquet_uri) == seer_db_uri()
    ):
        local = _DEFAULT_LOCAL_PARQUET

    if local:
        logger.info("[seer] reading dataset from local file: %s", local)

    if str(parquet_uri).startswith("s3://") and not local:
        _configure_httpfs(con, parquet_uri)
        src = f"read_parquet('{parquet_uri}')"
    else:
        path = local or parquet_uri
        if not os.path.exists(path):
            raise FileNotFoundError(f"SEER parquet not found: {path}")
        src = f"read_parquet('{path}')"

    con.execute(f"CREATE OR REPLACE VIEW seer AS SELECT * FROM {src}")
    _register_extra_views(con)
    _CONN_CACHE[parquet_uri] = con
    return con


def _configure_httpfs(con, s3_uri: str) -> None:
    from utils.storage.bucket import _aws_credentials, parse_s3_uri, _resolve_bucket_region

    creds = _aws_credentials() or {}
    try:
        bucket, _ = parse_s3_uri(s3_uri)
        region = _resolve_bucket_region(bucket) or creds.get("region")
    except Exception:
        region = creds.get("region")

    con.execute("INSTALL httpfs; LOAD httpfs;")
    if region:
        con.execute(f"SET s3_region='{region}';")
    if creds.get("access_key"):
        con.execute(f"SET s3_access_key_id='{creds['access_key']}';")
    if creds.get("secret_key"):
        con.execute(f"SET s3_secret_access_key='{creds['secret_key']}';")
    # Temporary credentials (STS, instance/task role) are rejected without their
    # token, and the failure looks identical to having no credentials at all.
    if creds.get("session_token"):
        con.execute(f"SET s3_session_token='{creds['session_token']}';")
    if creds.get("endpoint"):
        ep = str(creds["endpoint"]).replace("https://", "").replace("http://", "")
        con.execute(f"SET s3_endpoint='{ep}';")
    if not (creds.get("access_key") and creds.get("secret_key")):
        # DuckDB only reads the standard AWS_* names, which this repo does not
        # set — so nothing configured here means the read is about to 403.
        logger.warning(
            "[seer] no S3 credentials resolved for %s — read_parquet will likely "
            "fail with 403 AccessDenied",
            s3_uri,
        )


def _sql_literal_path(path: str) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _copy_relation_to_s3(
    con,
    view: str,
    key: str,
    *,
    bucket: str,
    fmt: str = "parquet",
) -> Optional[str]:
    """COPY a DuckDB relation to a temp file, upload to S3, then unlink the temp.

    Result parquet never stays under ``artifacts_dir`` — the working file lives
    in the OS temp dir only for the duration of the upload. Input working
    copies (downloaded uploads registered as views) are not touched.
    """
    import tempfile

    from utils.storage.bucket import upload_file_to_s3

    ext = "csv" if fmt == "csv" else "parquet"
    fd, tmp_path = tempfile.mkstemp(prefix="seer_persist_", suffix=f".{ext}")
    os.close(fd)
    try:
        fmt_clause = "FORMAT CSV, HEADER" if ext == "csv" else "FORMAT PARQUET"
        con.execute(
            f"COPY (SELECT * FROM {_q(view)}) TO '{_sql_literal_path(tmp_path)}' "
            f"({fmt_clause})"
        )
        content_type = (
            "text/csv" if ext == "csv" else "application/vnd.apache.parquet"
        )
        return upload_file_to_s3(
            tmp_path, key, bucket=bucket, content_type=content_type
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def seer_column_profile(parquet_uri: str, max_cols: int = 250) -> List[Dict[str, str]]:
    """Column name + duckdb type for the planner prompt."""
    con = get_seer_connection(parquet_uri)
    rows = con.execute("DESCRIBE seer").fetchall()
    out: List[Dict[str, str]] = []
    for r in rows[:max_cols]:
        out.append({"name": str(r[0]), "type": str(r[1])})
    return out


# ---------------------------------------------------------------------------
# SQL safety + identifier quoting
# ---------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|call|export|install|load)\b",
    re.IGNORECASE,
)

# String literals ('' is an escaped quote) and SQL comments. These are blanked
# out before structural checks so that data which legitimately contains ';' or
# SQL keywords is not mistaken for a statement separator / forbidden operation.
# e.g. SEER labels like 'Well differentiated; Grade I' must keep the ';' at
# runtime but must NOT be read as a statement terminator by the guard below.
_SQL_LITERAL_OR_COMMENT = re.compile(
    r"'(?:''|[^'])*'"  # single-quoted string literal
    r"|--[^\n]*"        # line comment
    r"|/\*.*?\*/",       # block comment
    re.DOTALL,
)


def _sql_skeleton(sql: str) -> str:
    """Blank out string literals and comments, keeping structural SQL only."""
    return _SQL_LITERAL_OR_COMMENT.sub(" ", sql)


def _assert_read_only(sql: str) -> None:
    body = sql.strip().rstrip(";")
    skeleton = _sql_skeleton(body)
    if ";" in skeleton:
        raise ValueError("Only a single read statement is allowed (no ';').")
    if _FORBIDDEN.search(skeleton):
        raise ValueError("Only SELECT/WITH read queries are allowed.")
    head = body.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise ValueError("Query must start with SELECT or WITH.")


def _bare(name: str) -> str:
    """Strip one layer of surrounding double quotes so quoting is idempotent.

    The planner is told to double-quote identifiers, so structured params may
    arrive pre-quoted (``"Sex"``) or bare (``Sex``). Normalize to bare.
    """
    s = str(name).strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].replace('""', '"')
    return s


def _q(view: str) -> str:
    """Quote a view/column identifier for SQL (idempotent for pre-quoted names)."""
    return '"' + _bare(view).replace('"', '""') + '"'


# Unquoted SQL identifiers may only be letters/digits/underscore. A hyphen
# (``CA15-3_group``) is minus, a space splits the token — both are syntax errors
# unless the name is double-quoted. ``CAST(x AS DOUBLE)`` stays untouched because
# type names match this pattern.
_SAFE_BARE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
# ``AS`` + already-quoted name, or the run of non-delimiter characters the model
# intended as the alias (stops before comma / FROM / closing paren). It does NOT
# stop at an OPENING paren, so on ``AS t(a, b)`` it captures ``t(a`` — which is why
# :func:`_requote_aliases` throws away any candidate holding a paren, and why the
# whole pass only runs on SQL that is already broken.
_AS_ALIAS = re.compile(
    r"\bAS\s+(\"(?:[^\"]|\"\")*\"|[^\s,);]+)",
    re.IGNORECASE,
)
# The engine every query here is bound for; :mod:`sql_lineage` reads the same one.
_SQL_DIALECT = "duckdb"


def _sql_parses(sql: str) -> Optional[bool]:
    """Whether DuckDB's grammar accepts ``sql``, or ``None`` when we cannot tell.

    ``None`` (no parser installed) is deliberately not reported as "broken". Callers
    read it as *leave the query alone*, because the failure this module exists to
    avoid is editing SQL that was already correct — and an unverifiable edit is the
    one we cannot afford to make.
    """
    try:
        from sqlglot import parse_one
    except Exception:
        return None
    try:
        parse_one(sql, dialect=_SQL_DIALECT)
    except Exception:
        return False
    return True


def _requote_aliases(sql: str) -> str:
    """Double-quote every ``AS`` alias that is not a valid bare identifier.

    String literals and comments are skipped so a label like ``'well; Grade I'`` is
    not mistaken for an alias, and so is any candidate containing a paren: ``AS`` also
    introduces subqueries (``WITH x AS (SELECT …)``), table aliases carrying a column
    list (``AS t(a, b, c)``) and parameterised cast types (``AS DECIMAL(10, 2)``), none
    of which is a column alias. This is a text pass over a query no parser could read,
    so it is a guess — :func:`_quote_unsafe_as_aliases` is what makes the guess safe.
    """
    literals = [m.span() for m in _SQL_LITERAL_OR_COMMENT.finditer(sql)]

    def _in_literal(pos: int) -> bool:
        return any(a <= pos < b for a, b in literals)

    out: List[str] = []
    last = 0
    for mo in _AS_ALIAS.finditer(sql):
        if _in_literal(mo.start()):
            continue
        alias = mo.group(1)
        if alias.startswith('"') or "(" in alias or ")" in alias:
            continue
        if _SAFE_BARE_IDENT.match(alias):
            continue
        start, end = mo.span(1)
        out.append(sql[last:start])
        out.append(_q(alias))
        last = end
    if not out:
        return sql
    out.append(sql[last:])
    return "".join(out)


def _quote_unsafe_as_aliases(sql: str) -> str:
    """Repair ``AS`` aliases DuckDB cannot read — and only when it cannot read them.

    LLM-authored ``sql`` queries often write ``"CA15-3_group" AS CA15-3_group``: the
    source got quoted by seq-token substitution, the alias did not, and DuckDB reads
    the hyphen as minus. Such a query is unparseable by construction, so the repair has
    to be textual — no parser can name the alias of a statement it cannot parse.

    Textual is also what made the previous version dangerous. It rewrote EVERY query,
    and ``AS`` is not only a column alias: it also introduces table aliases with a
    column list and parameterised cast types. :data:`_AS_ALIAS` halts at a comma but
    not at an opening paren, so ``AS t(int_start, int_end, period)`` yielded the
    candidate ``t(int_start``, which holds a paren, fails the bare-identifier test, and
    got quoted into ``AS "t(int_start", int_end, period)``. Correct SQL became a parse
    error — the same one on every retry, so no amount of re-planning could escape it,
    and the model was blamed for a query it had written correctly. One such node cost a
    delta run two downstream nodes and eleven already-finished artifacts, because a
    delta commits all-or-nothing. ``CAST(x AS DECIMAL(10, 2))`` broke the same way.

    Hence two gates. A query DuckDB can already read is returned untouched, which
    retires that entire class of damage: nothing valid is ever rewritten again. A query
    it cannot read is repaired only if the repair verifiably parses, so a guess that
    did not help is discarded and the model sees the error in its own SQL rather than
    in our edit of it.
    """
    if not sql or _sql_parses(sql) is not False:
        return sql
    candidate = _requote_aliases(sql)
    if candidate == sql or _sql_parses(candidate) is not True:
        return sql
    logger.info(
        "[seer] repaired unquoted SQL alias(es) — query did not parse, rewrite does"
    )
    return candidate


# ---------------------------------------------------------------------------
# Pipeline operations (the Kedro node vocabulary)
# ---------------------------------------------------------------------------
# Each op builder returns the SELECT body for the node's output. The runner
# registers it as ``CREATE OR REPLACE VIEW <output> AS <select>``.

def _op_filter(inputs: List[str], params: Dict[str, Any]) -> str:
    where = (params or {}).get("where", "").strip()
    if not where:
        raise ValueError("filter requires params.where")
    return f"SELECT * FROM {_q(inputs[0])} WHERE {where}"


def _op_aggregate(inputs: List[str], params: Dict[str, Any]) -> str:
    p = params or {}
    metrics = p.get("metrics") or [{"expr": "COUNT(*)", "alias": "n"}]
    group_by = p.get("group_by") or []
    select_terms: List[str] = []
    for col in group_by:
        # No self-alias: "col AS col" makes DuckDB treat GROUP BY as an alias ref.
        select_terms.append(_q(col))
    for m in metrics:
        expr = str(m.get("expr", "COUNT(*)")).strip()
        alias = str(m.get("alias", "value")).strip()
        select_terms.append(f"{expr} AS {_q(alias)}")
    sql = f"SELECT {', '.join(select_terms)} FROM {_q(inputs[0])}"
    where = str(p.get("where", "")).strip()
    if where:
        sql += f" WHERE {where}"
    if group_by:
        sql += " GROUP BY " + ", ".join(_q(c) for c in group_by)
    order_by = str(p.get("order_by", "")).strip()
    if order_by:
        sql += f" ORDER BY {order_by}"
    limit = p.get("limit")
    if isinstance(limit, int) and limit > 0:
        sql += f" LIMIT {limit}"
    return sql


def _op_value_counts(inputs: List[str], params: Dict[str, Any]) -> str:
    p = params or {}
    col = str(p.get("column", "")).strip()
    if not col:
        raise ValueError("value_counts requires params.column")
    top_n = int(p.get("top_n", 20) or 20)
    return (
        f"SELECT {_q(col)}, COUNT(*) AS n "
        f"FROM {_q(inputs[0])} GROUP BY {_q(col)} ORDER BY n DESC LIMIT {top_n}"
    )


def _op_describe(inputs: List[str], params: Dict[str, Any]) -> str:
    p = params or {}
    cols = p.get("columns") or []
    if not cols:
        raise ValueError("describe requires params.columns")
    unions: List[str] = []
    for c in cols:
        qc = _q(c)
        unions.append(
            "SELECT '" + _bare(c).replace("'", "''") + "' AS column, "
            f"COUNT({qc}) AS non_null, "
            f"COUNT(*) - COUNT({qc}) AS nulls, "
            f"MIN(TRY_CAST({qc} AS DOUBLE)) AS min, "
            f"MAX(TRY_CAST({qc} AS DOUBLE)) AS max, "
            f"AVG(TRY_CAST({qc} AS DOUBLE)) AS mean, "
            f"MEDIAN(TRY_CAST({qc} AS DOUBLE)) AS median "
            f"FROM {_q(inputs[0])}"
        )
    return " UNION ALL ".join(unions)


# An input reference inside a ``sql`` query: ``{input}`` (the first / only one),
# ``{input0}`` / ``{input1}`` … by position, or ``{input:some_table}`` by name.
_SQL_INPUT_REF = re.compile(r"\{input(?:(\d+)|:\s*([^{}]+?)\s*)?\}")
# Anything ELSE that was clearly MEANT as an input reference ({inputs}, {input 1},
# {INPUT0}, …). Left in place it reaches DuckDB as a syntax error that says nothing
# about placeholders, so we catch the near-miss and name the valid forms instead.
_SQL_INPUT_TYPO = re.compile(r"\{\s*input[^{}]*\}", re.IGNORECASE)


def _op_sql(inputs: List[str], params: Dict[str, Any]) -> str:
    """A single read-only SELECT over this node's input view(s).

    MULTI-INPUT by design: every input the node declares is registered as its own
    view, so one query can JOIN or UNION them — which is what a node that fuses
    several upstream result tables into one paper-style table needs. Address them
    positionally (``{input0}``, ``{input1}``, … in the node's declared order) or by
    name (``{input:cox_os_table}``); ``{input}`` stays shorthand for the first.
    """
    q = str((params or {}).get("query", "")).strip()
    if not q:
        raise ValueError("sql requires params.query")
    views = [str(v) for v in (inputs or ["seer"])]
    by_name = {_bare(v).strip().casefold(): v for v in views}
    forms = ", ".join(f"{{input{i}}}={v}" for i, v in enumerate(views))

    def _resolve(mo: "re.Match[str]") -> str:
        idx, name = mo.group(1), mo.group(2)
        if idx is not None:
            pos = int(idx)
            if pos >= len(views):
                raise ValueError(
                    f"sql query references {{input{pos}}} but this node declares only "
                    f"{len(views)} input(s): {forms}. Add the dataset to the node's "
                    f"inputs or reference an existing one."
                )
            return _q(views[pos])
        if name is not None:
            view = by_name.get(_bare(name).strip().casefold())
            if view is None:
                raise ValueError(
                    f"sql query references {{input:{name}}}, which is not an input of "
                    f"this node. Available: {forms}."
                )
            return _q(view)
        return _q(views[0])

    q = _SQL_INPUT_REF.sub(_resolve, q)
    typo = _SQL_INPUT_TYPO.search(q)
    if typo:
        raise ValueError(
            f"sql query contains an unresolved input placeholder '{typo.group(0)}'. "
            f"Write it as {{input}} (first input), {{input0}}/{{input1}} (by position) "
            f"or {{input:<dataset name>}}. Available: {forms}."
        )
    _assert_read_only(q)
    return _quote_unsafe_as_aliases(q)


SEER_OPS: Dict[str, Callable[[List[str], Dict[str, Any]], str]] = {
    "filter": _op_filter,
    "aggregate": _op_aggregate,
    "value_counts": _op_value_counts,
    "describe": _op_describe,
    "sql": _op_sql,
}


def _build_node_sql(op: str, inputs: List[str], params: Dict[str, Any]) -> str:
    builder = SEER_OPS.get(op)
    if builder is None:
        raise ValueError(f"Unknown op '{op}'. Allowed: {sorted(SEER_OPS)}")
    return builder(inputs or ["seer"], params or {})


# ---------------------------------------------------------------------------
# Pipeline op vocabulary (the SINGLE source of truth the planner sees)
# ---------------------------------------------------------------------------
# The DAG the planner drafts must be assembled from the ops below ONLY. Two
# families:
#   • TRANSFORM ops  → build a DuckDB view (cohort / analysis table). SQL.
#   • ANALYSIS tools → clinically-validated frozen functions (survival, matching,
#     regression). These MUST NOT be re-implemented in SQL by the planner; the
#     executor dispatches them to ``SeerToolbox`` methods.

ANALYSIS_OPS: set = {
    "basic_glm",
    # SURVIVAL analysis (lifelines) — PARQUET wrappers that read the cohort from
    # the node's first input, derive time/event/group columns from it BEFORE the
    # real lifelines call, and export the result table as the node's parquet out.
    # (lifelines.KaplanMeierFitter) survival curve + life-table + PNG figure.
    "kaplan_meier",
    # (lifelines.AalenJohansenFitter) competing-risk cumulative incidence — the
    # correct estimator when patients can die of an unrelated cause (1-KM would
    # overstate the risk). See SeerToolbox.competing_risk_cif.
    "competing_risk_cif",
    # (lifelines.CoxPHFitter) MULTIVARIABLE proportional-hazards regression: one
    # model over all covariates at once (mutually adjusted hazard ratios).
    "cox_ph",
    # (lifelines.CoxPHFitter) UNIVARIATE Cox: a SEPARATE single-covariate model per
    # covariate, stacked into one table — the "one characteristic at a time" column
    # printed beside the multivariable one. cox_ph cannot produce it, since a single
    # fit mutually adjusts every covariate. See SeerToolbox.cox_ph_univariate.
    "cox_ph_univariate",
    # (lifelines.CoxPHFitter) SUBGROUP Cox: SEPARATE exposure-only (or exposure +
    # optional covariates) fits within each level of each subgroup column — the
    # "HR in each subgroup" / Table-5 / forest-plot pattern. Not strata (shared
    # baseline hazard) and not interactions (one model). See
    # SeerToolbox.cox_ph_subgroup.
    "cox_ph_subgroup",
    # (lifelines.CoxTimeVaryingFitter) time-varying Cox on a long/counting-process
    # table (its cohort is a pre-built interval view, bound via `input`).
    "cox_time_varying",
    # (lifelines.statistics.logrank_test) compare survival between two arms.
    "logrank_test",
    # (lifelines proportional_hazard_test) Schoenfeld PH-assumption check for a Cox
    # model. See SeerToolbox.cox_ph_assumptions.
    "cox_ph_assumptions",
    # Active frozen analysis tools.
    # (psmpy) propensity-score matching. See SeerToolbox.propensity_score_match.
    "propensity_score_match",
    # Multi-arm (K≥3) 1:1:…:1 PSM (multinomial PS, Rassen-style K-tuples).
    # See SeerToolbox.propensity_score_match_multi.
    "propensity_score_match_multi",
    # (iptw-survival) inverse-probability-of-treatment / overlap weighting: keeps
    # the WHOLE cohort and re-weights it instead of discarding unmatched patients.
    # See SeerToolbox.iptw_weight.
    "iptw_weight",
    # (iptw-survival) weighted KM curves with bootstrap CIs. See
    # SeerToolbox.iptw_kaplan_meier.
    "iptw_kaplan_meier",
    # (iptw-survival) weighted survival probability / RMST / median + between-arm
    # differences. See SeerToolbox.iptw_survival_metrics.
    "iptw_survival_metrics",
    # (scipy.stats.mannwhitneyu). See SeerToolbox.mann_whitney_u.
    "mann_whitney_u",
    # (scipy.stats.chi2_contingency). See SeerToolbox.chi2_contingency.
    "chi2_contingency",
    # (statsmodels.Logit) multivariable logistic regression (OR + 95% CI).
    # See SeerToolbox.logistic_regression.
    "logistic_regression",
    # (statsmodels.GLM) the regression for outcomes that are NOT a binary event:
    # Poisson / negative-binomial rates (with a person-time offset), gamma costs,
    # gaussian means — plus weighted outcome models over an iptw / overlap_weight
    # column. Checks the design matrix rank before fitting, so a redundant
    # covariate is an actionable error instead of a pseudo-inverse fit whose
    # coefficients are not uniquely determined. See SeerToolbox.glm_regression.
    "glm_regression",
    # --- CAUSAL INFERENCE ---------------------------------------------------------
    # Each tool comes as a SINGLE version (one spec → one answer) and, where the
    # protocol repeats the same operation along an axis, a LOOP version that takes
    # the axis as a list parameter and stacks the results into one table. Never
    # emit N sibling nodes for N methods/specs/scenarios — bind the loop tool once.
    #
    # The family is chosen by ESTIMAND, not by convenience: att_* answers "what did
    # treatment do to the people who got it" (standardized to the treated), ate_*
    # answers "what would it do to everyone" (standardized to the whole cohort, or
    # to the overlap population with estimand="ato"). They are different numbers
    # whenever the effect varies across patients, so the request decides which.
    #
    # (sklearn) ATT propensity weights + common-support flag on the FULL cohort.
    # See SeerToolbox.att_weight.
    "att_weight",
    # (sklearn) ONE ATT estimate (mu0 / mu1 / difference) by ONE method.
    # See SeerToolbox.att_estimate.
    "att_estimate",
    # LOOP over `methods` (ipw / gcomp / psm / aipw) → one row per method.
    # See SeerToolbox.att_estimate_multi.
    "att_estimate_multi",
    # LOOP over `specifications` (each a full re-estimation under a different
    # analytic choice) → one row per specification. See SeerToolbox.att_sensitivity.
    "att_sensitivity",
    # (sklearn) ATE / ATO propensity weights on the FULL cohort — the population
    # sibling of att_weight, on the same propensity fit the ate_* estimators use.
    # See SeerToolbox.ate_weight.
    "ate_weight",
    # (sklearn) ONE ATE (or ATO) estimate by ONE method. `psm` is NOT available:
    # matching without replacement only identifies the ATT.
    # See SeerToolbox.ate_estimate.
    "ate_estimate",
    # LOOP over `methods` (ipw / gcomp / aipw) → one row per method.
    # See SeerToolbox.ate_estimate_multi.
    "ate_estimate_multi",
    # LOOP over `specifications` → one row per analytic choice.
    # See SeerToolbox.ate_sensitivity.
    "ate_sensitivity",
    # Absolute standardized differences for ONE population/weighting.
    # See SeerToolbox.covariate_balance.
    "covariate_balance",
    # LOOP over `scenarios` (unweighted / weighted / trimmed …) → stacked ASD table.
    # See SeerToolbox.covariate_balance_multi.
    "covariate_balance_multi",
    # E-value for ONE effect estimate (unmeasured-confounding threshold).
    # See SeerToolbox.evalue.
    "evalue",
    # LOOP over bias `scenarios` (Ding & VanderWeele bounding factor) → tipping
    # point for an unmeasured confounder. See SeerToolbox.bias_sensitivity.
    "bias_sensitivity",
    # (sklearn IterativeImputer) chained-equations imputation; `n_imputations`>1
    # stacks m completed copies of the SAME patients with an `_imputation` index —
    # m× the ROWS, not m× the patients. The estimators above (att_*, cox_*,
    # covariate_balance*, table1) detect that index and do mice's with()/pool()
    # internally (estimate inside each draw, combine by Rubin's rules, report
    # patient counts), so no node splits or averages the
    # stack by hand. A codegen `sql` node reading it MUST group by the index or
    # filter to one draw. See SeerToolbox.impute_missing.
    "impute_missing",
    # --- PROGNOSTIC MODELS (published calculators, nothing fitted here) ----------
    # PREDICT Breast v2.1 (Wishart et al.), ported from CRAN `nhs.predict` 1.4.0
    # and pinned to it by golden-case tests. Scores EVERY patient in the cohort:
    # `year`-year overall survival plus the INCREMENTAL benefit of hormone /
    # chemo / trastuzumab / bisphosphonate, appended to the cohort it read. Not a
    # fit — the coefficients are published, so there is no training arm and no
    # cross-validation. Out-of-domain patients keep a reason instead of vanishing.
    # See SeerToolbox.predict_breast_os + tool/predict_breast.py.
    "predict_breast_os",
    # --- COHORT QC (loop tools) --------------------------------------------------
    # LOOP over `steps` → CONSORT-style inclusion/exclusion flow table.
    # See SeerToolbox.attrition_table.
    "attrition_table",
    # LOOP over `columns` (+ optional `date_order` rules) → missingness / temporal
    # consistency report. See SeerToolbox.data_quality.
    "data_quality",
    # --- MODELING (scikit-learn prediction models) -------------------------------
    # Linear classifiers — first-class FIT tools (sklearn.linear_model). Each
    # writes the input cohort plus a score column; evaluation tools read that
    # column and must not refit. See SeerToolbox._fit_sklearn_linear.
    "LogisticRegression",
    "LogisticRegressionCV",
    "PassiveAggressiveClassifier",
    "Perceptron",
    "RidgeClassifier",
    "RidgeClassifierCV",
    "SGDClassifier",
    "SGDOneClassSVM",
    # SVM / tree / boosting — same FIT-once scored-dataset contract.
    "SVC",
    "LinearSVC",
    "NuSVC",
    "DecisionTreeClassifier",
    "ExtraTreeClassifier",
    "RandomForestClassifier",
    "ExtraTreesClassifier",
    "AdaBoostClassifier",
    "GradientBoostingClassifier",
    "HistGradientBoostingClassifier",
    # Eval tools READ predicted_probability from an upstream model node.
    # They never fit. See SeerToolbox._ml_read_scores.
    "ml_classifier_performance",
    "ml_roc_curve",
    "ml_calibration_curve",
    "ml_decision_curve",
    "ml_reclassification",
    # (sklearn.model_selection.train_test_split) tag each row train/test.
    # See SeerToolbox.ml_train_test_split.
    "ml_train_test_split",
    # Learning procedures: refit each fold from a model key. Not "eval a fit".
    "ml_cv_performance",
    "ml_compare",
    # (tableone.TableOne) baseline-characteristics "Table 1". See SeerToolbox.table1.
    "table1",
}

# Every op the planner is allowed to emit as a node.
PIPELINE_OPS: set = set(ANALYSIS_OPS)

# Run-scoped ops that are NOT part of the fixed toolbox: the planner may emit
# them, but their implementation is vibe-coded per run (see the codegen step) and
# never registered in SEER_OPS / ANALYSIS_OPS / tool_desc. ``custom_format`` is a
# one-off formatting/assembly tool: it gathers earlier step outputs and reshapes
# them into a final custom table via LLM-generated code executed in a restricted
# namespace. Allowed by the planner filter, dispatched by ``execute_step``.
RUNTIME_OPS: set = {"custom_format"}

# CODEGEN-BACKED ops: named in the catalog like any other tool — so the DAG can
# select them deliberately — but IMPLEMENTED by the codegen step rather than by a
# fixed function here. ``viz`` is the figure op: it replaces the frozen plotly_* /
# mpl_* / forest_plot wrappers (dormant in ANALYSIS_OPS) with plotting code written
# per figure against a whitelisted library set, which is the only way to get the
# multi-panel / annotated / faceted figures papers actually print.
#
# They never reach ``execute_step``: the agent routes them to its own codegen path
# (see ``tool_desc.is_codegen_backed`` and ``6_execute_node``).
CODEGEN_OPS: set = set()

# Every op the planner may emit (fixed toolbox + codegen-backed + run-scoped).
ALLOWED_PLAN_OPS: set = PIPELINE_OPS | CODEGEN_OPS | RUNTIME_OPS

# ---------------------------------------------------------------------------
# Tool categories (Stage-1 shortlist vocabulary)
# ---------------------------------------------------------------------------
# The planner is fronted by a lightweight "select tools" stage that picks the
# CATEGORIES relevant to the study. ``render_tool_index()`` renders these for the
# selector; ``render_pipeline_tool_catalog(categories=…)`` biases the DAG prompt
# toward the picked categories.
_SURVIVAL_OPS: set = {
    "kaplan_meier", "cox_ph", "cox_ph_univariate", "cox_ph_subgroup",
    "cox_time_varying", "logrank_test",
    "cox_ph_assumptions", "iptw_kaplan_meier", "iptw_survival_metrics",
    "competing_risk_cif",
}
_STATS_OPS: set = {
    "propensity_score_match", "propensity_score_match_multi", "iptw_weight",
    "mann_whitney_u", "chi2_contingency",
    "logistic_regression", "glm_regression",
    "att_weight", "att_estimate", "att_estimate_multi", "att_sensitivity",
    "ate_weight", "ate_estimate", "ate_estimate_multi", "ate_sensitivity",
    "covariate_balance", "covariate_balance_multi",
    "evalue", "bias_sensitivity", "impute_missing",
}
_SKLEARN_LINEAR_CLF_OPS: set = {
    "LogisticRegression", "LogisticRegressionCV",
    "PassiveAggressiveClassifier", "Perceptron",
    "RidgeClassifier", "RidgeClassifierCV",
    "SGDClassifier", "SGDOneClassSVM",
}
_SKLEARN_SVM_OPS: set = {"SVC", "LinearSVC", "NuSVC"}
_SKLEARN_TREE_OPS: set = {
    "DecisionTreeClassifier", "ExtraTreeClassifier",
    "RandomForestClassifier", "ExtraTreesClassifier",
}
_SKLEARN_BOOST_OPS: set = {
    "AdaBoostClassifier", "GradientBoostingClassifier",
    "HistGradientBoostingClassifier",
}
_MODELING_OPS: set = {
    *_SKLEARN_LINEAR_CLF_OPS,
    *_SKLEARN_SVM_OPS, *_SKLEARN_TREE_OPS, *_SKLEARN_BOOST_OPS,
    "ml_classifier_performance", "ml_roc_curve",
    "ml_calibration_curve", "ml_decision_curve", "ml_reclassification",
    "ml_train_test_split", "ml_cv_performance", "ml_compare",
    # Published calculators score the cohort without fitting anything on it, so
    # they sit beside the fitted models rather than in their own category: the
    # eval tools above are exactly what an external-validation study needs next.
    "predict_breast_os",
}
_DESCRIPTIVE_OPS: set = {"table1", "attrition_table", "data_quality"}

TOOL_CATEGORIES: Dict[str, set] = {
    "descriptive": _DESCRIPTIVE_OPS,            # baseline-characteristics Table 1 (tableone)
    "statistics": _STATS_OPS,                   # PSM + hypothesis tests
    "survival": _SURVIVAL_OPS,                  # KM / Cox / log-rank
    "modeling": _MODELING_OPS,                  # sklearn prediction models + eval
}

_TOOL_CATEGORY_DESC: Dict[str, str] = {
    "descriptive": "Baseline-characteristics \"Table 1\" with per-group p-values / "
                   "SMD (tableone), CONSORT attrition flow and data-quality "
                   "(missingness / temporal order) reports.",
    "statistics": "Confounding adjustment (propensity-score matching, IPTW / "
                  "overlap and ATT weighting), causal effect estimation for the "
                  "ATT (att_*) or the ATE / ATO (ate_*) by IPW / g-computation / "
                  "matching / doubly-robust AIPW, with method and "
                  "specification sweeps, covariate balance, unmeasured-confounding "
                  "bias analysis, imputation, and hypothesis tests (Mann-Whitney U, "
                  "chi-square, logistic regression).",
    "survival": "Time-to-event analysis (Kaplan-Meier, log-rank, Cox PH, "
                "time-varying Cox, IPTW-adjusted KM / RMST, competing-risk CIF).",
    "modeling": "Three layers. Model tools FIT once and write predicted_probability "
                "on a scored dataset. Evaluation tools READ that column only (no fit). "
                "ml_cv_performance / ml_compare refit each fold from a model key. "
                "Also holds the PUBLISHED calculators (predict_breast_os), which "
                "score every patient from fixed coefficients — no fit, no split.",
}


def render_tool_index() -> str:
    """Compact category index for the Stage-1 tool selector: one line per
    category with a short description and its tool names."""
    lines: List[str] = ["Available tool categories (pick the relevant ones):"]
    for cat in ("descriptive", "statistics", "survival", "modeling"):
        ops = sorted(TOOL_CATEGORIES.get(cat) or [])
        desc = _TOOL_CATEGORY_DESC.get(cat, "")
        lines.append(f"- {cat}: {desc}")
        lines.append(f"    tools: {', '.join(ops)}")
    return "\n".join(lines)

# Hand-authored input/output specs live in tool_desc/seer_pipeline_ops.py and
# tool_desc/seer_wrappers.py (same shape as required_parameters + output_schema).
_SEER_TOOL_DESC_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def load_seer_tool_specs() -> Dict[str, Dict[str, Any]]:
    """Load SEER pipeline + wrapper tool specs from tool_desc (name → spec dict).

    Each spec has ``required_parameters``, ``optional_parameters``, and
    ``output_schema`` documenting the Parquet / DuckDB view the node produces.
    Cached for the process lifetime.
    """
    global _SEER_TOOL_DESC_CACHE
    if _SEER_TOOL_DESC_CACHE is not None:
        return _SEER_TOOL_DESC_CACHE
    specs: Dict[str, Dict[str, Any]] = {}
    base = "multi_agents.seer_agent.tool_hub.tool_desc"
    for mod in ("seer_pipeline_ops", "seer_wrappers"):
        try:
            m = importlib.import_module(f"{base}.{mod}")
        except ModuleNotFoundError:
            continue
        for sc in getattr(m, "description", []):
            name = str(sc.get("name") or "").strip()
            if name:
                specs[name] = sc
    _SEER_TOOL_DESC_CACHE = specs
    return specs


def get_output_schema(op: str) -> Optional[Dict[str, Any]]:
    """Return the ``output_schema`` block for a pipeline op, or None.

    Prefers the analysis catalog in ``tool.tool_desc`` (the contract decompose
    / plan actually bind against). Falls back to the legacy seer_agent specs
    when that module has no entry.
    """
    try:
        from tool import tool_desc as _td

        schema = _td.get_output_schema(op)
        if schema:
            return schema
    except Exception:
        pass
    # The provided sample is a package named tool_sample, not production's tool.
    try:
        from . import tool_desc as _local_td
        schema = _local_td.get_output_schema(op)
        if schema:
            return schema
    except ImportError:
        pass
    return (load_seer_tool_specs().get(op) or {}).get("output_schema")


_TOOL_PARAM_SCHEMA_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def tool_param_schemas() -> Dict[str, Dict[str, Any]]:
    """Per-tool JSON schema (name → {description, parameters}) with PARAM-level docs.

    Extracted from :meth:`SeerToolbox.specs` WITHOUT opening a DuckDB connection —
    ``object.__new__`` skips ``__init__`` and ``specs`` only reads bound-method
    references + literal dicts. This lets the plan / tool-params authors see each
    parameter's real description (e.g. "treatment_values = value(s) that mark the
    TREATED arm", "covariates = baseline adjustment variables") instead of only
    tool_desc's terse one-line signature. Cached for the process lifetime.
    """
    global _TOOL_PARAM_SCHEMA_CACHE
    if _TOOL_PARAM_SCHEMA_CACHE is not None:
        return _TOOL_PARAM_SCHEMA_CACHE
    out: Dict[str, Dict[str, Any]] = {}
    try:
        stub = object.__new__(SeerToolbox)  # no __init__ → no connection needed
        for sc in stub.specs():
            nm = str(sc.get("name") or "").strip()
            if nm:
                out[nm] = {
                    "description": sc.get("description"),
                    "parameters": sc.get("parameters"),
                }
    except Exception as e:  # pragma: no cover — degrade to no detail
        logger.debug("tool_param_schemas extraction failed: %s", e)
        out = {}
    _TOOL_PARAM_SCHEMA_CACHE = out
    return out


def render_tool_param_details(op: str) -> str:
    """Render an op's PARAM-level schema (type · required · description) for prompts.

    Returns ``""`` when the op has no JSON schema (e.g. SQL transform ops that are
    built from a ``column_plan`` instead), so callers can append it unconditionally.
    """
    sc = tool_param_schemas().get(str(op or "").strip())
    if not sc:
        return ""
    params = sc.get("parameters") or {}
    props = params.get("properties") or {}
    if not isinstance(props, dict) or not props:
        return ""
    required = set(params.get("required") or [])
    lines: List[str] = []
    for pname, pinfo in props.items():
        if not isinstance(pinfo, dict):
            continue
        ptype = pinfo.get("type", "any")
        if ptype == "array" and isinstance(pinfo.get("items"), dict):
            item_t = pinfo["items"].get("type")
            ptype = f"array[{item_t}]" if item_t else "array"
        req = "required" if pname in required else "optional"
        desc = " ".join(str(pinfo.get("description") or "").split())
        lines.append(f"    - {pname} ({ptype}, {req}): {desc}".rstrip())
    return "  param details (from tool schema):\n" + "\n".join(lines)


def _format_output_schema_catalog() -> str:
    """Compact per-op OUTPUT SCHEMA section for the planner (from tool_desc).

    Returns ``""`` when no per-op output schemas are available, so the section
    header never reaches a prompt with nothing under it. ``tool_desc``'s
    ``output_type`` (dataset | table | figure) already rides along on every line
    of the compact catalog, which is what the planner actually binds against.
    """
    try:
        from tool import tool_desc as _td
    except Exception:
        _td = None
    names = []
    if _td is not None:
        names = [n for n in _td.list_tool_names() if _td.get_output_schema(n)]
    if not names:
        specs = load_seer_tool_specs()
        names = [op for op in sorted(PIPELINE_OPS) if (specs.get(op) or {}).get("output_schema")]
        if not names:
            return ""
    lines = [
        "OUTPUT SCHEMA (each node's `output` dataset — from tool_desc):",
        "Analysis tools write a single Parquet file (parquet-out); transforms register",
        "a DuckDB view (persisted as Parquet after verify when small enough).",
        "Wire viz.inputs to the producer table that already holds the plotted column",
        "(SMD / asd / effect / hazard_ratio) — never the raw cohort.\n",
    ]
    for op in names:
        if _td is not None:
            block = _td.render_output_schema(op, indent="      ")
            if block:
                lines.append(f"  • {op}")
                lines.append(block)
                lines.append("")
            continue
        out = (load_seer_tool_specs().get(op) or {}).get("output_schema") or {}
        fmt = out.get("format", "?")
        card = out.get("cardinality", "?")
        lines.append(f"  • {op}  [{fmt}, {card}]")
        if out.get("inherits_input_columns"):
            lines.append("      columns: all input columns (row subset)")
        for col in out.get("columns") or []:
            lines.append(
                f"      - {col.get('name', '?')} ({col.get('type', '?')}): "
                f"{(col.get('description') or '')[:120]}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def render_pipeline_tool_catalog(
    categories: Optional[Iterable[str]] = None,
    *,
    include_node_schema: bool = True,
) -> str:
    """Return the op/tool catalog the planner MUST build the DAG from.

    Generated from the live op registry (``SEER_OPS`` + ``ANALYSIS_OPS``) so the
    prompt never drifts from what the executor can actually run. When
    ``categories`` is supplied (Stage-1 shortlist), a directive is prepended so
    the planner prefers tools from those categories.

    Set ``include_node_schema=False`` to emit the op documentation ALONE. The
    node JSON shape below belongs to whichever prompt embeds this catalog, and
    prompts that declare their own (e.g. the decomposer's
    ``node``/``outputs``/``output_type`` matrix) must not receive a second,
    conflicting definition.
    """
    schema = (
        "Every node uses one op below and nothing else. A node is:\n"
        '  {"name","op","inputs":["<dataset>"],"output","params":{...},"purpose"}\n'
        '"inputs" defaults to ["seer"] (the raw SEER table). A node\'s "output" is a\n'
        "dataset name that later nodes may list in their own \"inputs\".\n\n"
    )
    body = (
        (schema if include_node_schema else "")
        + "FROZEN ANALYSIS tools — clinically validated wrappers. For statistical\n"
        "testing you MUST use these; NEVER hand-write the test in SQL. Each reads\n"
        "its cohort from the node's FIRST input:\n"
        '  • propensity_score_match {"treatment_column","treatment_values":[...],"covariates":[...],\n'
        '                      "where"?,"caliper"?:0.2,"ratio"?:1}\n'
        "        → Propensity-score matching for causal treatment comparisons. The wrapper\n"
        '          pulls the parquet cohort, one-hot encodes the categorical "covariates", fits a\n'
        '          logistic PS model, then greedily matches each treated patient ("treatment_column"\n'
        '          IN "treatment_values") to its nearest unused control on the PS logit, without\n'
        '          replacement, 1:"ratio", within "caliper"×SD(logit) (default 0.2, Austin).\n'
        "          Treated patients with no control inside the caliper are dropped.\n"
        "          Its OUTPUT is the matched patient COHORT (all input columns + a `_treat` flag) —\n"
        "          a real dataset a downstream tool/transform can consume; covariate balance\n"
        "          (standardized mean differences before/after) is surfaced as its deliverable.\n"
        "          Use to build a balanced cohort BEFORE comparing outcomes across arms.\n"
        "          TWO arms only — for 3+ arms use propensity_score_match_multi.\n"
        '  • propensity_score_match_multi {"treatment_column","arms":[A,B,C,…],"covariates":[...],\n'
        '                      "exact_columns"?:[...],"tolerance_columns"?:{col:tol}|[{column,tolerance}],\n'
        '                      "where"?,"caliper"?:0.6}\n'
        "        → Multi-arm (K≥3) 1:1:…:1 propensity-score matching (Rassen et al.). Fits a\n"
        '          multinomial logistic GPS for "treatment_column" across ordered "arms", then\n'
        "          greedily forms K-tuples by Euclidean GPS-vector distance with component-wise\n"
        '          logit calipers ("caliper"×SD of logit P(arm) within that arm; default 0.6).\n'
        '          Optional "exact_columns" are hard strata; "tolerance_columns" (e.g. age±2,\n'
        "          year±2) constrain every pair in a tuple. OUTPUT is the matched cohort\n"
        "          (equal n per arm + `_arm` 0..K-1); pairwise SMD before/after is the deliverable.\n"
        '  • iptw_weight      {"treatment_column","treatment_values":[...],"covariates":[...],\n'
        '                      "cont_var"?:[...],"where"?,"weight_type"?:"iptw"|"overlap",\n'
        '                      "stabilized"?:true,"clip_bounds"?:[0.01,0.99]}\n'
        "        → Inverse-probability-of-treatment weighting (iptw-survival). Same goal as\n"
        "          propensity_score_match, but it KEEPS every patient and attaches a weight\n"
        '          instead of discarding the unmatched — so the estimand is the population\n'
        '          ATE (or ATO with "overlap"). Its OUTPUT is the full cohort + a\n'
        "          `propensity_score` and `iptw` column; SMD balance before/after weighting is\n"
        "          the deliverable. Prefer it over matching when the paper reports IPTW/\n"
        "          weighted analyses or when losing unmatched patients would shrink the cohort.\n"
        '  • iptw_kaplan_meier {"treatment_column","treatment_values":[...],"duration_column",\n'
        '                      "event_column","event_values":[...],"covariates":[...],\n'
        '                      "cont_var"?:[...],"where"?,"n_bootstrap"?:200}\n'
        "        → IPTW-adjusted KM curves with bootstrapped 95% CIs. Use INSTEAD of\n"
        "          kaplan_meier when the arms must be confounder-adjusted. It does its own\n"
        "          weighting, so give it the UNWEIGHTED cohort.\n"
        '  • iptw_survival_metrics {"treatment_column","treatment_values":[...],"duration_column",\n'
        '                      "event_column","event_values":[...],"covariates":[...],\n'
        '                      "psurv_time_points"?:[60],"rmst_time_points"?:[60],\n'
        '                      "median_time"?:true,"where"?,"n_bootstrap"?:200}\n'
        "        → Adjusted survival probability at fixed timepoints, RMST and median, each\n"
        "          with a bootstrap CI, PLUS the treated-minus-control difference — the\n"
        "          absolute risk difference a hazard ratio cannot give. Use for questions like\n"
        '          "adjusted 5-year survival and the absolute benefit". Also does its own\n'
        "          weighting.\n"
        '  • mann_whitney_u   {"value_column","group_column","group_values"?:[A,B],"where"?,\n'
        '                      "alternative"?:"two-sided"|"less"|"greater","method"?:"auto"|"asymptotic"|"exact"}\n'
        "        → Mann-Whitney U rank test (scipy.stats.mannwhitneyu) comparing the numeric\n"
        '          "value_column" between the two arms of "group_column". The wrapper pulls the\n'
        "          parquet cohort, splits it into the two samples, then runs the test; it returns a\n"
        "          one-row table (per-arm n + median, U statistic, p-value). If \"group_column\" has\n"
        '          more than two labels, name the two arms with "group_values":["A","B"].\n'
        '  • chi2_contingency {"row_column","col_column","row_values"?:[...],"col_values"?:[...],\n'
        '                      "where"?,"correction"?:true,"lambda_"?}\n'
        "        → Chi-square test of independence (scipy.stats.chi2_contingency) between two\n"
        '          CATEGORICAL columns. The wrapper cross-tabulates "row_column" × "col_column" into\n'
        "          the R×C contingency table, then runs the test; it returns a one-row table (table\n"
        "          dims + N, chi2, dof, p-value, Cramér's V). Use for categorical vs. categorical\n"
        "          association (e.g. treatment received vs. tumor grade). NOT for numeric comparisons.\n"
        '  • logistic_regression {"outcome_column","outcome_values":[...],"covariates":[...],"where"?,\n'
        '                      "reference_levels"?:{"<col>":"<baseline level>"}}\n'
        "        → Multivariable logistic regression (statsmodels.Logit). Models a BINARY outcome\n"
        '          (1 if "outcome_column" ∈ "outcome_values") on "covariates" (categoricals one-hot\n'
        "          encoded, drop-first) with an intercept. Returns an ODDS-RATIO table (covariate,\n"
        "          level_type, coef, odds_ratio=exp(coef), or_lower95, or_upper95, z, p), including a\n"
        "          level_type='reference' row (OR=1.0) per categorical naming its baseline. Use for a\n"
        "          Table 2-style \"predictors of receiving treatment / of an outcome\" model. NOT for\n"
        "          time-to-event (use cox_ph) and NOT for a simple 2×2 association (chi2_contingency).\n"
        '          → Set "reference_levels" whenever the request names a reference/baseline category\n'
        "            (e.g. {\"Race recode\":\"Black\"}); otherwise the baseline is whichever level sorts\n"
        "            first and every OR answers a different question.\n"
        '  • table1          {"columns":[...],"groupby"?,"categorical"?:[...],"nonnormal"?:[...],\n'
        '                      "order"?:{"col":[labels]},"rename"?:{"col":"Label"},"limit"?:{"col":n},\n'
        '                      "decimals"?:{"col":n},"pval"?:true,"smd"?:true,"missing"?:true,\n'
        '                      "overall"?:true,"where"?}\n'
        '        → Baseline-characteristics "Table 1" (the `tableone` library). Summarizes the\n'
        '          "columns" across the cohort and, when "groupby" is given, per group WITH per-\n'
        '          variable p-values ("pval") and standardized mean differences ("smd"). Mark\n'
        '          categorical vars in "categorical" and skewed continuous vars in "nonnormal"\n'
        "          (reported as median [IQR] instead of mean (SD)). OUTPUT is the formatted Table 1\n"
        "          as a tidy table. Use for the standard baseline/demographics table of a study;\n"
        "          feed it a cohort whose columns already hold the display values.\n\n"
        "MODELING — three layers. Model tools FIT once and write `predicted_probability`\n"
        "on a scored dataset. Evaluation tools READ that column and NEVER fit.\n"
        "ml_cv_performance / ml_compare are the only tools that keep a model key:\n"
        "they refit each fold on purpose.\n"
        "  • Model tools (output_type=dataset): LogisticRegression, LogisticRegressionCV,\n"
        "    RandomForestClassifier, GradientBoostingClassifier, and the other sklearn\n"
        "    class-name tools in the catalog. Fit on train when split_column is set;\n"
        "    score EVERY row. Coef/importance is a side table; the node output is the\n"
        "    scored cohort. Distinct from statistics.logistic_regression (odds-ratio table).\n"
        "  • ml_train_test_split — adds a `split` column only. No fitting.\n"
        "  • Eval (input = scored dataset; NO model= / predictors= / hyperparams):\n"
        "    ml_roc_curve, ml_calibration_curve, ml_decision_curve, ml_classifier_performance\n"
        "    (split_column ⇒ test rows only), ml_reclassification (two probability columns\n"
        "    or two scored datasets joined on id_column).\n"
        "  • Learning procedure: ml_cv_performance (one model key + predictors, OOF\n"
        "    metrics) and ml_compare (models[] on the SAME folds).\n"
        "  DAG: cohort → ml_train_test_split → LogisticRegression(split_column=split)\n"
        "       → scored dataset → ml_roc_curve / ml_calibration_curve /\n"
        "         ml_decision_curve / ml_classifier_performance.\n"
        "  NEVER bind model= on an eval tool. NEVER use ml_classifier / ml_predict.\n\n"
        "SURVIVAL analysis tools — clinically validated lifelines wrappers for\n"
        "time-to-event outcomes. NEVER hand-write survival math in SQL; each derives\n"
        "the time/event/group columns from the parquet cohort (the node's FIRST\n"
        "input) BEFORE the real lifelines call:\n"
        '  • kaplan_meier   {"time_column","event_column","event_values":[...],\n'
        '                      "group_by"?:[...],"where"?}\n'
        "        → Kaplan-Meier survival curve (lifelines.KaplanMeierFitter). Derives an event flag\n"
        '          (1 if "event_column" ∈ "event_values", e.g. ["Dead"]) over the follow-up time in\n'
        '          "time_column"; fits one curve per "group_by" combination. OUTPUT is the full\n'
        "          life-table (time_months, n_at_risk, n_events, survival_probability, 95% CI) plus a\n"
        "          step survival-curve PNG figure. Use to show/estimate survival over time.\n"
        '  • competing_risk_cif {"duration_column","event_column","event_values":[...],\n'
        '                      "competing_values":[...],"group_column"?,"cif_time_points"?:[60],\n'
        '                      "weights_column"?,"where"?}\n'
        "        → Competing-risk cumulative incidence (lifelines.AalenJohansenFitter). Use INSTEAD\n"
        "          of kaplan_meier whenever patients can die of an UNRELATED cause: 1-KM counts those\n"
        '          deaths as censoring and overstates the risk. "event_values" = cause of interest,\n'
        '          "competing_values" = the competing cause, everything else censored. OUTPUT is the\n'
        "          tidy CIF table (group, cause, time, cif, 95% CI) + a stepped CIF figure; the CIF at\n"
        '          each "cif_time_points" horizon and the between-group ABSOLUTE RISK DIFFERENCE are\n'
        "          reported too. Typical SEER use: cancer-specific death vs death from other causes.\n"
        '  • logrank_test   {"time_column","event_column","event_values":[...],\n'
        '                      "group_column","group_values"?:[A,B],"where"?,\n'
        '                      "weightings"?:"wilcoxon"|"tarone-ware"|"peto","t_0"?}\n'
        "        → Log-rank test (lifelines.statistics.logrank_test) for whether survival DIFFERS\n"
        '          between the two arms of "group_column". Returns a one-row table (per-arm n +\n'
        "          events, chi-square statistic, dof, p-value). Pair with kaplan_meier to test the\n"
        '          curve separation. If "group_column" has >2 labels, name the two arms via\n'
        '          "group_values":["A","B"].\n'
        '  • cox_ph         {"duration_column","event_column","event_values":[...],\n'
        '                      "covariates":[...],"strata"?:[...],"where"?,"weights_column"?,\n'
        '                      "robust"?,"cluster_column"?,"interactions"?:["A * B"],\n'
        '                      "reference_levels"?:{"<col>":"<baseline level>"},"penalizer"?}\n'
        "        → MULTIVARIABLE Cox proportional-hazards regression (lifelines.CoxPHFitter): ONE\n"
        '          model over ALL "covariates" at once, so every HR is mutually adjusted. Derives\n'
        "          the event flag + duration, one-hot encodes categoricals, fits the model\n"
        '          (optionally "strata"-stratified). Returns a hazard-ratio table (coef, HR=exp(coef),\n'
        "          95% CI, z, p) + concordance, plus a `reference` row per categorical naming its\n"
        "          baseline. Use for MULTIVARIABLE adjusted survival effects.\n"
        '          → Set "reference_levels" whenever the request names a reference/baseline category\n'
        "            (e.g. {\"Race recode\":\"Black\"}). Otherwise the baseline is whichever level sorts\n"
        "            first and every HR answers a different question.\n"
        "          → MISSING DATA is handled by the tool, in EVERY cox_* op: rows missing ANY\n"
        '            covariate are dropped before encoding, and covariate columns that end up\n'
        "            constant or redundant in the surviving cohort are dropped and named in the\n"
        '            summary. Do NOT write "IS NOT NULL" guards into "where" — a hand-written set\n'
        "            that covers some covariates and not others is what empties a category and\n"
        '            leaves an all-zero dummy. Keep "where" for the CLINICAL cohort definition; if\n'
        "            a covariate is too incompletely recorded to lose, impute_missing it first.\n"
        '          → For an IPTW-WEIGHTED Cox, set "weights_column":"iptw" and give the node the\n'
        "            weighted cohort from an iptw_weight step as its input; robust (sandwich)\n"
        '            variance switches on automatically. "cluster_column" gives clustered robust SEs.\n'
        '          → For effect modification add "interactions":["<colA> * <colB>"] (both must also\n'
        "            be in covariates). Each interaction is reported with a JOINT WALD TEST over its\n"
        "            whole block — the only valid p-value when the interaction spans several dummies.\n"
        '          → If the fit fails to converge on a wide one-hot design, set "penalizer":0.1.\n'
        "          → For SEPARATE Cox fits WITHIN each subgroup category (Table 5 / forest of\n"
        '            subgroup HRs), use cox_ph_subgroup — NOT "strata" (baseline only) and NOT\n'
        "            interactions (one shared model).\n"
        '  • cox_ph_univariate {"duration_column","event_column","event_values":[...],\n'
        '                      "covariates":[...],"strata"?:[...],"where"?,"weights_column"?,\n'
        '                      "robust"?,"cluster_column"?,\n'
        '                      "reference_levels"?:{"<col>":"<baseline level>"},"penalizer"?}\n'
        "        → UNIVARIATE Cox: fits ONE SEPARATE single-covariate model per entry in\n"
        '          "covariates" and stacks them into one table — the "univariate / one\n'
        '          characteristic at a time" column that survival papers print beside the\n'
        "          multivariable one. Use THIS, not cox_ph, whenever the request asks for\n"
        "          unadjusted or one-variable-at-a-time hazard ratios: a single cox_ph fit\n"
        "          mutually adjusts every covariate and cannot produce them. ONE node covers\n"
        "          ALL the characteristics — never emit one node per variable.\n"
        "          Returns covariate/term_type/term/coef/se/hazard_ratio/hr_lower95/hr_upper95/\n"
        "          statistic/df/p/n/events, where `covariate` says which model a row came from and\n"
        "          term_type is 'coefficient' (per non-baseline level), 'reference' (that\n"
        "          covariate's baseline, HR=1.0) or 'global_wald' (the ONE p-value for the whole\n"
        "          characteristic — the only valid one when a categorical spans several levels).\n"
        '  • cox_ph_subgroup {"duration_column","event_column","event_values":[...],\n'
        '                      "exposure_column","reference_level"?,"subgroup_columns":[...],\n'
        '                      "include_overall"?:true,"covariates"?:[...],"where"?,\n'
        '                      "weights_column"?,"robust"?,"cluster_column"?,"strata"?:[...],\n'
        '                      "reference_levels"?:{"<col>":"<baseline level>"},"penalizer"?}\n'
        "        → SUBGROUP Cox: SEPARATE exposure models within each level of each\n"
        '          "subgroup_columns" entry (plus an optional Overall row). This is the\n'
        '          "HR for the exposure in every subgroup" / Table-5 / forest-plot pattern.\n'
        "          Wraps the same CoxPHFitter path as cox_ph. Use THIS whenever the request\n"
        "          asks for subgroup-specific HRs from SEPARATE fits — do NOT use cox_ph with\n"
        '          "strata" (only changes the baseline hazard) or "interactions" (one model).\n'
        "          ONE node covers ALL subgroup variables. Returns one stacked table with\n"
        "          subgroup_variable/subgroup_category/n/n_ref/n_exposed/events plus the\n"
        "          exposure HR columns (coef/se/hazard_ratio/hr_lower95/hr_upper95/p/term).\n"
        '  • cox_ph_assumptions {"duration_column","event_column","event_values":[...],\n'
        '                      "covariates":[...],"where"?,\n'
        '                      "reference_levels"?:{"<col>":"<baseline level>"},"penalizer"?}\n'
        "        → Proportional-hazards ASSUMPTION check for a Cox model (lifelines\n"
        "          proportional_hazard_test, scaled Schoenfeld residuals, rank time-transform).\n"
        "          Returns a per-covariate table (test_statistic, p, violates_ph=p<0.05). Use to\n"
        "          verify the PH assumption behind a cox_ph result before trusting its HRs.\n"
        "          → MIRROR the cox_ph node it checks: same covariates, where, reference_levels\n"
        "            and penalizer. The test describes a MODEL, so a different specification\n"
        "            reports the PH verdict of a model nobody published.\n"
        '  • cox_time_varying {"id_column","start_column","stop_column","event_column",\n'
        '                      "covariates":[...],"event_values"?:[...],"where"?}\n'
        "        → Time-varying Cox (lifelines.CoxTimeVaryingFitter). Consumes a LONG/counting-process\n"
        '          table (one row per subject×interval with id/start/stop) — its cohort is bound via\n'
        '          the node\'s first input (build that interval view first, e.g. an sql node). Returns\n'
        "          a hazard-ratio table. Use only when a covariate CHANGES over follow-up.\n\n"
        "RULES:\n"
        "  • Assemble the DAG from the ops above ONLY — unknown ops are rejected.\n"
        "  • Double-quote every column identifier (SEER names contain spaces/slashes).\n"
        "  • Define the cohort in a transform node first (`sql` when the build also recodes\n"
        "    or derives columns, `filter` for a pure row subset), then point the analysis\n"
        "    tool's input at that cohort. Keep transform outputs small (reduce early).\n"
        "  • Most analysis tools are TERMINAL deliverables, but the ones whose output_type is\n"
        "    `dataset` (propensity_score_match, propensity_score_match_multi, iptw_weight,\n"
        "    att_weight, ate_weight, ml_train_test_split, LogisticRegression,\n"
        "    RandomForestClassifier, and the other\n"
        "    sklearn model tools) emit a patient-level COHORT that later nodes consume —\n"
        "    e.g. iptw_weight → cox_ph with weights_column=\"iptw\", or\n"
        "    ml_train_test_split → LogisticRegression(split_column=\"split\") → scored\n"
        "    dataset → ml_roc_curve / ml_classifier_performance (probability column only).\n"
        "    Evaluation tools must NOT bind model= or predictors= — they never fit.\n"
        "  • MULTIPLY IMPUTED input (an impute_missing node with n_imputations>1): its\n"
        "    output holds m completed copies of the SAME patients tagged `_imputation` —\n"
        "    m× the ROWS, not m× the patients. The frozen estimators (att_*, cox_ph,\n"
        "    cox_ph_univariate, cox_ph_subgroup, cox_ph_assumptions, cox_time_varying,\n"
        "    covariate_balance*, table1) detect that column and estimate per draw with\n"
        "    Rubin pooling on their own, so do NOT plan a node to split, average or\n"
        "    de-duplicate the stack. A `sql` node reading it MUST group by `_imputation`\n"
        "    or filter to ONE draw, and a PATIENT count taken from it is\n"
        "    COUNT(DISTINCT <id>) — a raw COUNT(*) is m times the cohort.\n"
        "  • Never let `viz` compute a statistic: put the frozen analysis op upstream and\n"
        "    give its result table to `viz` as an input.\n"
        "  • Read-only: only SELECT. No INSERT/UPDATE/DELETE/CREATE/COPY.\n"
        "  • Every `sql` query is ONE statement — NEVER put a semicolon (';') in a query\n"
        "    (no terminator, no stacked statements). Split work across nodes instead.\n\n"
        + _format_output_schema_catalog()
        + "\n"
    )
    picked = [c for c in (categories or []) if c in TOOL_CATEGORIES]
    if picked:
        focus = list(picked)
        if focus:
            allowed_ops = sorted(set().union(*(TOOL_CATEGORIES[c] for c in focus)))
            directive = (
                "STAGE-1 TOOL SHORTLIST — this study needs these tool categories: "
                + ", ".join(focus) + ".\n"
                "Prefer analysis tools ONLY from: "
                + ", ".join(allowed_ops) + ".\n"
                "Reach for a tool outside the shortlist ONLY if the analysis "
                "clearly requires it.\n\n"
            )
            return directive + body
    return body


# ---------------------------------------------------------------------------
# Execution (sequential DuckDB-view runner)
# ---------------------------------------------------------------------------

def _run_builtin(
    con,
    pipeline_spec: List[Dict[str, Any]],
    progress: Optional[Callable[[str], None]] = None,
) -> None:
    """Sequential runner: register each step's output as a DuckDB view."""
    available = {"seer"} | set(_EXTRA_SOURCES)
    n = len(pipeline_spec)
    for i, spec in enumerate(pipeline_spec, start=1):
        op = spec["op"]
        out = spec["output"]
        inputs = spec.get("inputs") or ["seer"]
        for src in inputs:
            if src not in available:
                raise ValueError(
                    f"Step '{spec.get('name') or out}' references unknown input '{src}'."
                )
        if progress:
            progress(f"Executing step {i}/{n}: {spec.get('name') or out} ({op})")
        select = _build_node_sql(op, inputs, spec.get("params") or {})
        con.execute(f"CREATE OR REPLACE VIEW {_q(out)} AS {select}")
        available.add(out)


def _materialize(con, name: str) -> Dict[str, Any]:
    """Read a (small) view into a preview payload with a hard row cap."""
    try:
        total = con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0]
    except Exception as e:
        return {"name": name, "columns": [], "row_count": 0, "preview": [], "error": str(e)}

    df = con.execute(
        f"SELECT * FROM {_q(name)} LIMIT {MATERIALIZE_ROW_CAP}"
    ).fetchdf()
    preview = df.head(200).to_dict(orient="records")
    # Make values JSON-friendly (numpy/NaN -> native/None).
    for row in preview:
        for k, v in list(row.items()):
            try:
                if v != v:  # NaN
                    row[k] = None
                elif hasattr(v, "item"):
                    row[k] = v.item()
            except Exception:
                row[k] = None if v is None else str(v)
    return {
        "name": name,
        "columns": [str(c) for c in df.columns],
        "row_count": int(total),
        "truncated": int(total) > len(df),
        "preview": preview,
    }


# ---------------------------------------------------------------------------
# Single-step (cursor) execution — the PEV data plane
# ---------------------------------------------------------------------------
# The static P-E-V LangGraph walks the planned DAG one node at a time via a
# cursor. ``execute_step`` runs exactly ONE Kedro node (like
# ``session.run(node_names=[current step])``): it registers the node's DuckDB
# view on the shared (cached) connection and returns a materialized preview.
# Views persist across steps on the cached connection, so a later step can read
# an earlier step's output; ``CREATE OR REPLACE`` makes re-runs (retry/rewind)
# idempotent.

def execute_step(
    parquet_uri: str,
    spec: Dict[str, Any],
    *,
    available: Optional[List[str]] = None,
    user_id: str = "",
    note_id: str = "",
) -> Dict[str, Any]:
    """Execute a single pipeline node and return its materialized output.

    Args:
        parquet_uri: the SEER dataset (resolves to the shared cached connection).
        spec: one pipeline node ``{name, op, inputs, output, params}``.
        available: optional list of dataset names already produced; when given,
            every input is checked against it (``seer`` is always available).
        user_id, note_id: forwarded to frozen analysis tools (figure uploads).

    Returns the ``_materialize`` payload for the node's output view (transform
    ops), or the analysis deliverable payload (frozen analysis ops).

    Raises:
        ValueError: unknown op, missing input, or a bad SQL build.
        Exception: any DuckDB execution error (surfaced to Verify).
    """
    op = str(spec.get("op") or "").strip()
    out = str(spec.get("output") or "").strip()
    name = str(spec.get("name") or out)
    if not op or not out:
        raise ValueError("Step spec requires 'op' and 'output'.")

    # Frozen analysis tools (survival / matching / regression) run through the
    # SeerToolbox, not the SQL builder.
    if op in ANALYSIS_OPS:
        return run_analysis_step(
            parquet_uri, spec, available=available, user_id=user_id, note_id=note_id
        )

    # Run-scoped custom formatting tool: LLM-generated code (attached to the spec
    # as ``generated_code`` by the codegen step) reshapes earlier outputs.
    if op in RUNTIME_OPS:
        return run_custom_format_step(
            parquet_uri, spec, available=available, user_id=user_id, note_id=note_id
        )

    # Codegen-backed ops (`viz`) have no implementation here by design — the agent
    # generates and runs their code itself. Reaching this point means a node was
    # dispatched down the frozen-tool path, which would otherwise fail as an
    # "unknown op" and hide the real mistake.
    if op in CODEGEN_OPS:
        raise ValueError(
            f"Op '{op}' is CODEGEN-BACKED: it has no fixed implementation in the hub "
            f"and must be run through the agent's codegen step (plan → codegen → "
            f"build(inputs)), not dispatched as a frozen tool."
        )

    inputs = spec.get("inputs") or ["seer"]
    params = spec.get("params") or {}

    if available is not None:
        known = set(available) | {"seer"} | set(_EXTRA_SOURCES)
        for src in inputs:
            if src not in known:
                raise ValueError(
                    f"Step '{spec.get('name') or out}' references unknown input "
                    f"'{src}'. Available: {sorted(known)}."
                )

    con = get_seer_connection(parquet_uri)
    # Build the node SQL, logging the exact statement so a failing step is fully
    # reproducible from the terminal (op + params + rendered SELECT).
    try:
        select = _build_node_sql(op, inputs, params)
    except Exception as e:
        logger.warning(
            "[seer] step '%s' SQL BUILD failed: op=%s inputs=%s params=%s → %s",
            name, op, inputs, json.dumps(params, ensure_ascii=False, default=str), e,
        )
        raise
    logger.info(
        "[seer] execute step '%s' (op=%s, inputs=%s, output=%s)\n"
        "         params=%s\n"
        "         SQL: CREATE OR REPLACE VIEW %s AS %s",
        name, op, inputs, out,
        json.dumps(params, ensure_ascii=False, default=str),
        _q(out), select,
    )
    try:
        con.execute(f"CREATE OR REPLACE VIEW {_q(out)} AS {select}")
    except Exception as e:
        logger.warning("[seer] step '%s' SQL EXECUTE failed: %s\n         SQL: %s", name, e, select)
        raise
    result = _materialize(con, out)
    logger.info(
        "[seer] step '%s' output: %s rows, %d col(s)%s",
        name,
        f"{int(result.get('row_count') or 0):,}",
        len(result.get("columns") or []),
        f" — ERROR: {result['error']}" if result.get("error") else "",
    )
    return result


# The tool method name → the parameter it uses to read its cohort/source view.
_ANALYSIS_SOURCE_PARAM: Dict[str, str] = {
    # SURVIVAL analysis (lifelines) — see ANALYSIS_OPS.
    "kaplan_meier": "source",
    "competing_risk_cif": "source",
    "cox_ph": "source",
    "cox_ph_univariate": "source",
    "cox_ph_subgroup": "source",
    "cox_ph_assumptions": "source",
    "cox_time_varying": "input",
    "logrank_test": "source",
    "propensity_score_match": "source",
    "propensity_score_match_multi": "source",
    "iptw_weight": "source",
    "iptw_kaplan_meier": "source",
    "iptw_survival_metrics": "source",
    "mann_whitney_u": "source",
    "chi2_contingency": "source",
    "logistic_regression": "source",
    # CAUSAL (att_* / ate_*) + cohort QC + imputation — every one reads its cohort
    # from the node's first input, exactly like the tools above.
    "att_weight": "source",
    "att_estimate": "source",
    "att_estimate_multi": "source",
    "att_sensitivity": "source",
    "ate_weight": "source",
    "ate_estimate": "source",
    "ate_estimate_multi": "source",
    "ate_sensitivity": "source",
    "covariate_balance": "source",
    "covariate_balance_multi": "source",
    "evalue": "source",
    "bias_sensitivity": "source",
    "impute_missing": "source",
    "predict_breast_os": "source",
    "attrition_table": "source",
    "data_quality": "source",
    "ml_predict": "source",
    "ml_cv_performance": "source",
    "ml_compare": "source",
    "LogisticRegression": "source",
    "LogisticRegressionCV": "source",
    "PassiveAggressiveClassifier": "source",
    "Perceptron": "source",
    "RidgeClassifier": "source",
    "RidgeClassifierCV": "source",
    "SGDClassifier": "source",
    "SGDOneClassSVM": "source",
    "SVC": "source",
    "LinearSVC": "source",
    "NuSVC": "source",
    "DecisionTreeClassifier": "source",
    "ExtraTreeClassifier": "source",
    "RandomForestClassifier": "source",
    "ExtraTreesClassifier": "source",
    "AdaBoostClassifier": "source",
    "GradientBoostingClassifier": "source",
    "HistGradientBoostingClassifier": "source",
    "ml_classifier": "source",
    "ml_classifier_performance": "source",
    "ml_roc_curve": "source",
    "ml_calibration_curve": "source",
    "ml_decision_curve": "source",
    "ml_reclassification": "source",
    "ml_train_test_split": "source",
    "table1": "source",
}

# Prefixes of a tool's return string that signal a soft failure (no exception,
# but the step did not produce a usable result → surface to Verify as an error).
_ANALYSIS_FAILURE_MARKERS: tuple = (
    "error",
    "cohort is empty",
    "no matches",
    "no events",
    "no valid intervals",
    "both treated and control",
)


# Plumbing kwargs a frozen tool needs to run but that are NOT research knobs —
# the cohort source view name and the output label. Kept out of the persisted
# "what did this run with" params so a lookup sees only meaningful settings.
_EFFECTIVE_PARAM_PLUMBING = ("source", "input", "label")


def effective_tool_params(
    method: Any, params: Dict[str, Any], *, drop: "Iterable[str]" = ()
) -> Dict[str, Any]:
    """The kwargs a frozen tool ACTUALLY ran with = caller params + signature defaults.

    The planner authors only the knobs it chose; the tool fills every other
    argument from its own signature default (``n_bootstrap=500``, ``n_bins=10``,
    ``random_state=42``, …). Those defaults never reach the caller's ``params``,
    so a later "what did this step run with" lookup (Dora's ``query_parameters``)
    can't see them. Bind the call against the method signature and materialize the
    missing defaults so the persisted params reflect the real execution.

    ``drop`` removes pure plumbing (cohort source view, output label) that is not a
    research setting. Never raises — an unintrospectable callable degrades to the
    caller params minus ``drop``.
    """
    import inspect as _inspect

    eff = dict(params or {})
    try:
        sig = _inspect.signature(method)
    except (TypeError, ValueError):
        sig = None
    if sig is not None:
        for pname, p in sig.parameters.items():
            if p.kind in (
                _inspect.Parameter.VAR_POSITIONAL,
                _inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            if pname in eff or p.default is _inspect.Parameter.empty:
                continue
            eff[pname] = p.default
    drop_set = set(drop)
    return {k: v for k, v in eff.items() if k not in drop_set}


# 값 하나를 받는다고 **선언한** 어노테이션들. 이 모듈은 ``from __future__ import
# annotations`` 를 쓰므로 시그니처에서 읽히는 것은 타입 객체가 아니라 문자열이다.
_SCALAR_ANNOTATIONS = {
    "str": "a single value (a column name or other string)",
    "int": "a single whole number",
    "float": "a single number",
    "bool": "a single true/false flag",
}


def _scalar_annotation(annotation: Any) -> str:
    """어노테이션이 '값 하나' 를 뜻하면 사람이 읽을 설명, 아니면 ``""``.

    ``Any`` 와 ``List[...]`` 는 뜻이 없다 — ``event_values`` 나 ``group_by`` 처럼
    스칼라와 리스트를 모두 받는 노브가 실제로 있기 때문이다. 확실히 스칼라라고 적힌
    것만 본다.
    """
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    text = str(text).replace(" ", "")
    if text.startswith("Optional[") and text.endswith("]"):
        text = text[len("Optional["):-1]
    text = text.replace("|None", "").replace("None|", "")
    return _SCALAR_ANNOTATIONS.get(text, "")


def scalar_param_violations(method: Any, params: Dict[str, Any]) -> List[str]:
    """스칼라로 선언된 파라미터에 컨테이너가 들어온 자리들 — 고치는 법까지 담은 문장.

    파이썬은 어노테이션을 강제하지 않는다. ``time_column: str`` 에 맵을 넣어도 바인딩은
    멀쩡히 성공하고, 폭발은 툴 **안쪽** 에서 일어난다. 실제로 그렇게 무너진 런이 있다:
    델타가 ``time_column`` 을 ``{"Period_for_KM_DFS": "Period_for_KM_DFS"}`` 로 만들었고,
    KM 은 ``'dict' object has no attribute 'strip'`` 로 죽었다. verify 가 받은 것은
    노브 이름이 없는 파이썬 트레이스백이라 재계획은 어디를 고칠지 알 수 없었고, 그 노드
    하나 때문에 이미 성공한 다섯 노드가 통째로 버려졌다.

    그러니 값을 **고쳐 주지는** 않는다. ``{"col51": "col51"}`` 에서 키를 꺼낼지 값을
    꺼낼지 추측하는 순간, ``{"col51": "col49"}`` 였다면 조용히 틀린 곡선이 나온다.
    대신 어디가 왜 틀렸고 무엇을 보내야 하는지를 말하고 멈춘다 — 그 문장이 그대로
    재계획의 입력이 된다.

    후보가 하나뿐이면 그 값을 집어서 보여 준다. 우리가 고르는 것이 아니라 다음 시도가
    베껴 쓸 수 있게 하는 것이다.
    """
    import inspect as _inspect

    try:
        sig = _inspect.signature(method)
    except (TypeError, ValueError):  # 내성 없는 콜러블 — 검사할 근거가 없다
        return []

    out: List[str] = []
    for pname, value in (params or {}).items():
        if not isinstance(value, (dict, list, tuple, set)):
            continue
        p = sig.parameters.get(pname)
        if p is None:
            continue  # 모르는 kwarg — TypeError 가 더 정확하게 잡는다
        want = _scalar_annotation(p.annotation)
        if not want:
            continue
        shown = json.dumps(value, ensure_ascii=False, default=str)[:160]
        hint = ""
        candidates = list(value.keys()) if isinstance(value, dict) else list(value)
        if len(candidates) == 1 and isinstance(candidates[0], (str, int, float, bool)):
            hint = f' — did you mean {json.dumps(candidates[0], ensure_ascii=False)}?'
        out.append(
            f"'{pname}' takes {want}, but got a "
            f"{'mapping' if isinstance(value, dict) else 'list'} {shown}{hint}"
        )
    return out


def run_analysis_step(
    parquet_uri: str,
    spec: Dict[str, Any],
    *,
    available: Optional[List[str]] = None,
    user_id: str = "",
    note_id: str = "",
) -> Dict[str, Any]:
    """Execute a single FROZEN ANALYSIS node (KM / PSM / Cox) via SeerToolbox.

    The planner emits these as ordinary pipeline nodes; here we bind the node's
    first input as the tool's cohort source, run the frozen tool, register its
    (small) result table as a DuckDB relation named ``output`` so Verify /
    persistence read it uniformly, and return a materialized payload that also
    carries the tool ``deliverable`` (table + optional figure) for Finalize.
    """
    import pandas as pd

    op = str(spec.get("op") or "").strip()
    out = str(spec.get("output") or "").strip()
    name = str(spec.get("name") or out)
    inputs = spec.get("inputs") or ["seer"]
    params = dict(spec.get("params") or {})
    src = str(inputs[0]).strip() if inputs else "seer"

    if available is not None:
        known = set(available) | {"seer"} | set(_EXTRA_SOURCES)
        for s in inputs:
            if s not in known:
                raise ValueError(
                    f"Step '{name}' references unknown input '{s}'. "
                    f"Available: {sorted(known)}."
                )

    # Bind the cohort source view + name the deliverable after the node output.
    params.setdefault(_ANALYSIS_SOURCE_PARAM.get(op, "source"), src or "seer")
    params.setdefault("label", out)

    toolbox = SeerToolbox(parquet_uri, user_id=user_id, note_id=note_id)
    method = getattr(toolbox, op, None)
    if method is None or op not in ANALYSIS_OPS:
        raise ValueError(f"Unknown analysis op '{op}'.")

    # The kwargs this tool ACTUALLY runs with = the plan's params + the tool's own
    # signature defaults for everything it left unset (n_bootstrap=500, n_bins=10,
    # random_state=42, …). Capture them so the persisted params — and Dora's later
    # ``query_parameters`` lookup — reflect the real execution, not just the
    # authored subset. Drop the cohort/label plumbing; keep it out of the report.
    eff_params = effective_tool_params(
        method, params, drop=_EFFECTIVE_PARAM_PLUMBING
    )

    logger.info(
        "[seer] execute analysis '%s' (op=%s, source=%s, output=%s)\n         params=%s",
        name, op, src, out, json.dumps(params, ensure_ascii=False, default=str),
    )
    # Wrong param NAMES raise TypeError at bind time; wrong param SHAPES do not —
    # Python happily binds a mapping to a ``str`` parameter and the tool dies deep
    # inside on ``.strip()``, with a traceback that never names the knob. Check the
    # shapes here, where the signature is already in hand, so every frozen tool gets
    # the same actionable message instead of forty hand-written guards.
    shape_errors = scalar_param_violations(method, params)
    if shape_errors:
        raise ValueError(f"Bad params for analysis op '{op}': " + "; ".join(shape_errors))
    try:
        message = str(method(**params))
    except TypeError as e:
        # Bad / unknown params for this frozen tool → deterministic, actionable.
        raise ValueError(f"Bad params for analysis op '{op}': {e}")

    materialized = out in getattr(toolbox, "_materialized_outputs", set())
    deliverable = next(
        (d for d in toolbox.deliverables if d.get("name") == out), None
    )
    if deliverable is None and toolbox.deliverables and not materialized:
        deliverable = toolbox.deliverables[-1]

    low = message.lower()
    err = message if low.startswith(_ANALYSIS_FAILURE_MARKERS) else None

    # When the tool materialized the FULL result as a queryable relation
    # (PSM matched cohort, KM/Cox result tables), that relation is authoritative:
    # read the payload shape from it (never truncate to a preview) so Verify sees
    # the real dataset and persistence saves + profiles the full data.
    if materialized:
        con = get_seer_connection(parquet_uri)
        rel = _materialize(con, out)
        # A tool that already wrote its parquet output exposes the URI on its
        # deliverable; surface it so the graph's persist layer reuses it instead
        # of COPYing the relation to S3 a second time.
        storage_path = (deliverable or {}).get("storage_path") if deliverable else None
        return {
            "name": out,
            "columns": rel.get("columns") or [],
            "row_count": int(rel.get("row_count") or 0),
            "preview": rel.get("preview") or [],
            "error": err or rel.get("error"),
            "message": message,
            "deliverable": deliverable,
            "storage_path": storage_path,
            "effective_params": eff_params,
        }

    if deliverable is None:
        logger.info("[seer] analysis '%s' produced no deliverable — %s", name, message)
        return {
            "name": out,
            "columns": [],
            "row_count": 0,
            "preview": [],
            "error": err or message,
            "message": message,
            "effective_params": eff_params,
        }

    # Fallback (tool did not materialize): register the (small) result table from
    # the deliverable preview so downstream / persistence can read it.
    rows = deliverable.get("preview") or []
    try:
        if rows:
            con = get_seer_connection(parquet_uri)
            tmp = f"_analysis_{abs(hash(out)) % 10_000_000}"
            con.register(tmp, pd.DataFrame(rows))
            con.execute(f"CREATE OR REPLACE TABLE {_q(out)} AS SELECT * FROM {tmp}")
            con.unregister(tmp)
    except Exception as e:  # non-fatal: the deliverable itself still surfaces
        logger.warning("[seer] analysis '%s' result-view register failed: %s", out, e)

    result = {
        "name": out,
        "columns": deliverable.get("columns") or [],
        "row_count": int(deliverable.get("row_count") or 0),
        "preview": rows,
        "error": err,
        "message": message,
        "deliverable": deliverable,
        "effective_params": eff_params,
    }
    logger.info(
        "[seer] analysis '%s' output: %s rows, %d col(s)%s",
        name,
        f"{result['row_count']:,}",
        len(result["columns"]),
        f" — ERROR: {err}" if err else "",
    )
    return result


# ---------------------------------------------------------------------------
# Run-scoped custom formatting tool (vibe-coded per run; NOT in the toolbox)
# ---------------------------------------------------------------------------
# The codegen step (between Plan and Execute) attaches LLM-generated Python to a
# ``custom_format`` node as ``generated_code``. The code must define
#     def format_outputs(inputs: dict[str, pandas.DataFrame]) -> pandas.DataFrame
# where ``inputs`` maps the node's input dataset names to their DataFrames. We
# execute it in a restricted namespace (no imports / file / eval) — this is a
# TEST-grade guard, not a real sandbox — and treat the returned DataFrame as the
# node's parquet-out output, identical to the frozen analysis tools.

# Modules the generated formatter (and pandas' own lazy imports) may pull in.
# Everything else — os / sys / subprocess / socket / importlib, etc. — is denied,
# so ``import`` still cannot reach the filesystem, network, or process control.
_CUSTOM_FORMAT_ALLOWED_MODULES = frozenset({
    "pandas", "numpy", "re", "math", "statistics", "datetime", "itertools",
    "collections", "functools", "decimal", "fractions", "json", "string",
    "operator", "textwrap", "unicodedata", "tabulate",
})


def _make_safe_import(real_import: Callable[..., Any]) -> Callable[..., Any]:
    """A whitelisted ``__import__`` for the custom_format sandbox.

    ``import`` statements compile to a ``__builtins__['__import__']`` call, so a
    namespace without it raises "__import__ not found" the moment the generated
    code — or a pandas method doing a lazy import (e.g. ``to_markdown`` →
    ``tabulate``) — hits an import. We allow a fixed set of safe, pure-data
    modules and deny the rest.
    """

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        top = (name or "").split(".", 1)[0]
        if top in _CUSTOM_FORMAT_ALLOWED_MODULES:
            return real_import(name, globals, locals, fromlist, level)
        raise ImportError(f"import of '{name}' is not allowed in custom_format code.")

    return _safe_import


# Builtins the generated formatter may use (data-shaping only). ``open`` /
# ``eval`` / ``exec`` stay excluded; ``__import__`` is replaced by a whitelisted
# variant. Common exception classes are included so defensive try/except code
# (which the codegen prompt encourages) does not itself raise NameError.
def _build_custom_format_builtins() -> Dict[str, Any]:
    import builtins

    allowed = (
        "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
        "list", "map", "max", "min", "range", "round", "set", "sorted", "str",
        "sum", "tuple", "zip", "isinstance", "print", "reversed", "filter",
        "getattr", "hasattr", "type", "abs", "divmod", "format",
        # Exception classes so try/except / raise in generated code works.
        "Exception", "ValueError", "KeyError", "TypeError", "IndexError",
        "AttributeError", "ZeroDivisionError", "RuntimeError", "StopIteration",
    )
    out: Dict[str, Any] = {n: getattr(builtins, n) for n in allowed if hasattr(builtins, n)}
    out["__import__"] = _make_safe_import(builtins.__import__)
    return out


_CUSTOM_FORMAT_BUILTINS: Dict[str, Any] = _build_custom_format_builtins()


def _compile_format_fn(code: str) -> Callable[[Dict[str, Any]], Any]:
    """Compile vibe-coded formatter source into a ``format_outputs`` callable.

    ``pandas``/``numpy`` are injected as ``pd``/``np``; the code runs with a
    restricted ``__builtins__`` (no ``open`` / ``eval`` / ``exec``; ``import`` is
    limited to a safe module whitelist). Raises ValueError if the code does not
    define ``format_outputs``.
    """
    import numpy as np
    import pandas as pd

    ns: Dict[str, Any] = {
        "pd": pd,
        "np": np,
        "pandas": pd,
        "numpy": np,
        "__builtins__": _CUSTOM_FORMAT_BUILTINS,
    }
    try:  # the tool layer's presentation helpers (same `fmt` the codegen path gets)
        from . import fmt as _fmt

        ns["fmt"] = _fmt
    except Exception:
        pass
    try:
        compiled = compile(code, "<seer_custom_format>", "exec")
        exec(compiled, ns)  # noqa: S102 — restricted namespace; test-grade guard
    except Exception as e:
        raise ValueError(f"custom_format code failed to compile/exec: {e}")
    fn = ns.get("format_outputs")
    if not callable(fn):
        raise ValueError(
            "custom_format code must define a function "
            "`format_outputs(inputs)` returning a pandas DataFrame."
        )
    return fn


def run_custom_format_step(
    parquet_uri: str,
    spec: Dict[str, Any],
    *,
    available: Optional[List[str]] = None,
    user_id: str = "",
    note_id: str = "",
) -> Dict[str, Any]:
    """Execute a run-scoped ``custom_format`` node.

    Loads each input dataset (an earlier step's output view) into a pandas
    DataFrame, runs the node's vibe-coded ``format_outputs(inputs)`` over them,
    and materializes the returned DataFrame as the node's parquet-out output
    (same contract as the frozen analysis tools: full relation + S3 parquet +
    deliverable). The generated code is taken from ``spec['generated_code']`` and
    is never persisted to the toolbox.
    """
    import pandas as pd

    out = str(spec.get("output") or "").strip()
    name = str(spec.get("name") or out)
    inputs = [str(s) for s in (spec.get("inputs") or []) if str(s).strip()]
    code = str(spec.get("generated_code") or "").strip()
    if not out:
        raise ValueError("custom_format step requires an 'output'.")
    if not code:
        raise ValueError(f"custom_format step '{name}' has no generated_code.")

    if available is not None:
        known = set(available) | {"seer"} | set(_EXTRA_SOURCES)
        for s in inputs:
            if s not in known:
                raise ValueError(
                    f"Step '{name}' references unknown input '{s}'. "
                    f"Available: {sorted(known)}."
                )

    toolbox = SeerToolbox(parquet_uri, user_id=user_id, note_id=note_id)
    con = toolbox.con

    # Bind each input dataset name → its DataFrame (result tables are small).
    frames: Dict[str, Any] = {}
    for s in inputs:
        try:
            frames[s] = con.execute(f"SELECT * FROM {_q(s)}").fetchdf()
        except Exception as e:
            raise ValueError(f"custom_format '{name}' could not read input '{s}': {e}")

    logger.info(
        "[seer] execute custom_format '%s' (inputs=%s → output=%s), %d line(s) of code",
        name, inputs, out, len(code.splitlines()),
    )

    fn = _compile_format_fn(code)
    try:
        result_df = fn(frames)
    except Exception as e:
        raise ValueError(f"custom_format '{name}' raised while formatting: {e}")
    if not isinstance(result_df, pd.DataFrame):
        raise ValueError(
            f"custom_format '{name}' must return a pandas DataFrame, "
            f"got {type(result_df).__name__}."
        )
    if result_df.empty:
        return {
            "name": out,
            "columns": [str(c) for c in result_df.columns],
            "row_count": 0,
            "preview": [],
            "error": "custom_format produced 0 rows.",
            "message": "custom_format produced an empty DataFrame.",
        }

    # Parquet-out contract (identical to the frozen wrappers).
    toolbox._materialize_output(out, result_df)
    parquet_out = toolbox._export_parquet(out)
    toolbox._register_deliverable(
        out,
        result_df,
        len(result_df),
        title=str(spec.get("purpose") or f"Custom format: {out}"),
        storage_path=parquet_out,
        parquet_uri=parquet_out,
    )
    deliverable = next((d for d in toolbox.deliverables if d.get("name") == out), None)
    rel = _materialize(con, out)
    logger.info(
        "[seer] custom_format '%s' output: %s rows, %d col(s)",
        name, f"{int(rel.get('row_count') or 0):,}", len(rel.get("columns") or []),
    )
    return {
        "name": out,
        "columns": rel.get("columns") or [],
        "row_count": int(rel.get("row_count") or 0),
        "preview": rel.get("preview") or [],
        "error": rel.get("error"),
        "message": f"custom_format '{out}' produced {int(rel.get('row_count') or 0)} rows.",
        "deliverable": deliverable,
        "storage_path": parquet_out,
    }


def summarize_step_output(output: Dict[str, Any], *, preview_rows: int = 6) -> Dict[str, Any]:
    """Compress a step's materialized output into a lightweight state summary.

    Keeps only what a downstream step needs to make parameter decisions
    (name, shape, columns, a few preview rows) — never the full data (P2).
    """
    preview = list(output.get("preview") or [])[:preview_rows]
    return {
        "ref": output.get("name"),
        "row_count": int(output.get("row_count") or 0),
        "columns": list(output.get("columns") or []),
        "preview": preview,
        "truncated": bool(output.get("truncated")),
    }


def profile_step_output(
    parquet_uri: str,
    output_name: str,
    *,
    sample_rows: int = 2000,
    view_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Profile a verified step's output view WITHOUT loading the full table.

    Reads a bounded sample (``sample_rows``) of the DuckDB view into pandas and
    runs the unified profiler (:func:`utils.data_profiling.build_unified_data_summary`)
    over it, then overrides ``row_count`` with the exact ``COUNT(*)``. This is
    the control-plane summary that downstream steps read *instead of* re-loading
    the raw data — column names, roles, unique values, and ranges are enough to
    generate the next step's SQL.

    ``view_name`` overrides the DuckDB relation to read when it differs from the
    artifact's logical name (a codegen node's output is a temporarily registered
    frame, not a view named after the output — see :func:`persist_dataframe_output`).

    Returns ``{row_count, col_count, columns, column_types, profile_text,
    profile_struct}`` (best-effort: empty-ish dict on failure).
    """
    con = get_seer_connection(parquet_uri)
    view = str(view_name or output_name)
    try:
        total = int(con.execute(f"SELECT COUNT(*) FROM {_q(view)}").fetchone()[0])
    except Exception as e:
        logger.warning("[seer] profile '%s' COUNT failed: %s", output_name, e)
        return {}

    n = max(1, int(sample_rows or 2000))
    try:  # reservoir sample for better value coverage; fall back to head().
        sample_df = con.execute(
            f"SELECT * FROM {_q(view)} USING SAMPLE {n} ROWS"
        ).fetchdf()
    except Exception:
        try:
            sample_df = con.execute(
                f"SELECT * FROM {_q(view)} LIMIT {n}"
            ).fetchdf()
        except Exception as e:
            logger.warning("[seer] profile '%s' sample failed: %s", output_name, e)
            return {"row_count": total}

    try:
        from utils.data_profiling import build_unified_data_summary

        summary = build_unified_data_summary(
            df=sample_df, name=output_name, source_uri=output_name
        )
        # The sample gives roles / uniques / ranges; the row_count is exact.
        summary.row_count = total
        summary.approx = True
        summary.notes.append(
            f"stats from a {len(sample_df)}-row sample; row_count exact ({total:,})."
        )
        return {
            "row_count": total,
            "col_count": int(summary.col_count),
            "columns": [c.name for c in summary.columns][:300],
            "column_types": {c.name: c.role for c in summary.columns[:300]},
            "profile_text": summary.to_text()[:60000],
            "profile_struct": summary.to_struct(),
        }
    except Exception as e:
        logger.warning("[seer] profile '%s' build failed: %s", output_name, e)
        return {"row_count": total, "columns": [str(c) for c in sample_df.columns]}


def persist_step_output(
    parquet_uri: str,
    output_name: str,
    *,
    user_id: str = "",
    note_id: str = "",
    fmt: str = "parquet",
    max_cells: Optional[int] = None,
    precomputed_uri: Optional[str] = None,
    view_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a verified step's output — its **profile** always, its **data**
    when small enough.

    A step is only saved AFTER it passes verification (plan.md FR-VP3). Two
    things are produced:

    1. A lightweight **profile** (:func:`profile_step_output`) — always built,
       from a bounded sample, so it never stalls. This is what downstream steps
       read instead of re-loading the raw output.
    2. The **data** itself, written as a single Parquet/CSV to
       ``s3://<seer-bucket>/seer_outputs/<user>/<note>/<output>_<ts>.<ext>`` —
       DuckDB ``COPY`` to a temp file, then boto3 upload, then the temp is
       unlinked. ONLY when ``rows × cols`` is under :func:`_max_persist_cells`.
       Wide intermediate cohorts (700+ cols × 100k+ rows) would stall the run,
       so those keep their live DuckDB view (downstream steps still read it)
       and are persisted as *profile-only* (``skipped=True``, no ``uri``).
       A successful upload leaves no durable local copy of the result file.

    Returns ``{uri, storage_path, row_count, columns, format, skipped,
    profile_text, profile_struct, column_types}``.
    """
    import time as _time

    from utils.storage.bucket import parse_s3_uri

    con = get_seer_connection(parquet_uri)
    view = str(view_name or output_name)
    total = int(con.execute(f"SELECT COUNT(*) FROM {_q(view)}").fetchone()[0])
    cols = [str(r[0]) for r in con.execute(f"DESCRIBE {_q(view)}").fetchall()]

    # (1) Profile first — this is the durable, always-saved control-plane info.
    profile = profile_step_output(parquet_uri, output_name, view_name=view)

    ext = "csv" if fmt == "csv" else "parquet"
    base: Dict[str, Any] = {
        "row_count": total,
        "columns": cols,
        "format": ext,
        "profile_text": profile.get("profile_text", ""),
        "profile_struct": profile.get("profile_struct", {}),
        "column_types": profile.get("column_types", {}),
    }

    # A tool that already wrote its own parquet (SEER-template parquet-out
    # contract, e.g. mann_whitney_u) passes that URI in; reuse it so the data is
    # not COPYed to S3 a second time — only the profile above is (re)built.
    pre = (precomputed_uri or "").strip()
    if pre:
        logger.info("[seer] persist '%s': reusing tool-written parquet %s", output_name, pre)
        return {**base, "uri": pre, "storage_path": pre, "format": "parquet", "skipped": False}

    # (2) Data export — guarded by the cell cap so wide intermediates never
    # stall the run. Profile-only when over the cap.
    cap = _max_persist_cells() if max_cells is None else int(max_cells)
    cells = total * max(1, len(cols))
    if cap and cells > cap:
        logger.warning(
            "[seer] persist '%s': profile-only (%s rows × %d cols = %s cells > "
            "cap %s). DuckDB view kept for downstream; S3 data export skipped.",
            output_name, f"{total:,}", len(cols), f"{cells:,}", f"{cap:,}",
        )
        return {**base, "uri": None, "storage_path": None, "skipped": True}

    try:
        bucket, _ = parse_s3_uri(seer_db_uri())
    except Exception:
        bucket = None
    if not bucket:
        logger.warning("[seer] persist '%s': no S3 bucket resolved; profile-only.", output_name)
        return {**base, "uri": None, "storage_path": None, "skipped": True}

    uid = (user_id or "").strip() or "anon"
    nid = (note_id or "").strip() or "default"
    key = f"seer_outputs/{uid}/{nid}/{output_name}_{int(_time.time())}.{ext}"
    target_uri = f"s3://{bucket}/{key}"
    t0 = _time.time()
    logger.info(
        "[seer] persist '%s' → %s (%s rows × %d cols)…",
        output_name, target_uri, f"{total:,}", len(cols),
    )
    try:
        uri = _copy_relation_to_s3(con, view, key, bucket=bucket, fmt=ext)
        if not uri:
            raise RuntimeError("S3 upload returned no URI")
        logger.info("[seer] persist '%s' done in %.1fs", output_name, _time.time() - t0)
        return {**base, "uri": uri, "storage_path": uri, "skipped": False}
    except Exception as e:
        # Do NOT fall back to a full pandas materialization (would OOM on wide
        # tables) or a durable local parquet. Keep the view + profile.
        logger.warning(
            "[seer] persist '%s' S3 upload failed (%s); profile-only.", output_name, e,
        )
        return {**base, "uri": None, "storage_path": None, "skipped": True}


def persist_dataframe_output(
    parquet_uri: str,
    output_name: str,
    df: Any,
    *,
    user_id: str = "",
    note_id: str = "",
    fmt: str = "parquet",
    max_cells: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist a codegen node's in-memory frame the same way a tool node's view is.

    :func:`persist_step_output` reads a DuckDB relation, which only exists for
    frozen-tool / sql nodes. A codegen node's result lives solely as a pandas frame
    in graph state, so it is registered on the same cached connection under a
    throwaway name and then takes the identical cell-cap + temp-COPY + S3
    upload path — one persistence route for every node kind, instead of a
    second S3 writer that would drift from this one.

    Returns the same dict as :func:`persist_step_output`.
    """
    import time as _time

    if df is None:
        return {"uri": None, "storage_path": None, "skipped": True, "row_count": 0,
                "columns": [], "format": fmt}

    con = get_seer_connection(parquet_uri)
    # Namespaced + timestamped so registering never shadows a real pipeline view
    # (a retried node persists twice within the same connection).
    view = f"__an_persist_{_bare(output_name)}_{int(_time.time() * 1000)}"
    try:
        con.register(view, df)
    except Exception as e:  # noqa: BLE001
        logger.warning("[seer] persist '%s': frame register failed (%s)", output_name, e)
        return {"uri": None, "storage_path": None, "skipped": True, "row_count": 0,
                "columns": [], "format": fmt}
    try:
        return persist_step_output(
            parquet_uri,
            output_name,
            user_id=user_id,
            note_id=note_id,
            fmt=fmt,
            max_cells=max_cells,
            view_name=view,
        )
    finally:
        try:
            con.unregister(view)
        except Exception:  # noqa: BLE001
            pass


# ===========================================================================
# ReAct toolbox — query tools + generalized Kaplan-Meier
# ===========================================================================
# The execute (E) node runs a ReAct loop (like the cohort agent): the LLM
# iteratively calls these tools, observes the (DuckDB) results, and self-
# corrects — e.g. inspecting the schema and category labels before filtering,
# which avoids the classic "n_tnbc = 0" from guessing wrong column values.

# Materialization / preview caps for tool observations returned to the LLM.
_TOOL_PREVIEW_ROWS = 40
# Max rows pulled into pandas for a Kaplan-Meier fit (2 small cols + groups).
_KM_MAX_ROWS = 3_000_000


def _jsonify_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """numpy / NaN → JSON-native so the payload survives ``_safe_serialize``."""
    for row in records:
        for k, v in list(row.items()):
            try:
                if v is None:
                    continue
                if isinstance(v, float) and v != v:  # NaN
                    row[k] = None
                elif hasattr(v, "item"):
                    row[k] = v.item()
            except Exception:
                row[k] = str(v)
    return records


def _df_to_deliverable(name: str, df, total: Optional[int] = None) -> Dict[str, Any]:
    preview = _jsonify_records(df.head(200).to_dict(orient="records"))
    n = int(total if total is not None else len(df))
    return {
        "name": name,
        "columns": [str(c) for c in df.columns],
        "row_count": n,
        "truncated": n > len(df),
        "preview": preview,
    }


def _fmt_rows_for_llm(df, limit: int = _TOOL_PREVIEW_ROWS) -> str:
    import json as _json

    head = _jsonify_records(df.head(limit).to_dict(orient="records"))
    return _json.dumps(head, ensure_ascii=False, default=str)


# Max rows pulled into pandas for a regression / matching fit.
_MODEL_MAX_ROWS = 1_000_000


def _fold_label(value: Any) -> str:
    """Fold a category label for matching: case, spacing and dash style ignored.

    A requested reference level is typed by hand (or by an LLM reading a paper),
    so it routinely differs from the stored label only in an en-dash vs hyphen or
    a stray space — ``"20–39 years"`` vs ``"20-39 years"``. Those are the same
    category, and failing the match on them would be indefensible.
    """
    text = " ".join(str(value).split()).casefold()
    for dash in ("\u2013", "\u2014", "\u2212", "\u2011"):
        text = text.replace(dash, "-")
    return text


def _num_or_none(value: Any) -> Optional[float]:
    """Float, or None for anything that is not one (including ``""`` and bools)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _opt_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """``_num_or_none`` with a fallback — for optional numeric tool params."""
    got = _num_or_none(value)
    return default if got is None else got


def _as_records(value: Any) -> List[Any]:
    """Normalize a param that may be one object, a list, or a JSON string of either."""
    if value is None:
        return []
    if isinstance(value, str):
        import json as _json

        try:
            value = _json.loads(value)
        except ValueError:
            return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _reference_map(reference_levels: Any, covariates: List[str]) -> Tuple[Dict[str, str], Optional[str]]:
    """Normalize ``{covariate: reference level}`` → ``(mapping, error)``.

    Keys are matched to ``covariates`` case/space-insensitively so a caller does
    not have to reproduce a SEER column name byte-for-byte. An unknown key is an
    error rather than a silent no-op: a reference level that is quietly ignored
    changes every hazard/odds ratio in the output without any signal.
    """
    if not reference_levels:
        return {}, None
    if not isinstance(reference_levels, dict):
        return {}, (
            "Error: 'reference_levels' must be an object mapping a covariate to its "
            'reference category, e.g. {"Race recode": "Black"}.'
        )
    by_fold = {_fold_label(c): c for c in covariates}
    out: Dict[str, str] = {}
    for key, level in reference_levels.items():
        cov = by_fold.get(_fold_label(_bare(key)))
        if cov is None:
            return {}, (
                f"Error: reference_levels names '{key}', which is not in 'covariates' "
                f"({covariates}). A reference level only means something for a covariate "
                "that is in the model."
            )
        if level is None or not str(level).strip():
            return {}, f"Error: reference_levels['{key}'] is empty — name the baseline category."
        out[cov] = str(level)
    return out, None


# A numeric covariate is left continuous; forcing it to a factor because a
# reference level was requested is only sane while its distinct values stay few.
_MAX_FACTOR_LEVELS = 20


def _design_matrix(
    df,
    alias_cols: List[str],
    cov_map: Dict[str, str],
    reference_levels: Optional[Dict[str, str]] = None,
):
    """Build a numeric design matrix from raw covariate columns.

    Numeric-looking columns are cast to float; categorical columns are one-hot
    encoded (drop-first). Column names use the original covariate labels so the
    fitted model's summary is human-readable. Returns ``(X, feature_names)``.

    ``reference_levels`` maps an ORIGINAL covariate name to the category that must
    become the model's baseline. Without it the reference is whichever level sorts
    first, which is not something a caller can work around — every coefficient is
    expressed RELATIVE to the baseline, so reproducing a published table requires
    naming it. A covariate listed here is always treated as a factor, even when its
    values look numeric. Raises ``ValueError`` (with the observed levels) when a
    requested level is absent, since silently keeping the default baseline would
    change every reported ratio without saying so.
    """
    import pandas as pd

    refs = reference_levels or {}
    # Build each covariate's block (a numeric Series or a one-hot DataFrame) and
    # concatenate ONCE at the end. Inserting columns one-by-one into a growing
    # frame fragments it and raises pandas' PerformanceWarning on wide one-hot
    # expansions, so we avoid the incremental assignment entirely.
    parts: List[Any] = []
    features: List[str] = []
    for a in alias_cols:
        orig = cov_map.get(a, a)
        col = df[a]
        ref = refs.get(orig)
        num = pd.to_numeric(col, errors="coerce")
        if ref is None and float(num.notna().mean()) >= 0.8:  # mostly numeric → keep as-is
            parts.append(num.rename(orig))
            features.append(orig)
            continue

        # categorical → one-hot, dropping the baseline level
        text = col.astype("string")
        levels = sorted(str(v) for v in text.dropna().unique())
        if ref is not None:
            if len(levels) > _MAX_FACTOR_LEVELS:
                raise ValueError(
                    f"Error: covariate '{orig}' has {len(levels)} distinct values, so it is "
                    "modelled as a continuous term and has no reference category. Bin it "
                    "into groups first, or drop it from 'reference_levels'."
                )
            wanted = _fold_label(ref)
            hit = next((lv for lv in levels if _fold_label(lv) == wanted), None)
            if hit is None:
                raise ValueError(
                    f"Error: reference level '{ref}' does not occur in covariate '{orig}'. "
                    f"Observed levels: {levels}. Copy one of them verbatim."
                )
            levels = [hit] + [lv for lv in levels if lv != hit]
            text = pd.Categorical(text, categories=levels)
        dummies = pd.get_dummies(
            text, prefix=orig, prefix_sep="=", drop_first=True, dummy_na=False
        ).astype(float)
        dummies.index = col.index
        parts.append(dummies)
        features.extend(str(c) for c in dummies.columns)
    if not parts:
        return pd.DataFrame(index=df.index), features
    X = pd.concat(parts, axis=1)
    return X, features


def _greedy_nn_match(
    treated_logit,
    treated_ids,
    control_logit,
    control_ids,
    *,
    caliper: Optional[float] = None,
    ratio: int = 1,
    progress_every: int = 20_000,
) -> Tuple[List[Tuple[Any, Any]], int]:
    """Greedy nearest-neighbour matching on the 1-D propensity logit, no replacement.

    The standard clinical recipe (greedy 1:``ratio`` nearest neighbour within a
    caliper), computed the way a ONE-DIMENSIONAL distance should be. psmpy's
    ``kdtree_matched`` asks a KD-tree for k = *every* control, which materializes an
    |treated| x |control| distance matrix — 36 GB at SEER scale — and then dedupes
    used controls by linear-scanning a Python list per treated patient, which is
    quadratic on top. Sorting the controls once and walking them with a bisect plus
    a path-compressed "next available" pointer yields the SAME greedy answer in
    O((T+C) log C) time and linear memory.

    Equivalence with the KD-tree version: taking the nearest AVAILABLE control and
    then testing the caliper is the same as filtering to within-caliper controls and
    taking the nearest available one — if the nearest available control is outside
    the caliper then every closer control is already used, so both rules leave the
    patient unmatched.

    Deterministic by construction, because a greedy match depends on the order it
    runs in: treated patients are processed by DESCENDING logit (hardest to match
    first, as ``MatchIt``'s propensity-score default does) with the id as a
    tie-break, and an equidistant pair of controls resolves to the smaller id. Row
    order in the source table therefore cannot change the result.

    Returns ``(pairs, n_unmatched_treated)`` with one ``(treated_id, control_id)``
    per match; a 1:n run contributes ``n`` pairs for the same treated id.
    """
    import numpy as np

    t_logit = np.asarray(treated_logit, dtype=float)
    c_logit = np.asarray(control_logit, dtype=float)
    t_ids = np.asarray(treated_ids)
    c_ids = np.asarray(control_ids)
    n_ctl = int(c_logit.size)
    if t_logit.size == 0 or n_ctl == 0:
        return [], int(t_logit.size)

    order = np.argsort(c_logit, kind="stable")
    c_sorted = c_logit[order]
    c_sorted_ids = c_ids[order]

    # Two disjoint-set "skip" chains over the sorted controls, so consuming a
    # control costs O(1) amortized instead of a list scan. `up[i]` walks toward the
    # nearest still-available index >= i (n_ctl = none); `dn[i + 1]` walks toward
    # the nearest available index <= i (0 = none, hence the +1 offset).
    up = list(range(n_ctl + 1))
    dn = list(range(n_ctl + 1))

    def find_up(i: int) -> int:
        root = i
        while up[root] != root:
            root = up[root]
        while up[i] != i:
            up[i], i = root, up[i]
        return root

    def find_dn(i: int) -> int:
        k = i + 1
        root = k
        while dn[root] != root:
            root = dn[root]
        while dn[k] != k:
            dn[k], k = root, dn[k]
        return root - 1

    # Hardest-to-match first; the id breaks ties so the pass is reproducible.
    t_order = np.lexsort((t_ids, -t_logit))
    cal = None if caliper is None else float(caliper)
    rounds = max(1, int(ratio or 1))

    pairs: List[Tuple[Any, Any]] = []
    matched_treated: set = set()
    processed = 0
    for rnd in range(rounds):
        for ti in t_order:
            processed += 1
            if progress_every and processed % progress_every == 0:
                logger.info(
                    "[seer] PSM: matching… %d treated processed, %d pair(s) so far",
                    processed, len(pairs),
                )
            lt = float(t_logit[ti])
            j = int(np.searchsorted(c_sorted, lt, side="left"))
            hi = find_up(j)                     # nearest available with logit >= lt
            lo = find_dn(j - 1)                 # nearest available with logit <  lt
            best = -1
            best_d = float("inf")
            for cand in (lo, hi):
                if cand < 0 or cand >= n_ctl:
                    continue
                d = abs(c_sorted[cand] - lt)
                if d < best_d or (
                    d == best_d and best >= 0 and c_sorted_ids[cand] < c_sorted_ids[best]
                ):
                    best, best_d = cand, d
            if best < 0 or (cal is not None and best_d > cal):
                continue
            pairs.append((t_ids[ti], c_sorted_ids[best]))
            matched_treated.add(int(ti))
            up[best] = best + 1                 # consume: skip past it from below
            dn[best + 1] = best                 # …and from above
        if len(pairs) == 0 and rnd == 0:
            break                               # nothing is reachable; further rounds cannot help
    return pairs, int(t_logit.size - len(matched_treated))


def _parse_tolerance_columns(tolerance_columns: Any) -> Dict[str, float]:
    """Normalize ``tolerance_columns`` to ``{column: max_abs_diff}``.

    Accepts a mapping ``{col: tol}`` or a list of ``{column, tolerance}`` /
    ``{col, tol}`` dicts. Empty / None → ``{}``.
    """
    out: Dict[str, float] = {}
    if not tolerance_columns:
        return out
    if isinstance(tolerance_columns, dict) and not (
        "column" in tolerance_columns or "col" in tolerance_columns
    ):
        for k, v in tolerance_columns.items():
            col = str(k).strip()
            if not col:
                continue
            try:
                out[col] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(tolerance_columns, (list, tuple)):
        for item in tolerance_columns:
            if isinstance(item, dict):
                col = str(item.get("column") or item.get("col") or "").strip()
                raw = item.get("tolerance", item.get("tol"))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                col, raw = str(item[0]).strip(), item[1]
            else:
                continue
            if not col:
                continue
            try:
                out[col] = float(raw)
            except (TypeError, ValueError):
                continue
    return out


def _greedy_k_tuple_match(
    arm_gps: List[Any],
    arm_ids: List[Any],
    calipers: List[float],
    *,
    arm_tol: Optional[List[Any]] = None,
    tol_limits: Optional[List[float]] = None,
    candidate_cap: int = 40,
    progress_every: int = 5_000,
) -> Tuple[List[Tuple[Any, ...]], int]:
    """Rassen-style 1:1:…:1 K-tuple matching on the generalized PS vector (K≥3).

    Callers should already restrict to one exact-match stratum. Arm 0 is the
    reference (hardest-to-match first); each other arm contributes one unused
    patient. Every patient carries the same K-dimensional GPS
    ``(P(arm0),…,P(armK-1))`` (probability scale). A pair is valid only when
    every component-wise ``|logit GPS_d(i) − logit GPS_d(j)|`` is within
    ``calipers[d]`` and every tolerance column (if any) is within its limit.

    Distance minimized among valid tuples: sum of pairwise Euclidean distances
    on the probability GPS vectors. For K=3 the best pair among the nearest
    ``candidate_cap`` candidates per arm is searched exhaustively; for K>3
    partners are chosen greedily one arm at a time.

    Returns ``(tuples, n_unmatched_reference)`` where each tuple is a length-K
    sequence of patient ids (matcher arm-slot order).
    """
    import numpy as np

    k = len(arm_gps)
    if k < 3:
        raise ValueError("K-tuple matching requires at least 3 arms")
    gps = [np.asarray(a, dtype=float) for a in arm_gps]
    ids = [np.asarray(a) for a in arm_ids]
    cals = [float(c) for c in calipers]
    if any(g.ndim != 2 or g.shape[1] != len(cals) for g in gps):
        raise ValueError("each arm_gps must be shape (n_arm, K) aligned with calipers")
    n_ref = int(gps[0].shape[0])
    if n_ref == 0 or any(g.shape[0] == 0 for g in gps[1:]):
        return [], n_ref

    eps = 1e-6
    logit_gps = []
    for g in gps:
        clipped = np.clip(g, eps, 1.0 - eps)
        logit_gps.append(np.log(clipped / (1.0 - clipped)))

    tol_arr: Optional[List[Any]] = None
    tlim: List[float] = []
    if arm_tol is not None and tol_limits:
        tol_arr = [np.asarray(t, dtype=float) for t in arm_tol]
        tlim = [float(x) for x in tol_limits]
        if any(t.ndim != 2 or t.shape[0] != gps[i].shape[0] for i, t in enumerate(tol_arr)):
            raise ValueError("arm_tol rows must align with each arm's patients")
        if len(tlim) != tol_arr[0].shape[1]:
            raise ValueError("tol_limits length must match tolerance columns")

    n_dim = len(cals)

    def pair_ok(ai: int, i: int, aj: int, j: int) -> bool:
        for d in range(n_dim):
            if abs(float(logit_gps[ai][i, d]) - float(logit_gps[aj][j, d])) > cals[d]:
                return False
        if tol_arr is None:
            return True
        for t in range(len(tlim)):
            if abs(float(tol_arr[ai][i, t]) - float(tol_arr[aj][j, t])) > tlim[t]:
                return False
        return True

    def pair_dist(ai: int, i: int, aj: int, j: int) -> float:
        return float(np.linalg.norm(gps[ai][i] - gps[aj][j]))

    # Hardest reference patients first: extreme GPS logit vectors, id tie-break.
    hardness = np.linalg.norm(logit_gps[0], axis=1)
    ref_order = np.lexsort((ids[0], -hardness))
    available: List[set] = [set()] + [set(range(int(g.shape[0]))) for g in gps[1:]]
    tuples: List[Tuple[Any, ...]] = []
    matched_ref = 0
    processed = 0
    cap = max(5, int(candidate_cap or 40))

    for ri in ref_order:
        processed += 1
        if progress_every and processed % progress_every == 0:
            logger.info(
                "[seer] PSM-multi: matching… %d reference processed, %d tuple(s) so far",
                processed, len(tuples),
            )
        cands: List[List[int]] = [[int(ri)]]
        ok = True
        for a in range(1, k):
            pool = []
            for j in available[a]:
                if pair_ok(0, int(ri), a, int(j)):
                    pool.append((pair_dist(0, int(ri), a, int(j)), int(j)))
            if not pool:
                ok = False
                break
            pool.sort(key=lambda x: (x[0], int(ids[a][x[1]])))
            cands.append([j for _, j in pool[:cap]])
        if not ok:
            continue

        best_members: Optional[List[int]] = None
        best_cost = float("inf")

        if k == 3:
            for j1 in cands[1]:
                for j2 in cands[2]:
                    if not pair_ok(1, j1, 2, j2):
                        continue
                    cost = (
                        pair_dist(0, int(ri), 1, j1)
                        + pair_dist(0, int(ri), 2, j2)
                        + pair_dist(1, j1, 2, j2)
                    )
                    if cost < best_cost or (
                        cost == best_cost
                        and best_members is not None
                        and (
                            int(ids[1][j1]),
                            int(ids[2][j2]),
                        )
                        < (
                            int(ids[1][best_members[1]]),
                            int(ids[2][best_members[2]]),
                        )
                    ):
                        best_cost = cost
                        best_members = [int(ri), j1, j2]
        else:
            partial = [int(ri)]
            failed = False
            for a in range(1, k):
                local_best = None
                local_cost = float("inf")
                local_id = None
                for j in cands[a]:
                    good = True
                    add = 0.0
                    for p, memb in enumerate(partial):
                        if not pair_ok(a, j, p, memb):
                            good = False
                            break
                        add += pair_dist(a, j, p, memb)
                    if not good:
                        continue
                    cid = int(ids[a][j])
                    if add < local_cost or (
                        add == local_cost and (local_id is None or cid < local_id)
                    ):
                        local_cost = add
                        local_best = j
                        local_id = cid
                if local_best is None:
                    failed = True
                    break
                partial.append(int(local_best))
            if not failed:
                best_members = partial

        if best_members is None:
            continue
        tuples.append(tuple(ids[a][best_members[a]] for a in range(k)))
        matched_ref += 1
        for a in range(1, k):
            available[a].discard(best_members[a])

    return tuples, int(n_ref - matched_ref)


# Separator for interaction terms in a design matrix. Plain ASCII with spaces so
# the name survives any downstream formula parser that treats ':' / '*' as syntax.
_INTERACT_SEP = " x "


def _feature_block(features: List[str], covariate: str) -> List[str]:
    """The design-matrix columns produced by ONE original covariate.

    :func:`_design_matrix` names a numeric covariate after itself and a one-hot
    level ``"<covariate>=<level>"``, so a covariate's block is recoverable from
    the feature names alone.
    """
    prefix = f"{covariate}="
    return [f for f in features if f == covariate or f.startswith(prefix)]


def _parse_interactions(interactions: Any, covariates: List[str]):
    """Normalize the ``interactions`` param to ``(pairs, error)``.

    Accepts ``"A*B"`` / ``"A:B"`` / ``"A x B"`` strings and ``["A","B"]`` pairs.
    Both members must already be main-effect covariates — an interaction without
    its main effects is not interpretable.
    """
    if not interactions:
        return [], None
    if isinstance(interactions, str):
        interactions = [interactions]
    pairs: List[Tuple[str, str]] = []
    for item in interactions:
        if isinstance(item, str):
            parts = re.split(r"\s*(?:\*|:| x )\s*", item.strip())
        elif isinstance(item, dict):
            parts = [str(v) for v in item.values()]
        else:
            parts = [str(v) for v in (item or [])]
        parts = [_bare(p) for p in parts if _bare(p)]
        if len(parts) != 2:
            return [], (
                f"Error: interaction {item!r} must name exactly TWO covariates, "
                'e.g. "Radiation recode * Age".'
            )
        missing = [p for p in parts if p not in covariates]
        if missing:
            return [], (
                f"Error: interaction {item!r} references {missing}, which are not in "
                "'covariates'. An interaction requires both main effects."
            )
        pairs.append((parts[0], parts[1]))
    return pairs, None


def _wald_block_test(params, cov_matrix, block: List[str]):
    """Joint Wald test that every coefficient in ``block`` is zero.

    Returns ``(chi2, df, p)`` — the global interaction test that a per-term p-value
    cannot provide once a categorical interaction spans several dummies.
    """
    import numpy as np
    from scipy import stats

    block = [f for f in block if f in params.index]
    if not block:
        return None, 0, None
    b = params.loc[block].to_numpy(dtype=float)
    V = cov_matrix.loc[block, block].to_numpy(dtype=float)
    try:
        chi2 = float(b @ np.linalg.solve(V, b))
    except np.linalg.LinAlgError:  # singular block → fall back to a pseudo-inverse
        chi2 = float(b @ np.linalg.pinv(V) @ b)
    if not np.isfinite(chi2) or chi2 < 0:
        return None, len(block), None
    df = len(block)
    return round(chi2, 4), df, float(stats.chi2.sf(chi2, df))


def _cox_fitter(penalizer: float):
    """A ``CoxPHFitter`` that also KEEPS the robust covariance matrix.

    lifelines only ever exposes the naive (inverse-Hessian) ``variance_matrix_``:
    with ``robust=True`` it builds the Huber sandwich matrix, takes its DIAGONAL
    for the standard errors and discards the rest. Interaction contrasts and joint
    Wald tests need the off-diagonal robust terms, so capture the whole matrix at
    the one call site where it exists — computing it once, not twice. Any
    deviation in a future lifelines falls back to the stock code path.
    """
    import numpy as np
    import pandas as pd
    from lifelines import CoxPHFitter
    from lifelines import utils as ll_utils
    from lifelines.fitters.coxph_fitter import SemiParametricPHFitter

    class _KeepsRobustCov(SemiParametricPHFitter):
        robust_variance_matrix_ = None

        def _compute_standard_errors(self, X, T, E, weights):
            if not (self.robust or self.cluster_col):
                return super()._compute_standard_errors(X, T, E, weights)
            try:
                sandwich = self._compute_sandwich_estimator(X, T, E, weights)
                idx = self.params_.index
                se = pd.Series(np.sqrt(sandwich.diagonal()), name="se", index=idx)
            except Exception:
                logger.warning("[seer] cox_ph: robust covariance unavailable — "
                               "contrasts/Wald fall back to the naive matrix.")
                return super()._compute_standard_errors(X, T, E, weights)
            self.robust_variance_matrix_ = pd.DataFrame(sandwich, index=idx, columns=idx)
            return se

    # CoxPHFitter is a façade that delegates the fit to an inner
    # SemiParametricPHFitter (and forwards attribute reads to it), so the hook has
    # to be installed on the INNER model.
    class _CoxPH(CoxPHFitter):
        def _fit_model_breslow(self, *args, **kwargs):
            if not ll_utils.CensoringType.is_right_censoring(self):
                return super()._fit_model_breslow(*args, **kwargs)
            model = _KeepsRobustCov(
                penalizer=self.penalizer, l1_ratio=self.l1_ratio,
                strata=self.strata, alpha=self.alpha, label=self._label,
            )
            model.fit(*args, **kwargs)
            return model

    return _CoxPH(penalizer=penalizer)


def _cox_cov_matrix(cph):
    """The covariance matrix the model's reported SEs came from."""
    robust = getattr(cph, "robust_variance_matrix_", None)
    return cph.variance_matrix_ if robust is None else robust


def _level_of(feature: str, covariate: str) -> str:
    """The category label a one-hot design column encodes ('' for a numeric term)."""
    prefix = f"{covariate}="
    return feature[len(prefix):] if feature.startswith(prefix) else ""


def _dropped_level(values, covariate: str, features: List[str]) -> Optional[str]:
    """The one-hot REFERENCE level of a categorical covariate.

    :func:`_design_matrix` encodes categoricals with ``drop_first``, so exactly one
    level has no design column. Inside that level the focal exposure's effect is
    its main effect alone, so naming it is what lets the reference row be reported
    alongside the other levels. Returns None when it cannot be identified.
    """
    import pandas as pd

    kept = {_level_of(f, covariate) for f in features if f.startswith(f"{covariate}=")}
    if not kept:
        return None
    seen = {str(v) for v in pd.Series(values).astype("string").dropna().unique()}
    missing = sorted(seen - kept)
    return missing[0] if len(missing) == 1 else None


def _baseline_rows(df, cov_map: Dict[str, str], features: List[str]) -> List[Dict[str, Any]]:
    """One ``reference`` row per categorical covariate, naming its baseline level.

    The one-hot design drops the baseline, so a coefficient table alone never says
    which level the ratios are measured against — leaving a reader (or a verifier)
    to guess. Emitting the dropped level as an explicit row with ratio 1.0 both
    states the choice and gives a formatting node the "Reference" line that
    published tables print.
    """
    rows: List[Dict[str, Any]] = []
    for alias, orig in cov_map.items():
        level = _dropped_level(df[alias], orig, features)
        if level is None:
            continue
        rows.append({
            "term_type": "reference",
            "term": f"{orig}={level}",
            "group": None,
            "coef": 0.0, "se": None,
            "hazard_ratio": 1.0, "hr_lower95": None, "hr_upper95": None,
            "statistic": None, "df": None, "p": None,
        })
    return rows


# ---------------------------------------------------------------------------
# GLM helpers (shared by the glm_regression frozen tool)
# ---------------------------------------------------------------------------
# family key → (statsmodels family class, default link). The default is the link
# that outcome type is PUBLISHED with, which is not always statsmodels' canonical
# link: Gamma's canonical link is inverse power, but cost / length-of-stay models
# are reported as log-link ratios, so `family="gamma"` with no link means log.
_GLM_FAMILY_SPECS: Dict[str, Tuple[str, str]] = {
    "gaussian": ("Gaussian", "identity"),
    "binomial": ("Binomial", "logit"),
    "poisson": ("Poisson", "log"),
    "negativebinomial": ("NegativeBinomial", "log"),
    "gamma": ("Gamma", "log"),
    "inverse_gaussian": ("InverseGaussian", "log"),
}

# Spellings a methods section (or an LLM reading one) actually writes.
_GLM_FAMILY_ALIASES: Dict[str, str] = {
    "normal": "gaussian",
    "linear": "gaussian",
    "ols": "gaussian",
    "logistic": "binomial",
    "bernoulli": "binomial",
    "binary": "binomial",
    "negative_binomial": "negativebinomial",
    "negbin": "negativebinomial",
    "nb": "negativebinomial",
    # Quasi-Poisson is a Poisson mean model with a free dispersion; statsmodels
    # has no separate family, and the scale correction it implies is what
    # cov_type="HC0" already buys, so it maps onto Poisson rather than erroring.
    "quasipoisson": "poisson",
    "quasi_poisson": "poisson",
    "invgauss": "inverse_gaussian",
    "inversegaussian": "inverse_gaussian",
    "wald": "inverse_gaussian",
}

_GLM_LINK_CLASSES: Dict[str, str] = {
    "identity": "Identity",
    "log": "Log",
    "logit": "Logit",
    "probit": "Probit",
    "cloglog": "CLogLog",
    "inverse": "InversePower",
    "inverse_power": "InversePower",
    "sqrt": "Sqrt",
}

# exp(coef) is only interpretable as a ratio on these links.
_GLM_RATIO_LINKS = frozenset({"log", "logit"})


def _glm_effect_label(family: str, link: str) -> str:
    """What ``exp(coef)`` (or the bare coefficient) MEANS for this family/link.

    Naming the scale in the table is not cosmetic: a log link exponentiates to a
    RATE ratio on a count outcome but a RISK ratio on a binomial one, and logit
    gives an ODDS ratio. A formatting or forest node that had to guess would
    mislabel the column, and the three are not interchangeable in a paper.
    """
    if link == "logit":
        return "odds_ratio"
    if link == "log":
        if family in ("poisson", "negativebinomial"):
            return "rate_ratio"
        if family == "binomial":
            return "risk_ratio"
        return "ratio"
    if link == "identity":
        return "mean_difference"
    return "coefficient"


def _constant_columns(X) -> List[str]:
    """Design columns with zero variance.

    Almost always a covariate that collapsed to one category under ``where`` (a
    female-only cohort still adjusting for sex). The fit does not fail on it, it
    simply cannot identify that coefficient.
    """
    import numpy as np

    out: List[str] = []
    for col in X.columns:
        values = np.asarray(X[col], dtype=float)
        if values.size and float(np.nanstd(values)) == 0.0:
            out.append(str(col))
    return out


def _dependent_columns(X) -> List[str]:
    """Design columns that are exact linear combinations of the earlier columns.

    statsmodels does NOT fail on a rank-deficient design: GLM falls back to a
    pseudo-inverse, warns once per IRLS iteration ("The design matrix is
    rank-deficient") and returns coefficients that are not uniquely determined,
    which makes the standard errors and CIs unreportable too. It is also slow —
    IRLS then burns every iteration without meeting its convergence tolerance.
    Naming the redundant columns turns a silent bad result into a fixable error.
    """
    import numpy as np

    values = np.asarray(X, dtype=float)
    names = [str(c) for c in X.columns]
    dependent: List[str] = []
    keep: List[int] = []
    rank = 0
    for i in range(values.shape[1]):
        trial = keep + [i]
        r = int(np.linalg.matrix_rank(values[:, trial]))
        if r > rank:
            rank, keep = r, trial
        else:
            dependent.append(names[i])
    return dependent


def _incomplete_rows(df, cov_map: Dict[str, str]):
    """Rows whose covariates are not fully recorded, and who is responsible.

    ``model_df.dropna()`` — what every Cox tool used to rely on — only removes rows
    whose NUMERIC covariate failed to parse. A missing CATEGORICAL value survives
    it: :func:`_design_matrix` encodes with ``dummy_na=False``, so an unrecorded
    category becomes all-zero dummies, which is arithmetically the reference level.
    The patient stays in the model silently counted as baseline, and nothing in the
    hazard ratios reveals it. That is a much stronger claim than "adjusted for
    menopausal status", so those rows are dropped here instead, alongside the ones
    dropna would have taken.

    Returns ``(mask, per_covariate)`` where ``mask`` is a positional boolean array
    marking rows to REMOVE. A row missing two covariates is counted under both —
    the point of the tally is to name which column is emptying the cohort, not to
    partition the loss.
    """
    import numpy as np

    n = len(df)
    mask = np.zeros(n, dtype=bool)
    per_covariate: Dict[str, int] = {}
    for alias, orig in cov_map.items():
        if alias not in df.columns:
            continue
        miss = df[alias].isna().to_numpy()
        hit = int(miss.sum())
        if hit:
            per_covariate[orig] = per_covariate.get(orig, 0) + hit
            mask |= miss
    return mask, per_covariate


def _prune_unidentifiable(model_df, features: List[str]):
    """Drop design columns whose coefficient the fit cannot identify.

    A constant column makes lifelines normalize by a zero standard deviation
    (``(X - mean) / std`` → ``0/0``), so the first Newton step is NaN and the fit
    dies with "delta contains nan value(s)" — a message that names nothing and
    that a retry cannot act on. An exact linear combination of the other columns
    does the same through a singular Hessian.

    Dropping them is safe rather than merely convenient: a Cox partial likelihood
    has no intercept, so a constant column shifts every risk set identically and
    cancels out of every comparison. The remaining coefficients are unchanged —
    which is exactly why keeping the column cannot be worth losing the model.

    Returns ``(model_df, features, constant, dependent)`` with the dropped columns
    removed from both.
    """
    keep = [f for f in features if f in getattr(model_df, "columns", [])]
    if not keep:
        return model_df, keep, [], []

    # Judge the columns on the rows the FIT will see. A numeric covariate that
    # failed to parse leaves NaN here, and ``matrix_rank`` on a frame containing
    # NaN reports nonsense rather than raising.
    X = model_df[keep].astype(float).dropna()
    if X.empty:
        return model_df, keep, [], []

    constant = _constant_columns(X)
    if constant:
        keep = [f for f in keep if f not in constant]
        X = X[keep]
    # Rank is only meaningful once there are at least two columns left to be
    # dependent on, and the SVD is the expensive part of this whole check.
    dependent = _dependent_columns(X) if len(keep) > 1 else []
    if dependent:
        keep = [f for f in keep if f not in dependent]

    dropped = constant + dependent
    return (model_df.drop(columns=dropped) if dropped else model_df), keep, constant, dependent


def _unrepresented_covariates(cov_map: Dict[str, str], features: List[str]) -> List[str]:
    """Covariates that produced no design column at all.

    :func:`_design_matrix` one-hot encodes with ``drop_first``, so a covariate with
    exactly ONE observed level yields zero columns and leaves without a word — it
    never reaches :func:`_constant_columns`, which can only judge columns that
    exist. The non-identifiability is the same one, and so is the reason it must be
    said out loud: the fitted model no longer contains a covariate the caller asked
    to adjust for, and no hazard ratio in the output hints at the omission.
    """
    present = set()
    for f in features:
        name = str(f)
        present.add(name.split("=", 1)[0] if "=" in name else name)
    return [orig for orig in dict.fromkeys(cov_map.values()) if orig not in present]


def _design_note(
    n_loaded: int,
    n_used: int,
    per_covariate: Optional[Dict[str, int]] = None,
    constant: Any = (),
    dependent: Any = (),
    unrepresented: Any = (),
) -> str:
    """What the fit quietly lost, in one line — or ``""`` when it lost nothing.

    Appended to the tool's own summary so the number a reader would quote always
    arrives with the cohort it was computed on. Without it a Cox table reports an
    adjustment set that the model may no longer contain.
    """
    bits: List[str] = []
    dropped_rows = int(n_loaded) - int(n_used)
    if dropped_rows > 0:
        worst = sorted((per_covariate or {}).items(), key=lambda kv: -kv[1])[:5]
        blame = ", ".join(f"{k} ({v:,})" for k, v in worst)
        bits.append(
            f"complete-case restriction dropped {dropped_rows:,} of {int(n_loaded):,} "
            "row(s)" + (f" — missing in {blame}" if blame else "")
        )
    if len(list(unrepresented)):
        bits.append(
            f"NOT adjusted for {list(unrepresented)}: single-valued in this cohort, so "
            "the covariate contributes no design column"
        )
    if len(list(constant)):
        bits.append(
            f"dropped constant covariate column(s) {list(constant)}: single-valued in "
            "this cohort, so the coefficient is not identifiable"
        )
    if len(list(dependent)):
        bits.append(
            f"dropped redundant covariate column(s) {list(dependent)}: exact linear "
            "combination(s) of the others"
        )
    return "; ".join(bits)


def _empty_cohort_reason(n_loaded: int, per_covariate: Optional[Dict[str, int]]) -> str:
    """Why nothing survived — named, so the remedy does not need a second run."""
    worst = sorted((per_covariate or {}).items(), key=lambda kv: -kv[1])[:5]
    if worst:
        blame = ", ".join(f"{k} ({v:,} missing)" for k, v in worst)
        return (
            f"Cohort is empty after the complete-case restriction: all {int(n_loaded):,} "
            f"row(s) were missing at least one covariate — {blame}. Drop the barely "
            "recorded covariate(s), or impute first with impute_missing and pass "
            "'imputation_column'."
        )
    return (
        f"Cohort is empty after dropping rows with missing covariates ({int(n_loaded):,} "
        "row(s) loaded). Widen 'where' or check the covariate columns."
    )


# ---------------------------------------------------------------------------
# scikit-learn prediction-model helpers (shared by the ml_* frozen tools)
# ---------------------------------------------------------------------------
# Three layers. Model tools (sklearn class names) FIT once and write
# ``predicted_probability`` on a scored dataset. Evaluation tools READ that
# column and never fit. ``ml_cv_performance`` / ``ml_compare`` are the only
# tools that still take a model key — they refit each fold on purpose.
# The DAG passes parquet tables (never a pickled estimator).

# The model keys the ml_* tools accept, mapped to a short human label.
_ML_MODELS: Dict[str, str] = {
    "elasticnet_logistic": "Elastic Net logistic regression",
    "logistic": "Logistic regression (unpenalized baseline)",
    "random_forest": "Random Forest",
    "gradient_boosting": "Gradient boosting (XGBoost / sklearn)",
}

# Linear models are coefficient-interpretable (odds ratios); tree ensembles are
# importance-interpretable (mean decrease in impurity / gain).
_ML_LINEAR = frozenset({"elasticnet_logistic", "logistic"})


def _sklearn_estimator(
    model: str,
    *,
    random_state: int = 42,
    l1_ratio: float = 0.5,
    cv_folds: int = 10,
    n_estimators: int = 500,
    max_depth: int = 3,
    learning_rate: float = 0.1,
    class_weight: Any = None,
):
    """Build a fresh (unfitted) sklearn-compatible binary classifier.

    Linear models (``elasticnet_logistic`` / ``logistic``) are wrapped in a
    ``StandardScaler`` pipeline — the ``saga`` solver needs standardized inputs
    to converge — so a caller can always ``fit``/``predict_proba`` uniformly.
    Tree ensembles are returned bare. ``gradient_boosting`` prefers
    ``xgboost.XGBClassifier`` and falls back to sklearn's
    ``HistGradientBoostingClassifier`` when xgboost is not installed.

    Returns ``(estimator, kind)`` with ``kind ∈ {"linear", "tree"}``. Raises
    ``ValueError`` for an unknown model key.
    """
    from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    key = str(model or "").strip()
    if key == "elasticnet_logistic":
        clf = LogisticRegressionCV(
            penalty="elasticnet", solver="saga", l1_ratios=[float(l1_ratio)],
            Cs=10, cv=int(cv_folds), max_iter=5000, scoring="roc_auc",
            class_weight=class_weight, n_jobs=-1, random_state=random_state,
        )
        return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), "linear"
    if key == "logistic":
        clf = LogisticRegression(
            penalty=None, solver="lbfgs", max_iter=2000, class_weight=class_weight,
        )
        return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), "linear"
    if key == "random_forest":
        from sklearn.ensemble import RandomForestClassifier

        clf = RandomForestClassifier(
            n_estimators=int(n_estimators), max_features="sqrt",
            min_samples_split=5, min_samples_leaf=2, class_weight=class_weight,
            oob_score=True, bootstrap=True, n_jobs=-1, random_state=random_state,
        )
        return clf, "tree"
    if key == "gradient_boosting":
        try:
            from xgboost import XGBClassifier

            clf = XGBClassifier(
                n_estimators=int(n_estimators), max_depth=int(max_depth),
                learning_rate=float(learning_rate), subsample=0.8,
                colsample_bytree=0.8, eval_metric="auc", random_state=random_state,
                n_jobs=-1,
            )
            return clf, "tree"
        except Exception:  # pragma: no cover — xgboost optional
            from sklearn.ensemble import HistGradientBoostingClassifier

            clf = HistGradientBoostingClassifier(
                max_depth=int(max_depth), learning_rate=float(learning_rate),
                max_iter=int(n_estimators), random_state=random_state,
            )
            return clf, "tree"
    raise ValueError(
        f"Unknown model '{model}'. Choose one of {sorted(_ML_MODELS)}."
    )


# First-class sklearn.linear_model classifiers — catalog keys are the class names.
_SKLEARN_LINEAR_CLFS = (
    "LogisticRegression", "LogisticRegressionCV",
    "PassiveAggressiveClassifier", "Perceptron",
    "RidgeClassifier", "RidgeClassifierCV",
    "SGDClassifier", "SGDOneClassSVM",
)


def _sklearn_linear_estimator(name: str, *, random_state: int = 42, class_weight: Any = None, **hp):
    """Build a fresh sklearn linear classifier, scaled (StandardScaler + clf).

    Catalog key is the sklearn class name. Returns ``(pipeline, meta)`` where
    ``meta["one_class"]`` is true for ``SGDOneClassSVM`` (no labels).
    """
    from sklearn.linear_model import (
        LogisticRegression, LogisticRegressionCV,
        PassiveAggressiveClassifier, Perceptron,
        RidgeClassifier, RidgeClassifierCV, SGDClassifier, SGDOneClassSVM,
    )
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    key = str(name or "").strip()
    max_iter = int(hp["max_iter"]) if hp.get("max_iter") not in (None, "") else 2000
    C = float(hp["C"]) if hp.get("C") not in (None, "") else 1.0
    alpha = float(hp["alpha"]) if hp.get("alpha") not in (None, "") else 0.0001
    l1_ratio = hp.get("l1_ratio")
    l1_ratio = None if l1_ratio in (None, "") else float(l1_ratio)
    penalty = str(hp.get("penalty") or "").strip() or None
    solver = str(hp.get("solver") or "").strip() or None
    cw = class_weight

    if key == "LogisticRegression":
        pen = penalty or "l2"
        if str(pen).lower() in ("none", "null"):
            pen = None
        kwargs: Dict[str, Any] = dict(
            penalty=pen, C=C, solver=solver or ("saga" if pen == "elasticnet" else "lbfgs"),
            max_iter=max_iter, class_weight=cw, random_state=random_state,
        )
        if pen == "elasticnet":
            kwargs["l1_ratio"] = 0.5 if l1_ratio is None else l1_ratio
        clf = LogisticRegression(**kwargs)
    elif key == "LogisticRegressionCV":
        pen = penalty or "l2"
        cv = int(hp["cv"]) if hp.get("cv") not in (None, "") else 5
        kwargs = dict(
            penalty=pen, solver=solver or ("saga" if pen == "elasticnet" else "lbfgs"),
            Cs=10, cv=cv, max_iter=max_iter, scoring="roc_auc",
            class_weight=cw, n_jobs=-1, random_state=random_state,
        )
        if pen == "elasticnet":
            kwargs["l1_ratios"] = [0.5 if l1_ratio is None else l1_ratio]
        clf = LogisticRegressionCV(**kwargs)
    elif key == "PassiveAggressiveClassifier":
        clf = PassiveAggressiveClassifier(
            C=C, max_iter=max_iter, random_state=random_state,
        )
    elif key == "Perceptron":
        clf = Perceptron(
            penalty=penalty, alpha=alpha, max_iter=max_iter,
            class_weight=cw, random_state=random_state,
        )
    elif key == "RidgeClassifier":
        ridge_alpha = float(hp["alpha"]) if hp.get("alpha") not in (None, "") else 1.0
        clf = RidgeClassifier(
            alpha=ridge_alpha, class_weight=cw, random_state=random_state,
        )
    elif key == "RidgeClassifierCV":
        alphas = hp.get("alphas")
        clf = RidgeClassifierCV(
            alphas=alphas if alphas not in (None, "") else (0.1, 1.0, 10.0),
            class_weight=cw, cv=int(hp["cv"]) if hp.get("cv") not in (None, "") else None,
        )
    elif key == "SGDClassifier":
        loss = str(hp.get("loss") or "hinge").strip() or "hinge"
        clf = SGDClassifier(
            loss=loss, penalty=penalty or "l2", alpha=alpha,
            l1_ratio=0.15 if l1_ratio is None else l1_ratio,
            max_iter=max_iter, class_weight=cw, random_state=random_state,
            learning_rate=str(hp.get("learning_rate") or "optimal"),
            eta0=float(hp["eta0"]) if hp.get("eta0") not in (None, "") else 0.0,
        )
    elif key == "SGDOneClassSVM":
        nu = float(hp["nu"]) if hp.get("nu") not in (None, "") else 0.5
        clf = SGDOneClassSVM(
            nu=max(1e-4, min(nu, 1.0)), max_iter=max_iter, random_state=random_state,
        )
    else:
        raise ValueError(
            f"Unknown linear classifier '{name}'. Choose one of {list(_SKLEARN_LINEAR_CLFS)}."
        )
    return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), {
        "one_class": key == "SGDOneClassSVM",
    }


_SKLEARN_SVM_CLFS = ("SVC", "LinearSVC", "NuSVC")
_SKLEARN_TREE_CLFS = (
    "DecisionTreeClassifier", "ExtraTreeClassifier",
    "RandomForestClassifier", "ExtraTreesClassifier",
)
_SKLEARN_BOOST_CLFS = (
    "AdaBoostClassifier", "GradientBoostingClassifier",
    "HistGradientBoostingClassifier",
)


def _sklearn_tree_svm_boost_estimator(
    name: str, *, random_state: int = 42, class_weight: Any = None, **hp
):
    """Build a fresh sklearn SVM / tree / boosting classifier.

    SVM estimators are scaled (StandardScaler + clf). Trees and boosting are
    returned bare — they do not need scaling. Catalog key is the class name.
    """
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    key = str(name or "").strip()
    cw = class_weight
    n_est = int(hp["n_estimators"]) if hp.get("n_estimators") not in (None, "") else 200
    max_depth = hp.get("max_depth")
    max_depth = None if max_depth in (None, "", "None") else int(max_depth)
    C = float(hp["C"]) if hp.get("C") not in (None, "") else 1.0
    nu = float(hp["nu"]) if hp.get("nu") not in (None, "") else 0.5
    lr = float(hp["learning_rate"]) if hp.get("learning_rate") not in (None, "") else 0.1
    min_split = int(hp["min_samples_split"]) if hp.get("min_samples_split") not in (None, "") else 2
    min_leaf = int(hp["min_samples_leaf"]) if hp.get("min_samples_leaf") not in (None, "") else 1
    max_iter = int(hp["max_iter"]) if hp.get("max_iter") not in (None, "") else 2000

    if key == "SVC":
        from sklearn.svm import SVC

        clf = SVC(
            C=C, kernel=str(hp.get("kernel") or "rbf"),
            gamma=hp.get("gamma") or "scale",
            probability=True, class_weight=cw, random_state=random_state,
        )
        return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), {"one_class": False}
    if key == "LinearSVC":
        from sklearn.svm import LinearSVC

        clf = LinearSVC(
            C=C, class_weight=cw, max_iter=max_iter, random_state=random_state,
        )
        return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), {"one_class": False}
    if key == "NuSVC":
        from sklearn.svm import NuSVC

        clf = NuSVC(
            nu=max(1e-4, min(nu, 1.0)), kernel=str(hp.get("kernel") or "rbf"),
            gamma=hp.get("gamma") or "scale",
            probability=True, class_weight=cw, random_state=random_state,
        )
        return Pipeline([("scaler", StandardScaler()), ("clf", clf)]), {"one_class": False}
    if key == "DecisionTreeClassifier":
        from sklearn.tree import DecisionTreeClassifier

        return DecisionTreeClassifier(
            max_depth=max_depth, min_samples_split=min_split,
            min_samples_leaf=min_leaf, class_weight=cw, random_state=random_state,
        ), {"one_class": False}
    if key == "ExtraTreeClassifier":
        from sklearn.tree import ExtraTreeClassifier

        return ExtraTreeClassifier(
            max_depth=max_depth, min_samples_split=min_split,
            min_samples_leaf=min_leaf, class_weight=cw, random_state=random_state,
        ), {"one_class": False}
    if key == "RandomForestClassifier":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(
            n_estimators=n_est, max_depth=max_depth, max_features="sqrt",
            min_samples_split=min_split, min_samples_leaf=min_leaf,
            class_weight=cw, n_jobs=-1, random_state=random_state,
        ), {"one_class": False}
    if key == "ExtraTreesClassifier":
        from sklearn.ensemble import ExtraTreesClassifier

        return ExtraTreesClassifier(
            n_estimators=n_est, max_depth=max_depth, max_features="sqrt",
            min_samples_split=min_split, min_samples_leaf=min_leaf,
            class_weight=cw, n_jobs=-1, random_state=random_state,
        ), {"one_class": False}
    if key == "AdaBoostClassifier":
        from sklearn.ensemble import AdaBoostClassifier

        return AdaBoostClassifier(
            n_estimators=int(hp["n_estimators"]) if hp.get("n_estimators") not in (None, "") else 50,
            learning_rate=lr, random_state=random_state,
        ), {"one_class": False}
    if key == "GradientBoostingClassifier":
        from sklearn.ensemble import GradientBoostingClassifier

        return GradientBoostingClassifier(
            n_estimators=n_est, learning_rate=lr,
            max_depth=3 if max_depth is None else max_depth,
            min_samples_split=min_split, min_samples_leaf=min_leaf,
            random_state=random_state,
        ), {"one_class": False}
    if key == "HistGradientBoostingClassifier":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=int(hp["max_iter"]) if hp.get("max_iter") not in (None, "") else 200,
            learning_rate=lr, max_depth=max_depth, random_state=random_state,
            class_weight=cw,
        ), {"one_class": False}
    raise ValueError(
        f"Unknown SVM/tree/boosting classifier '{name}'. "
        f"Choose one of {list(_SKLEARN_SVM_CLFS + _SKLEARN_TREE_CLFS + _SKLEARN_BOOST_CLFS)}."
    )


def _sklearn_catalog_estimator(name: str, **kw):
    """Dispatch a catalog class name to the matching sklearn factory."""
    key = str(name or "").strip()
    if key in _SKLEARN_LINEAR_CLFS:
        return _sklearn_linear_estimator(name, **kw)
    if key in _SKLEARN_SVM_CLFS + _SKLEARN_TREE_CLFS + _SKLEARN_BOOST_CLFS:
        return _sklearn_tree_svm_boost_estimator(name, **kw)
    raise ValueError(
        f"Unknown sklearn classifier '{name}'. "
        f"Linear: {list(_SKLEARN_LINEAR_CLFS)}; "
        f"SVM: {list(_SKLEARN_SVM_CLFS)}; "
        f"tree: {list(_SKLEARN_TREE_CLFS)}; "
        f"boosting: {list(_SKLEARN_BOOST_CLFS)}."
    )


_SKLEARN_CATALOG = frozenset(
    _SKLEARN_LINEAR_CLFS + _SKLEARN_SVM_CLFS + _SKLEARN_TREE_CLFS + _SKLEARN_BOOST_CLFS
)


def _ml_is_known_model(model: str) -> bool:
    """True for a CV/compare key: sklearn class name or legacy ml_* alias."""
    key = str(model or "").strip()
    return key in _ML_MODELS or key in _SKLEARN_CATALOG


def _ml_known_model_keys() -> List[str]:
    return sorted(_ML_MODELS) + sorted(_SKLEARN_CATALOG)


def _ml_native_scores(est, X):
    """Score a fitted estimator: ``(probability_or_none, decision_or_none)``."""
    import numpy as np

    proba = None
    if hasattr(est, "predict_proba"):
        try:
            proba = np.asarray(_ml_predict_proba(est, X), dtype=float)
        except Exception:
            proba = None
    decision = None
    if hasattr(est, "decision_function"):
        try:
            raw = np.asarray(est.decision_function(X), dtype=float)
            decision = raw[:, -1] if raw.ndim > 1 else raw.ravel()
        except Exception:
            decision = None
    return proba, decision


def _ml_estimator_core(est):
    """The final estimator inside a pipeline (or the estimator itself)."""
    steps = getattr(est, "named_steps", None)
    if steps and "clf" in steps:
        return steps["clf"]
    return est


def _ml_predict_proba(est, X):
    """Positive-class probability vector for a fitted estimator."""
    import numpy as np

    proba = est.predict_proba(X)
    return np.asarray(proba)[:, 1]


def _ml_threshold_metrics(y, p, threshold: float) -> Dict[str, Any]:
    """Sensitivity / specificity / PPV / NPV / accuracy at a probability cut."""
    import numpy as np

    y = np.asarray(y).astype(int)
    pred = (np.asarray(p) >= float(threshold)).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())

    def _ratio(num: int, den: int) -> Optional[float]:
        return round(num / den, 4) if den else None

    return {
        "threshold": round(float(threshold), 4),
        "sensitivity": _ratio(tp, tp + fn),
        "specificity": _ratio(tn, tn + fp),
        "ppv": _ratio(tp, tp + fp),
        "npv": _ratio(tn, tn + fn),
        "accuracy": _ratio(tp + tn, tp + fp + tn + fn),
    }


def _ml_youden_threshold(y, p) -> float:
    """Probability cut maximizing Youden's J (sensitivity + specificity − 1)."""
    import numpy as np
    from sklearn.metrics import roc_curve

    fpr, tpr, thr = roc_curve(np.asarray(y).astype(int), np.asarray(p))
    j = tpr - fpr
    idx = int(np.argmax(j))
    cut = float(thr[idx])
    # roc_curve's first threshold is +inf; guard against a degenerate pick.
    return cut if np.isfinite(cut) else 0.5


# ---------------------------------------------------------------------------
# Causal inference — the estimation core shared by the att_* / ate_* frozen tools
# ---------------------------------------------------------------------------
# Every causal tool (single and loop) funnels into :func:`_causal_point_estimate`,
# so a "run the same estimator over 4 methods / 6 specifications" node is one
# node with a list parameter rather than N sibling nodes that could drift apart.
#
# TWO axes, deliberately separate. METHOD is how the counterfactual mean is
# computed (weighting / outcome regression / matching / doubly robust). ESTIMAND is
# WHOSE effect it is, and it is not a presentation choice: the ATT, the ATE and
# the ATO are three different numbers on the same data whenever the effect varies
# across patients. So the estimand is carried on every result row and locked by
# ``spec_contract`` — a node that omits it is not comparable with one that sets it.

# The estimator's TARGET POPULATION.
#   ATT — "what did the treatment do to the people who actually got it", the
#         question a treated-cohort study asks. Standardized to the treated.
#   ATE — "what would it do if everyone were treated vs. nobody", the
#         population/policy question. Standardized to the whole cohort.
#   ATO — the same contrast restricted to the patients both arms actually contain.
#         Bounded weights, so it stays stable where the ATE's 1/PS explodes.
_ESTIMANDS: Dict[str, str] = {
    "att": "ATT (average treatment effect in the TREATED)",
    "ate": "ATE (average treatment effect in the WHOLE cohort)",
    "ato": "ATO (average treatment effect in the OVERLAP population)",
}

# Method → the estimands it can identify. Matching WITHOUT replacement builds a
# control group *for the treated*, so `psm` is an ATT design by construction and
# there is no honest way to read an ATE off it — it is rejected up front rather
# than silently relabelled.
_METHOD_LABELS: Dict[str, Dict[str, str]] = {
    "ipw": {
        "att": "IPW (ATT weights: 1 for treated, PS/(1-PS) for controls)",
        "ate": "IPW (ATE weights: 1/PS for treated, 1/(1-PS) for controls)",
        "ato": "Overlap weighting (ATO weights: 1-PS for treated, PS for controls)",
    },
    "gcomp": {
        "att": "G-computation (outcome regression standardized to the treated)",
        "ate": "G-computation (outcome regression standardized to the whole cohort)",
        "ato": "G-computation (outcome regression standardized to the overlap population)",
    },
    "psm": {
        "att": "Propensity-score matching (nearest neighbour on the PS logit)",
    },
    "aipw": {
        "att": "AIPW (doubly robust: outcome model + PS weights, in the treated)",
        "ate": "AIPW (doubly robust: outcome model + PS weights, whole cohort)",
        "ato": "AIPW (doubly robust: outcome model + PS weights, overlap population)",
    },
}

# Kept for the ATT tools' own validation messages and for callers that only ever
# offer the ATT method set.
_ATT_METHODS: Dict[str, str] = {
    name: labels["att"] for name, labels in _METHOD_LABELS.items()
}


# The estimands ONE tool family owns. The att_* tools answer the treated-cohort
# question and the ate_* tools the population one; letting a sensitivity row cross
# that line would put two different questions under one "primary" estimate.
_ESTIMAND_FAMILY: Dict[str, Tuple[str, ...]] = {
    "att": ("att",),
    "ate": ("ate", "ato"),
    "ato": ("ate", "ato"),
}

# Estimand → the column name its weights land in. "overlap_weight" rather than
# "ato_weight" because that is what the literature (and ``iptw_weight``) calls it,
# and a downstream `covariate_balance` node has to name the column verbatim.
_DEFAULT_WEIGHT_COLUMN: Dict[str, str] = {
    "att": "att_weight",
    "ate": "ate_weight",
    "ato": "overlap_weight",
}


def _estimand_key(estimand: Any) -> str:
    """``estimand`` normalized to an ``_ESTIMANDS`` key, or ``""`` when unknown."""
    key = str(estimand or "").strip().lower()
    return key if key in _ESTIMANDS else ""


def _estimand_methods(estimand: Any) -> Dict[str, str]:
    """``{method: label}`` for the methods that identify ``estimand``."""
    key = _estimand_key(estimand) or "att"
    return {
        name: labels[key] for name, labels in _METHOD_LABELS.items() if key in labels
    }


def _estimator_label(method: Any, estimand: Any = "att") -> str:
    """Human label for one (method, estimand) pair."""
    name = str(method or "").strip().lower()
    key = _estimand_key(estimand) or "att"
    return (_METHOD_LABELS.get(name) or {}).get(key) or name

# Below this many patients in EITHER arm the ATT is not an estimate, it is a
# diagnostic: the propensity model has nothing left to balance and the bootstrap
# resamples the same handful of people. Such a specification reports WHY it is
# infeasible rather than a number a reader would quote — a complete-case analysis
# that keeps 7 controls says "this covariate is unobservable here", not "the effect
# is -19.8 points".
_ATT_MIN_ARM = 10


def _att_one_draw(frame: Any) -> Any:
    """One imputation draw of ``frame``, which IS its patient list.

    ``_att_id`` numbers SOURCE ROWS, and a multiply imputed input holds m completed
    copies of the same people, so counting ids there reports m x the cohort. Every
    draw carries the same patients, so restricting to one is the patient-level view.
    """
    cols = getattr(frame, "columns", None)
    if cols is None or "_mi" not in list(cols):
        return frame
    seen = frame["_mi"].dropna()
    return frame if seen.empty else frame[frame["_mi"] == seen.iloc[0]]


def _att_attrition(
    raw: Any, loaded: Any, complete: Any, cov_map: Dict[str, str]
) -> Dict[str, Any]:
    """Where the patients went, and which covariates were never recorded.

    Two different losses, deliberately reported apart because they have different
    remedies. LISTWISE DELETION drops a patient outright, and is what a paper's
    attrition figure must show stage by stage (loaded -> complete -> common support)
    rather than as one lump "excluded".

    A missing CATEGORICAL level is not dropped at all: ``_design_matrix`` one-hot
    encodes with ``dummy_na=False``, so an unrecorded category becomes all-zero
    dummies — arithmetically identical to the reference level. The patient is kept
    and silently counted as baseline. That is a far stronger claim than "adjusted
    for menopausal status", and nothing in the estimate reveals it, so the count is
    reported here per covariate and per arm: a covariate recorded in one arm only
    cannot adjust for anything, and seeing that is the whole diagnosis.
    """
    def counts(frame: Any) -> Dict[str, int]:
        one = _att_one_draw(frame)
        treated = one["_treat"].astype(float) == 1
        return {
            "patients": int(one["_att_id"].nunique()),
            "treated": int(one.loc[treated, "_att_id"].nunique()),
            "control": int(one.loc[~treated, "_att_id"].nunique()),
        }

    before, after = counts(loaded), counts(complete)
    out: Dict[str, Any] = {
        "n_loaded": before["patients"],
        "n_complete": after["patients"],
        "n_dropped_incomplete": before["patients"] - after["patients"],
        "treated_loaded": before["treated"],
        "treated_complete": after["treated"],
        "treated_dropped_incomplete": before["treated"] - after["treated"],
        "control_loaded": before["control"],
        "control_complete": after["control"],
        "control_dropped_incomplete": before["control"] - after["control"],
    }

    one = _att_one_draw(raw)
    treated = one["_treat"].astype(float) == 1
    # NOTE: don't write ``getattr(...) or []`` — a pandas Index is ambiguous in a
    # boolean context and raises ValueError.
    cols = getattr(one, "columns", None)
    available = [] if cols is None else list(cols)
    per_cov: Dict[str, Dict[str, int]] = {}
    any_missing = None
    for alias, original in (cov_map or {}).items():
        if alias not in available:
            continue
        missing = one[alias].isna()
        if not bool(missing.any()):
            continue
        per_cov[str(original)] = {
            "missing": int(missing.sum()),
            "treated": int((missing & treated).sum()),
            "control": int((missing & ~treated).sum()),
        }
        any_missing = missing if any_missing is None else (any_missing | missing)
    out["n_covariate_missing"] = 0 if any_missing is None else int(any_missing.sum())
    out["covariate_missing"] = per_cov
    out["covariates_unrecorded"] = "; ".join(
        f"{name}: {d['missing']:,} unrecorded ({d['treated']:,} treated, "
        f"{d['control']:,} control)"
        for name, d in sorted(per_cov.items(), key=lambda kv: -kv[1]["missing"])
    )
    return out


# The cohort-flow columns every ATT row carries, so `loaded -> complete -> analyzed`
# is readable off the result table itself (and survives Rubin pooling unchanged,
# since listwise deletion happens once, before the draws are split).
_ATT_FLOW_KEYS = (
    "n_loaded",
    "n_complete",
    "n_dropped_incomplete",
    "treated_dropped_incomplete",
    "control_dropped_incomplete",
    "n_covariate_missing",
    "covariates_unrecorded",
)


def _att_flow_note(row: Dict[str, Any]) -> str:
    """The cohort flow as one sentence, when listwise deletion actually cost rows.

    Written so the attrition figure can be read straight off the log: a single
    "349 excluded" hides that some were lost to a missing covariate and the rest
    to common support, which are different objections with different remedies.
    """
    loaded = _num(row.get("n_loaded"))
    complete = _num(row.get("n_complete"))
    analyzed = _num(row.get("n_analyzed"))
    if loaded is None or complete is None or analyzed is None:
        return ""
    unrecorded = str(row.get("covariates_unrecorded") or "").strip()
    if loaded == complete == analyzed and not unrecorded:
        return ""
    note = (
        f" Cohort flow: {int(loaded):,} loaded -> {int(complete):,} complete "
        f"-> {int(analyzed):,} analyzed (common support)."
    )
    dropped = _num(row.get("n_dropped_incomplete")) or 0
    if dropped:
        note += (
            f" Listwise deletion cost {int(dropped):,} patient(s) "
            f"({int(_num(row.get('treated_dropped_incomplete')) or 0):,} treated, "
            f"{int(_num(row.get('control_dropped_incomplete')) or 0):,} control), so "
            f"this estimate is conditional on those covariates being recorded."
        )
    if unrecorded:
        kept = int(_num(row.get("n_covariate_missing")) or 0)
        note += (
            f" WARNING — {kept:,} analyzed patient(s) were KEPT with a covariate that "
            f"was never recorded and are therefore modelled at its reference level, "
            f"not adjusted for it ({unrecorded}). A covariate recorded in one arm only "
            f"cannot adjust for confounding: impute it (impute_missing) or drop it."
        )
    return note


def _att_infeasible_cause(attrition: Dict[str, Any], where: str = "") -> str:
    """Name what emptied the arm, so the remedy is obvious from the message alone."""
    filt = str(where or "").strip()
    looks_complete_case = bool(filt) and (
        "is not null" in filt.lower() or "is null" in filt.lower()
    )
    if looks_complete_case:
        return (
            f"This node's own filter already restricted the cohort to "
            f"{int(attrition.get('n_loaded') or 0):,} patient(s) before estimation "
            f"(where: {filt[:160]}). A complete-case restriction on a barely recorded "
            f"covariate is the usual cause: it does not adjust for that covariate, it "
            f"deletes whichever arm rarely has it. Impute instead (impute_missing), or "
            f"report this as the missingness finding."
        )
    dropped = attrition.get("n_dropped_incomplete") or 0
    if dropped:
        return (
            f"Listwise deletion on the covariates removed {int(dropped):,} patient(s) "
            f"({int(attrition.get('treated_dropped_incomplete') or 0):,} treated, "
            f"{int(attrition.get('control_dropped_incomplete') or 0):,} control) from "
            f"{int(attrition.get('n_loaded') or 0):,}, so at least one covariate here "
            f"is observed almost only in one arm."
        )
    unrecorded = str(attrition.get("covariates_unrecorded") or "").strip()
    if unrecorded:
        return f"Covariates that are barely recorded: {unrecorded}."
    loaded = int(attrition.get("n_loaded") or 0)
    if loaded:
        return (
            f"Common support emptied the arms: {loaded:,} patients were loaded but "
            f"overlap/trimming left too few in one arm. A covariate that almost "
            f"classifies exposure (for example a value recorded in only one arm) is "
            f"the usual cause — this is a positivity failure, not a cohort-definition one."
        )
    return (
        "The arms were already this small before any covariate was applied, so this is "
        "a cohort-definition problem rather than a missing-data one."
    )


def _clip_pair(clip_bounds: Any, default: Tuple[float, float] = (1e-6, 1 - 1e-6)):
    """Parse ``[lo, hi]`` propensity clip bounds → a valid ``(lo, hi)`` pair."""
    if not clip_bounds:
        return default
    try:
        lo, hi = (float(x) for x in list(clip_bounds)[:2])
    except Exception:
        return default
    return (lo, hi) if 0.0 < lo < hi < 1.0 else default


def _fit_propensity(X, t, *, seed: int = 42, clip_bounds: Any = None):
    """P(T=1 | X) from a standardized L2 logistic model, clipped away from 0/1.

    A mildly penalized fit is deliberate: an unpenalized propensity model
    separates whenever one covariate level is exclusive to an arm, and the
    resulting PS of ~0/1 blows the ATT weights up by orders of magnitude.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    est = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000,
                                   random_state=int(seed))),
    ])
    est.fit(X, np.asarray(t).astype(int))
    ps = np.asarray(est.predict_proba(X))[:, 1]
    lo, hi = _clip_pair(clip_bounds)
    return np.clip(ps, lo, hi)


def _att_weight_vector(ps, t):
    """ATT weights: the treated keep weight 1, controls are re-weighted by the
    odds of treatment so they stand in for the treated population."""
    import numpy as np

    ps = np.asarray(ps, dtype=float)
    t = np.asarray(t).astype(int)
    return np.where(t == 1, 1.0, ps / np.maximum(1.0 - ps, 1e-12))


def _ate_weight_vector(ps, t):
    """ATE (IPTW) weights: 1/PS for the treated, 1/(1-PS) for the controls.

    Both arms are re-weighted to stand in for the WHOLE cohort, which is what
    makes the contrast a population effect rather than a treated-cohort one. The
    price is that a propensity score near 0 or 1 produces an enormous weight —
    clip (``clip_bounds``) or use the ATO instead when that happens.
    """
    import numpy as np

    ps = np.asarray(ps, dtype=float)
    t = np.asarray(t).astype(int)
    return np.where(
        t == 1, 1.0 / np.maximum(ps, 1e-12), 1.0 / np.maximum(1.0 - ps, 1e-12)
    )


def _ato_weight_vector(ps, t):
    """ATO (overlap) weights: 1-PS for the treated, PS for the controls.

    Li, Morgan & Zaslavsky's overlap weights. Bounded by construction, so a
    patient whose treatment was nearly determined loses influence instead of
    dominating the estimate the way 1/PS lets it.
    """
    import numpy as np

    ps = np.asarray(ps, dtype=float)
    t = np.asarray(t).astype(int)
    return np.where(t == 1, 1.0 - ps, ps)


def _causal_weight_vector(ps, t, *, estimand: str = "att"):
    """The per-patient weight vector targeting ``estimand``."""
    key = _estimand_key(estimand) or "att"
    if key == "ate":
        return _ate_weight_vector(ps, t)
    if key == "ato":
        return _ato_weight_vector(ps, t)
    return _att_weight_vector(ps, t)


def _tilt_weights(ps, *, estimand: str):
    """Population tilting function used to standardize outcome-model predictions.

    ``None`` for the ATE (every patient counts once) and ``PS(1-PS)`` for the ATO
    (the overlap population's density). The ATT tilts by treatment status, which
    the callers handle by selecting the treated rows directly.
    """
    import numpy as np

    if _estimand_key(estimand) != "ato":
        return None
    ps = np.asarray(ps, dtype=float)
    h = ps * (1.0 - ps)
    if float(h.sum()) <= 0:
        raise ValueError("overlap weights sum to zero")
    return h


def _overlap_mask(ps, t, *, trim: float = 0.0):
    """Common-support mask: PS inside the range shared by both arms.

    ``trim`` additionally drops rows whose PS falls outside ``[trim, 1-trim]``
    (the usual 0.01/0.05 asymmetric-trimming rule).
    """
    import numpy as np

    ps = np.asarray(ps, dtype=float)
    t = np.asarray(t).astype(int) == 1
    if not t.any() or not (~t).any():
        return np.ones(len(ps), dtype=bool)
    lo = max(ps[t].min(), ps[~t].min())
    hi = min(ps[t].max(), ps[~t].max())
    mask = (ps >= lo) & (ps <= hi)
    try:
        cut = float(trim)
    except (TypeError, ValueError):
        cut = 0.0
    if 0.0 < cut < 0.5:
        mask &= (ps >= cut) & (ps <= 1.0 - cut)
    return mask


def _psm_match_weights(ps, t, *, ratio: int = 1, caliper: float = 0.2, seed: int = 42):
    """Greedy nearest-neighbour ATT matching on the PS logit, without replacement.

    Returns ``(treated_mask, control_weight)``: matched treated units are True,
    and each matched control carries ``1/k`` so every treated unit contributes
    the same total control weight regardless of how many partners it found.
    ``caliper`` is in standard deviations of the logit (Austin's 0.2 default).
    """
    import numpy as np

    ps = np.asarray(ps, dtype=float)
    t = np.asarray(t).astype(int)
    logit = np.log(ps / np.maximum(1.0 - ps, 1e-12))
    sd = float(np.std(logit)) or 1.0
    width = float(caliper) * sd if float(caliper) > 0 else np.inf
    k = max(1, int(ratio))

    treated_idx = np.flatnonzero(t == 1)
    control_idx = np.flatnonzero(t == 0)
    matched_treated = np.zeros(len(ps), dtype=bool)
    cweight = np.zeros(len(ps), dtype=float)
    if len(treated_idx) == 0 or len(control_idx) == 0:
        return matched_treated, cweight

    # Controls sorted by logit → each treated unit's neighbours are a window
    # around its insertion point, so matching stays O(n log n) at SEER scale.
    order = control_idx[np.argsort(logit[control_idx], kind="stable")]
    clogit = logit[order]
    used = np.zeros(len(order), dtype=bool)
    rng = np.random.default_rng(int(seed))
    for i in rng.permutation(treated_idx):
        pos = int(np.searchsorted(clogit, logit[i]))
        lo, hi = pos - 1, pos
        picked: List[int] = []
        while len(picked) < k:
            dlo = abs(logit[i] - clogit[lo]) if lo >= 0 else np.inf
            dhi = abs(clogit[hi] - logit[i]) if hi < len(clogit) else np.inf
            if not np.isfinite(dlo) and not np.isfinite(dhi):
                break
            if dlo <= dhi:
                if not used[lo] and dlo <= width:
                    picked.append(lo)
                elif dlo > width:
                    break
                lo -= 1
            else:
                if not used[hi] and dhi <= width:
                    picked.append(hi)
                elif dhi > width:
                    break
                hi += 1
        if not picked:
            continue
        matched_treated[i] = True
        share = 1.0 / len(picked)
        for j in picked:
            used[j] = True
            cweight[order[j]] += share
    return matched_treated, cweight


def _fit_outcome(X, y, *, binary: bool, seed: int = 42):
    """Outcome regression used by g-computation / AIPW (logistic or linear)."""
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = (
        LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000, random_state=int(seed))
        if binary
        else Ridge(alpha=1.0, random_state=int(seed))
    )
    est = Pipeline([("scaler", StandardScaler()), ("model", model)])
    est.fit(X, y)
    return est


def _outcome_predict(est, X, *, binary: bool):
    import numpy as np

    if binary:
        return np.asarray(est.predict_proba(X))[:, 1]
    return np.asarray(est.predict(X), dtype=float)


def _causal_point_estimate(
    X,
    t,
    y,
    *,
    method: str = "ipw",
    estimand: str = "att",
    binary: bool = True,
    seed: int = 42,
    clip_bounds: Any = None,
    ratio: int = 1,
    caliper: float = 0.2,
) -> Dict[str, Any]:
    """ONE causal estimate by ONE (method, estimand) pair — the single source of
    truth for the att_* / ate_* tools.

    Returns ``{mu0, mu1, effect, ratio, n_treated, n_control}`` where ``effect``
    is the risk/mean DIFFERENCE over the estimand's target population and
    ``ratio`` the risk ratio (binary outcomes only). The propensity model is
    re-fitted here rather than passed in, so a bootstrap replicate re-estimates
    it — treating an estimated PS as fixed understates the variance.

    Raises ``ValueError`` when an arm is empty, when the method cannot identify
    the requested estimand, or when matching finds no partners.
    """
    import numpy as np

    Xa = np.asarray(X, dtype=float)
    t = np.asarray(t).astype(int)
    y = np.asarray(y, dtype=float)
    treated = t == 1
    n1, n0 = int(treated.sum()), int((~treated).sum())
    if n1 == 0 or n0 == 0:
        raise ValueError("both treated and control patients are required")

    m = str(method or "ipw").strip().lower()
    if m not in _METHOD_LABELS:
        raise ValueError(
            f"unknown method '{method}'. Choose one of {sorted(_METHOD_LABELS)}."
        )
    est = _estimand_key(estimand)
    if not est:
        raise ValueError(
            f"unknown estimand '{estimand}'. Choose one of {sorted(_ESTIMANDS)}."
        )
    if est not in _METHOD_LABELS[m]:
        raise ValueError(
            f"method '{m}' cannot identify the {est.upper()}: matching without "
            f"replacement builds a control group FOR THE TREATED, so it only "
            f"identifies the ATT. Use "
            f"{', '.join(sorted(_estimand_methods(est)))} instead."
        )

    if m == "gcomp":
        # Fit ONE outcome model on treatment + covariates, then read both potential
        # outcomes off the ESTIMAND's target population: the treated rows for the
        # ATT, every row for the ATE, every row tilted by PS(1-PS) for the ATO.
        #
        # NOTE the model is additive in treatment (no T×X interaction), so for a
        # CONTINUOUS outcome it fits a constant effect and the three estimands come
        # out identical by construction. Agreement between a gcomp ATT and ATE is
        # therefore not evidence that the effect is homogeneous — check ipw/aipw,
        # which standardize the data rather than the model.
        design = np.column_stack([t.astype(float), Xa])
        model = _fit_outcome(design, y, binary=binary, seed=seed)
        d1, d0 = design.copy(), design.copy()
        d1[:, 0], d0[:, 0] = 1.0, 0.0
        p1 = _outcome_predict(model, d1, binary=binary)
        p0 = _outcome_predict(model, d0, binary=binary)
        if est == "att":
            mu1, mu0 = float(np.mean(p1[treated])), float(np.mean(p0[treated]))
        elif est == "ate":
            mu1, mu0 = float(np.mean(p1)), float(np.mean(p0))
        else:
            # Only the ATO needs a propensity model here — fitting one for the ATE
            # would double the cost of every bootstrap replicate for nothing.
            h = _tilt_weights(
                _fit_propensity(Xa, t, seed=seed, clip_bounds=clip_bounds), estimand=est
            )
            mu1 = float(np.average(p1, weights=h))
            mu0 = float(np.average(p0, weights=h))
        n_used_t, n_used_c = n1, n0
    else:
        ps = _fit_propensity(Xa, t, seed=seed, clip_bounds=clip_bounds)
        if m == "ipw":
            # ATT weights are 1 in the treated arm, so this reduces to the observed
            # treated mean there and stays the weighted mean for the ATE / ATO.
            w = _causal_weight_vector(ps, t, estimand=est)
            wt, wc = w[treated], w[~treated]
            if wt.sum() <= 0 or wc.sum() <= 0:
                raise ValueError("treated or control weights sum to zero")
            mu1 = float(np.average(y[treated], weights=wt))
            mu0 = float(np.average(y[~treated], weights=wc))
            n_used_t, n_used_c = n1, n0
        elif m == "psm":
            mt, cw = _psm_match_weights(ps, t, ratio=ratio, caliper=caliper, seed=seed)
            if not mt.any() or cw.sum() <= 0:
                raise ValueError("no treated patient found a control within the caliper")
            mu1 = float(np.mean(y[mt]))
            mu0 = float(np.average(y[cw > 0], weights=cw[cw > 0]))
            n_used_t, n_used_c = int(mt.sum()), int((cw > 0).sum())
        else:  # aipw — doubly robust: consistent if EITHER model is right
            if est == "att":
                m0est = _fit_outcome(Xa[~treated], y[~treated], binary=binary, seed=seed)
                m0 = _outcome_predict(m0est, Xa, binary=binary)
                odds = ps / np.maximum(1.0 - ps, 1e-12)
                mu1 = float(np.mean(y[treated]))
                mu0 = float(
                    (m0[treated].sum() + (odds[~treated] * (y[~treated] - m0[~treated])).sum()) / n1
                )
            else:
                # Each arm gets its OWN outcome model, and each patient's augmented
                # score is that prediction corrected by the arm's inverse-probability
                # weighted residual — the standard AIPW influence function. Averaging
                # it over everyone gives the ATE; tilting by PS(1-PS) gives the ATO.
                m1est = _fit_outcome(Xa[treated], y[treated], binary=binary, seed=seed)
                m0est = _fit_outcome(Xa[~treated], y[~treated], binary=binary, seed=seed)
                m1 = _outcome_predict(m1est, Xa, binary=binary)
                m0 = _outcome_predict(m0est, Xa, binary=binary)
                tf = t.astype(float)
                psi1 = m1 + tf * (y - m1) / np.maximum(ps, 1e-12)
                psi0 = m0 + (1.0 - tf) * (y - m0) / np.maximum(1.0 - ps, 1e-12)
                h = _tilt_weights(ps, estimand=est)
                mu1 = float(np.mean(psi1) if h is None else np.average(psi1, weights=h))
                mu0 = float(np.mean(psi0) if h is None else np.average(psi0, weights=h))
            n_used_t, n_used_c = n1, n0

    out: Dict[str, Any] = {
        "mu0": mu0, "mu1": mu1, "effect": mu1 - mu0,
        "n_treated": n_used_t, "n_control": n_used_c,
    }
    out["ratio"] = (mu1 / mu0) if (binary and mu0 > 0) else None
    return out


def _causal_effect_with_ci(
    X,
    t,
    y,
    *,
    method: str,
    binary: bool,
    seed: int,
    clip_bounds: Any,
    ratio: int,
    caliper: float,
    n_bootstrap: int,
    estimand: str = "att",
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Point estimate + percentile bootstrap CI (the whole estimator is resampled).

    ``n_bootstrap=0`` skips the CI, which is the right call for ``psm`` on a
    large cohort: every replicate re-matches, so the resampling — not the
    estimate — dominates the runtime.
    """
    import numpy as np

    point = _causal_point_estimate(
        X, t, y, method=method, estimand=estimand, binary=binary, seed=seed,
        clip_bounds=clip_bounds, ratio=ratio, caliper=caliper,
    )
    try:
        reps = max(0, int(n_bootstrap))
    except (TypeError, ValueError):
        reps = 0
    point["n_bootstrap"] = reps
    if reps < 20:
        point["effect_lower95"] = point["effect_upper95"] = None
        point["effect_se"] = None
        return point

    Xa = np.asarray(X, dtype=float)
    ta = np.asarray(t).astype(int)
    ya = np.asarray(y, dtype=float)
    rng = np.random.default_rng(int(seed))
    n = len(ta)
    draws: List[float] = []
    beat = _ToolHeartbeat(
        f"{(_estimand_key(estimand) or 'att').upper()} {method} bootstrap", reps
    )
    beat.start()
    for i in range(reps):
        idx = rng.integers(0, n, size=n)
        try:
            rep = _causal_point_estimate(
                Xa[idx], ta[idx], ya[idx], method=method, estimand=estimand,
                binary=binary, seed=seed,
                clip_bounds=clip_bounds, ratio=ratio, caliper=caliper,
            )
        except Exception:
            beat.tick(i + 1)
            continue  # a degenerate replicate (empty arm / no match) is dropped
        draws.append(float(rep["effect"]))
        beat.tick(i + 1)
    beat.done()
    if len(draws) < max(20, reps // 4):
        point["effect_lower95"] = point["effect_upper95"] = None
        point["effect_se"] = None
        point["n_bootstrap"] = len(draws)
        return point
    lo, hi = np.percentile(draws, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    point["effect_lower95"] = float(lo)
    point["effect_upper95"] = float(hi)
    # The bootstrap SD is the WITHIN-sample variance Rubin's rules need when this
    # estimate is one of several imputation draws (see _rubin_pool).
    point["effect_se"] = float(np.std(draws, ddof=1))
    point["n_bootstrap"] = len(draws)
    return point


def _round_causal_row(row: Dict[str, Any], digits: int = 5) -> Dict[str, Any]:
    """Round the numeric fields of a causal result row for the output table."""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        out[k] = round(float(v), digits) if isinstance(v, float) else v
    return out


# ── multiple imputation: with() + pool() ────────────────────────────────────
#
# ``impute_missing(n_imputations=m)`` returns ONE table holding m completed
# copies of the SAME patients, tagged by ``_imputation``. Read as a single
# cohort it counts every patient m times, so n, the bootstrap CI and every
# "patients affected" figure come out m-fold wrong — and a node that happens to
# divide by m disagrees with one that does not.
#
# So an estimator does what mice's ``with()`` / ``pool()`` do: run the SAME
# estimate INSIDE each draw, then combine the m results by Rubin's rules
# (total variance = within-draw + between-draw). Patient counts stay per draw,
# which is the unique-patient count. This is not a parameter the planner has to
# remember: the tools detect the column, exactly as ``mids`` makes R's
# ``coxph`` unusable on stacked draws by accident.
#
# Two shapes of the same thing. A tool that computes ONE estimate loops the draws
# itself and calls :func:`_rubin_pool` (the ``att_*`` family). A tool whose result
# is a long coefficient TABLE is instead re-run per draw by
# :meth:`SeerToolbox._mi_pool_tool` and its m tables combined term by term by
# :func:`_pool_model_tables` (the ``cox_*`` family) — the fit, the design matrix
# and the covariance stay exactly what the single-dataset tool produces.

MI_COLUMN = "_imputation"
# Per-draw bootstrap floor. Rubin's within-variance is the MEAN of m bootstrap
# variances, so its precision already improves by √m — 50 reps × 20 draws is as
# precise a within term as 1000 reps on one draw, at the same total cost.
_MI_MIN_REPS = 50


def _mi_disabled(imputation_column: Any) -> bool:
    """``imputation_column="none"`` opts out of pooling (analyse the stack as-is)."""
    return str(imputation_column or "").strip().lower() in ("none", "off", "false")


def _mi_column(imputation_column: Any = None) -> str:
    """The draw-index column to look for (explicit name wins over the default)."""
    name = _bare(imputation_column or "")
    return name or MI_COLUMN


def _has_column(con, relation: str, column: str) -> bool:
    try:
        con.execute(f"SELECT {_q(column)} FROM {_q(relation)} LIMIT 0")
        return True
    except Exception:
        return False


def _mi_draw_ids(
    con, source: str, where: str = "", imputation_column: Any = None
) -> List[Any]:
    """Sorted draw ids in ``source``, or ``[]`` when it is not a stack of draws."""
    if _mi_disabled(imputation_column):
        return []
    col = _mi_column(imputation_column)
    src = (source or "seer").strip() or "seer"
    sql = f"SELECT DISTINCT {_q(col)} AS d FROM {_q(src)}"
    w = str(where or "").strip()
    if w:
        sql += f" WHERE ({w})"
    try:
        rows = con.execute(sql + " ORDER BY d").fetchall()
    except Exception:
        return []  # no such column → an ordinary one-row-per-patient cohort
    ids = [r[0] for r in rows if r[0] is not None]
    return ids if len(ids) > 1 else []


def _mi_where(where: str, draw: Any, imputation_column: Any = None) -> str:
    """``where`` narrowed to ONE imputation draw."""
    col = _mi_column(imputation_column)
    lit = (
        str(draw)
        if isinstance(draw, (int, float)) and not isinstance(draw, bool)
        else "'" + str(draw).replace("'", "''") + "'"
    )
    one = f"{_q(col)} = {lit}"
    w = str(where or "").strip()
    return f"({w}) AND {one}" if w else one


def _mi_reps(n_bootstrap: Any, m: int) -> int:
    """Bootstrap replicates PER DRAW so m draws cost what one draw used to."""
    try:
        reps = max(0, int(n_bootstrap))
    except (TypeError, ValueError):
        reps = 0
    if reps <= 0 or m <= 1:
        return reps
    return max(_MI_MIN_REPS, int(round(reps / float(m))))


# Stand-in for "the complete-data reference distribution" (t with this many df is
# the normal to 6 decimals) when the draws leave no between-imputation variance.
_MI_DF_COMPLETE = 1.0e6


def _t_crit(df: float, alpha: float = 0.05) -> float:
    """Two-sided t critical value, falling back to the normal quantile."""
    try:
        from scipy import stats

        return float(stats.t.ppf(1.0 - alpha / 2.0, max(1.0, float(df))))
    except Exception:
        return 1.959963984540054


def _num(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None. Tolerates numpy scalars and NaN."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if (f == f and f not in (float("inf"), float("-inf"))) else None


def _mean_or_none(values: Sequence[Any]) -> Optional[float]:
    nums = [f for f in (_num(v) for v in values) if f is not None]
    return (sum(nums) / len(nums)) if nums else None


def _round_or_none(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _two_sided_p(statistic: float, df: float) -> Optional[float]:
    """Two-sided p for a t statistic, falling back to the normal approximation."""
    stat = _num(statistic)
    if stat is None:
        return None
    try:
        from scipy import stats

        return float(2.0 * stats.t.sf(abs(stat), max(1.0, float(df))))
    except Exception:
        import math

        return float(math.erfc(abs(stat) / math.sqrt(2.0)))


# Columns that count PATIENTS (or events) rather than measuring something: pooled
# by averaging over draws, because every draw holds the same cohort once.
_MI_COUNT_COLS = frozenset({
    "n", "events", "n_ref", "n_exposed", "n_analyzed", "n_treated", "n_control",
    "n_missing", "n_flagged", "n_in_overlap",
})
# (point estimate, lower, upper) triples reported on the RATIO scale, i.e. the
# exponential of the pooled coefficient.
_MI_RATIO_TRIPLES = (
    ("hazard_ratio", "hr_lower95", "hr_upper95"),
    ("odds_ratio", "or_lower95", "or_upper95"),
)


def _pool_model_tables(tables: Sequence[Any], key_cols: Sequence[str]) -> Any:
    """Rubin-pool m per-draw model tables that share one row key → one table.

    The other half of :func:`_rubin_pool`: each table is the SAME model fitted on
    one completed dataset, so rows are matched on ``key_cols`` and combined term
    by term. A row carrying ``coef`` + ``se`` is pooled properly (the ratio
    columns and the p-value are recomputed from the pooled coefficient); the rest
    — reference rows, Wald blocks, assumption tests — are averaged, counts are
    averaged back onto the PATIENT scale, and a boolean flag takes the majority
    verdict across draws.
    """
    import pandas as pd

    frames = [t for t in tables if t is not None and len(t)]
    if not frames:
        return pd.DataFrame()
    base = frames[0]
    keys = [c for c in key_cols if c in base.columns]
    numeric = [
        c for c in base.columns
        if pd.api.types.is_numeric_dtype(base[c]) and not pd.api.types.is_bool_dtype(base[c])
    ]
    booleans = [c for c in base.columns if pd.api.types.is_bool_dtype(base[c])]
    pooled_coef = "coef" in base.columns and "se" in base.columns

    def row_key(row) -> Tuple[str, ...]:
        return tuple("" if row.get(c) is None else str(row.get(c)) for c in keys)

    lookups: List[Dict[Tuple[str, ...], Any]] = []
    for f in frames:
        seen: Dict[Tuple[str, ...], Any] = {}
        for _, r in f.iterrows():
            seen.setdefault(row_key(r), r)
        lookups.append(seen)

    out_rows: List[Dict[str, Any]] = []
    for _, first in base.iterrows():
        k = row_key(first)
        matches = [lk[k] for lk in lookups if k in lk]
        row: Dict[str, Any] = {c: first.get(c) for c in base.columns}
        coef0 = _num(first.get("coef")) if pooled_coef else None

        if coef0 is not None:
            pooled = _rubin_pool(
                [r.get("coef") for r in matches],
                [
                    None if _num(r.get("se")) is None else float(_num(r.get("se"))) ** 2
                    for r in matches
                ],
            )
            est, se = pooled.get("estimate"), pooled.get("se")
            row["coef"] = _round_or_none(est, 5)
            row["se"] = _round_or_none(se, 5)
            for point, lo, hi in _MI_RATIO_TRIPLES:
                if point in row and est is not None:
                    row[point] = round(float(_np_exp(est)), 5)
                    if lo in row and pooled.get("ci_lower") is not None:
                        row[lo] = round(float(_np_exp(pooled["ci_lower"])), 5)
                        row[hi] = round(float(_np_exp(pooled["ci_upper"])), 5)
            stat = (est / se) if (est is not None and se) else None
            for c in ("statistic", "z"):
                if c in row:
                    row[c] = _round_or_none(stat, 4)
            if "p" in row:
                row["p"] = _round_or_none(
                    _two_sided_p(stat, pooled.get("df", max(1, len(matches) - 1))), 6
                ) if stat is not None else None
            row["fmi"] = _round_or_none(pooled.get("fmi"), 4)

        for c in numeric:
            if c in keys or (coef0 is not None and c in
                             ("coef", "se", "statistic", "z", "p", "fmi",
                              "hazard_ratio", "hr_lower95", "hr_upper95",
                              "odds_ratio", "or_lower95", "or_upper95")):
                continue
            mean = _mean_or_none([r.get(c) for r in matches])
            row[c] = (
                None if mean is None
                else int(round(mean)) if c in _MI_COUNT_COLS
                else round(mean, 6)
            )
        for c in booleans:
            share = _mean_or_none([1.0 if bool(r.get(c)) else 0.0 for r in matches])
            row[c] = None if share is None else bool(share >= 0.5)
        row["n_imputations"] = len(matches)
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def _np_exp(value: float) -> float:
    import numpy as np

    return float(np.exp(float(value)))


def _rubin_pool(
    estimates: Sequence[Any],
    variances: Optional[Sequence[Any]] = None,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Combine per-imputation estimates by Rubin's rules.

    ``estimates`` are the m point estimates and ``variances`` their WITHIN-draw
    sampling variances (here the bootstrap variance). The pooled point estimate
    is their mean; the pooled variance is ``within + (1 + 1/m) × between``, so an
    analysis run on m completed datasets carries the imputation uncertainty the
    stacked-table shortcut throws away. Returns ``{}`` when nothing is usable.

    Without usable within-variances the between term alone is reported and
    ``within_variance`` is False — a CI that is too NARROW, flagged rather than
    passed off as complete.
    """
    import numpy as np

    q = np.asarray(
        [f for f in (_num(v) for v in estimates) if f is not None],
        dtype=float,
    )
    if q.size == 0:
        return {}
    m = int(q.size)
    qbar = float(q.mean())
    out: Dict[str, Any] = {"estimate": qbar, "m": m}

    u = np.asarray(
        [f for f in (_num(v) for v in (variances or [])) if f is not None],
        dtype=float,
    )
    ubar = float(u.mean()) if u.size else float("nan")
    between = float(q.var(ddof=1)) if m > 1 else 0.0
    inflate = (1.0 + 1.0 / m) * between

    has_within = bool(u.size) and np.isfinite(ubar)
    total = (ubar if has_within else 0.0) + inflate
    out["within_variance"] = has_within
    out["between_variance"] = between
    if total <= 0:
        out["se"] = None
        out["ci_lower"] = out["ci_upper"] = None
        out["fmi"] = None
        return out
    se = float(total**0.5)
    if has_within and ubar > 0:
        if inflate > 0:
            r = inflate / ubar
            df = (m - 1) * (1.0 + 1.0 / r) ** 2
        else:
            # The draws agree exactly, so imputation costs no information: the
            # pooled variance IS the within variance and the reference
            # distribution is the complete-data one, NOT t on m-1 (which would
            # widen a CI that has nothing extra to account for).
            df = _MI_DF_COMPLETE
    else:
        df = max(1, m - 1)
    crit = _t_crit(df, alpha)
    out["se"] = se
    out["df"] = float(df)
    out["ci_lower"] = qbar - crit * se
    out["ci_upper"] = qbar + crit * se
    out["fmi"] = float(inflate / total)
    return out


def _mi_note(row: Dict[str, Any]) -> str:
    """One sentence stating that a result was pooled, so the reader of the log
    (and of the report) knows the counts are per patient, not per stacked row."""
    try:
        m = int(row.get("n_imputations") or 0)
    except (TypeError, ValueError):
        return ""
    if m < 2:
        return ""
    used = row.get("n_imputations_used") or m
    note = (
        f" Estimated in each of {used}/{m} imputation draw(s) and pooled by "
        f"Rubin's rules — the n above counts PATIENTS, not imputed rows."
    )
    if row.get("variance_method") == "rubin_between_only":
        note += (
            " No within-draw variance was available (bootstrap off), so the CI "
            "reflects between-imputation variation only and is too narrow."
        )
    per_draw, total = row.get("n_bootstrap_per_draw"), row.get("n_bootstrap_total")
    requested = row.get("n_bootstrap_requested")
    if per_draw and total:
        note += (
            f" Bootstrap: {per_draw} replicate(s) per draw = {total} in total"
            + (f" (requested {requested})." if requested else ".")
        )
    fmi = row.get("fmi")
    if isinstance(fmi, (int, float)):
        note += f" Fraction of missing information {round(float(fmi), 3)}."
    return note


def _evalue_from_ratio(rr: Optional[float]) -> Optional[float]:
    """E-value for a risk/hazard/odds RATIO (VanderWeele & Ding 2017).

    The E-value is the minimum strength of association — on the ratio scale —
    that an unmeasured confounder would need with BOTH exposure and outcome to
    explain away the observed estimate. Ratios below 1 are inverted first, since
    the measure is symmetric about the null.
    """
    if rr is None:
        return None
    try:
        r = float(rr)
    except (TypeError, ValueError):
        return None
    if r <= 0:
        return None
    if r < 1:
        r = 1.0 / r
    return round(r + (r * (r - 1.0)) ** 0.5, 4)


def _bounding_factor(rr_ud: float, rr_eu: float) -> float:
    """Ding & VanderWeele bounding factor for an unmeasured confounder U.

    ``rr_ud`` is U's association with the outcome, ``rr_eu`` U's association
    with the exposure; the maximum bias an unmeasured U of that strength can
    produce is this factor, so dividing the observed ratio by it gives the
    bias-adjusted estimate.
    """
    a, b = float(rr_ud), float(rr_eu)
    denom = a + b - 1.0
    if denom <= 0:
        return 1.0
    return (a * b) / denom


def _contrast_stats(params, cov_matrix, weights: Dict[str, float]):
    """Point estimate, SE, z and p for the linear combination ``L'β``.

    ``weights`` maps a design-matrix term to its coefficient in the contrast. The
    variance is ``L'VL``, which needs the OFF-DIAGONAL covariances — that is why a
    contrast can never be recovered from a coefficient table alone and has to be
    computed here, while the fitted covariance matrix still exists.
    """
    import numpy as np
    from scipy import stats

    terms = [t for t in weights if t in params.index]
    if not terms:
        return None, None, None, None
    L = np.array([float(weights[t]) for t in terms], dtype=float)
    b = params.loc[terms].to_numpy(dtype=float)
    V = cov_matrix.loc[terms, terms].to_numpy(dtype=float)
    theta = float(L @ b)
    var = float(L @ V @ L)
    if not np.isfinite(theta):
        return None, None, None, None
    if not np.isfinite(var) or var <= 0:
        return theta, None, None, None
    se = var ** 0.5
    z = theta / se
    return theta, se, z, float(2.0 * stats.norm.sf(abs(z)))


def _interaction_contrast_rows(params, cov_matrix, meta: List[Dict[str, Any]]):
    """Stratum-specific effects of the focal exposure within each modifier level.

    An interaction's raw coefficients are NOT the stratum effects: inside a
    non-reference level the effect is ``β_focal + β_interaction``. Emits one row
    per (focal term × modifier level), including the reference level where the
    contrast is the main effect alone.
    """
    import numpy as np

    rows: List[Dict[str, Any]] = []
    for m in meta:
        modifier = m.get("modifier")
        ref_level = m.get("modifier_reference")
        if not modifier:
            continue
        for ff in m["focal_features"]:
            levels: List[Tuple[Optional[str], Optional[str]]] = [(ref_level, None)]
            levels += [(_level_of(mf, modifier) or mf, mf) for mf in m["modifier_features"]]
            for level, mf in levels:
                if not level:
                    continue
                weights = {ff: 1.0}
                if mf is not None:
                    inter = (
                        f"{ff}{_INTERACT_SEP}{mf}" if m["focal_is_first"]
                        else f"{mf}{_INTERACT_SEP}{ff}"
                    )
                    # An empty cell was dropped before the fit — not estimable.
                    if inter not in params.index:
                        continue
                    weights[inter] = 1.0
                theta, se, z, p = _contrast_stats(params, cov_matrix, weights)
                if theta is None:
                    continue
                rows.append({
                    "term_type": "contrast",
                    "term": f"{ff} @ {modifier}={level}",
                    "group": str(level),
                    "coef": round(theta, 5),
                    "se": None if se is None else round(se, 5),
                    "hazard_ratio": round(float(np.exp(theta)), 5),
                    "hr_lower95": None if se is None else round(float(np.exp(theta - 1.96 * se)), 5),
                    "hr_upper95": None if se is None else round(float(np.exp(theta + 1.96 * se)), 5),
                    "statistic": None if z is None else round(z, 4),
                    "df": None,
                    "p": None if p is None else round(p, 6),
                })
    return rows


def _smd(treated_vals, control_vals) -> float:
    """Standardized mean difference (Cohen's d style) for one covariate."""
    import numpy as np

    a = np.asarray(treated_vals, dtype=float)
    b = np.asarray(control_vals, dtype=float)
    ma, mb = float(np.nanmean(a)), float(np.nanmean(b))
    va, vb = float(np.nanvar(a)), float(np.nanvar(b))
    pooled = ((va + vb) / 2.0) ** 0.5
    if pooled <= 0:
        return 0.0
    return round((ma - mb) / pooled, 4)


class SeerToolbox:
    """Bound set of SEER ReAct tools over one DuckDB connection.

    ``specs`` are provider-neutral tool specs ({name, description, parameters,
    invoke}); ``deliverables`` accumulates the tables the tools materialize
    (query outputs, KM curves) so the graph can surface them to the frontend.
    """

    def __init__(
        self,
        parquet_uri: str,
        *,
        user_id: str = "",
        note_id: str = "",
    ):
        self.parquet_uri = parquet_uri
        self.user_id = (user_id or "").strip() or "anon"
        self.note_id = (note_id or "").strip() or "default"
        self.con = get_seer_connection(parquet_uri)
        self.deliverables: List[Dict[str, Any]] = []
        # Output names for which a tool registered the FULL result as a queryable
        # DuckDB relation (dataset-producing tools: PSM matched cohort, KM/Cox
        # result tables). run_analysis_step treats these as authoritative instead
        # of overwriting them with a 200-row preview.
        self._materialized_outputs: set = set()
        self._n = 0
        # Set while a tool is being re-run once per imputation draw: the per-draw
        # fits are intermediates, so they must not each write a parquet to S3.
        self._suppress_export = False

    # ── individual tools ────────────────────────────────────────────────
    def basic_glm(
        self, outcome_column: str, covariates: Any, family: str = "gaussian",
        categorical: Any = None, reference_levels: Any = None,
        missing: str = "raise", max_iter: int = 100, tolerance: float = 1e-8,
        where: str = "", label: str = "", source: str = "seer",
    ) -> str:
        """Submission GLM: explicit types, missing policy and diagnostics."""
        from .glm import run_basic_glm
        return run_basic_glm(
            self, outcome_column, covariates, family, categorical, reference_levels,
            missing, max_iter, tolerance, where, label, source,
        )

    def seer_schema(self, keyword: str = "") -> str:
        rows = self.con.execute("DESCRIBE seer").fetchall()
        kw = (keyword or "").strip().lower()
        cols = [(str(r[0]), str(r[1])) for r in rows]
        if kw:
            cols = [c for c in cols if kw in c[0].lower()]
        if not cols:
            return f"No columns match '{keyword}'. Try a broader keyword or omit it."
        head = cols[:120]
        body = "\n".join(f'- "{n}" ({t})' for n, t in head)
        more = f"\n… {len(cols) - len(head)} more" if len(cols) > len(head) else ""
        return f"{len(cols)} column(s):\n{body}{more}"

    def seer_value_counts(self, column: str, top_n: int = 25) -> str:
        col = (column or "").strip()
        if not col:
            return "Error: 'column' is required."
        top_n = max(1, min(int(top_n or 25), 100))
        try:
            df = self.con.execute(
                f"SELECT {_q(col)} AS value, COUNT(*) AS n "
                f"FROM seer GROUP BY 1 ORDER BY n DESC LIMIT {top_n}"
            ).fetchdf()
        except Exception as e:
            return f"Error: {e}"
        return f'Distinct values of "{_bare(col)}" (top {top_n}):\n{_fmt_rows_for_llm(df, top_n)}'

    def seer_sql(self, query: str, output_name: str = "") -> str:
        q = (query or "").strip()
        if not q:
            return "Error: 'query' is required."
        try:
            _assert_read_only(q)
        except Exception as e:
            return f"Error: {e}"
        out = (output_name or "").strip()
        try:
            if out:
                self.con.execute(f"CREATE OR REPLACE VIEW {_q(out)} AS {q}")
                total = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(out)}").fetchone()[0])
                df = self.con.execute(
                    f"SELECT * FROM {_q(out)} LIMIT {MATERIALIZE_ROW_CAP}"
                ).fetchdf()
                self._register_deliverable(out, df, total)
                return (
                    f"Saved result as '{out}' ({total:,} rows). Preview:\n"
                    f"{_fmt_rows_for_llm(df)}"
                )
            df = self.con.execute(f"SELECT * FROM ({q}) AS _sub LIMIT {MATERIALIZE_ROW_CAP}").fetchdf()
            return f"{len(df)} row(s) (preview):\n{_fmt_rows_for_llm(df)}"
        except Exception as e:
            return f"Error running query: {e}"

    def duckdb_query(self, query: str, limit: int = MATERIALIZE_ROW_CAP) -> str:
        """Execute a raw read-only DuckDB query given as input.

        The query string is taken verbatim and run against the in-memory DuckDB
        connection, which exposes the ``seer`` view (the fixed SEER DB) plus any
        views materialized by earlier tool calls. Results are capped to ``limit``
        rows (never dumps the full 4.8M-row table). Read-only only — DDL/DML is
        rejected. Unlike :meth:`seer_sql`, this does not register a deliverable;
        use it for ad-hoc exploration.
        """
        q = (query or "").strip()
        if not q:
            return "Error: 'query' is required."
        try:
            _assert_read_only(q)
        except Exception as e:
            return f"Error: {e}"
        try:
            cap = max(1, min(int(limit or MATERIALIZE_ROW_CAP), MATERIALIZE_ROW_CAP))
        except (TypeError, ValueError):
            cap = MATERIALIZE_ROW_CAP
        try:
            df = self.con.execute(
                f"SELECT * FROM ({q}) AS _sub LIMIT {cap}"
            ).fetchdf()
        except Exception as e:
            return f"Error running query: {e}"
        return f"{len(df)} row(s) (preview, max {cap}):\n{_fmt_rows_for_llm(df)}"

    def kaplan_meier(
        self,
        time_column: str,
        event_column: str,
        event_values: Any,
        where: str = "",
        group_by: Any = None,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Generalized KM estimator over the SEER table (via lifelines).

        Reads the cohort from ``source`` (a view name; default the raw ``seer``
        table, or an upstream pipeline step's output), derives an event
        indicator (1 if ``event_column`` is in ``event_values``), applies
        ``where``, and fits a Kaplan-Meier curve — per group when ``group_by``
        is given — returning a life-table deliverable with time_months,
        n_at_risk, n_events, survival_probability, and 95% CI.
        """
        try:
            from lifelines import KaplanMeierFitter
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines unavailable ({e})."

        tcol = (time_column or "").strip()
        ecol = (event_column or "").strip()
        if not tcol or not ecol:
            return "Error: 'time_column' and 'event_column' are required."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return "Error: 'event_values' must list the event_column value(s) counted as an event (e.g. [\"Dead\"])."
        groups = group_by if isinstance(group_by, list) else ([group_by] if group_by else [])
        groups = [str(g) for g in groups if str(g).strip()]

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        sel = [
            f"TRY_CAST({_q(tcol)} AS DOUBLE) AS _t",
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e",
        ]
        for g in groups:
            sel.append(f"{_q(g)} AS {_q(g)}")
        src = (source or "seer").strip() or "seer"
        sql = f"SELECT {', '.join(sel)} FROM {_q(src)} WHERE TRY_CAST({_q(tcol)} AS DOUBLE) IS NOT NULL"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        try:
            total = int(self.con.execute(f"SELECT COUNT(*) FROM ({sql}) AS _s").fetchone()[0])
        except Exception as e:
            return f"Error building cohort: {e}"
        if total == 0:
            return (
                "Cohort is empty after filtering (0 rows). Re-check the filter — "
                "verify column names and category labels with seer_value_counts."
            )
        if total > _KM_MAX_ROWS:
            return (
                f"Cohort too large for KM ({total:,} rows > {_KM_MAX_ROWS:,}). "
                "Add a narrower 'where' filter first."
            )
        df = self.con.execute(sql).fetchdf()

        import pandas as pd

        def _fit(sub, group_label: str) -> List[Dict[str, Any]]:
            kmf = KaplanMeierFitter()
            kmf.fit(sub["_t"], event_observed=sub["_e"], label=group_label or "overall")
            et = kmf.event_table  # index=time; at_risk, observed, censored, …
            sf = kmf.survival_function_.iloc[:, 0]
            ci = kmf.confidence_interval_
            out_rows: List[Dict[str, Any]] = []
            for t in et.index:
                row: Dict[str, Any] = {
                    "time_months": float(t),
                    "n_at_risk": int(et.loc[t, "at_risk"]),
                    "n_events": int(et.loc[t, "observed"]),
                    "survival_probability": round(float(sf.get(t, float("nan"))), 5),
                }
                try:
                    row["ci_lower"] = round(float(ci.iloc[:, 0].get(t)), 5)
                    row["ci_upper"] = round(float(ci.iloc[:, 1].get(t)), 5)
                except Exception:
                    pass
                if group_label:
                    row = {"group": group_label, **row}
                out_rows.append(row)
            return out_rows

        rows: List[Dict[str, Any]] = []
        summary: List[str] = []
        if groups:
            gcols = [_bare(g) for g in groups]
            for key, sub in df.groupby(gcols, dropna=False):
                lbl = " | ".join(str(x) for x in (key if isinstance(key, tuple) else (key,)))
                rows.extend(_fit(sub, lbl))
                summary.append(f"{lbl}: n={len(sub)}, events={int(sub['_e'].sum())}")
        else:
            rows.extend(_fit(df, ""))
            summary.append(f"n={len(df)}, events={int(df['_e'].sum())}")

        km_df = pd.DataFrame(rows)
        name = (label or "").strip() or f"km_curve_{self._n + 1}"
        title = (label or "").strip() or "Kaplan-Meier survival"
        figure = self._render_km_png(km_df, name, title)
        # Parquet-out contract (like mann_whitney_u): persist the full life-table
        # as the node's output relation, write it to S3 as a single parquet, and
        # RETURN that path; the graph's persist layer reuses this URI (no second
        # copy). The step-survival PNG is still surfaced as a `figure` deliverable.
        self._materialize_output(name, km_df)
        parquet_uri = self._export_parquet(name)
        extra: Dict[str, Any] = {"kind": "figure", "title": title}
        if figure:
            extra.update(figure)
        if parquet_uri:
            extra["storage_path"] = parquet_uri
            extra["parquet_uri"] = parquet_uri
        self._register_deliverable(name, km_df, len(km_df), **extra)
        img_note = (
            " A survival-curve PNG was rendered and will be shown in the UI (do "
            "not paste any URL)." if figure else " (figure render failed)"
        )
        stats = (
            f"Kaplan-Meier '{name}' computed ({total:,} patients). "
            f"Groups: {'; '.join(summary)}.{img_note}"
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\nLife-table preview:\n{_fmt_rows_for_llm(km_df, 30)}"
        return f"{stats}\nLife-table preview:\n{_fmt_rows_for_llm(km_df, 30)}"

    def competing_risk_cif(
        self,
        duration_column: str,
        event_column: str,
        event_values: Any,
        competing_values: Any,
        group_column: str = "",
        group_values: Any = None,
        cif_time_points: Any = None,
        where: str = "",
        weights_column: str = "",
        both_causes: Any = True,
        title: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Competing-risk cumulative incidence, Aalen-Johansen (frozen tool, lifelines).

        Use INSTEAD of ``kaplan_meier`` whenever patients can die of something
        other than the event of interest: 1-KM treats those competing deaths as
        censoring and therefore OVERSTATES the cumulative incidence, while the
        Aalen-Johansen estimator accounts for them.

        Patients are classified into three states — ``event_values`` (cause 1, the
        event of interest), ``competing_values`` (cause 2), everything else
        censored — and one CIF is estimated per ``group_column`` level (and per
        cause when ``both_causes``). Returns the tidy CIF curve table plus a
        stepped CIF figure, and reports the CIF at each ``cif_time_points`` value
        with the between-group ABSOLUTE RISK DIFFERENCE when there are two groups.
        ``weights_column`` (e.g. the ``iptw`` column from :meth:`iptw_weight`)
        makes it an adjusted CIF.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from lifelines import AalenJohansenFitter
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        dcol, ecol = _bare(duration_column), _bare(event_column)
        if not dcol or not ecol:
            return "Error: 'duration_column' and 'event_column' are required."

        def _vals(v: Any) -> List[str]:
            if isinstance(v, str):
                v = [v]
            return [str(x) for x in (v or [])]

        evs, cvs = _vals(event_values), _vals(competing_values)
        if not evs:
            return (
                "Error: 'event_values' must list the value(s) of the EVENT OF INTEREST, "
                'e.g. ["Dead (attributable to this cancer dx)"].'
            )
        if not cvs:
            return (
                "Error: 'competing_values' must list the COMPETING event value(s), e.g. "
                '["Dead (attributable to causes other than this cancer dx)"]. Without '
                "them there is no competing risk — use kaplan_meier instead."
            )
        overlap = sorted(set(evs) & set(cvs))
        if overlap:
            return f"Error: {overlap} appear in BOTH 'event_values' and 'competing_values'."

        gcol = _bare(group_column)
        gvals = _vals(group_values)
        times = []
        for x in (cif_time_points if isinstance(cif_time_points, (list, tuple)) else
                  ([cif_time_points] if cif_time_points is not None else [])):
            try:
                times.append(float(x))
            except Exception:
                continue
        wcol = _bare(weights_column)
        show_both = str(both_causes).strip().lower() in ("true", "1", "yes")

        ev_list = ", ".join("'" + v.replace("'", "''") + "'" for v in evs)
        cv_list = ", ".join("'" + v.replace("'", "''") + "'" for v in cvs)
        sel = [
            f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _t",
            f"CASE WHEN CAST({_q(ecol)} AS VARCHAR) IN ({ev_list}) THEN 1 "
            f"WHEN CAST({_q(ecol)} AS VARCHAR) IN ({cv_list}) THEN 2 ELSE 0 END AS _e",
        ]
        if gcol:
            sel.append(f"CAST({_q(gcol)} AS VARCHAR) AS _g")
        if wcol:
            sel.append(f"TRY_CAST({_q(wcol)} AS DOUBLE) AS _w")
        src = (source or "seer").strip() or "seer"
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(dcol)} AS DOUBLE) >= 0"
        )
        if wcol:
            sql += f" AND TRY_CAST({_q(wcol)} AS DOUBLE) > 0"
        if gcol and gvals:
            g_list = ", ".join("'" + v.replace("'", "''") + "'" for v in gvals)
            sql += f" AND CAST({_q(gcol)} AS VARCHAR) IN ({g_list})"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."
        n_ev, n_cmp = int((df["_e"] == 1).sum()), int((df["_e"] == 2).sum())
        if n_ev == 0:
            return (
                "No events of interest in the cohort — check 'event_values' against the "
                "column's real labels (seer_value_counts)."
            )
        if n_cmp == 0:
            return (
                "No competing events in the cohort — 'competing_values' matched nobody, so "
                "the Aalen-Johansen estimate would just reproduce 1-KM. Verify the labels "
                "or use kaplan_meier."
            )

        causes = [1, 2] if show_both else [1]
        cause_label = {1: "event of interest", 2: "competing event"}
        groups: List[Tuple[str, Any]] = (
            [(str(k), sub) for k, sub in df.groupby("_g", dropna=False)] if gcol
            else [("overall", df)]
        )
        logger.info(
            "[seer] CIF: Aalen-Johansen over %d patients — %d event(s) of interest, "
            "%d competing, %d group(s)%s",
            len(df), n_ev, n_cmp, len(groups), f", weighted by '{wcol}'" if wcol else "",
        )

        # The estimator jitters tied event times (SEER durations are whole months,
        # so essentially every time is tied), which leaves a curve indexed by ~n
        # noisy floats — even slightly negative ones. Report it on the real
        # observed time grid instead: one row per genuine follow-up time.
        grid = np.unique(df["_t"].to_numpy(dtype=float))
        if len(grid) > 2000:
            keep = np.linspace(0, len(grid) - 1, 2000).astype(int)
            grid = grid[keep]
        grid = np.unique(np.concatenate([[0.0], grid, np.array(times, dtype=float)]))
        grid = grid[grid >= 0]

        rows: List[Dict[str, Any]] = []
        curves: Dict[Tuple[str, int], Any] = {}
        summary: List[str] = []
        for glabel, sub in groups:
            if int((sub["_e"] == 1).sum()) == 0:
                logger.warning("[seer] CIF: group '%s' has no events of interest — skipped.", glabel)
                continue
            for cause in causes:
                try:
                    ajf = AalenJohansenFitter(seed=42)
                    ajf.fit(
                        sub["_t"], sub["_e"], event_of_interest=cause,
                        weights=sub["_w"] if wcol else None,
                    )
                except Exception as e:
                    logger.warning("[seer] CIF: group '%s' cause %d failed (%s)", glabel, cause, e)
                    continue
                raw = pd.DataFrame({"cif": ajf.cumulative_density_.iloc[:, 0]})
                ci = ajf.confidence_interval_
                if ci is not None and ci.shape[1] >= 2:
                    # lifelines labels the Aalen-Johansen CI columns the wrong way
                    # round, so order the two bounds by VALUE rather than by name.
                    a_, b_ = ci.iloc[:, 0].to_numpy(dtype=float), ci.iloc[:, 1].to_numpy(dtype=float)
                    raw["cif_lower95"] = np.fmin(a_, b_)
                    raw["cif_upper95"] = np.fmax(a_, b_)
                curve = (
                    raw.sort_index()
                    .reindex(raw.index.union(grid))
                    .ffill()
                    .reindex(grid)
                )
                curve["cif"] = curve["cif"].fillna(0.0)  # nothing has happened at t=0
                curve.index.name = "time"
                curves[(glabel, cause)] = curve
                for t, r in curve.iterrows():
                    rows.append({
                        "group": glabel,
                        "cause": cause_label[cause],
                        "time": float(t),
                        "cif": round(float(r["cif"]), 6),
                        "cif_lower95": (
                            None if pd.isna(r.get("cif_lower95")) else round(float(r["cif_lower95"]), 6)
                        ),
                        "cif_upper95": (
                            None if pd.isna(r.get("cif_upper95")) else round(float(r["cif_upper95"]), 6)
                        ),
                    })
            summary.append(
                f"{glabel}: n={len(sub):,}, events={int((sub['_e'] == 1).sum()):,}, "
                f"competing={int((sub['_e'] == 2).sum()):,}"
            )
        if not rows:
            return "The Aalen-Johansen estimator produced no curves (every group failed)."
        cif_df = pd.DataFrame(rows)

        # CIF at the requested horizons, plus the absolute risk difference between
        # the two arms — the number a hazard ratio cannot express.
        point_lines: List[str] = []
        for t in times:
            at_t: Dict[str, float] = {}
            for (glabel, cause), curve in curves.items():
                if cause != 1 or t not in curve.index:
                    continue
                at_t[glabel] = float(curve.loc[t, "cif"])
            if not at_t:
                continue
            parts = ", ".join(f"{g}={v:.4f}" for g, v in sorted(at_t.items()))
            line = f"  t={t:g}: {parts}"
            if len(at_t) == 2:
                (ga, va), (gb, vb) = sorted(at_t.items())
                line += f" | absolute risk difference ({ga} − {gb}) = {va - vb:+.4f}"
            point_lines.append(line)

        name = (label or "").strip() or f"competing_risk_cif_{self._n + 1}"
        ttl = (title or "").strip() or (
            f"Cumulative incidence ({'IPTW-adjusted, ' if wcol else ''}Aalen-Johansen)"
        )
        try:
            plt, fig, ax = self._new_mpl_axes()
            palette = ["#4C78A8", "#E45756", "#54A24B", "#B279A2", "#EECA3B", "#72B7B2"]
            glabels = sorted({g for g, _ in curves})
            for (glabel, cause), curve in sorted(curves.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                color = palette[glabels.index(glabel) % len(palette)]
                ax.step(
                    curve.index, curve["cif"].to_numpy(dtype=float), where="post", color=color,
                    linestyle="-" if cause == 1 else "--",
                    label=f"{glabel} — {cause_label[cause]}",
                )
                if cause == 1 and "cif_lower95" in curve:
                    ax.fill_between(
                        curve.index, curve["cif_lower95"], curve["cif_upper95"],
                        step="post", color=color, alpha=0.15, linewidth=0,
                    )
            ax.set_xlabel(dcol)
            ax.set_ylabel("Cumulative incidence")
            ax.set_ylim(0, None)
            ax.set_title(ttl)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.25)
            fig.tight_layout()
        except Exception as e:
            return f"Error rendering the CIF figure: {e}"

        stats = (
            f"Competing-risk CIF '{name}' (Aalen-Johansen) over {len(df):,} patients — "
            f"{n_ev:,} events of interest, {n_cmp:,} competing events"
            f"{f', IPTW-weighted on ' + repr(wcol) if wcol else ''}. {'; '.join(summary)}."
        )
        if point_lines:
            stats += "\nCIF at the requested time points:\n" + "\n".join(point_lines)
        return self._finalize_mpl_plot(name, ttl, cif_df, fig, stats=stats)

    def propensity_score_match(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        where: str = "",
        caliper: float = 0.2,
        ratio: int = 1,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Propensity-score matching (frozen tool; ``psmpy`` propensity model).

        Builds a numeric design matrix for ``covariates`` (categoricals one-hot
        encoded), fits :class:`psmpy.PsmPy`'s logistic propensity model for
        ``treatment_column`` in ``treatment_values``, then matches greedily on the
        propensity LOGIT by nearest neighbour without replacement, 1:``ratio``,
        within ``caliper`` × SD(logit) — Austin's 0.2 by default, and applied at
        every ratio (psmpy's own 1:n matcher silently ignored the caliper).

        The matching itself is :func:`_greedy_nn_match` rather than psmpy's
        ``kdtree_matched``: the recipe is identical, but psmpy's implementation
        materializes an |treated| x |control| distance matrix and dedupes with a
        per-patient list scan, which does not complete on a SEER-sized cohort.

        Returns a covariate balance deliverable (standardized mean differences
        before/after) plus the matched sample sizes; the node OUTPUT is the matched
        patient-level cohort.
        """
        try:
            import numpy as np
            import pandas as pd
            from psmpy import PsmPy
        except Exception as e:  # pragma: no cover
            return f"Error: psmpy / pandas unavailable ({e})."

        tcol = (treatment_column or "").strip()
        if not tcol:
            return "Error: 'treatment_column' is required."
        if isinstance(treatment_values, str):
            treatment_values = [treatment_values]
        treatment_values = [str(v) for v in (treatment_values or [])]
        if not treatment_values:
            return "Error: 'treatment_values' must list the treated arm's value(s)."
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in treatment_values)
        cov_map: Dict[str, str] = {}
        cov_sel: List[str] = []
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            cov_sel.append(f"{_q(c)} AS {a}")
        src = (source or "seer").strip() or "seer"
        w = (where or "").strip()
        name = (label or "").strip() or f"psm_matched_{self._n + 1}"

        # Materialize the PSM working set ONCE: every source column + a treatment
        # flag + a stable row id. Matching runs on the covariate slice, but the
        # node OUTPUT is the full patient-level matched cohort (survival /
        # treatment / covariate columns intact) so downstream KM / Cox can consume
        # it as a real dataset (persisted + profiled), not a summary table.
        work = f"_psm_work_{abs(hash(name)) % 10_000_000}"
        base_sql = (
            f"SELECT *, "
            f"CASE WHEN {_q(tcol)} IN ({in_list}) THEN 1 ELSE 0 END AS _treat, "
            f"ROW_NUMBER() OVER () AS _psm_id "
            f"FROM {_q(src)}"
        )
        if w:
            base_sql += f" WHERE ({w})"
        base_sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS {base_sql}")
            total_work = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(work)}").fetchone()[0])
        except Exception as e:
            self._drop_relation(work)
            return f"Error building cohort: {e}"
        if total_work == 0:
            self._drop_relation(work)
            return "Cohort is empty after filtering (0 rows). Verify column values."

        logger.info("[seer] PSM: cohort loaded (%d rows) from '%s'", total_work, src)
        try:
            match_df = self.con.execute(
                f"SELECT _psm_id, _treat, {', '.join(cov_sel)} FROM {_q(work)}"
            ).fetchdf()
        except Exception as e:
            self._drop_relation(work)
            return f"Error reading covariates: {e}"

        alias_cols = list(cov_map.keys())
        X, features = _design_matrix(match_df, alias_cols, cov_map)
        data = pd.concat(
            [match_df[["_psm_id", "_treat"]].reset_index(drop=True), X.reset_index(drop=True)],
            axis=1,
        ).dropna().reset_index(drop=True)
        if data["_treat"].nunique() < 2:
            self._drop_relation(work)
            return "Both treated and control patients are required (one arm is empty after filtering)."
        data["_treat"] = data["_treat"].astype(int)
        n_treated0 = int((data["_treat"] == 1).sum())
        n_control0 = int((data["_treat"] == 0).sum())
        logger.info(
            "[seer] PSM: design matrix ready — %d rows after dropna, %d features "
            "(%d treated / %d control)",
            len(data), len(features), n_treated0, n_control0,
        )

        k = max(1, int(ratio or 1))
        try:
            logger.info("[seer] PSM: fitting propensity model (psmpy logistic)…")
            # psmpy uses every column except treatment + indx as covariates.
            psm = PsmPy(
                data[["_psm_id", "_treat"] + features],
                treatment="_treat",
                indx="_psm_id",
                exclude=[],
            )
            # balance=False keeps the fit on the full cohort (no imblearn
            # resampling), so it stays deterministic on large SEER cohorts.
            psm.logistic_ps(balance=False)
        except Exception as e:
            self._drop_relation(work)
            return f"Error fitting propensity model (psmpy): {e}"

        # `caliper` is a fraction of SD(logit) — Austin's recommendation is 0.2 —
        # while the matcher needs an absolute threshold on 'propensity_logit'.
        cal_abs: Optional[float] = None
        try:
            logit = psm.predicted_data["propensity_logit"].to_numpy(dtype=float)
            if caliper:
                cal_abs = float(caliper) * float(np.std(logit))
        except Exception:
            cal_abs = None

        # Match on the fitted logit ourselves. psmpy's own matcher asks a KD-tree for
        # every control at once, which needs an |treated|x|control| distance matrix
        # (36 GB on a SEER-sized cohort) and then dedupes with a per-patient list
        # scan, so it does not finish here. _greedy_nn_match computes the identical
        # greedy result from the sorted logit — see its docstring.
        try:
            pred = psm.predicted_data
            t_side = pred[pred["_treat"] == 1]
            c_side = pred[pred["_treat"] == 0]
            logger.info(
                "[seer] PSM: matching START — %d treated vs %d control (greedy 1:%d "
                "nearest-neighbour on the logit, no replacement%s)…",
                len(t_side), len(c_side), k,
                f", caliper={cal_abs:.4f}" if cal_abs is not None else ", no caliper",
            )
            pairs, n_unmatched = _greedy_nn_match(
                t_side["propensity_logit"].to_numpy(dtype=float),
                t_side["_psm_id"].to_numpy(),
                c_side["propensity_logit"].to_numpy(dtype=float),
                c_side["_psm_id"].to_numpy(),
                caliper=cal_abs,
                ratio=k,
            )
        except Exception as e:
            self._drop_relation(work)
            return f"Error during matching: {e}"

        if not pairs:
            self._drop_relation(work)
            return (
                "No matches found within the caliper. Widen 'caliper', reduce "
                "'ratio', or reconsider covariates."
            )
        matched_pids = {int(t) for t, _ in pairs} | {int(c) for _, c in pairs}
        if n_unmatched:
            logger.info(
                "[seer] PSM: %d treated patient(s) had no control within the caliper "
                "and were dropped", n_unmatched,
            )

        # Covariate balance: SMD before (full cohort) vs after (matched sample).
        t_mask = (data["_treat"] == 1).to_numpy()
        c_mask = ~t_mask
        in_matched = data["_psm_id"].isin(matched_pids).to_numpy()
        m_t_mask = t_mask & in_matched
        m_c_mask = c_mask & in_matched
        n_mt = int(m_t_mask.sum())
        n_mc = int(m_c_mask.sum())
        logger.info(
            "[seer] PSM: matching DONE — %d treated / %d control matched "
            "(from %d / %d)",
            n_mt, n_mc, n_treated0, n_control0,
        )

        rows: List[Dict[str, Any]] = []
        for f in features:
            col = data[f].to_numpy(dtype=float)
            rows.append(
                {
                    "covariate": f,
                    "smd_before": _smd(col[t_mask], col[c_mask]),
                    "smd_after": _smd(col[m_t_mask], col[m_c_mask]),
                }
            )
        balance = pd.DataFrame(rows)

        # Materialize the full matched PATIENT cohort as the node OUTPUT relation
        # (all source columns + the _treat flag; internal _psm_id dropped), so a
        # downstream KM/Cox node can query survival/treatment columns and the
        # cohort is persisted + profiled like any dataset.
        ids_tmp = f"_psm_ids_{abs(hash(name)) % 10_000_000}"
        try:
            ids_df = pd.DataFrame({"_psm_id": sorted(matched_pids)})
            self.con.register(ids_tmp, ids_df)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT * EXCLUDE (_psm_id) FROM {_q(work)} "
                f"WHERE _psm_id IN (SELECT _psm_id FROM {ids_tmp})"
            )
            self._materialized_outputs.add(name)
            matched_total = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0])
        except Exception as e:
            self._drop_relation(work)
            return f"Error materializing matched cohort: {e}"
        finally:
            try:
                self.con.unregister(ids_tmp)
            except Exception:
                pass
            self._drop_relation(work)

        # The matched cohort is the node output (dataset); the SMD balance is the
        # user-facing deliverable surfaced under the same node name.
        self._register_deliverable(name, balance, len(balance), title="PSM covariate balance")
        cal_txt = f", caliper={cal_abs:.3f} on logit" if cal_abs is not None else ""
        return (
            f"Propensity-score matching '{name}' done (greedy nearest-neighbour on the "
            f"psmpy logistic propensity logit, without replacement) — matched cohort has "
            f"{matched_total:,} patients (full survival/treatment columns retained). "
            f"Before: {n_treated0} treated / {n_control0} control. "
            f"Matched (1:{k}{cal_txt}): {n_mt} treated / {n_mc} control"
            + (f"; {n_unmatched} treated dropped as unmatched.\n" if n_unmatched else ".\n")
            + f"Covariate balance (SMD before→after):\n{_fmt_rows_for_llm(balance, 40)}"
        )

    def propensity_score_match_multi(
        self,
        treatment_column: str,
        arms: Any,
        covariates: Any,
        where: str = "",
        exact_columns: Any = None,
        tolerance_columns: Any = None,
        caliper: float = 0.6,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Multi-arm (K≥3) 1:1:…:1 propensity-score matching (Rassen-style).

        Fits a multinomial logistic propensity model for ``treatment_column``
        across the ordered ``arms``, keeps each patient's full generalized PS
        vector ``(P(arm0),…,P(armK-1))``, and greedily forms K-tuples by
        Euclidean GPS distance with component-wise logit calipers. Optional
        ``exact_columns`` define strata; ``tolerance_columns`` (e.g. age±2,
        year±2) further constrain every pair in a tuple. Per-arm calipers are
        ``caliper`` × SD(logit P(arm=a) among patients in arm a) — default 0.6.
        Binary two-arm matching stays on :meth:`propensity_score_match`.

        OUTPUT is the matched patient cohort (equal n per arm, ``_arm`` index
        0..K-1); pairwise covariate SMD before/after is the deliverable.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
        except Exception as e:  # pragma: no cover
            return f"Error: sklearn / pandas unavailable ({e})."

        tcol = (treatment_column or "").strip()
        if not tcol:
            return "Error: 'treatment_column' is required."
        if isinstance(arms, str):
            arms = [arms]
        arm_labels = [str(v) for v in (arms or []) if str(v).strip()]
        # Deduplicate while preserving order.
        seen: set = set()
        arm_labels = [a for a in arm_labels if not (a in seen or seen.add(a))]
        if len(arm_labels) < 3:
            return (
                "Error: 'arms' must list at least 3 distinct treatment values "
                "(for 2-arm matching use propensity_score_match)."
            )
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."
        exact_cols = [str(c).strip() for c in (exact_columns or []) if str(c).strip()]
        tol_map = _parse_tolerance_columns(tolerance_columns)
        tol_cols = list(tol_map.keys())
        tol_limits = [tol_map[c] for c in tol_cols]

        k_arms = len(arm_labels)
        arm_in = ", ".join("'" + v.replace("'", "''") + "'" for v in arm_labels)
        case_parts = [
            f"WHEN {_q(tcol)} = '{v.replace(chr(39), chr(39)+chr(39))}' THEN {i}"
            for i, v in enumerate(arm_labels)
        ]
        arm_case = "CASE " + " ".join(case_parts) + " END"

        cov_map: Dict[str, str] = {}
        cov_sel: List[str] = []
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            cov_sel.append(f"{_q(c)} AS {a}")
        exact_sel = [f"{_q(c)} AS {_q(f'_ex{i}')}" for i, c in enumerate(exact_cols)]
        tol_sel = [f"{_q(c)} AS {_q(f'_tol{i}')}" for i, c in enumerate(tol_cols)]

        src = (source or "seer").strip() or "seer"
        w = (where or "").strip()
        name = (label or "").strip() or f"psm_multi_matched_{self._n + 1}"
        work = f"_psm_mw_{abs(hash(name)) % 10_000_000}"

        base_sql = (
            f"SELECT *, {arm_case} AS _arm, "
            f"ROW_NUMBER() OVER () AS _psm_id "
            f"FROM {_q(src)} "
            f"WHERE {_q(tcol)} IN ({arm_in})"
        )
        if w:
            base_sql += f" AND ({w})"
        base_sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS {base_sql}")
            total_work = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(work)}").fetchone()[0])
        except Exception as e:
            self._drop_relation(work)
            return f"Error building cohort: {e}"
        if total_work == 0:
            self._drop_relation(work)
            return "Cohort is empty after filtering (0 rows). Verify column values."

        logger.info(
            "[seer] PSM-multi: cohort loaded (%d rows, %d arms) from '%s'",
            total_work, k_arms, src,
        )

        sel_bits = ["_psm_id", "_arm"] + cov_sel + exact_sel + tol_sel
        try:
            match_df = self.con.execute(
                f"SELECT {', '.join(sel_bits)} FROM {_q(work)}"
            ).fetchdf()
        except Exception as e:
            self._drop_relation(work)
            return f"Error reading covariates: {e}"

        alias_cols = list(cov_map.keys())
        try:
            X, features = _design_matrix(match_df, alias_cols, cov_map)
        except ValueError as e:
            self._drop_relation(work)
            return str(e)
        keep_cols = ["_psm_id", "_arm"] + [f"_ex{i}" for i in range(len(exact_cols))] + [
            f"_tol{i}" for i in range(len(tol_cols))
        ]
        # Only keep columns that exist (exact/tol aliases).
        keep_cols = [c for c in keep_cols if c in match_df.columns]
        tol_aliases = [f"_tol{i}" for i in range(len(tol_cols))]
        data = pd.concat(
            [match_df[keep_cols].reset_index(drop=True), X.reset_index(drop=True)],
            axis=1,
        ).dropna(subset=["_arm"] + features + tol_aliases).reset_index(drop=True)
        data["_arm"] = data["_arm"].astype(int)
        present = sorted(int(x) for x in data["_arm"].unique())
        if len(present) < k_arms:
            missing = [arm_labels[i] for i in range(k_arms) if i not in present]
            self._drop_relation(work)
            return (
                f"Error: after filtering/dropna, missing arm(s): {missing}. "
                "Every listed arm must have patients."
            )
        n_before = {arm_labels[i]: int((data["_arm"] == i).sum()) for i in range(k_arms)}
        logger.info(
            "[seer] PSM-multi: design matrix ready — %d rows, %d features; n by arm: %s",
            len(data), len(features), n_before,
        )

        try:
            logger.info("[seer] PSM-multi: fitting multinomial propensity model…")
            # sklearn ≥1.8 dropped multi_class=; multinomial is the default for
            # K>2 targets with solver='lbfgs'. Scale covariates — unscaled SEER
            # features routinely hit the iteration limit and yield unstable GPS.
            clf = LogisticRegression(
                solver="lbfgs",
                max_iter=2000,
                random_state=0,
            )
            y = data["_arm"].to_numpy(dtype=int)
            Xmat = StandardScaler().fit_transform(data[features].to_numpy(dtype=float))
            clf.fit(Xmat, y)
            proba = clf.predict_proba(Xmat)
            # Align predict_proba columns to arm index 0..K-1; keep FULL GPS.
            class_to_col = {int(c): j for j, c in enumerate(clf.classes_)}
            gps = np.empty((len(data), k_arms), dtype=float)
            for a in range(k_arms):
                gps[:, a] = proba[:, class_to_col[a]]
            eps = 1e-6
            logit_gps = np.log(np.clip(gps, eps, 1.0 - eps) / (1.0 - np.clip(gps, eps, 1.0 - eps)))
            data = data.copy()
            for a in range(k_arms):
                data[f"_gps{a}"] = gps[:, a]
                data[f"_logit_gps{a}"] = logit_gps[:, a]
        except Exception as e:
            self._drop_relation(work)
            return f"Error fitting multinomial propensity model: {e}"

        cal_mult = float(caliper if caliper is not None else 0.6)
        if cal_mult <= 0:
            self._drop_relation(work)
            return "Error: 'caliper' must be a positive multiple of SD(logit)."
        # Per GPS dimension d: caliper on logit P(arm=d), SD among patients IN arm d.
        cal_abs: List[float] = []
        for a in range(k_arms):
            sd = float(np.std(logit_gps[y == a, a]))
            cal_abs.append(cal_mult * sd if sd > 0 else cal_mult * 1e-6)
        logger.info(
            "[seer] PSM-multi: per-arm GPS calipers (%.3f×SD logit P(arm)): %s",
            cal_mult,
            {arm_labels[i]: round(cal_abs[i], 4) for i in range(k_arms)},
        )

        # Reference arm = rarest (maximizes complete K-tuples); reorder arms for
        # the matcher, then map ids back. GPS columns stay in original arm order.
        ref_arm = min(range(k_arms), key=lambda i: n_before[arm_labels[i]])
        order = [ref_arm] + [i for i in range(k_arms) if i != ref_arm]
        gps_cols = [f"_gps{a}" for a in range(k_arms)]

        ex_aliases = [f"_ex{i}" for i in range(len(exact_cols))]
        if ex_aliases:
            strata_keys = (
                data[ex_aliases]
                .astype("string")
                .fillna("<NA>")
                .agg(tuple, axis=1)
            )
        else:
            strata_keys = pd.Series([()] * len(data), index=data.index)

        all_tuples: List[Tuple[Any, ...]] = []
        n_unmatched_ref = 0
        n_strata = int(strata_keys.nunique())
        logger.info(
            "[seer] PSM-multi: matching START — reference arm '%s', %d exact strata, "
            "tol=%s (GPS-vector Euclidean + component logit calipers)…",
            arm_labels[ref_arm],
            n_strata,
            {c: tol_map[c] for c in tol_cols} if tol_cols else "{}",
        )
        try:
            for _, idx in data.groupby(strata_keys, sort=False).groups.items():
                sub = data.loc[list(idx)]
                arm_gps: List[Any] = []
                arm_ids: List[Any] = []
                arm_tol_arr: Optional[List[Any]] = [] if tol_cols else None
                skip = False
                for slot, orig in enumerate(order):
                    part = sub[sub["_arm"] == orig]
                    if part.empty:
                        skip = True
                        break
                    arm_gps.append(part[gps_cols].to_numpy(dtype=float))
                    arm_ids.append(part["_psm_id"].to_numpy())
                    if arm_tol_arr is not None:
                        cols = [f"_tol{t}" for t in range(len(tol_cols))]
                        arm_tol_arr.append(part[cols].to_numpy(dtype=float))
                if skip:
                    # Stratum lacks at least one arm — nothing to match here.
                    n_unmatched_ref += int((sub["_arm"] == ref_arm).sum())
                    continue
                # Calipers stay in original GPS-dimension order (not matcher slots).
                tuples, n_um = _greedy_k_tuple_match(
                    arm_gps,
                    arm_ids,
                    cal_abs,
                    arm_tol=arm_tol_arr,
                    tol_limits=tol_limits if tol_cols else None,
                )
                n_unmatched_ref += n_um
                # Remap matcher-slot order back to original arm order in the tuple.
                for tup in tuples:
                    by_slot = list(tup)
                    by_orig = [None] * k_arms
                    for slot, orig in enumerate(order):
                        by_orig[orig] = by_slot[slot]
                    all_tuples.append(tuple(by_orig))
        except Exception as e:
            self._drop_relation(work)
            return f"Error during multi-arm matching: {e}"

        if not all_tuples:
            self._drop_relation(work)
            return (
                "No K-tuples found within caliper/exact/tolerance constraints. "
                "Widen 'caliper', relax exact/tolerance columns, or reconsider covariates."
            )

        matched_pids = {int(pid) for tup in all_tuples for pid in tup}
        n_matched_per = {arm_labels[i]: len(all_tuples) for i in range(k_arms)}
        logger.info(
            "[seer] PSM-multi: matching DONE — %d tuples (%s); unmatched reference: %d",
            len(all_tuples),
            n_matched_per,
            n_unmatched_ref,
        )

        # Pairwise SMD before (full multi-arm cohort) vs after (matched).
        in_matched = data["_psm_id"].isin(matched_pids).to_numpy()
        rows: List[Dict[str, Any]] = []
        for f in features:
            col = data[f].to_numpy(dtype=float)
            for i in range(k_arms):
                for j in range(i + 1, k_arms):
                    mi = (data["_arm"] == i).to_numpy()
                    mj = (data["_arm"] == j).to_numpy()
                    rows.append(
                        {
                            "covariate": f,
                            "arm_a": arm_labels[i],
                            "arm_b": arm_labels[j],
                            "smd_before": _smd(col[mi], col[mj]),
                            "smd_after": _smd(col[mi & in_matched], col[mj & in_matched]),
                        }
                    )
        balance = pd.DataFrame(rows)

        ids_tmp = f"_psm_mids_{abs(hash(name)) % 10_000_000}"
        try:
            ids_df = pd.DataFrame({"_psm_id": sorted(matched_pids)})
            self.con.register(ids_tmp, ids_df)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT * EXCLUDE (_psm_id) FROM {_q(work)} "
                f"WHERE _psm_id IN (SELECT _psm_id FROM {ids_tmp})"
            )
            self._materialized_outputs.add(name)
            matched_total = int(
                self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0]
            )
        except Exception as e:
            self._drop_relation(work)
            return f"Error materializing matched cohort: {e}"
        finally:
            try:
                self.con.unregister(ids_tmp)
            except Exception:
                pass
            self._drop_relation(work)

        self._register_deliverable(
            name, balance, len(balance), title="Multi-arm PSM covariate balance"
        )
        ratio_txt = ":".join(["1"] * k_arms)
        cal_txt = ", ".join(
            f"{arm_labels[i]}={cal_abs[i]:.3f}" for i in range(k_arms)
        )
        before_txt = ", ".join(f"{arm_labels[i]}={n_before[arm_labels[i]]}" for i in range(k_arms))
        after_txt = ", ".join(
            f"{arm_labels[i]}={n_matched_per[arm_labels[i]]}" for i in range(k_arms)
        )
        exact_txt = f", exact={exact_cols}" if exact_cols else ""
        tol_txt = (
            f", tolerance={{{', '.join(f'{c}±{tol_map[c]}' for c in tol_cols)}}}"
            if tol_cols
            else ""
        )
        return (
            f"Multi-arm propensity-score matching '{name}' done "
            f"(multinomial GPS vector, Rassen-style {ratio_txt} K-tuples, "
            f"without replacement{exact_txt}{tol_txt}) — matched cohort has "
            f"{matched_total:,} patients (full columns retained, `_arm` 0..{k_arms - 1}). "
            f"Before: {before_txt}. "
            f"Matched ({ratio_txt}; calipers {cal_mult}×SD: {cal_txt}): {after_txt}"
            + (
                f"; {n_unmatched_ref} reference-arm patient(s) unmatched.\n"
                if n_unmatched_ref
                else ".\n"
            )
            + f"Pairwise covariate balance (SMD before→after):\n{_fmt_rows_for_llm(balance, 40)}"
        )

    # ── IPTW / overlap weighting (frozen tools, powered by `iptw-survival`) ──
    # Weight-based causal survival analysis. Where `propensity_score_match`
    # DISCARDS unmatched patients, these keep the whole cohort and re-weight it,
    # so the estimand stays population-level (ATE for IPTW, ATO for overlap).
    # All three tools are self-contained: each loads its own cohort and refits
    # the propensity model, because the bootstrap recomputes weights inside
    # every resample and therefore needs the estimator's own fit state.

    _IPTW_RESERVED = (
        "_treat", "_iptw_id", "_time", "_event", "propensity_score",
        "iptw", "overlap_weight",
    )

    def _iptw_type_covariates(
        self,
        work: str,
        covs: List[str],
        cont_var: List[str],
        cat_var: List[str],
        binary_var: List[str],
    ):
        """Bucket covariates into continuous / categorical / binary.

        Explicit ``cont_var`` / ``cat_var`` / ``binary_var`` always win. Anything
        left in ``covariates`` is typed from the relation schema: numeric columns
        become continuous, and a text column whose values all parse as numbers
        over many distinct levels is promoted to continuous (SEER stores plenty
        of numeric fields as VARCHAR). Everything else is categorical.
        """
        numeric_db = (
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT",
            "USMALLINT", "UINTEGER", "UBIGINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL",
        )
        try:
            desc = self.con.execute(f"DESCRIBE {_q(work)}").fetchdf()
            types = {
                str(r["column_name"]): str(r["column_type"]).upper()
                for _, r in desc.iterrows()
            }
        except Exception:
            types = {}

        cont = [c for c in cont_var if c in covs or not covs]
        cat = [c for c in cat_var if c in covs or not covs]
        binary = [c for c in binary_var if c in covs or not covs]
        assigned = set(cont) | set(cat) | set(binary)
        undecided = [c for c in covs if c not in assigned]

        text_candidates: List[str] = []
        for c in undecided:
            if any(t in types.get(c, "") for t in numeric_db):
                cont.append(c)
            else:
                text_candidates.append(c)

        # One pass over the cohort decides the VARCHAR-but-really-numeric cases.
        if text_candidates:
            parts: List[str] = []
            for i, c in enumerate(text_candidates):
                parts.append(f"COUNT({_q(c)}) AS nn{i}")
                parts.append(f"COUNT(TRY_CAST({_q(c)} AS DOUBLE)) AS nc{i}")
                parts.append(f"COUNT(DISTINCT {_q(c)}) AS nd{i}")
            probe: Dict[str, Any] = {}
            try:
                probe = self.con.execute(
                    f"SELECT {', '.join(parts)} FROM {_q(work)}"
                ).fetchdf().iloc[0].to_dict()
            except Exception:
                probe = {}
            for i, c in enumerate(text_candidates):
                nn = float(probe.get(f"nn{i}") or 0)
                nc = float(probe.get(f"nc{i}") or 0)
                nd = float(probe.get(f"nd{i}") or 0)
                if nn > 0 and nc >= 0.98 * nn and nd > 20:
                    cont.append(c)
                else:
                    cat.append(c)
        return cont, cat, binary

    def _iptw_prepare(
        self,
        *,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        cont_var: Any,
        cat_var: Any,
        binary_var: Any,
        where: str,
        source: str,
        name: str,
        weight_type: str,
        stabilized: Any,
        clip_bounds: Any,
        normalize: str,
        random_state: Any,
        duration_column: str = "",
        event_column: str = "",
        event_values: Any = None,
    ):
        """Load the cohort, type the covariates and fit the weighting model.

        Returns ``(ctx, err)``: on success ``ctx`` carries the fitted estimator,
        the weighted frame (``propensity_score`` + weight column attached), the
        scratch work table and the covariate typing; on failure ``ctx`` is None
        and ``err`` is a human-readable message. The caller MUST drop
        ``ctx["work"]`` when done.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from iptw_survival import (
                IPTWSurvivalEstimator,
                OverlapWeightSurvivalEstimator,
            )
        except Exception as e:  # pragma: no cover
            return None, f"Error: iptw-survival / pandas unavailable ({e})."

        tcol = _bare(treatment_column)
        if not tcol:
            return None, "Error: 'treatment_column' is required."
        if isinstance(treatment_values, str):
            treatment_values = [treatment_values]
        treatment_values = [str(v) for v in (treatment_values or [])]
        if not treatment_values:
            return None, "Error: 'treatment_values' must list the treated arm's value(s)."

        def _as_list(v: Any) -> List[str]:
            if isinstance(v, str):
                v = [v]
            return [_bare(c) for c in (v or []) if _bare(c)]

        covs = _as_list(covariates)
        forced_cont, forced_cat, forced_bin = _as_list(cont_var), _as_list(cat_var), _as_list(binary_var)
        # Explicitly typed columns count as covariates even if omitted from `covariates`.
        for extra in (forced_cont, forced_cat, forced_bin):
            for c in extra:
                if c not in covs:
                    covs.append(c)
        if not covs:
            return None, (
                "Error: at least one covariate is required — pass 'covariates' "
                "(auto-typed) and/or 'cont_var' / 'cat_var' / 'binary_var'."
            )
        clash = [c for c in covs if c in self._IPTW_RESERVED]
        if clash:
            return None, f"Error: covariate name(s) {clash} collide with reserved IPTW columns."

        wtype = (weight_type or "iptw").strip().lower()
        if wtype in ("overlap", "overlap_weight", "ow"):
            wtype, wcol = "overlap", "overlap_weight"
        else:
            wtype, wcol = "iptw", "iptw"
        # Overlap weights are 1-PS / PS by construction — stabilization is an
        # IPTW-only notion, so don't let it show up in the run summary.
        stab = wtype == "iptw" and str(stabilized).strip().lower() in ("true", "1", "yes")

        bounds: Optional[Tuple[float, float]] = None
        if clip_bounds:
            try:
                lo, hi = (float(x) for x in list(clip_bounds)[:2])
                if 0.0 < lo < hi < 1.0:
                    bounds = (lo, hi)
            except Exception:
                bounds = None
        try:
            seed: Optional[int] = int(random_state)
        except Exception:
            seed = None

        # Working cohort: every source column + a 0/1 treatment flag + a stable
        # row id, so the weights can be joined back onto the full patient rows.
        src = (source or "seer").strip() or "seer"
        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in treatment_values)
        sel = [
            "*",
            f"CASE WHEN CAST({_q(tcol)} AS VARCHAR) IN ({in_list}) THEN 1 ELSE 0 END AS _treat",
            "ROW_NUMBER() OVER () AS _iptw_id",
        ]
        conds = [f"({w})" for w in (str(where or "").strip(),) if w]
        dcol, ecol = _bare(duration_column), _bare(event_column)
        if dcol:
            sel.append(f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _time")
            conds.append(f"TRY_CAST({_q(dcol)} AS DOUBLE) >= 0")
            if isinstance(event_values, str):
                event_values = [event_values]
            evs = [str(v) for v in (event_values or [])]
            if not evs:
                return None, "Error: 'event_values' must list the value(s) that mark an event."
            ev_list = ", ".join("'" + v.replace("'", "''") + "'" for v in evs)
            sel.append(
                f"CASE WHEN CAST({_q(ecol)} AS VARCHAR) IN ({ev_list}) THEN 1 ELSE 0 END AS _event"
            )

        work = f"_iptw_work_{abs(hash(name)) % 10_000_000}"
        base_sql = f"SELECT {', '.join(sel)} FROM {_q(src)}"
        if conds:
            base_sql += " WHERE " + " AND ".join(conds)
        base_sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS {base_sql}")
            total = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(work)}").fetchone()[0])
        except Exception as e:
            self._drop_relation(work)
            return None, f"Error building cohort: {e}"
        if total == 0:
            self._drop_relation(work)
            return None, "Cohort is empty after filtering (0 rows). Verify column values."
        logger.info("[seer] IPTW: cohort loaded (%d rows) from '%s'", total, src)

        cont, cat, binary = self._iptw_type_covariates(work, covs, forced_cont, forced_cat, forced_bin)

        # Pull the modelling frame with each covariate cast to the dtype the
        # estimator validates for (numeric for continuous, text for the rest).
        cols = ["_iptw_id", "_treat"] + (["_time", "_event"] if dcol else [])
        msel = [_q(c) for c in cols]
        for c in cont:
            msel.append(f"TRY_CAST({_q(c)} AS DOUBLE) AS {_q(c)}")
        for c in cat + binary:
            msel.append(f"CAST({_q(c)} AS VARCHAR) AS {_q(c)}")
        try:
            mdf = self.con.execute(f"SELECT {', '.join(msel)} FROM {_q(work)}").fetchdf()
        except Exception as e:
            self._drop_relation(work)
            return None, f"Error reading covariates: {e}"

        mdf["_treat"] = mdf["_treat"].astype(int)
        if mdf["_treat"].nunique() < 2:
            self._drop_relation(work)
            return None, (
                "Both treated and control patients are required (one arm is empty). "
                "Check that 'treatment_values' copies the data's values verbatim."
            )
        if dcol:
            mdf = mdf[mdf["_time"].notna()].reset_index(drop=True)
            mdf["_event"] = mdf["_event"].astype(int)
            if len(mdf) == 0:
                self._drop_relation(work)
                return None, f"No rows with a usable numeric '{dcol}' (all durations are null)."
        # The estimator rejects missing categorical levels, so blanks become their
        # own 'Unknown' category; continuous NaNs are median-imputed by the
        # package itself (with missing-indicator flags).
        for c in cat:
            mdf[c] = mdf[c].fillna("Unknown").replace("", "Unknown").astype("category")
        demoted: List[str] = []
        for c in list(binary):
            filled = mdf[c].fillna("Unknown").replace("", "Unknown")
            if filled.nunique() != 2:  # not actually binary once blanks are folded in
                mdf[c] = filled.astype("category")
                binary.remove(c)
                cat.append(c)
                demoted.append(c)
                continue
            # Binary covariates are passed straight through to scikit-learn, so
            # the two levels must already be 0/1 — encode labelled ones ourselves.
            levels = sorted(str(v) for v in filled.unique())
            if set(levels) <= {"0", "1"}:
                mdf[c] = filled.astype(int)
            else:
                mdf[c] = (filled.astype(str) == levels[1]).astype(int)
                logger.info("[seer] IPTW: binary '%s' encoded as %s=1, %s=0", c, levels[1], levels[0])
        if demoted:
            logger.info("[seer] IPTW: %s not binary after cleaning → treated as categorical", demoted)

        lr_kwargs: Dict[str, Any] = {"max_iter": 1000}
        if seed is not None:
            lr_kwargs["random_state"] = seed
        est = (
            OverlapWeightSurvivalEstimator(normalize=(normalize or None))
            if wtype == "overlap"
            else IPTWSurvivalEstimator()
        )
        logger.info(
            "[seer] IPTW: fitting propensity model — %d rows, %d continuous / %d categorical / %d binary "
            "(weights=%s, stabilized=%s, clip=%s)",
            len(mdf), len(cont), len(cat), len(binary), wtype, stab, bounds,
        )
        try:
            wdf = est.fit_transform(
                mdf,
                treatment_col="_treat",
                cat_var=cat or None,
                cont_var=cont or None,
                binary_var=binary or None,
                lr_kwargs=lr_kwargs,
                clip_bounds=bounds,
                stabilized=stab,
            )
        except Exception as e:
            self._drop_relation(work)
            return None, f"Error fitting the {wtype} weighting model: {e}"

        ctx = {
            "est": est, "wdf": wdf, "work": work, "weight_col": wcol,
            "weight_type": wtype, "cont": cont, "cat": cat, "binary": binary,
            "seed": seed, "total": total, "stabilized": stab, "bounds": bounds,
        }
        return ctx, None

    @staticmethod
    def _iptw_bootstrap(fn, **kwargs):
        """Run one of the package's bootstrap estimators, degrading gracefully.

        Both bootstrap methods fan out over joblib/loky worker PROCESSES, which
        a hardened or containerised runtime may refuse to spawn ("Operation not
        permitted"). Retry the whole estimate single-threaded rather than losing
        the analysis — slower, but identical results.
        """
        try:
            return fn(n_jobs=-1, **kwargs)
        except Exception as e:
            if not isinstance(e, (OSError, PermissionError)):
                raise
            logger.warning(
                "[seer] IPTW: parallel bootstrap unavailable (%s); retrying single-threaded.", e
            )
            return fn(n_jobs=1, **kwargs)

    def _iptw_weight_stats(self, ctx: Dict[str, Any]) -> str:
        """One-line summary of the fitted weights (effective sample size etc.)."""
        wdf, wcol = ctx["wdf"], ctx["weight_col"]
        w = wdf[wcol].to_numpy(dtype=float)
        t = wdf["_treat"].to_numpy(dtype=int) == 1
        parts = []
        for arm, mask in (("treated", t), ("control", ~t)):
            wa = w[mask]
            if len(wa) == 0:
                continue
            ess = float(wa.sum() ** 2 / (wa**2).sum()) if (wa**2).sum() > 0 else 0.0
            parts.append(
                f"{arm}: n={int(mask.sum()):,}, weighted n={wa.sum():,.0f}, ESS={ess:,.0f}"
            )
        return (
            f"{'; '.join(parts)}; weight range "
            f"[{w.min():.3f}, {w.max():.3f}] (mean {w.mean():.3f})"
        )

    def iptw_weight(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any = None,
        cont_var: Any = None,
        cat_var: Any = None,
        binary_var: Any = None,
        where: str = "",
        weight_type: str = "iptw",
        stabilized: Any = True,
        clip_bounds: Any = None,
        normalize: str = "",
        random_state: Any = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Inverse-probability-of-treatment weights (frozen tool, ``iptw-survival``).

        Fits a logistic propensity model for ``treatment_column`` in
        ``treatment_values`` given ``covariates`` and attaches ``propensity_score``
        plus a weight column (``iptw``, or ``overlap_weight`` when
        ``weight_type='overlap'``) to EVERY patient. Unlike
        ``propensity_score_match`` no one is dropped, so the node OUTPUT is the
        full weighted cohort that downstream weighted KM / Cox nodes consume.
        The deliverable is the covariate balance table (standardized mean
        differences before vs. after weighting).
        """
        name = (label or "").strip() or f"iptw_cohort_{self._n + 1}"
        ctx, err = self._iptw_prepare(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, cont_var=cont_var, cat_var=cat_var,
            binary_var=binary_var, where=where, source=source, name=name,
            weight_type=weight_type, stabilized=stabilized, clip_bounds=clip_bounds,
            normalize=normalize, random_state=random_state,
        )
        if err:
            return err
        assert ctx is not None
        work, wdf, wcol = ctx["work"], ctx["wdf"], ctx["weight_col"]

        try:
            balance = ctx["est"].standardized_mean_differences()
        except Exception as e:
            balance = None
            logger.warning("[seer] IPTW: SMD balance unavailable (%s)", e)

        # Node OUTPUT: the full patient cohort with propensity score + weight
        # joined back on, so downstream nodes keep every survival/covariate column.
        tmp = f"_iptw_w_{abs(hash(name)) % 10_000_000}"
        try:
            self.con.register(tmp, wdf[["_iptw_id", "propensity_score", wcol]])
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT c.* EXCLUDE (_iptw_id), w.propensity_score, w.{_q(wcol)} "
                f"FROM {_q(work)} c JOIN {tmp} w USING (_iptw_id)"
            )
            self._materialized_outputs.add(name)
            n_out = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0])
        except Exception as e:
            return f"Error materializing the weighted cohort: {e}"
        finally:
            try:
                self.con.unregister(tmp)
            except Exception:
                pass
            self._drop_relation(work)

        stats = self._iptw_weight_stats(ctx)
        logger.info("[seer] IPTW: weighting DONE — %s", stats)
        msg = (
            f"{ctx['weight_type'].upper()} weighting '{name}' done — weighted cohort has "
            f"{n_out:,} patients with a '{wcol}' column "
            f"(stabilized={ctx['stabilized']}, clip_bounds={ctx['bounds']}).\n{stats}"
        )
        if balance is not None and len(balance):
            self._register_deliverable(
                name, balance, len(balance), title="IPTW covariate balance (SMD)"
            )
            try:
                bad = int((balance["smd_weighted"].abs() > 0.1).sum())
            except Exception:
                bad = -1
            msg += (
                f"\nCovariate balance ({bad} variable(s) still |SMD|>0.1 after weighting):\n"
                f"{_fmt_rows_for_llm(balance, 40)}"
                if bad >= 0
                else f"\nCovariate balance:\n{_fmt_rows_for_llm(balance, 40)}"
            )
        return msg

    def iptw_kaplan_meier(
        self,
        treatment_column: str,
        treatment_values: Any,
        duration_column: str,
        event_column: str,
        event_values: Any,
        covariates: Any = None,
        cont_var: Any = None,
        cat_var: Any = None,
        binary_var: Any = None,
        where: str = "",
        weight_type: str = "iptw",
        stabilized: Any = True,
        clip_bounds: Any = None,
        normalize: str = "",
        n_bootstrap: Any = 200,
        random_state: Any = 42,
        title: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """IPTW-adjusted Kaplan-Meier curves with bootstrap CIs (``iptw-survival``).

        Fits the weighting model, then estimates a WEIGHTED KM curve per arm and
        bootstraps ``n_bootstrap`` resamples (refitting the propensity model each
        time, so the CI reflects weight-estimation uncertainty). Produces the
        adjusted survival figure plus the underlying curve table (``time`` and
        ``{treatment,control}_{estimate,lower_ci,upper_ci}``). Use this instead of
        ``kaplan_meier`` whenever the comparison must be confounder-adjusted.
        """
        name = (label or "").strip() or f"iptw_km_{self._n + 1}"
        try:
            nboot = max(20, int(n_bootstrap))
        except Exception:
            nboot = 200
        ctx, err = self._iptw_prepare(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, cont_var=cont_var, cat_var=cat_var,
            binary_var=binary_var, where=where, source=source, name=name,
            weight_type=weight_type, stabilized=stabilized, clip_bounds=clip_bounds,
            normalize=normalize, random_state=random_state,
            duration_column=duration_column, event_column=event_column,
            event_values=event_values,
        )
        if err:
            return err
        assert ctx is not None
        wdf, wcol = ctx["wdf"], ctx["weight_col"]
        n_ev = int(wdf["_event"].sum())
        _emit_tool_progress(
            f"IPTW-KM bootstrap {nboot} resamples "
            f"({len(wdf):,} patients, {n_ev:,} events)"
        )
        t0 = time.monotonic()
        try:
            km = self._iptw_bootstrap(
                ctx["est"].km_confidence_intervals,
                df=wdf, duration_col="_time", event_col="_event", weight_col=wcol,
                n_bootstrap=nboot, random_state=ctx["seed"],
            )
        except Exception as e:
            return f"Error estimating the weighted KM curves: {e}"
        finally:
            self._drop_relation(ctx["work"])
        _emit_tool_progress(f"IPTW-KM bootstrap done ({time.monotonic() - t0:.0f}s)")
        if km is None or len(km) == 0:
            return "The weighted KM estimator returned no time points."

        ttl = (title or "").strip() or f"{ctx['weight_type'].upper()}-adjusted Kaplan-Meier"
        try:
            plt, fig, ax = self._new_mpl_axes()
            for arm, color in (("treatment", "#4C78A8"), ("control", "#E45756")):
                ax.step(km["time"], km[f"{arm}_estimate"], where="post", color=color, label=arm.title())
                ax.fill_between(
                    km["time"], km[f"{arm}_lower_ci"], km[f"{arm}_upper_ci"],
                    step="post", color=color, alpha=0.15, linewidth=0,
                )
            ax.set_xlabel(_bare(duration_column) or "Time")
            ax.set_ylabel("Survival probability")
            ax.set_ylim(0, 1.02)
            ax.set_title(ttl)
            ax.legend(title=f"Arm ({nboot} bootstraps)")
            ax.grid(True, alpha=0.25)
            fig.tight_layout()
        except Exception as e:
            return f"Error rendering the adjusted KM figure: {e}"

        stats = (
            f"{ctx['weight_type'].upper()}-adjusted KM '{name}': {len(wdf):,} patients, "
            f"{n_ev:,} events, {len(km):,} time points, 95% CI from {nboot} bootstrap "
            f"resamples. {self._iptw_weight_stats(ctx)}"
        )
        return self._finalize_mpl_plot(name, ttl, km, fig, stats=stats)

    def iptw_survival_metrics(
        self,
        treatment_column: str,
        treatment_values: Any,
        duration_column: str,
        event_column: str,
        event_values: Any,
        covariates: Any = None,
        cont_var: Any = None,
        cat_var: Any = None,
        binary_var: Any = None,
        where: str = "",
        psurv_time_points: Any = None,
        rmst_time_points: Any = None,
        median_time: Any = True,
        weight_type: str = "iptw",
        stabilized: Any = True,
        clip_bounds: Any = None,
        normalize: str = "",
        n_bootstrap: Any = 200,
        random_state: Any = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Weighted, non-parametric survival metrics (frozen tool, ``iptw-survival``).

        After IPTW/overlap weighting, reports per-arm survival probability at each
        ``psurv_time_points`` value, restricted mean survival time (RMST) at each
        ``rmst_time_points`` horizon and median survival — each with bootstrap 95%
        CIs — AND the treated-minus-control difference, which is the absolute risk
        difference the Cox hazard ratio cannot give you. No proportional-hazards
        assumption is involved. Returns one tidy row per group × metric × timepoint.
        """
        import pandas as pd

        name = (label or "").strip() or f"iptw_survival_metrics_{self._n + 1}"
        try:
            nboot = max(20, int(n_bootstrap))
        except Exception:
            nboot = 200

        def _times(v: Any) -> List[float]:
            if v is None or isinstance(v, bool):
                return []
            if isinstance(v, (int, float, str)):
                v = [v]
            out: List[float] = []
            for x in v:
                try:
                    out.append(float(x))
                except Exception:
                    continue
            return out

        psurv, rmst = _times(psurv_time_points), _times(rmst_time_points)
        want_median = str(median_time).strip().lower() in ("true", "1", "yes")
        if not (psurv or rmst or want_median):
            return (
                "Error: request at least one metric — 'psurv_time_points', "
                "'rmst_time_points' and/or median_time=true."
            )

        ctx, err = self._iptw_prepare(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, cont_var=cont_var, cat_var=cat_var,
            binary_var=binary_var, where=where, source=source, name=name,
            weight_type=weight_type, stabilized=stabilized, clip_bounds=clip_bounds,
            normalize=normalize, random_state=random_state,
            duration_column=duration_column, event_column=event_column,
            event_values=event_values,
        )
        if err:
            return err
        assert ctx is not None
        wdf, wcol = ctx["wdf"], ctx["weight_col"]
        n_ev = int(wdf["_event"].sum())
        _emit_tool_progress(
            f"IPTW metrics bootstrap {nboot} resamples "
            f"({len(wdf):,} patients, {n_ev:,} events)"
        )
        t0 = time.monotonic()
        try:
            res = self._iptw_bootstrap(
                ctx["est"].survival_metrics,
                df=wdf, duration_col="_time", event_col="_event", weight_col=wcol,
                psurv_time_points=psurv or None, rmst_time_points=rmst or None,
                median_time=want_median, n_bootstrap=nboot, random_state=ctx["seed"],
            )
        except Exception as e:
            return f"Error computing the weighted survival metrics: {e}"
        finally:
            self._drop_relation(ctx["work"])
        _emit_tool_progress(f"IPTW metrics bootstrap done ({time.monotonic() - t0:.0f}s)")

        def _triple(v: Any):
            try:
                est, lo, hi = (float(x) for x in list(v)[:3])
                return est, lo, hi
            except Exception:
                return None, None, None

        rows: List[Dict[str, Any]] = []
        for group in ("treatment", "control", "difference"):
            block = (res or {}).get(group) or {}
            for tp, val in (block.get("survival_prob") or {}).items():
                e, lo, hi = _triple(val)
                rows.append({"group": group, "metric": "survival_probability",
                             "timepoint": float(tp), "estimate": e,
                             "lower_ci": lo, "upper_ci": hi})
            for tp, val in (block.get("rmst") or {}).items():
                e, lo, hi = _triple(val)
                rows.append({"group": group, "metric": "rmst", "timepoint": float(tp),
                             "estimate": e, "lower_ci": lo, "upper_ci": hi})
            if block.get("median") is not None:
                e, lo, hi = _triple(block.get("median"))
                rows.append({"group": group, "metric": "median_survival", "timepoint": None,
                             "estimate": e, "lower_ci": lo, "upper_ci": hi})
        if not rows:
            return "The weighted survival-metrics estimator returned no results."

        out = pd.DataFrame(rows)
        self._materialize_output(name, out)
        self._register_deliverable(
            name, out, len(out),
            title=f"{ctx['weight_type'].upper()}-adjusted survival metrics",
        )
        return (
            f"{ctx['weight_type'].upper()}-adjusted survival metrics '{name}': "
            f"{len(wdf):,} patients, {n_ev:,} events, 95% CI from {nboot} bootstrap "
            f"resamples. 'difference' rows are treated minus control (absolute "
            f"risk/time difference).\n{self._iptw_weight_stats(ctx)}\n"
            f"{_fmt_rows_for_llm(out, 40)}"
        )

    def cox_ph(
        self,
        duration_column: str,
        event_column: str,
        event_values: Any,
        covariates: Any,
        where: str = "",
        strata: Any = None,
        weights_column: str = "",
        robust: Any = None,
        cluster_column: str = "",
        interactions: Any = None,
        reference_levels: Any = None,
        penalizer: Any = 0.0,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Cox proportional-hazards regression (frozen tool, lifelines).

        Derives an event indicator (1 if ``event_column`` ∈ ``event_values``),
        builds a numeric design matrix from ``covariates`` (categoricals are
        one-hot encoded against the baseline named in ``reference_levels``), and
        fits ``lifelines.CoxPHFitter`` — optionally stratified by ``strata``.

        Returns ONE long table (``term_type`` / ``term`` / ``group`` / ``coef`` /
        ``se`` / ``hazard_ratio`` / ``hr_lower95`` / ``hr_upper95`` / ``statistic``
        / ``df`` / ``p``) carrying every quantity the fit supports, so a downstream
        node only ever reshapes it:

        * ``coefficient``      — one row per design term.
        * ``contrast``         — with ``interactions``, the focal exposure's effect
          INSIDE each modifier level (main effect + that level's interaction
          coefficient). Its SE needs the off-diagonal covariance, so it can only be
          computed here; ``group`` holds the level.
        * ``interaction_wald`` — the joint test over a whole interaction block.

        ``reference_levels`` names each categorical covariate's BASELINE category
        (``{"Race recode": "Black"}``). Every hazard ratio is relative to that
        level, so a published table cannot be reproduced without it; the default is
        whichever level sorts first.

        Supports the adjustments a causal survival analysis needs:
        ``weights_column`` fits an IPTW-WEIGHTED Cox on the weights produced by
        :meth:`iptw_weight` (robust/sandwich variance is then required and turned
        on automatically), ``cluster_column`` gives clustered robust standard
        errors,         ``interactions`` adds product terms (each reported with a joint
        Wald test over the whole interaction block, which is the only valid way to
        test a categorical interaction spanning several dummies), and
        ``penalizer`` applies ridge regularization when a wide one-hot design is
        collinear.

        A MULTIPLY IMPUTED input (a ``_imputation`` column, from
        :meth:`impute_missing`) is detected automatically: the model is fitted
        separately in each draw and the coefficients pooled by Rubin's rules.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from lifelines import CoxPHFitter
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        dcol = (duration_column or "").strip()
        ecol = (event_column or "").strip()
        if not dcol or not ecol:
            return "Error: 'duration_column' and 'event_column' are required."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return 'Error: \'event_values\' must list the event value(s), e.g. ["Dead"].'
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."
        strata_cols = strata if isinstance(strata, list) else ([strata] if strata else [])
        strata_cols = [str(s) for s in strata_cols if str(s).strip()]
        pairs, perr = _parse_interactions(interactions, covs)
        if perr:
            return perr
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr
        wcol, ccol = _bare(weights_column), _bare(cluster_column)
        try:
            pen = max(0.0, float(penalizer or 0.0))
        except Exception:
            pen = 0.0
        src = (source or "seer").strip() or "seer"

        draws = _mi_draw_ids(self.con, src, where, imputation_column)
        if draws:
            return self._mi_pool_tool(
                "cox_ph",
                draws=draws, imputation_column=imputation_column, where=where,
                key_cols=("term_type", "term", "group"),
                title="Cox PH hazard ratios (multiple-imputation pooled)",
                label=label,
                kwargs=dict(
                    duration_column=duration_column, event_column=event_column,
                    event_values=event_values, covariates=covariates, strata=strata,
                    weights_column=weights_column, robust=robust,
                    cluster_column=cluster_column, interactions=interactions,
                    reference_levels=reference_levels, penalizer=penalizer, source=src,
                ),
            )

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        cov_map: Dict[str, str] = {}
        sel = [
            f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _t",
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e",
        ]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        strata_map: Dict[str, str] = {}
        for i, s in enumerate(strata_cols):
            a = f"s{i}"
            strata_map[a] = s
            sel.append(f"{_q(s)} AS {a}")
        if wcol:
            sel.append(f"TRY_CAST({_q(wcol)} AS DOUBLE) AS _w")
        if ccol:
            sel.append(f"CAST({_q(ccol)} AS VARCHAR) AS _c")
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(dcol)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(dcol)} AS DOUBLE) >= 0"
        )
        if wcol:  # a zero/negative/absent weight contributes nothing and breaks the fit
            sql += f" AND TRY_CAST({_q(wcol)} AS DOUBLE) > 0"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        # Restrict to the rows the model can use BEFORE encoding. Doing it after
        # would leave a dummy column for a level that occurred ONLY in the dropped
        # rows — an all-zero column that lifelines normalizes by a zero standard
        # deviation and reports as "delta contains nan value(s)", naming nothing.
        n_loaded = len(df)
        miss_mask, missing_by_cov = _incomplete_rows(df, cov_map)
        if miss_mask.any():
            df = df[~miss_mask].reset_index(drop=True)
        if len(df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)

        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            return str(e)

        unrepresented = _unrepresented_covariates(cov_map, features)
        X, features, const_cols, dep_cols = _prune_unidentifiable(X, features)
        if not features:
            return (
                "Error: no identifiable covariate column is left — every one is "
                f"single-valued in this cohort ({list(const_cols) or unrepresented}). "
                "Drop them from 'covariates', or widen 'where' so they actually vary."
            )

        # Interaction terms: the cross-product of the two covariates' design
        # blocks, so a categorical × categorical interaction expands over levels.
        inter_blocks: List[Tuple[str, List[str]]] = []
        inter_meta: List[Dict[str, Any]] = []
        inter_cols: Dict[str, Any] = {}
        for a, b in pairs:
            fa, fb = _feature_block(features, a), _feature_block(features, b)
            if not fa or not fb:
                return f"Error: interaction '{a} * {b}' has no design columns for {a if not fa else b}."
            if len(fa) * len(fb) > 60:
                return (
                    f"Error: interaction '{a} * {b}' would expand to {len(fa) * len(fb)} terms. "
                    "Bin one of the variables (e.g. into age groups) before interacting them."
                )
            block: List[str] = []
            empty: List[str] = []
            for f1 in fa:
                for f2 in fb:
                    prod = X[f1].astype(float) * X[f2].astype(float)
                    # An empty cell (no patient has both levels) is an all-zero
                    # column that makes the design singular — drop it rather than
                    # letting the Cox fit fail on "matrix inversion problems".
                    if float(prod.std(skipna=True) or 0.0) == 0.0:
                        empty.append(f"{f1}{_INTERACT_SEP}{f2}")
                        continue
                    nm = f"{f1}{_INTERACT_SEP}{f2}"
                    inter_cols[nm] = prod
                    block.append(nm)
            if empty:
                logger.info(
                    "[seer] cox_ph: dropped %d empty interaction cell(s) for '%s * %s' "
                    "(no patients in that combination)", len(empty), a, b,
                )
            if not block:
                return (
                    f"Error: interaction '{a} * {b}' has no non-empty cells — every level "
                    "combination is empty, so the interaction is not estimable."
                )
            inter_blocks.append((f"{a} * {b}", block))
            inter_meta.append({"term": f"{a} * {b}", "a": a, "fa": fa, "b": b, "fb": fb})
        # Decide which side of each interaction is the effect MODIFIER — the
        # categorical variable whose levels the other variable's effect is
        # reported within. The declared order (first = exposure) wins when both
        # are categorical. This drives the post-estimation contrasts below.
        alias_of = {orig: a for a, orig in cov_map.items()}
        for m in inter_meta:
            a, b, fa, fb = m["a"], m["b"], m["fa"], m["fb"]
            a_cat = any(f.startswith(f"{a}=") for f in fa)
            b_cat = any(f.startswith(f"{b}=") for f in fb)
            if b_cat:
                m.update(focal=a, focal_features=fa, modifier=b,
                         modifier_features=fb, focal_is_first=True)
            elif a_cat:
                m.update(focal=b, focal_features=fb, modifier=a,
                         modifier_features=fa, focal_is_first=False)
            else:  # two numeric terms — there are no levels to stratify by
                m["modifier"] = None
                continue
            m["modifier_reference"] = _dropped_level(
                df[alias_of[m["modifier"]]], m["modifier"], m["modifier_features"]
            )
        if inter_cols:
            X = pd.concat([X, pd.DataFrame(inter_cols, index=X.index)], axis=1)

        model_df = pd.concat(
            [df[["_t", "_e"]].reset_index(drop=True), X.reset_index(drop=True)], axis=1
        )
        strata_names: List[str] = []
        for a, orig in strata_map.items():
            model_df[orig] = df[a].astype("string").reset_index(drop=True)
            strata_names.append(orig)
        if wcol:
            model_df["_w"] = df["_w"].reset_index(drop=True)
        if ccol:
            model_df["_c"] = df["_c"].reset_index(drop=True)
        model_df = model_df.dropna()
        if len(model_df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)
        if int(model_df["_e"].sum()) == 0:
            return "No events in the cohort — check 'event_values' / the event column."

        design_note = _design_note(
            n_loaded, len(model_df), missing_by_cov, const_cols, dep_cols, unrepresented
        )
        if design_note:
            logger.warning("[seer] cox_ph: %s", design_note)

        # lifelines only trusts non-integer (i.e. IPTW) weights with the robust
        # sandwich estimator, so default it on whenever weights are supplied.
        if robust is None:
            use_robust = bool(wcol)
        else:
            use_robust = str(robust).strip().lower() in ("true", "1", "yes")
        if wcol and not use_robust:
            logger.warning(
                "[seer] cox_ph: weights without robust variance — standard errors "
                "will be too small; pass robust=true."
            )
        logger.info(
            "[seer] cox_ph: fitting n=%d (%d events), %d term(s)%s%s%s%s",
            len(model_df), int(model_df["_e"].sum()), len(X.columns),
            f", weights='{wcol}'" if wcol else "",
            ", robust SE" if use_robust else "",
            f", clustered by '{ccol}'" if ccol else "",
            f", penalizer={pen}" if pen else "",
        )
        try:
            cph = _cox_fitter(pen)
            cph.fit(
                model_df,
                duration_col="_t",
                event_col="_e",
                strata=strata_names or None,
                weights_col="_w" if wcol else None,
                cluster_col="_c" if ccol else None,
                robust=use_robust,
            )
        except Exception as e:
            return f"Error fitting Cox model: {e}"

        # ONE long result table holding every quantity the fit can support, so a
        # downstream node only ever has to RESHAPE it — never to recompute from
        # the covariance matrix, which does not survive this call. `term_type`
        # separates the three row kinds.
        summ = cph.summary  # coef, exp(coef), se, z, p, CI, ...
        rows: List[Dict[str, Any]] = []
        for cov, r in summ.iterrows():
            rows.append(
                {
                    "term_type": "coefficient",
                    "term": str(cov),
                    "group": None,
                    "coef": round(float(r.get("coef", float("nan"))), 5),
                    "se": round(float(r.get("se(coef)", float("nan"))), 5),
                    "hazard_ratio": round(float(r.get("exp(coef)", float("nan"))), 5),
                    "hr_lower95": round(float(r.get("exp(coef) lower 95%", float("nan"))), 5),
                    "hr_upper95": round(float(r.get("exp(coef) upper 95%", float("nan"))), 5),
                    "statistic": round(float(r.get("z", float("nan"))), 4),
                    "df": None,
                    "p": round(float(r.get("p", float("nan"))), 6),
                }
            )

        # Stratum-specific effects (β_focal + β_interaction) for every interaction.
        cov_mat = _cox_cov_matrix(cph)
        contrast_rows = _interaction_contrast_rows(cph.params_, cov_mat, inter_meta)

        # Joint Wald test per interaction block — a categorical interaction spread
        # over several dummies has no single p-value, only this global one.
        wald_rows: List[Dict[str, Any]] = []
        for term, block in inter_blocks:
            chi2, dfree, p = _wald_block_test(cph.params_, cov_mat, block)
            wald_rows.append({
                "term_type": "interaction_wald",
                "term": f"{term} (global)",
                "group": None,
                "coef": None, "se": None, "hazard_ratio": None,
                "hr_lower95": None, "hr_upper95": None,
                "statistic": chi2, "df": dfree,
                "p": None if p is None else round(float(p), 6),
            })
        base_rows = _baseline_rows(df, cov_map, features)
        table = pd.DataFrame(rows + base_rows + contrast_rows + wald_rows)
        name = (label or "").strip() or f"cox_ph_{self._n + 1}"
        try:
            cindex = round(float(cph.concordance_index_), 4)
        except Exception:
            cindex = None
        # Parquet-out contract (like mann_whitney_u): materialize the hazard-ratio
        # table, write it to S3 as a single parquet, RETURN that path, and let the
        # graph's persist layer reuse the URI (no second copy).
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Cox PH hazard ratios",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        notes = "".join([
            f" Stratified by {strata_names}." if strata_names else "",
            f" IPTW-weighted on '{wcol}' (effective n={model_df['_w'].sum():,.0f})." if wcol else "",
            " Robust (sandwich) variance." if use_robust else "",
            f" Clustered by '{ccol}'." if ccol else "",
            f" Ridge penalizer={pen}." if pen else "",
        ])
        stats = (
            f"Cox PH '{name}' fitted on n={len(model_df):,} "
            f"({int(model_df['_e'].sum()):,} events), concordance={cindex}.{notes}"
            + (f" Cohort/design: {design_note}." if design_note else "")
        )
        out = f"{stats}\nModel terms (term_type='coefficient'):\n{_fmt_rows_for_llm(pd.DataFrame(rows), 40)}"
        if base_rows:
            out += (
                "\nBaseline categories (term_type='reference', hazard_ratio=1.0) — every HR "
                "above is measured against THESE levels:\n"
                f"{_fmt_rows_for_llm(pd.DataFrame(base_rows)[['term']], 40)}"
            )
        if contrast_rows:
            out += (
                "\nStratum-specific effects (term_type='contrast') — the focal term's "
                "effect INSIDE each modifier level, i.e. the main effect plus that "
                "level's interaction coefficient, with the SE taken from the full "
                "covariance matrix. Report THESE, not the raw interaction coefficients:\n"
                f"{_fmt_rows_for_llm(pd.DataFrame(contrast_rows), 40)}"
            )
        if wald_rows:
            out += (
                "\nInteraction global (Wald) tests (term_type='interaction_wald') — use "
                "THESE p-values, not the per-term ones, to judge effect modification:\n"
                f"{_fmt_rows_for_llm(pd.DataFrame(wald_rows), 20)}"
            )
        if parquet_uri:
            return f"{parquet_uri}\n{out}"
        return out

    def cox_ph_univariate(
        self,
        duration_column: str,
        event_column: str,
        event_values: Any,
        covariates: Any,
        where: str = "",
        strata: Any = None,
        weights_column: str = "",
        robust: Any = None,
        cluster_column: str = "",
        reference_levels: Any = None,
        penalizer: Any = 0.0,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """UNIVARIATE Cox regression — one SEPARATE model per covariate (lifelines).

        Fits ``len(covariates)`` independent ``CoxPHFitter`` models, each containing
        exactly ONE covariate, and stacks their results into a single long table.
        This is the "univariate, one characteristic at a time" column that survival
        papers print beside the multivariable one; :meth:`cox_ph` cannot produce it,
        because a single fit mutually adjusts every covariate.

        Returns one table (``covariate`` / ``term_type`` / ``term`` / ``coef`` /
        ``se`` / ``hazard_ratio`` / ``hr_lower95`` / ``hr_upper95`` / ``statistic`` /
        ``df`` / ``p`` / ``n`` / ``events``) where ``covariate`` says which model a
        row came from and ``term_type`` is one of:

        * ``coefficient`` — one row per non-baseline level (or the numeric term).
        * ``reference``   — that model's baseline level, ``hazard_ratio`` 1.0.
        * ``global_wald`` — the joint test over all of the covariate's levels, i.e.
          the ONE p-value for the characteristic as a whole. A categorical spanning
          several dummies has no other valid single p-value.

        Accepts the same ``strata`` / ``weights_column`` / ``robust`` /
        ``cluster_column`` / ``reference_levels`` / ``penalizer`` adjustments as
        :meth:`cox_ph`; they are applied identically to every model. A MULTIPLY
        IMPUTED input is detected automatically and every model is fitted inside
        each draw, then pooled by Rubin's rules.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        dcol = (duration_column or "").strip()
        ecol = (event_column or "").strip()
        if not dcol or not ecol:
            return "Error: 'duration_column' and 'event_column' are required."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return 'Error: \'event_values\' must list the event value(s), e.g. ["Dead"].'
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."
        strata_cols = strata if isinstance(strata, list) else ([strata] if strata else [])
        strata_cols = [str(s) for s in strata_cols if str(s).strip()]
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr
        wcol, ccol = _bare(weights_column), _bare(cluster_column)
        try:
            pen = max(0.0, float(penalizer or 0.0))
        except Exception:
            pen = 0.0
        src = (source or "seer").strip() or "seer"

        draws = _mi_draw_ids(self.con, src, where, imputation_column)
        if draws:
            return self._mi_pool_tool(
                "cox_ph_univariate",
                draws=draws, imputation_column=imputation_column, where=where,
                key_cols=("covariate", "term_type", "term"),
                title="Univariate Cox hazard ratios (multiple-imputation pooled)",
                label=label,
                kwargs=dict(
                    duration_column=duration_column, event_column=event_column,
                    event_values=event_values, covariates=covariates, strata=strata,
                    weights_column=weights_column, robust=robust,
                    cluster_column=cluster_column, reference_levels=reference_levels,
                    penalizer=penalizer, source=src,
                ),
            )

        # Pull the cohort ONCE for every model: the covariate set is fixed, so N
        # queries would only re-read the same rows N times.
        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        cov_map: Dict[str, str] = {}
        sel = [
            f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _t",
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e",
        ]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        strata_map: Dict[str, str] = {}
        for i, s in enumerate(strata_cols):
            a = f"s{i}"
            strata_map[a] = s
            sel.append(f"{_q(s)} AS {a}")
        if wcol:
            sel.append(f"TRY_CAST({_q(wcol)} AS DOUBLE) AS _w")
        if ccol:
            sel.append(f"CAST({_q(ccol)} AS VARCHAR) AS _c")
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(dcol)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(dcol)} AS DOUBLE) >= 0"
        )
        if wcol:
            sql += f" AND TRY_CAST({_q(wcol)} AS DOUBLE) > 0"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        if robust is None:
            use_robust = bool(wcol)
        else:
            use_robust = str(robust).strip().lower() in ("true", "1", "yes")
        logger.info(
            "[seer] cox_ph_univariate: %d separate model(s) on n=%d rows%s%s",
            len(covs), len(df), ", robust SE" if use_robust else "",
            f", strata={strata_cols}" if strata_cols else "",
        )

        rows: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for alias, orig in cov_map.items():
            # Each univariate model has its OWN analysis population — that is the
            # point of the table — so the complete-case restriction is applied per
            # covariate rather than once across all of them, which would shrink
            # every row to the intersection nobody asked for.
            miss_i, _missing_i = _incomplete_rows(df, {alias: orig})
            sub = df[~miss_i].reset_index(drop=True) if miss_i.any() else df
            if len(sub) == 0:
                skipped.append(f"{orig} (never recorded in this cohort)")
                continue
            try:
                X, features = _design_matrix(sub, [alias], cov_map, refs)
            except ValueError as e:
                return str(e)
            X, features, const_i, _dep_i = _prune_unidentifiable(X, features)
            if not features:
                reason = ("single-valued in this cohort — not identifiable"
                          if const_i else "no usable design columns")
                skipped.append(f"{orig} ({reason})")
                continue

            model_df = pd.concat(
                [sub[["_t", "_e"]].reset_index(drop=True), X.reset_index(drop=True)], axis=1
            )
            strata_names: List[str] = []
            for s_alias, s_orig in strata_map.items():
                if s_orig == orig:  # a covariate cannot be both the term and its stratum
                    continue
                model_df[s_orig] = sub[s_alias].astype("string").reset_index(drop=True)
                strata_names.append(s_orig)
            if wcol:
                model_df["_w"] = sub["_w"].reset_index(drop=True)
            if ccol:
                model_df["_c"] = sub["_c"].reset_index(drop=True)
            model_df = model_df.dropna()
            n_used = len(model_df)
            n_events = int(model_df["_e"].sum()) if n_used else 0
            if n_used == 0 or n_events == 0:
                skipped.append(f"{orig} (no rows/events after dropping missing values)")
                continue

            try:
                cph = _cox_fitter(pen)
                cph.fit(
                    model_df,
                    duration_col="_t",
                    event_col="_e",
                    strata=strata_names or None,
                    weights_col="_w" if wcol else None,
                    cluster_col="_c" if ccol else None,
                    robust=use_robust,
                )
            except Exception as e:
                # One unestimable characteristic must not sink the other models:
                # record it and keep going, so the table still reports the rest.
                logger.warning("[seer] cox_ph_univariate: '%s' failed to fit: %s", orig, e)
                skipped.append(f"{orig} ({e})")
                continue

            for term, r in cph.summary.iterrows():
                rows.append({
                    "covariate": orig,
                    "term_type": "coefficient",
                    "term": str(term),
                    "coef": round(float(r.get("coef", float("nan"))), 5),
                    "se": round(float(r.get("se(coef)", float("nan"))), 5),
                    "hazard_ratio": round(float(r.get("exp(coef)", float("nan"))), 5),
                    "hr_lower95": round(float(r.get("exp(coef) lower 95%", float("nan"))), 5),
                    "hr_upper95": round(float(r.get("exp(coef) upper 95%", float("nan"))), 5),
                    "statistic": round(float(r.get("z", float("nan"))), 4),
                    "df": None,
                    "p": round(float(r.get("p", float("nan"))), 6),
                    "n": n_used,
                    "events": n_events,
                })
            for base in _baseline_rows(sub, {alias: orig}, features):
                rows.append({
                    "covariate": orig, "term_type": "reference", "term": base["term"],
                    "coef": 0.0, "se": None, "hazard_ratio": 1.0,
                    "hr_lower95": None, "hr_upper95": None,
                    "statistic": None, "df": None, "p": None,
                    "n": n_used, "events": n_events,
                })
            # One p-value for the characteristic as a whole. With a single design
            # column this equals the term's own Wald p; with several dummies it is
            # the only defensible way to test the variable.
            chi2, dfree, p = _wald_block_test(cph.params_, _cox_cov_matrix(cph), features)
            rows.append({
                "covariate": orig, "term_type": "global_wald",
                "term": f"{orig} (global)",
                "coef": None, "se": None, "hazard_ratio": None,
                "hr_lower95": None, "hr_upper95": None,
                "statistic": chi2, "df": dfree,
                "p": None if p is None else round(float(p), 6),
                "n": n_used, "events": n_events,
            })

        if not rows:
            return (
                "Error: no univariate Cox model could be fitted. "
                + ("Skipped: " + "; ".join(skipped) if skipped else "")
            )

        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"cox_ph_univariate_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Univariate Cox hazard ratios",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        fitted = table["covariate"].nunique()
        notes = "".join([
            f" Stratified by {strata_cols}." if strata_cols else "",
            f" IPTW-weighted on '{wcol}'." if wcol else "",
            " Robust (sandwich) variance." if use_robust else "",
            f" Clustered by '{ccol}'." if ccol else "",
            f" Ridge penalizer={pen}." if pen else "",
            f" Not estimable: {'; '.join(skipped)}." if skipped else "",
        ])
        out = (
            f"Univariate Cox '{name}': {fitted} separate single-covariate model(s), "
            f"each on its own complete cases.{notes}\n"
            "One row per level (term_type='coefficient'), each covariate's baseline "
            "(term_type='reference', hazard_ratio=1.0) and its whole-variable p-value "
            "(term_type='global_wald'):\n"
            f"{_fmt_rows_for_llm(table, 80)}"
        )
        if parquet_uri:
            return f"{parquet_uri}\n{out}"
        return out

    def cox_ph_subgroup(
        self,
        duration_column: str,
        event_column: str,
        event_values: Any,
        exposure_column: str,
        subgroup_columns: Any,
        reference_level: str = "",
        reference_levels: Any = None,
        covariates: Any = None,
        include_overall: Any = True,
        where: str = "",
        strata: Any = None,
        weights_column: str = "",
        robust: Any = None,
        cluster_column: str = "",
        penalizer: Any = 0.0,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """SUBGROUP Cox — separate exposure fits within each subgroup level.

        Wraps the same ``CoxPHFitter`` / design-matrix path as :meth:`cox_ph`, but
        fits ONE model per slot:

        * optional Overall (full cohort after ``where``), then
        * every distinct level of every column in ``subgroup_columns``.

        Each fit is exposure-only by default (plus optional ``covariates``). This is
        the Table-5 / forest-plot pattern ("HR of surgery within age <40", …). It is
        NOT ``strata`` (shared coefficients, separate baselines) and NOT
        ``interactions`` (one model). Use :meth:`cox_ph` / :meth:`cox_ph_univariate`
        for those.

        Returns one stacked table with ``subgroup_variable`` / ``subgroup_category``
        / ``n`` / ``n_ref`` / ``n_exposed`` / ``events`` plus the exposure HR row
        (``term`` / ``coef`` / ``se`` / ``hazard_ratio`` / ``hr_lower95`` /
        ``hr_upper95`` / ``p``). A MULTIPLY IMPUTED input is detected
        automatically: every subgroup is fitted inside each draw and pooled by
        Rubin's rules, so the reported counts stay on the patient scale.
        """
        try:
            import pandas as pd
            from lifelines import CoxPHFitter  # noqa: F401 — exercised via _cox_fitter
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        dcol = (duration_column or "").strip()
        ecol = (event_column or "").strip()
        exp = (exposure_column or "").strip()
        if not dcol or not ecol:
            return "Error: 'duration_column' and 'event_column' are required."
        if not exp:
            return "Error: 'exposure_column' is required (the binary/group term whose HR is reported in every subgroup)."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return 'Error: \'event_values\' must list the event value(s), e.g. ["Dead"].'
        sub_cols = [str(c) for c in (subgroup_columns or []) if str(c).strip()]
        if not sub_cols:
            return "Error: 'subgroup_columns' (at least one) are required."
        for c in sub_cols:
            if c in (dcol, ecol, exp):
                return (
                    f"Error: subgroup column '{c}' cannot be the duration, event, or "
                    "exposure column."
                )
        extra = [str(c) for c in (covariates or []) if str(c).strip()]
        for c in extra:
            if c in (dcol, ecol, exp) or c in sub_cols:
                return (
                    f"Error: optional covariate '{c}' collides with duration/event/"
                    "exposure/subgroup_columns."
                )
        model_covs = [exp] + extra
        strata_cols = strata if isinstance(strata, list) else ([strata] if strata else [])
        strata_cols = [str(s) for s in strata_cols if str(s).strip()]
        refs, rerr = _reference_map(reference_levels, model_covs)
        if rerr:
            return rerr
        ref_one = (reference_level or "").strip()
        if ref_one:
            refs[exp] = ref_one
        if include_overall is None or include_overall == "":
            do_overall = True
        elif isinstance(include_overall, bool):
            do_overall = include_overall
        else:
            do_overall = str(include_overall).strip().lower() in ("true", "1", "yes", "y")
        wcol, ccol = _bare(weights_column), _bare(cluster_column)
        try:
            pen = max(0.0, float(penalizer or 0.0))
        except Exception:
            pen = 0.0
        src = (source or "seer").strip() or "seer"

        draws = _mi_draw_ids(self.con, src, where, imputation_column)
        if draws:
            return self._mi_pool_tool(
                "cox_ph_subgroup",
                draws=draws, imputation_column=imputation_column, where=where,
                key_cols=("subgroup_variable", "subgroup_category", "term"),
                title="Subgroup Cox hazard ratios (multiple-imputation pooled)",
                label=label,
                kwargs=dict(
                    duration_column=duration_column, event_column=event_column,
                    event_values=event_values, exposure_column=exposure_column,
                    subgroup_columns=subgroup_columns, reference_level=reference_level,
                    reference_levels=reference_levels, covariates=covariates,
                    include_overall=include_overall, strata=strata,
                    weights_column=weights_column, robust=robust,
                    cluster_column=cluster_column, penalizer=penalizer, source=src,
                ),
            )

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        cov_map: Dict[str, str] = {}
        sel = [
            f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _t",
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e",
        ]
        for i, c in enumerate(model_covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        sub_map: Dict[str, str] = {}
        for i, c in enumerate(sub_cols):
            a = f"g{i}"
            sub_map[a] = c
            sel.append(f"CAST({_q(c)} AS VARCHAR) AS {a}")
        strata_map: Dict[str, str] = {}
        for i, s in enumerate(strata_cols):
            a = f"s{i}"
            strata_map[a] = s
            sel.append(f"{_q(s)} AS {a}")
        if wcol:
            sel.append(f"TRY_CAST({_q(wcol)} AS DOUBLE) AS _w")
        if ccol:
            sel.append(f"CAST({_q(ccol)} AS VARCHAR) AS _c")
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(dcol)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(dcol)} AS DOUBLE) >= 0"
        )
        if wcol:
            sql += f" AND TRY_CAST({_q(wcol)} AS DOUBLE) > 0"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        if robust is None:
            use_robust = bool(wcol)
        else:
            use_robust = str(robust).strip().lower() in ("true", "1", "yes")
        exp_alias = next(a for a, c in cov_map.items() if c == exp)

        # Slots: optional overall, then every level of every subgroup column.
        slots: List[Tuple[str, str, Any]] = []
        if do_overall:
            slots.append(("Overall", "All", None))
        for alias, orig in sub_map.items():
            levels = sorted(
                str(v) for v in df[alias].dropna().unique() if str(v).strip() != ""
            )
            for lv in levels:
                slots.append((orig, lv, (alias, lv)))

        logger.info(
            "[seer] cox_ph_subgroup: %d slot(s) on n=%d rows, exposure='%s'%s%s",
            len(slots), len(df), exp, ", robust SE" if use_robust else "",
            f", strata={strata_cols}" if strata_cols else "",
        )

        def _arm_counts(frame) -> Tuple[int, int]:
            """n_ref / n_exposed for the exposure column inside ``frame``."""
            text = frame[exp_alias].astype("string")
            ref = refs.get(exp)
            if ref is not None:
                wanted = _fold_label(ref)
                is_ref = text.map(lambda v: _fold_label(v) if v is not None else "") == wanted
            else:
                levels = sorted(str(v) for v in text.dropna().unique())
                if not levels:
                    return 0, 0
                is_ref = text.astype(str) == levels[0]
            n_ref = int(is_ref.sum())
            n_exp = int((~is_ref & text.notna()).sum())
            return n_ref, n_exp

        def _exposure_terms(features: List[str]) -> List[str]:
            return [
                f for f in features
                if f == exp or str(f).startswith(f"{exp}=")
            ]

        rows: List[Dict[str, Any]] = []
        skipped: List[str] = []
        # Covariates that dropped out of AT LEAST ONE slot's design. Inside a
        # subgroup this is routine, but it silently changes what "adjusted" means
        # for that row, so the summary has to say which ones.
        unadjusted: set = set()
        for sub_var, sub_cat, filt in slots:
            slot_label = f"{sub_var}={sub_cat}"
            if filt is None:
                sub = df
            else:
                alias, lv = filt
                sub = df[df[alias].astype("string") == lv]
            if len(sub) == 0:
                skipped.append(f"{slot_label} (0 rows)")
                continue
            sub_i = sub.reset_index(drop=True)
            # Restrict to complete rows before encoding, so a level that only
            # occurred in the incomplete ones never becomes an all-zero dummy.
            miss_s, missing_s = _incomplete_rows(sub_i, cov_map)
            if miss_s.any():
                sub_i = sub_i[~miss_s].reset_index(drop=True)
            if len(sub_i) == 0:
                worst = sorted(missing_s.items(), key=lambda kv: -kv[1])[:3]
                blame = ", ".join(k for k, _ in worst)
                skipped.append(
                    f"{slot_label} (no complete row — every one is missing "
                    f"{blame or 'a covariate'})"
                )
                continue
            try:
                X, features = _design_matrix(
                    sub_i, list(cov_map.keys()), cov_map, refs
                )
            except ValueError as e:
                skipped.append(f"{slot_label} ({e})")
                continue
            # Inside one subgroup a covariate routinely collapses to a single
            # level — adjusting for stage within a stage-defined subgroup. That
            # column carries no information and would take the whole fit with it.
            unadjusted.update(_unrepresented_covariates(cov_map, features))
            X, features, const_s, _dep_s = _prune_unidentifiable(X, features)
            unadjusted.update(
                f.split("=", 1)[0] if "=" in str(f) else str(f) for f in const_s
            )
            exp_terms = _exposure_terms(features)
            if not exp_terms:
                why = (
                    f"exposure '{exp}' is single-valued in this subgroup"
                    if _exposure_terms(list(const_s))
                    else f"exposure '{exp}' has no estimable contrast — "
                         "need ≥2 levels in this subgroup"
                )
                skipped.append(f"{slot_label} ({why})")
                continue
            model_df = pd.concat(
                [sub_i[["_t", "_e"]], X.reset_index(drop=True)], axis=1
            )
            strata_names: List[str] = []
            for s_alias, s_orig in strata_map.items():
                model_df[s_orig] = sub_i[s_alias].astype("string")
                strata_names.append(s_orig)
            if wcol:
                model_df["_w"] = sub_i["_w"]
            if ccol:
                model_df["_c"] = sub_i["_c"]
            keep = model_df.dropna().index
            model_df = model_df.loc[keep]
            n_used = len(model_df)
            n_events = int(model_df["_e"].sum()) if n_used else 0
            if n_used == 0 or n_events == 0:
                skipped.append(f"{slot_label} (no rows/events after dropping missing)")
                continue
            n_ref, n_exposed = _arm_counts(sub_i.loc[keep])
            try:
                cph = _cox_fitter(pen)
                cph.fit(
                    model_df,
                    duration_col="_t",
                    event_col="_e",
                    strata=strata_names or None,
                    weights_col="_w" if wcol else None,
                    cluster_col="_c" if ccol else None,
                    robust=use_robust,
                )
            except Exception as e:
                logger.warning(
                    "[seer] cox_ph_subgroup: '%s' failed to fit: %s", slot_label, e
                )
                skipped.append(f"{slot_label} ({e})")
                continue
            for term in exp_terms:
                if term not in cph.summary.index:
                    continue
                r = cph.summary.loc[term]
                rows.append({
                    "subgroup_variable": sub_var,
                    "subgroup_category": sub_cat,
                    "exposure": exp,
                    "term_type": "coefficient",
                    "term": str(term),
                    "coef": round(float(r.get("coef", float("nan"))), 5),
                    "se": round(float(r.get("se(coef)", float("nan"))), 5),
                    "hazard_ratio": round(float(r.get("exp(coef)", float("nan"))), 5),
                    "hr_lower95": round(
                        float(r.get("exp(coef) lower 95%", float("nan"))), 5
                    ),
                    "hr_upper95": round(
                        float(r.get("exp(coef) upper 95%", float("nan"))), 5
                    ),
                    "statistic": round(float(r.get("z", float("nan"))), 4),
                    "p": round(float(r.get("p", float("nan"))), 6),
                    "n": n_used,
                    "n_ref": n_ref,
                    "n_exposed": n_exposed,
                    "events": n_events,
                })

        if not rows:
            return (
                "Error: no subgroup Cox model could be fitted. "
                + ("Skipped: " + "; ".join(skipped) if skipped else "")
            )

        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"cox_ph_subgroup_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Subgroup Cox hazard ratios",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        n_slots = table[["subgroup_variable", "subgroup_category"]].drop_duplicates().shape[0]
        notes = "".join([
            f" Stratified by {strata_cols}." if strata_cols else "",
            f" IPTW-weighted on '{wcol}'." if wcol else "",
            " Robust (sandwich) variance." if use_robust else "",
            f" Clustered by '{ccol}'." if ccol else "",
            f" Ridge penalizer={pen}." if pen else "",
            f" Extra covariates: {extra}." if extra else "",
            (f" Single-valued in at least one subgroup, so NOT adjusted for there: "
             f"{sorted(unadjusted)}." if unadjusted else ""),
            f" Not estimable: {'; '.join(skipped)}." if skipped else "",
        ])
        out = (
            f"Subgroup Cox '{name}': {n_slots} slot(s), exposure='{exp}' "
            f"({len(table)} HR row(s)).{notes}\n"
            "One row per estimable exposure contrast inside each subgroup "
            "(subgroup_variable / subgroup_category / n / n_ref / n_exposed / "
            "events / hazard_ratio / CI / p):\n"
            f"{_fmt_rows_for_llm(table, 80)}"
        )
        if parquet_uri:
            return f"{parquet_uri}\n{out}"
        return out

    def logistic_regression(
        self,
        outcome_column: str,
        outcome_values: Any,
        covariates: Any,
        where: str = "",
        reference_levels: Any = None,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Multivariable logistic regression (frozen tool, statsmodels).

        Models a BINARY outcome (1 if ``outcome_column`` ∈ ``outcome_values``,
        else 0) on ``covariates`` (categoricals one-hot encoded, drop-first),
        fitting ``statsmodels.api.Logit`` with an intercept. Returns an
        odds-ratio table (``covariate`` / ``level_type`` / coef, OR=exp(coef),
        95% CI, z, p) — e.g. the Table 2 "predictors of receiving the treatment"
        model. Each categorical covariate also gets a ``level_type='reference'``
        row (OR 1.0) naming its baseline.

        ``reference_levels`` names each categorical covariate's BASELINE category
        (``{"Race recode": "Black"}``). Every odds ratio is relative to that level,
        so a published table cannot be reproduced without it; the default baseline
        is whichever level sorts first.
        """
        try:
            import numpy as np
            import pandas as pd
            import statsmodels.api as sm
        except Exception as e:  # pragma: no cover
            return f"Error: statsmodels / pandas unavailable ({e})."

        ycol = (outcome_column or "").strip()
        if not ycol:
            return "Error: 'outcome_column' is required."
        if isinstance(outcome_values, str):
            outcome_values = [outcome_values]
        outcome_values = [str(v) for v in (outcome_values or [])]
        if not outcome_values:
            return 'Error: \'outcome_values\' must list the positive-class value(s), e.g. ["Yes"].'
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in outcome_values)
        cov_map: Dict[str, str] = {}
        sel = [f"CASE WHEN {_q(ycol)} IN ({in_list}) THEN 1 ELSE 0 END AS _y"]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        src = (source or "seer").strip() or "seer"
        sql = f"SELECT {', '.join(sel)} FROM {_q(src)} WHERE {_q(ycol)} IS NOT NULL"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            return str(e)
        if not features:
            return "Error: no usable covariate columns after encoding."
        model_df = pd.concat(
            [df[["_y"]].reset_index(drop=True), X.reset_index(drop=True)], axis=1
        ).dropna()
        if model_df["_y"].nunique() < 2:
            return "Outcome has only one class after filtering — check 'outcome_values'."

        y = model_df["_y"].astype(int)
        Xd = model_df[features].astype(float)
        Xc = sm.add_constant(Xd, has_constant="add")
        try:
            res = sm.Logit(y, Xc).fit(disp=0, maxiter=200)
        except Exception as e:
            return f"Error fitting logistic model (statsmodels): {e}"

        conf = res.conf_int()
        rows: List[Dict[str, Any]] = []
        for term in res.params.index:
            coef = float(res.params[term])
            lo = float(conf.loc[term, 0])
            hi = float(conf.loc[term, 1])
            rows.append(
                {
                    "covariate": "(Intercept)" if term == "const" else str(term),
                    "level_type": "intercept" if term == "const" else "coefficient",
                    "coef": round(coef, 5),
                    "odds_ratio": round(float(np.exp(coef)), 5),
                    "or_lower95": round(float(np.exp(lo)), 5),
                    "or_upper95": round(float(np.exp(hi)), 5),
                    "z": round(float(res.tvalues[term]), 4),
                    "p": round(float(res.pvalues[term]), 6),
                }
            )
        # Name each categorical covariate's dropped baseline: the ORs above mean
        # nothing without it, and a published table prints it as "Reference".
        base_rows = [
            {
                "covariate": r["term"], "level_type": "reference",
                "coef": 0.0, "odds_ratio": 1.0, "or_lower95": None,
                "or_upper95": None, "z": None, "p": None,
            }
            for r in _baseline_rows(df, cov_map, features)
        ]
        table = pd.DataFrame(rows + base_rows)
        name = (label or "").strip() or f"logistic_regression_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Logistic regression odds ratios",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        try:
            pseudo_r2 = round(float(res.prsquared), 4)
        except Exception:
            pseudo_r2 = None
        stats = (
            f"Logistic regression '{name}' fitted on n={len(model_df):,} "
            f"({int((y == 1).sum()):,} positive), pseudo-R²={pseudo_r2}."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\nOdds ratios:\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\nOdds ratios:\n{_fmt_rows_for_llm(table, 40)}"

    def glm_regression(
        self,
        outcome_column: str,
        covariates: Any,
        family: str = "gaussian",
        link: str = "",
        outcome_values: Any = None,
        exposure_column: str = "",
        offset_column: str = "",
        weights_column: str = "",
        cov_type: str = "nonrobust",
        cluster_column: str = "",
        alpha: float = 1.0,
        where: str = "",
        reference_levels: Any = None,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Generalized linear model (frozen tool, statsmodels GLM).

        The regression tool for outcomes that are NOT a plain binary event:
        counts and incidence rates (``poisson`` / ``negativebinomial``, with
        ``exposure_column`` for person-time), skewed positive costs or
        length-of-stay (``gamma``, log link), and continuous means (``gaussian``).
        For a binary outcome reported as odds ratios use ``logistic_regression``;
        come here with ``family="binomial", link="log"`` only when the paper
        reports RISK ratios.

        Returns one row per model term: ``coef`` / ``se`` plus ``estimate`` with a
        95% CI, where ``estimate`` is ``exp(coef)`` on a log/logit link and the
        coefficient itself otherwise. ``estimate_type`` names the scale
        (rate_ratio / risk_ratio / odds_ratio / ratio / mean_difference) so a
        downstream table or forest node never has to guess. Each categorical
        covariate also gets a ``level_type='reference'`` row naming its baseline.

        RATE models: pass ``exposure_column`` — person-time in the unit the rate
        should be reported in. It enters as ``log(exposure)`` with its coefficient
        fixed at 1, which is what makes the ratios incidence-RATE ratios instead
        of count ratios. ``offset_column`` is the raw linear-predictor offset for
        callers who already logged it; pass one or the other, never both.

        WEIGHTED models: ``weights_column`` applies per-row weights (the ``iptw``
        / ``overlap_weight`` column from ``iptw_weight`` / ``ate_weight``), which
        is how a weighted outcome model is fitted. A weighted fit needs
        ``cov_type="HC0"`` — or ``"cluster"`` with ``cluster_column`` — for honest
        standard errors, because the model-based ones are too small.

        ``family``: gaussian | binomial | poisson | negativebinomial | gamma |
        inverse_gaussian. ``link`` defaults to that family's published link and
        may be identity | log | logit | probit | cloglog | inverse | sqrt.
        ``alpha`` is the negative-binomial dispersion (default 1.0 — GLM does not
        estimate it). ``outcome_values`` binarizes the outcome and is only for
        ``family="binomial"``; every other family reads ``outcome_column`` as a
        number.

        The design matrix is one-hot encoded drop-first and its RANK is checked
        before fitting: a constant or redundant covariate comes back as an error
        naming the column, rather than being absorbed into a pseudo-inverse fit
        whose coefficients are not uniquely determined.
        """
        try:
            import numpy as np
            import pandas as pd
            import statsmodels.api as sm
        except Exception as e:  # pragma: no cover
            return f"Error: statsmodels / pandas unavailable ({e})."

        ycol = (outcome_column or "").strip()
        if not ycol:
            return "Error: 'outcome_column' is required."
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."

        def _key(text: Any) -> str:
            return str(text or "").strip().lower().replace("-", "_").replace(" ", "_")

        fam_key = _key(family) or "gaussian"
        fam_key = _GLM_FAMILY_ALIASES.get(fam_key, fam_key)
        if fam_key not in _GLM_FAMILY_SPECS:
            return (
                f"Error: unknown family '{family}'. Choose one of "
                f"{sorted(_GLM_FAMILY_SPECS)}."
            )
        fam_cls, default_link = _GLM_FAMILY_SPECS[fam_key]
        link_key = _key(link) or default_link
        if link_key not in _GLM_LINK_CLASSES:
            return (
                f"Error: unknown link '{link}'. Choose one of "
                f"{sorted(_GLM_LINK_CLASSES)}."
            )

        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr

        exposure = (exposure_column or "").strip()
        offset = (offset_column or "").strip()
        weights = (weights_column or "").strip()
        cluster = (cluster_column or "").strip()
        ctype = (cov_type or "nonrobust").strip() or "nonrobust"
        if exposure and offset:
            return (
                "Error: pass 'exposure_column' OR 'offset_column', not both — "
                "exposure is logged for you, offset is used as given."
            )
        if exposure and link_key != "log":
            return (
                f"Error: 'exposure_column' is a rate denominator and only means that "
                f"on a log link (got link='{link_key}'). Drop it or set link=\"log\"."
            )
        if ctype.lower() == "cluster" and not cluster:
            return 'Error: cov_type="cluster" requires \'cluster_column\'.'

        cov_map: Dict[str, str] = {}
        if fam_key == "binomial" and outcome_values:
            if isinstance(outcome_values, str):
                outcome_values = [outcome_values]
            vals = [str(v) for v in (outcome_values or [])]
            in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in vals)
            sel = [f"CASE WHEN {_q(ycol)} IN ({in_list}) THEN 1 ELSE 0 END AS _y"]
        else:
            sel = [f"{_q(ycol)} AS _y"]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        for alias, col in (
            ("_exposure", exposure), ("_offset", offset),
            ("_w", weights), ("_cl", cluster),
        ):
            if col:
                sel.append(f"{_q(col)} AS {alias}")

        src = (source or "seer").strip() or "seer"
        sql = f"SELECT {', '.join(sel)} FROM {_q(src)} WHERE {_q(ycol)} IS NOT NULL"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            return str(e)
        if not features:
            return "Error: no usable covariate columns after encoding."
        # A covariate can vanish without a word: a single-level categorical has its
        # only level dropped as the baseline, so the fit is NOT adjusted for the
        # thing the caller asked to adjust for and nothing in the output says so.
        vanished = [
            orig for orig in cov_map.values()
            if orig not in features
            and not any(str(f).startswith(f"{orig}=") for f in features)
        ]
        if vanished:
            return (
                "Error: these covariates contributed no columns to the design and would "
                f"be silently left out of the model: {vanished}. A categorical with a "
                "single observed level is dropped as its own baseline. Remove it from "
                "'covariates', or widen 'where' so it actually varies."
            )

        aux: Dict[str, Any] = {"_y": pd.to_numeric(df["_y"], errors="coerce")}
        for alias in ("_exposure", "_offset", "_w"):
            if alias in df.columns:
                aux[alias] = pd.to_numeric(df[alias], errors="coerce")
        if "_cl" in df.columns:
            aux["_cl"] = df["_cl"].astype(str)
        model_df = pd.concat(
            [pd.DataFrame(aux).reset_index(drop=True), X.reset_index(drop=True)],
            axis=1,
        ).dropna()
        if len(model_df) == 0:
            return (
                "Error: no complete rows after dropping missing outcome / covariate / "
                "exposure cells. Check for a covariate that is almost entirely NULL."
            )

        y = model_df["_y"].astype(float)
        if fam_key == "binomial" and y.nunique() < 2:
            return (
                "Error: the outcome has only one class after filtering — check "
                "'outcome_values' and 'where'."
            )
        if fam_key in ("poisson", "negativebinomial") and float(y.min()) < 0:
            return (
                f"Error: family '{fam_key}' models counts and needs a non-negative "
                f"outcome (min={float(y.min()):g})."
            )
        if fam_key in ("gamma", "inverse_gaussian") and float(y.min()) <= 0:
            return (
                f"Error: family '{fam_key}' needs a strictly positive outcome "
                f"(min={float(y.min()):g}). Costs / durations of 0 need a different "
                "family (e.g. a two-part model) rather than a shifted outcome."
            )

        # Identifiability BEFORE the fit. statsmodels would accept both of these
        # and answer with pseudo-inverse coefficients plus a per-iteration warning.
        Xd = model_df[features].astype(float)
        const_cols = _constant_columns(Xd)
        if const_cols:
            return (
                "Error: these design columns are constant in this cohort, so their "
                f"coefficients are not identifiable: {const_cols}. Drop the covariate, "
                "or widen 'where' so the column actually varies."
            )
        Xc = sm.add_constant(Xd, has_constant="add")
        dependent = _dependent_columns(Xc)
        if dependent:
            return (
                "Error: the design matrix is rank-deficient — these columns are exact "
                f"linear combinations of the others: {dependent}. The coefficients "
                "would not be uniquely determined, so the CIs would be meaningless. "
                "Usually one covariate is a duplicate or a rescaling of another (age "
                "and age_in_months), or two columns encode the SAME partition under "
                "different labels (stage and a stage_group alias). Drop the redundant "
                "one. Note that a BINNED version of a continuous covariate (age and "
                "age_band) is not redundant — that pair is fine."
            )

        build_kwargs: Dict[str, Any] = {}
        if "_exposure" in model_df.columns:
            expo = model_df["_exposure"].astype(float)
            if float(expo.min()) <= 0:
                return (
                    "Error: 'exposure_column' must be strictly positive person-time "
                    f"(min={float(expo.min()):g}). Rows with no follow-up contribute "
                    "no information and must be filtered out in 'where'."
                )
            build_kwargs["exposure"] = expo.to_numpy()
        if "_offset" in model_df.columns:
            build_kwargs["offset"] = model_df["_offset"].astype(float).to_numpy()
        if "_w" in model_df.columns:
            wv = model_df["_w"].astype(float)
            if float(wv.min()) <= 0:
                return (
                    "Error: 'weights_column' must be positive "
                    f"(min={float(wv.min()):g})."
                )
            build_kwargs["freq_weights"] = wv.to_numpy()

        try:
            link_obj = getattr(sm.families.links, _GLM_LINK_CLASSES[link_key])()
            fam_ctor = getattr(sm.families, fam_cls)
            fam_obj = (
                fam_ctor(link=link_obj, alpha=float(alpha))
                if fam_key == "negativebinomial"
                else fam_ctor(link=link_obj)
            )
        except Exception as e:
            return (
                f"Error: family '{fam_key}' does not accept link '{link_key}' ({e})."
            )

        try:
            model = sm.GLM(y.to_numpy(), Xc, family=fam_obj, **build_kwargs)
            if ctype.lower() == "cluster":
                res = model.fit(
                    maxiter=100, cov_type="cluster",
                    cov_kwds={"groups": model_df["_cl"].to_numpy()},
                )
            else:
                res = model.fit(maxiter=100, cov_type=ctype)
        except Exception as e:
            return f"Error fitting GLM (statsmodels): {e}"
        if not bool(getattr(res, "converged", True)):
            return (
                "Error: the GLM did not converge, so the coefficients are not "
                "reportable. Try a smaller covariate set, or a link the outcome "
                f"supports (a {link_key} link needs the linear predictor to stay "
                "in range for every row)."
            )

        conf = res.conf_int()
        as_ratio = link_key in _GLM_RATIO_LINKS
        etype = _glm_effect_label(fam_key, link_key)
        rows: List[Dict[str, Any]] = []
        for term in list(res.params.index):
            coef = float(res.params[term])
            lo = float(conf.loc[term, 0])
            hi = float(conf.loc[term, 1])
            rows.append(
                {
                    "covariate": "(Intercept)" if term == "const" else str(term),
                    "level_type": "intercept" if term == "const" else "coefficient",
                    "coef": round(coef, 5),
                    "se": round(float(res.bse[term]), 5),
                    "estimate": round(float(np.exp(coef)) if as_ratio else coef, 5),
                    "ci_lower": round(float(np.exp(lo)) if as_ratio else lo, 5),
                    "ci_upper": round(float(np.exp(hi)) if as_ratio else hi, 5),
                    "estimate_type": etype,
                    "z": round(float(res.tvalues[term]), 4),
                    "p": round(float(res.pvalues[term]), 6),
                }
            )
        # Name each categorical covariate's dropped baseline — every ratio above is
        # measured against it, and published tables print it as "Reference".
        base_rows = [
            {
                "covariate": r["term"], "level_type": "reference",
                "coef": 0.0, "se": None,
                "estimate": 1.0 if as_ratio else 0.0,
                "ci_lower": None, "ci_upper": None,
                "estimate_type": etype, "z": None, "p": None,
            }
            for r in _baseline_rows(df, cov_map, features)
        ]
        table = pd.DataFrame(rows + base_rows)

        name = (label or "").strip() or f"glm_regression_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title=f"GLM ({fam_key}, {link_key} link) coefficients",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )

        notes: List[str] = []
        if exposure:
            notes.append(f"exposure={exposure}")
        if offset:
            notes.append(f"offset={offset}")
        if weights:
            notes.append(f"weights={weights}")
        if ctype.lower() != "nonrobust":
            notes.append(f"cov_type={ctype}" + (f"({cluster})" if cluster else ""))
        try:
            dispersion = round(
                float(res.pearson_chi2) / float(res.df_resid), 3
            ) if float(res.df_resid) > 0 else None
        except Exception:
            dispersion = None
        try:
            aic = round(float(res.aic), 2) if np.isfinite(float(res.aic)) else None
        except Exception:
            aic = None
        stats = (
            f"GLM '{name}' ({fam_key}, {link_key} link) fitted on n={len(model_df):,}; "
            f"estimates are {etype}; Pearson dispersion={dispersion}; AIC={aic}"
            + (f"; {', '.join(notes)}" if notes else "")
            + "."
        )
        # Overdispersion invalidates Poisson CIs (they come out too narrow), and it
        # is the single most common reason a published count model is a negative
        # binomial instead. Say so here rather than letting it pass into a table.
        if fam_key == "poisson" and dispersion is not None and dispersion > 1.5:
            stats += (
                f" NOTE: Pearson dispersion {dispersion} > 1.5 indicates "
                'overdispersion — refit with family="negativebinomial" (or '
                'cov_type="HC0") before reporting these CIs.'
            )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\nCoefficients:\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\nCoefficients:\n{_fmt_rows_for_llm(table, 40)}"

    # ── scikit-learn prediction models (frozen tools) ────────────────────
    # Model tools FIT once via :meth:`_fit_sklearn_linear` and write a scored
    # dataset. Evaluation tools read ``predicted_probability`` and never fit.
    # ``ml_cv_performance`` / ``ml_compare`` still use :meth:`_ml_fit_frame`
    # because they refit each fold from a model key.

    def _ml_fit_frame(
        self,
        *,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        where: str,
        reference_levels: Any,
        source: str,
        split_column: str = "",
    ):
        """Build ``(X, y, feature_names)`` from a cohort, or return an error str.

        Mirrors :meth:`logistic_regression`'s cohort build: the binary outcome is
        1 when ``outcome_column`` ∈ ``outcome_values`` (else 0), predictors are
        one-hot encoded (drop-first, ``reference_levels`` honoured) into a numeric
        design matrix. Rows with any missing design cell are dropped (complete
        case), matching the protocol's primary-analysis rule.

        When ``split_column`` is set (from :meth:`ml_train_test_split`), the
        aligned split labels are returned as a fourth value so the caller can
        fit on ``train`` and score on ``test`` without re-encoding each arm.
        """
        import pandas as pd

        ycol = (outcome_column or "").strip()
        if not ycol:
            return "Error: 'outcome_column' is required."
        if isinstance(outcome_values, str):
            outcome_values = [outcome_values]
        outcome_values = [str(v) for v in (outcome_values or [])]
        if not outcome_values:
            return 'Error: \'outcome_values\' must list the positive-class value(s), e.g. ["Yes"].'
        covs = [str(c) for c in (predictors or []) if str(c).strip()]
        if not covs:
            return "Error: 'predictors' (at least one) are required."
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in outcome_values)
        cov_map: Dict[str, str] = {}
        sel = [f"CASE WHEN {_q(ycol)} IN ({in_list}) THEN 1 ELSE 0 END AS _y"]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        split_col = (split_column or "").strip()
        if split_col:
            sel.append(f"{_q(split_col)} AS _split")
        src = (source or "seer").strip() or "seer"
        sql = f"SELECT {', '.join(sel)} FROM {_q(src)} WHERE {_q(ycol)} IS NOT NULL"
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."
        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            return str(e)
        if not features:
            return "Error: no usable predictor columns after encoding."
        keep = ["_y"] + (["_split"] if split_col else [])
        model_df = pd.concat(
            [df[keep].reset_index(drop=True), X.reset_index(drop=True)], axis=1
        ).dropna()
        if model_df["_y"].nunique() < 2:
            return "Outcome has only one class after filtering — check 'outcome_values'."
        y = model_df["_y"].astype(int)
        Xd = model_df[features].astype(float)
        if split_col:
            return Xd, y, features, model_df["_split"].astype(str)
        return Xd, y, features

    @staticmethod
    def _ml_class_weight(class_weight: Any):
        """Parse the ``class_weight`` param → sklearn 'balanced' or None."""
        return (
            "balanced"
            if str(class_weight).strip().lower() in ("balanced", "true", "1", "yes")
            else None
        )

    def ml_train_test_split(
        self,
        test_size: float = 0.3,
        stratify_column: str = "",
        split_column: str = "split",
        random_state: int = 42,
        where: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Tag every row ``train`` / ``test`` via sklearn ``train_test_split``.

        OUTPUT is the input cohort plus a ``split`` column (override the name
        with ``split_column``). Chain a model tool next
        (``LogisticRegression``, ``RandomForestClassifier``, …) with
        ``split_column="split"`` so it fits on train and scores every row.
        Evaluation tools then read ``predicted_probability`` — and
        ``ml_classifier_performance`` with ``split_column="split"`` keeps the
        test rows only. Stratify on the outcome when the request asks for a
        class-balanced holdout.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.model_selection import train_test_split
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        src = (source or "seer").strip() or "seer"
        out_col = (split_column or "split").strip() or "split"
        sql = f"SELECT * FROM {_q(src)}"
        w = (where or "").strip()
        if w:
            sql += f" WHERE ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error reading cohort for train/test split: {e}"
        if len(df) < 4:
            return f"Error: need at least 4 rows to split (got {len(df)})."

        try:
            frac = float(test_size)
        except (TypeError, ValueError):
            return "Error: 'test_size' must be a fraction in (0, 1), e.g. 0.3."
        if not (0.0 < frac < 1.0):
            return "Error: 'test_size' must be a fraction in (0, 1), e.g. 0.3."

        idx = np.arange(len(df))
        strat = None
        strat_note = ""
        scol = (stratify_column or "").strip()
        if scol:
            if scol not in df.columns:
                return (
                    f"Error: stratify_column '{scol}' is not in this input. "
                    f"Available: {list(df.columns)[:30]}"
                )
            strat = df[scol].astype(str).fillna("__NA__")
        try:
            train_i, test_i = train_test_split(
                idx, test_size=frac, random_state=int(random_state), stratify=strat,
            )
        except ValueError:
            train_i, test_i = train_test_split(
                idx, test_size=frac, random_state=int(random_state), stratify=None,
            )
            strat_note = " (stratify failed — split is unstratified)"

        split = np.full(len(df), "train", dtype=object)
        split[np.asarray(test_i, dtype=int)] = "test"
        df = df.copy()
        df[out_col] = split

        name = (label or "").strip() or f"ml_split_{self._n + 1}"
        self._materialize_output(name, df)
        parquet_uri = self._export_parquet(name)
        n_train = int((df[out_col] == "train").sum())
        n_test = int((df[out_col] == "test").sum())
        counts = pd.DataFrame([
            {"split": "train", "n": n_train},
            {"split": "test", "n": n_test},
        ])
        self._register_deliverable(
            name, counts, len(counts),
            title="Train/test split counts",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Train/test split '{name}': {n_train:,} train / {n_test:,} test "
            f"(test_size={frac}, column='{out_col}'"
            + (f", stratified on '{scol}'" if scol else "")
            + f"){strat_note}."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}"
        return stats

    def ml_classifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        model: str = "elasticnet_logistic",
        where: str = "",
        reference_levels: Any = None,
        l1_ratio: float = 0.5,
        cv_folds: int = 10,
        n_estimators: int = 500,
        max_depth: int = 3,
        learning_rate: float = 0.1,
        class_weight: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Unregistered wrapper. Use a sklearn class-name model tool instead.

        Fit an sklearn binary classifier and return its coefficient/importance table.

        ``model`` selects the estimator: ``elasticnet_logistic``
        (``LogisticRegressionCV`` penalty='elasticnet', saga, λ by CV),
        ``logistic`` (unpenalized baseline), ``random_forest``
        (``RandomForestClassifier`` 500 trees, mtry=√p, OOB AUC) or
        ``gradient_boosting`` (XGBoost if installed, else sklearn HistGB).

        Linear models return ``feature`` / ``coef`` / ``odds_ratio`` / ``selected``
        (Elastic Net flags features shrunk to zero). Tree ensembles
        (``random_forest`` / ``gradient_boosting``) return only ``feature`` /
        ``importance`` / ``selected`` — no empty coef/OR columns. Rows are sorted
        by |coef| or importance. This is a MODEL deliverable — its performance is
        quantified by ``ml_classifier_performance`` and its curves by the
        ``ml_roc_curve`` / ``ml_calibration_curve`` / ``ml_decision_curve`` tools.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.metrics import roc_auc_score
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        res = self._ml_fit_frame(
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            source=source,
        )
        if isinstance(res, str):
            return res
        X, y, features = res
        try:
            est, kind = _sklearn_estimator(
                model, random_state=random_state, l1_ratio=l1_ratio,
                cv_folds=cv_folds, n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate,
                class_weight=self._ml_class_weight(class_weight),
            )
        except ValueError as e:
            return str(e)
        try:
            est.fit(X, y)
        except Exception as e:
            return f"Error fitting {model}: {e}"

        core = _ml_estimator_core(est)
        rows: List[Dict[str, Any]] = []
        if kind == "linear":
            coefs = np.asarray(core.coef_).ravel()
            intercept = float(np.asarray(core.intercept_).ravel()[0])
            rows.append({
                "feature": "(Intercept)", "coef": round(intercept, 5),
                "odds_ratio": round(float(np.exp(intercept)), 5),
                "selected": True,
            })
            for feat, c in zip(features, coefs):
                rows.append({
                    "feature": feat, "coef": round(float(c), 5),
                    "odds_ratio": round(float(np.exp(c)), 5),
                    "selected": bool(abs(c) > 1e-8),
                })
            table = pd.DataFrame(rows)
            table = pd.concat([
                table[table["feature"] == "(Intercept)"],
                table[table["feature"] != "(Intercept)"].sort_values(
                    "coef", key=lambda s: s.abs(), ascending=False, na_position="last"
                ),
            ], ignore_index=True)
        else:
            imp = np.asarray(getattr(core, "feature_importances_", []), dtype=float)
            if imp.size != len(features):
                # Some estimators (sklearn HistGradientBoosting, the fallback when
                # xgboost is absent) expose no impurity importances — use
                # permutation importance so the table is never empty.
                try:
                    from sklearn.inspection import permutation_importance

                    pi = permutation_importance(
                        est, X, y, n_repeats=5, random_state=random_state, n_jobs=-1,
                    )
                    imp = np.asarray(pi.importances_mean, dtype=float)
                except Exception:
                    imp = np.zeros(len(features), dtype=float)
            for feat, v in zip(features, imp):
                rows.append({
                    "feature": feat,
                    "importance": round(float(v), 6),
                    "selected": bool(v > 0),
                })
            table = pd.DataFrame(rows)
            table = table.sort_values(
                "importance", ascending=False, na_position="last"
            ).reset_index(drop=True)

        # Apparent discrimination + (for RF) OOB AUC give an at-a-glance sniff
        # test; the optimism-corrected numbers come from ml_classifier_performance.
        try:
            apparent_auc = round(float(roc_auc_score(y, _ml_predict_proba(est, X))), 4)
        except Exception:
            apparent_auc = None
        oob_auc = None
        if model == "random_forest" and hasattr(core, "oob_decision_function_"):
            try:
                oob_p = np.asarray(core.oob_decision_function_)[:, 1]
                mask = np.isfinite(oob_p)
                oob_auc = round(float(roc_auc_score(y[mask], oob_p[mask])), 4)
            except Exception:
                oob_auc = None

        name = (label or "").strip() or f"ml_classifier_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title=f"{_ML_MODELS.get(model, model)} — coefficients/importance",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"{_ML_MODELS.get(model, model)} '{name}' fitted on n={len(y):,} "
            f"({int((y == 1).sum()):,} positive), {len(features)} feature(s), "
            f"apparent AUC={apparent_auc}"
            + (f", OOB AUC={oob_auc}" if oob_auc is not None else "") + "."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 40)}"

    def _fit_sklearn_linear(
        self,
        estimator: str,
        *,
        outcome_column: str = "",
        outcome_values: Any = None,
        predictors: Any = None,
        where: str = "",
        reference_levels: Any = None,
        split_column: str = "",
        class_weight: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
        probability_column: str = "predicted_probability",
        score_column: str = "predicted_score",
        **est_hp: Any,
    ) -> str:
        """Fit one sklearn linear classifier and return the SCORED cohort.

        OUTPUT is the input table plus ``predicted_probability`` (when the
        estimator has ``predict_proba``) and/or ``predicted_score``
        (``decision_function``). Incomplete rows keep every column and get a
        NULL score. Evaluation tools must read these columns — this node is the
        only place the model is fitted.
        """
        import numpy as np
        import pandas as pd

        one_class = str(estimator) == "SGDOneClassSVM"
        split_col = (split_column or "").strip()
        if one_class:
            covs = [str(c) for c in (predictors or []) if str(c).strip()]
            if not covs:
                return "Error: 'predictors' (at least one) are required."
            refs, rerr = _reference_map(reference_levels, covs)
            if rerr:
                return rerr
            src = (source or "seer").strip() or "seer"
            cov_map: Dict[str, str] = {}
            sel = ["ROW_NUMBER() OVER () AS _fit_id"]
            if split_col:
                sel.append(f"{_q(split_col)} AS _split")
            for i, c in enumerate(covs):
                alias = f"x{i}"
                cov_map[alias] = c
                sel.append(f"{_q(c)} AS {alias}")
            sql = f"SELECT {', '.join(sel)} FROM {_q(src)}"
            w = (where or "").strip()
            if w:
                sql += f" WHERE ({w})"
            sql += f" LIMIT {_MODEL_MAX_ROWS}"
            try:
                raw = self.con.execute(sql).fetchdf()
            except Exception as e:
                return f"Error building cohort: {e}"
            if raw.empty:
                return "Cohort is empty after filtering (0 rows). Verify column values."
            try:
                X_all, features = _design_matrix(raw, list(cov_map.keys()), cov_map, refs)
            except ValueError as e:
                return str(e)
            ok = X_all.notna().all(axis=1)
            X = X_all.loc[ok].reset_index(drop=True)
            if split_col:
                train = raw.loc[ok, "_split"].astype(str).str.casefold().eq("train").to_numpy()
                if int(train.sum()) < 8:
                    return f"Error: holdout train split too small after complete-case ({int(train.sum())})."
                X_fit = X.loc[train]
            else:
                X_fit = X
            y_fit = None
        else:
            res = self._ml_fit_frame(
                outcome_column=outcome_column, outcome_values=outcome_values,
                predictors=predictors, where=where, reference_levels=reference_levels,
                source=source, split_column=split_col,
            )
            if isinstance(res, str):
                return res
            if split_col:
                X, y, features, splits = res
                train = splits.str.casefold().eq("train")
                if int(train.sum()) < 8:
                    return (
                        f"Error: holdout train split too small after complete-case "
                        f"({int(train.sum())}). Check '{split_col}'."
                    )
                X_fit, y_fit = X.loc[train], y[train]
            else:
                X, y, features = res
                X_fit, y_fit = X, y
            refs, rerr = _reference_map(reference_levels, [str(c) for c in (predictors or []) if str(c).strip()])
            if rerr:
                return rerr
            covs = [str(c) for c in (predictors or []) if str(c).strip()]

        try:
            est, _meta = _sklearn_catalog_estimator(
                estimator, random_state=random_state,
                class_weight=self._ml_class_weight(class_weight), **est_hp,
            )
        except ValueError as e:
            return str(e)
        try:
            if y_fit is None:
                est.fit(X_fit)
            else:
                est.fit(X_fit, y_fit)
        except Exception as e:
            return f"Error fitting {estimator}: {e}"

        core = _ml_estimator_core(est)
        coef_rows: List[Dict[str, Any]] = []
        coefs = getattr(core, "coef_", None)
        imps = getattr(core, "feature_importances_", None)
        if coefs is not None:
            arr = np.asarray(coefs, dtype=float)
            if arr.ndim > 1:
                arr = arr[-1] if arr.shape[0] > 1 else arr.ravel()
            else:
                arr = arr.ravel()
            intercept = getattr(core, "intercept_", None)
            if intercept is not None:
                iv = float(np.asarray(intercept).ravel()[-1])
                coef_rows.append({"feature": "(Intercept)", "coef": round(iv, 5)})
            for feat, c in zip(features, arr):
                coef_rows.append({"feature": feat, "coef": round(float(c), 5)})
        elif imps is not None:
            for feat, v in zip(features, np.asarray(imps, dtype=float).ravel()):
                coef_rows.append({"feature": feat, "importance": round(float(v), 6)})
        coef_table = pd.DataFrame(coef_rows) if coef_rows else pd.DataFrame(
            columns=["feature", "coef"]
        )

        # Score EVERY row of the source (incomplete → NULL), like ml_predict.
        pcol = _bare(probability_column) or "predicted_probability"
        scol = _bare(score_column) or "predicted_score"
        src = (source or "seer").strip() or "seer"
        w = (where or "").strip()
        work = f"_lin_work_{abs(hash((src, w, estimator))) % 10_000_000}"
        base = (
            f"(SELECT *, ROW_NUMBER() OVER () AS _pred_id FROM {_q(src)}"
            + (f" WHERE ({w})" if w else "")
            + ")"
        )
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS SELECT * FROM {base}")
        except Exception as e:
            return f"Error reading the scoring cohort '{src}': {e}"
        cov_map = {}
        sel = ["_pred_id"]
        for i, c in enumerate(covs):
            alias = f"x{i}"
            cov_map[alias] = c
            sel.append(f"{_q(c)} AS {alias}")
        try:
            sdf = self.con.execute(
                f"SELECT {', '.join(sel)} FROM {_q(work)} LIMIT {_MODEL_MAX_ROWS}"
            ).fetchdf()
            Xs, _feats = _design_matrix(sdf, list(cov_map.keys()), cov_map, refs)
        except Exception as e:
            self._drop_relation(work)
            return f"Error scoring '{src}': {e}"
        Xs = Xs.reindex(columns=features, fill_value=0.0).astype(float)
        valid = Xs.notna().all(axis=1).to_numpy()
        proba = np.full(len(sdf), np.nan, dtype=float)
        decision = np.full(len(sdf), np.nan, dtype=float)
        pred = np.full(len(sdf), np.nan, dtype=float)
        if valid.any():
            try:
                p, d = _ml_native_scores(est, Xs[valid])
                if p is not None:
                    proba[valid] = p
                if d is not None:
                    decision[valid] = d
                pred[valid] = np.asarray(est.predict(Xs[valid]), dtype=float).ravel()
            except Exception as e:
                self._drop_relation(work)
                return f"Error scoring '{src}': {e}"

        scored = pd.DataFrame({"_pred_id": sdf["_pred_id"].to_numpy()})
        extra_cols = ["predicted_class"]
        scored["predicted_class"] = pred
        has_proba = bool(np.isfinite(proba).any())
        has_dec = bool(np.isfinite(decision).any())
        if has_proba:
            scored[pcol] = proba
            extra_cols.append(pcol)
        if has_dec:
            scored[scol] = decision
            extra_cols.append(scol)
        if not has_proba and not has_dec:
            self._drop_relation(work)
            return f"Error: {estimator} produced neither predict_proba nor decision_function."

        name = (label or "").strip() or f"{estimator}_{self._n + 1}"
        tmp = f"_lin_{abs(hash(name)) % 10_000_000}"
        extra_sql = "".join(f", p.{_q(c)}" for c in extra_cols)
        try:
            self.con.register(tmp, scored)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT c.* EXCLUDE (_pred_id){extra_sql} "
                f"FROM {_q(work)} c LEFT JOIN {tmp} p USING (_pred_id)"
            )
            self._materialized_outputs.add(name)
            n_out = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0])
        except Exception as e:
            return f"Error materializing the scored cohort: {e}"
        finally:
            try:
                self.con.unregister(tmp)
            except Exception:
                pass
            self._drop_relation(work)

        parquet_uri = self._export_parquet(name)
        n_scored = int(np.isfinite(proba if has_proba else decision).sum())
        title = f"{estimator} — scored cohort"
        self._register_deliverable(
            name, coef_table if len(coef_table) else scored.head(5), max(len(coef_table), 1),
            title=title, kind="dataset",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        n_fit = int(len(X_fit))
        stats = (
            f"{estimator} '{name}' fitted on n={n_fit:,}"
            + ("" if one_class else f" ({int((y_fit == 1).sum()):,} positive)")
            + f", {len(features)} feature(s); scored {n_scored:,}/{n_out:,} row(s)"
            + (f" → '{pcol}'" if has_proba else "")
            + (f" → '{scol}'" if has_dec else "")
            + "."
        )
        bits = [stats]
        if parquet_uri:
            bits.insert(0, parquet_uri)
        if len(coef_table):
            bits.append(_fmt_rows_for_llm(coef_table, 40))
        return "\n".join(bits)

    def LogisticRegression(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        penalty: str = "l2",
        C: float = 1.0,
        solver: str = "",
        l1_ratio: Any = None,
        max_iter: int = 2000,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``LogisticRegression`` — fit once, write a scored dataset."""
        return self._fit_sklearn_linear(
            "LogisticRegression",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            penalty=penalty, C=C, solver=solver, l1_ratio=l1_ratio, max_iter=max_iter,
        )

    def LogisticRegressionCV(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        penalty: str = "l2",
        solver: str = "",
        l1_ratio: Any = None,
        cv: int = 5,
        max_iter: int = 2000,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``LogisticRegressionCV`` — λ / C chosen by CV, then scored dataset."""
        return self._fit_sklearn_linear(
            "LogisticRegressionCV",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            penalty=penalty, solver=solver, l1_ratio=l1_ratio, cv=cv, max_iter=max_iter,
        )

    def PassiveAggressiveClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        C: float = 1.0,
        max_iter: int = 2000,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``PassiveAggressiveClassifier`` — fit once, write a scored dataset."""
        return self._fit_sklearn_linear(
            "PassiveAggressiveClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, random_state=random_state,
            label=label, source=source, C=C, max_iter=max_iter,
        )

    def Perceptron(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        penalty: str = "",
        alpha: float = 0.0001,
        max_iter: int = 2000,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``Perceptron`` — fit once, write a scored dataset."""
        return self._fit_sklearn_linear(
            "Perceptron",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            penalty=penalty, alpha=alpha, max_iter=max_iter,
        )

    def RidgeClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        alpha: float = 1.0,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``RidgeClassifier`` — fit once, write a scored dataset."""
        return self._fit_sklearn_linear(
            "RidgeClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source, alpha=alpha,
        )

    def RidgeClassifierCV(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        alphas: Any = None,
        cv: Any = None,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``RidgeClassifierCV`` — α by CV, then scored dataset."""
        return self._fit_sklearn_linear(
            "RidgeClassifierCV",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            alphas=alphas, cv=cv,
        )

    def SGDClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        loss: str = "hinge",
        penalty: str = "l2",
        alpha: float = 0.0001,
        l1_ratio: float = 0.15,
        max_iter: int = 2000,
        learning_rate: str = "optimal",
        eta0: float = 0.0,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``SGDClassifier`` — fit once, write a scored dataset.

        ``loss="log_loss"`` (or ``modified_huber``) is required for a true
        ``predicted_probability``; hinge/others write ``predicted_score`` only.
        """
        return self._fit_sklearn_linear(
            "SGDClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            loss=loss, penalty=penalty, alpha=alpha, l1_ratio=l1_ratio,
            max_iter=max_iter, learning_rate=learning_rate, eta0=eta0,
        )

    def SGDOneClassSVM(
        self,
        predictors: Any,
        nu: float = 0.5,
        max_iter: int = 2000,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``SGDOneClassSVM`` — unsupervised novelty fit, scored dataset.

        No outcome. Writes ``predicted_score`` (decision) and ``predicted_class``
        (+1 inlier / −1 outlier).
        """
        return self._fit_sklearn_linear(
            "SGDOneClassSVM",
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, random_state=random_state,
            label=label, source=source, nu=nu, max_iter=max_iter,
        )

    def SVC(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        C: float = 1.0,
        kernel: str = "rbf",
        gamma: Any = "scale",
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``SVC`` (C-Support Vector Classification) — scored dataset.

        ``probability=True`` so the output includes ``predicted_probability``.
        """
        return self._fit_sklearn_linear(
            "SVC",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            C=C, kernel=kernel, gamma=gamma,
        )

    def LinearSVC(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        C: float = 1.0,
        max_iter: int = 2000,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``LinearSVC`` — linear SVM. Writes ``predicted_score`` (no proba)."""
        return self._fit_sklearn_linear(
            "LinearSVC",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            C=C, max_iter=max_iter,
        )

    def NuSVC(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        nu: float = 0.5,
        kernel: str = "rbf",
        gamma: Any = "scale",
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``NuSVC`` — ν-SVM. Writes ``predicted_probability``."""
        return self._fit_sklearn_linear(
            "NuSVC",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            nu=nu, kernel=kernel, gamma=gamma,
        )

    def DecisionTreeClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        max_depth: Any = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``DecisionTreeClassifier`` — fit once, scored dataset + importances."""
        return self._fit_sklearn_linear(
            "DecisionTreeClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            max_depth=max_depth, min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
        )

    def ExtraTreeClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        max_depth: Any = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``ExtraTreeClassifier`` (single extremely randomized tree)."""
        return self._fit_sklearn_linear(
            "ExtraTreeClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            max_depth=max_depth, min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
        )

    def RandomForestClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        n_estimators: int = 200,
        max_depth: Any = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``RandomForestClassifier`` — fit once, scored dataset + importances."""
        return self._fit_sklearn_linear(
            "RandomForestClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            n_estimators=n_estimators, max_depth=max_depth,
            min_samples_split=min_samples_split, min_samples_leaf=min_samples_leaf,
        )

    def ExtraTreesClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        n_estimators: int = 200,
        max_depth: Any = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``ExtraTreesClassifier`` — extremely randomized forest."""
        return self._fit_sklearn_linear(
            "ExtraTreesClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            n_estimators=n_estimators, max_depth=max_depth,
            min_samples_split=min_samples_split, min_samples_leaf=min_samples_leaf,
        )

    def AdaBoostClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        n_estimators: int = 50,
        learning_rate: float = 1.0,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``AdaBoostClassifier`` — fit once, scored dataset."""
        return self._fit_sklearn_linear(
            "AdaBoostClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, random_state=random_state,
            label=label, source=source,
            n_estimators=n_estimators, learning_rate=learning_rate,
        )

    def GradientBoostingClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        n_estimators: int = 200,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``GradientBoostingClassifier`` — fit once, scored dataset."""
        return self._fit_sklearn_linear(
            "GradientBoostingClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, random_state=random_state,
            label=label, source=source,
            n_estimators=n_estimators, learning_rate=learning_rate,
            max_depth=max_depth, min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
        )

    def HistGradientBoostingClassifier(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        max_iter: int = 200,
        learning_rate: float = 0.1,
        max_depth: Any = None,
        class_weight: Any = None,
        split_column: str = "",
        where: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """sklearn ``HistGradientBoostingClassifier`` — histogram GB, scored dataset."""
        return self._fit_sklearn_linear(
            "HistGradientBoostingClassifier",
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            split_column=split_column, class_weight=class_weight,
            random_state=random_state, label=label, source=source,
            max_iter=max_iter, learning_rate=learning_rate, max_depth=max_depth,
        )

    def ml_classifier_performance(
        self,
        outcome_column: str,
        outcome_values: Any,
        where: str = "",
        n_bootstrap: int = 500,
        threshold: Any = None,
        probability_column: str = "predicted_probability",
        score_column: str = "predicted_score",
        split_column: str = "",
        split_value: str = "test",
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """AUC / Brier / threshold metrics from an already-scored dataset.

        Does not fit. Reads ``probability_column`` (default
        ``predicted_probability``) written by an upstream model tool. When
        ``split_column`` is set (from :meth:`ml_train_test_split`), only the
        ``split_value`` rows (default ``test``) are scored. Bootstrap CIs resample
        the existing ``(y, p)`` pairs — they do not refit. Optimism correction
        is not computed here; use :meth:`ml_cv_performance` for out-of-fold
        estimates.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.metrics import (
                average_precision_score, brier_score_loss, roc_auc_score,
            )
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        got = self._ml_read_scores(
            outcome_column=outcome_column, outcome_values=outcome_values,
            source=source, where=where, probability_column=probability_column,
            score_column=score_column, split_column=split_column,
            split_value=split_value, require_probability=False,
        )
        if isinstance(got, str):
            return got
        yv, p, meta = got
        n = int(meta["n"])
        auc = float(roc_auc_score(yv, p))
        brier = None
        if meta["is_probability"]:
            try:
                brier = float(brier_score_loss(yv, p))
            except Exception:
                brier = None
        prauc = None
        try:
            prauc = float(average_precision_score(yv, p))
        except Exception:
            prauc = None
        thr = (
            _ml_youden_threshold(yv, p)
            if threshold in (None, "") else float(threshold)
        )
        tm = _ml_threshold_metrics(yv, p, thr)

        rng = np.random.default_rng(random_state)
        boot_auc: List[float] = []
        for _ in range(max(0, int(n_bootstrap))):
            bi = rng.integers(0, n, n)
            yb = yv[bi]
            if len(np.unique(yb)) < 2:
                continue
            try:
                boot_auc.append(float(roc_auc_score(yb, p[bi])))
            except Exception:
                continue
        auc_lo = auc_hi = None
        if boot_auc:
            auc_lo = round(float(np.percentile(boot_auc, 2.5)), 4)
            auc_hi = round(float(np.percentile(boot_auc, 97.5)), 4)

        slope = intercept = None
        if meta["is_probability"]:
            try:
                import statsmodels.api as sm

                eps = 1e-6
                clipped = np.clip(p, eps, 1 - eps)
                lp = np.log(clipped / (1 - clipped))
                cal = sm.Logit(yv, sm.add_constant(lp, has_constant="add")).fit(disp=0)
                intercept = round(float(cal.params[0]), 4)
                slope = round(float(cal.params[1]), 4)
            except Exception:
                pass

        def _row(metric, value, lo=None, hi=None):
            return {
                "metric": metric,
                "value": None if value is None else round(float(value), 4),
                "ci_lower": lo, "ci_upper": hi,
            }

        auc_name = "auc_test" if meta["split_column"] else "auc"
        brier_name = "brier_test" if meta["split_column"] else "brier"
        rows = [
            _row(auc_name, auc, auc_lo, auc_hi),
            _row(brier_name, brier),
            _row("pr_auc", prauc),
            _row("sensitivity", tm["sensitivity"]),
            _row("specificity", tm["specificity"]),
            _row("ppv", tm["ppv"]),
            _row("npv", tm["npv"]),
            _row("calibration_slope", slope),
            _row("calibration_intercept", intercept),
            _row("threshold", tm["threshold"]),
            _row("n", n),
            _row("n_events", int(yv.sum())),
            _row("bootstrap_reps", len(boot_auc)),
        ]
        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"ml_performance_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        holdout = (
            f" ({meta['split_column']}={meta['split_value']})"
            if meta["split_column"] else ""
        )
        self._register_deliverable(
            name, table, len(table),
            title=f"Classifier performance{holdout}",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Performance '{name}'{holdout}: AUC={round(auc, 4)}"
            + (f" (95% CI {auc_lo}-{auc_hi})" if auc_lo is not None else "")
            + (f", Brier={round(brier, 4)}" if brier is not None else "")
            + f", n={n:,} ({int(yv.sum()):,} events). Does not fit — "
            f"read `{meta['score_column']}`."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 20)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 20)}"

    def ml_roc_curve(
        self,
        outcome_column: str,
        outcome_values: Any,
        where: str = "",
        probability_column: str = "predicted_probability",
        score_column: str = "predicted_score",
        split_column: str = "",
        split_value: str = "test",
        title: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """ROC curve from an already-scored dataset (figure + fpr/tpr table).

        Does not fit. Reads ``predicted_probability`` (or ``predicted_score``)
        from the upstream model node. ``sklearn.metrics.roc_curve(y, p)``.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.metrics import roc_auc_score, roc_curve
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        got = self._ml_read_scores(
            outcome_column=outcome_column, outcome_values=outcome_values,
            source=source, where=where, probability_column=probability_column,
            score_column=score_column, split_column=split_column,
            split_value=split_value, require_probability=False,
        )
        if isinstance(got, str):
            return got
        yv, p, meta = got
        fpr, tpr, thr = roc_curve(yv, p)
        auc = float(roc_auc_score(yv, p))
        plot_df = pd.DataFrame({
            "fpr": np.round(fpr, 6), "tpr": np.round(tpr, 6),
            "threshold": np.round(np.where(np.isfinite(thr), thr, np.nan), 6),
        })
        j = tpr - fpr
        jidx = int(np.argmax(j))

        image = None
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=140)
            ax.plot(fpr, tpr, linewidth=2.0, label=f"{meta['score_column']} (AUC={auc:.3f})")
            ax.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1.0, label="Chance")
            ax.scatter([fpr[jidx]], [tpr[jidx]], color="crimson", zorder=5,
                       label=f"Youden (thr={thr[jidx]:.2f})")
            ax.set_xlabel("1 − Specificity (FPR)")
            ax.set_ylabel("Sensitivity (TPR)")
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            ax.set_title(title or "ROC curve")
            ax.legend(loc="lower right", fontsize=8, frameon=False)
            ax.grid(True, alpha=0.25)
            image = self._render_mpl_png(fig, (label or "ml_roc").strip())
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] ROC figure render failed: %s", e)

        name = (label or "").strip() or f"ml_roc_{self._n + 1}"
        stats = (
            f"ROC '{name}': AUC={round(auc, 4)}, n={len(yv):,} "
            f"({int(yv.sum()):,} events). Does not fit — read `{meta['score_column']}`."
        )
        return self._finalize_figure(name, title or "ROC curve", plot_df, image, stats=stats)

    def ml_calibration_curve(
        self,
        outcome_column: str,
        outcome_values: Any,
        n_bins: int = 10,
        where: str = "",
        probability_column: str = "predicted_probability",
        split_column: str = "",
        split_value: str = "test",
        title: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Calibration curve from an already-scored dataset (figure + table).

        Does not fit. Reads ``predicted_probability`` from the upstream model
        node. Bins into ``n_bins`` quantile groups and plots observed vs
        mean-predicted event rate against the 45° line.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.calibration import calibration_curve
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        got = self._ml_read_scores(
            outcome_column=outcome_column, outcome_values=outcome_values,
            source=source, where=where, probability_column=probability_column,
            split_column=split_column, split_value=split_value,
            require_probability=True,
        )
        if isinstance(got, str):
            return got
        yv, p, meta = got
        nb = max(2, int(n_bins))
        try:
            prob_true, prob_pred = calibration_curve(yv, p, n_bins=nb, strategy="quantile")
        except Exception as e:
            return f"Error computing calibration curve: {e}"
        edges = np.unique(np.quantile(p, np.linspace(0, 1, nb + 1)))
        binned = np.clip(np.digitize(p, edges[1:-1]), 0, len(edges) - 2)
        counts = [int((binned == b).sum()) for b in range(len(prob_pred))]
        plot_df = pd.DataFrame({
            "prob_pred": np.round(prob_pred, 6),
            "prob_true": np.round(prob_true, 6),
            "bin_count": counts[: len(prob_pred)] + [None] * max(0, len(prob_pred) - len(counts)),
        })

        image = None
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=140)
            ax.plot([0, 1], [0, 1], linestyle="--", color="gray", linewidth=1.0,
                    label="Perfect calibration")
            ax.plot(prob_pred, prob_true, marker="o", linewidth=1.8,
                    label=meta["score_column"])
            ax.set_xlabel("Mean predicted probability")
            ax.set_ylabel("Observed event rate")
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            ax.set_title(title or "Calibration curve")
            ax.legend(loc="upper left", fontsize=8, frameon=False)
            ax.grid(True, alpha=0.25)
            image = self._render_mpl_png(fig, (label or "ml_calibration").strip())
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] calibration figure render failed: %s", e)

        name = (label or "").strip() or f"ml_calibration_{self._n + 1}"
        stats = (
            f"Calibration '{name}': {nb} bins, n={len(yv):,} "
            f"({int(yv.sum()):,} events). Does not fit — read `{meta['score_column']}`."
        )
        return self._finalize_figure(
            name, title or "Calibration curve", plot_df, image, stats=stats
        )

    def ml_decision_curve(
        self,
        outcome_column: str,
        outcome_values: Any,
        thresholds: Any = None,
        where: str = "",
        probability_column: str = "predicted_probability",
        split_column: str = "",
        split_value: str = "test",
        title: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Decision-curve analysis from an already-scored dataset (figure + table).

        Does not fit. Reads ``predicted_probability`` from the upstream model
        node. Net benefit vs treat-all / treat-none:
        ``NB = TP/n − FP/n · pt/(1−pt)``. ``thresholds`` defaults to
        0.01…0.99 step 0.01.
        """
        try:
            import numpy as np
            import pandas as pd
        except Exception as e:  # pragma: no cover
            return f"Error: numpy / pandas unavailable ({e})."

        got = self._ml_read_scores(
            outcome_column=outcome_column, outcome_values=outcome_values,
            source=source, where=where, probability_column=probability_column,
            split_column=split_column, split_value=split_value,
            require_probability=True,
        )
        if isinstance(got, str):
            return got
        yv, p, meta = got
        n = len(yv)
        prev = float(yv.mean())
        if thresholds:
            pts = [float(t) for t in thresholds if 0.0 < float(t) < 1.0]
        else:
            pts = list(np.round(np.arange(0.01, 1.0, 0.01), 4))
        rows: List[Dict[str, Any]] = []
        for pt in pts:
            pred = (p >= pt).astype(int)
            tp = int(((pred == 1) & (yv == 1)).sum())
            fp = int(((pred == 1) & (yv == 0)).sum())
            w = pt / (1.0 - pt)
            nb_model = tp / n - fp / n * w
            nb_all = prev - (1.0 - prev) * w
            rows.append({
                "threshold": round(float(pt), 4),
                "net_benefit_model": round(float(nb_model), 6),
                "net_benefit_all": round(float(nb_all), 6),
                "net_benefit_none": 0.0,
            })
        plot_df = pd.DataFrame(rows)

        image = None
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(7.0, 5.2), dpi=140)
            ax.plot(plot_df["threshold"], plot_df["net_benefit_model"], linewidth=2.0,
                    label=meta["score_column"])
            ax.plot(plot_df["threshold"], plot_df["net_benefit_all"], linewidth=1.2,
                    color="gray", label="Treat all")
            ax.axhline(0.0, linestyle="--", color="black", linewidth=1.0, label="Treat none")
            ax.set_xlabel("Threshold probability")
            ax.set_ylabel("Net benefit")
            lo = float(min(0.0, plot_df["net_benefit_model"].min()))
            ax.set_ylim(max(lo, -prev), prev + 0.02)
            ax.set_xlim(0, 1)
            ax.set_title(title or "Decision curve analysis")
            ax.legend(loc="upper right", fontsize=8, frameon=False)
            ax.grid(True, alpha=0.25)
            image = self._render_mpl_png(fig, (label or "ml_dca").strip())
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] DCA figure render failed: %s", e)

        name = (label or "").strip() or f"ml_dca_{self._n + 1}"
        stats = (
            f"Decision curve '{name}': {len(pts)} thresholds, "
            f"prevalence={round(prev, 4)}, n={n:,}. Does not fit — "
            f"read `{meta['score_column']}`."
        )
        return self._finalize_figure(
            name, title or "Decision curve analysis", plot_df, image, stats=stats
        )

    def ml_reclassification(
        self,
        outcome_column: str,
        outcome_values: Any,
        probability_column: str = "predicted_probability",
        baseline_probability_column: str = "",
        baseline_source: str = "",
        id_column: str = "",
        nri_thresholds: Any = None,
        where: str = "",
        split_column: str = "",
        split_value: str = "test",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """IDI / NRI from two already-scored probability columns. Does not fit.

        Either (1) two probability columns on the same scored table
        (``probability_column`` + ``baseline_probability_column``), or (2) two
        scored datasets joined on ``id_column`` when ``baseline_source`` is set.
        Join two model outputs with ``sql`` first if you prefer one table.
        """
        try:
            import numpy as np
            import pandas as pd
            from sklearn.metrics import roc_auc_score
        except Exception as e:  # pragma: no cover
            return f"Error: scikit-learn / pandas unavailable ({e})."

        oc = str(outcome_column or "").strip()
        if not oc:
            return "Error: 'outcome_column' is required."
        pcol = str(probability_column or "predicted_probability").strip() or "predicted_probability"
        bsrc = str(baseline_source or "").strip()
        df = self._ml_load_table(
            source, where=where, split_column=split_column, split_value=split_value,
        )
        if isinstance(df, str):
            return df
        if oc not in df.columns:
            return f"outcome_column '{oc}' is not in the scored dataset."
        if pcol not in df.columns:
            return (
                f"'{pcol}' is missing. Fit the FULL model tool first so the "
                f"dataset carries predicted_probability."
            )

        if bsrc:
            idc = str(id_column or "").strip()
            if not idc:
                return "id_column is required when baseline_source is set (join key)."
            if idc not in df.columns:
                return f"id_column '{idc}' is not in '{source}'."
            odf = self._ml_load_table(
                bsrc, where=where, split_column=split_column, split_value=split_value,
            )
            if isinstance(odf, str):
                return odf
            bcol = str(baseline_probability_column or pcol).strip() or pcol
            if idc not in odf.columns:
                return f"id_column '{idc}' is not in baseline_source '{bsrc}'."
            if bcol not in odf.columns:
                return f"'{bcol}' is not in baseline_source '{bsrc}'."
            left = df[[idc, oc, pcol]].copy()
            right = odf[[idc, bcol]].rename(columns={bcol: "_p_baseline"})
            left["_id"] = left[idc].astype(str)
            right["_id"] = right[idc].astype(str)
            merged = left.merge(right[["_id", "_p_baseline"]], on="_id", how="inner")
            yser, yerr = self._ml_binary_y(merged[oc], outcome_values)
            if yerr:
                return yerr
            pf = pd.to_numeric(merged[pcol], errors="coerce")
            pr = pd.to_numeric(merged["_p_baseline"], errors="coerce")
        else:
            bcol = str(baseline_probability_column or "").strip()
            if not bcol:
                return (
                    "baseline_probability_column is required (or set "
                    "baseline_source + id_column to join two scored datasets)."
                )
            if bcol not in df.columns:
                return (
                    f"'{bcol}' is missing. Join the two scored datasets with sql "
                    f"and alias one probability column, or pass baseline_source."
                )
            yser, yerr = self._ml_binary_y(df[oc], outcome_values)
            if yerr:
                return yerr
            pf = pd.to_numeric(df[pcol], errors="coerce")
            pr = pd.to_numeric(df[bcol], errors="coerce")

        ok = yser.notna() & pf.notna() & pr.notna()
        yv = yser.loc[ok].astype(int).to_numpy()
        pf = pf.loc[ok].astype(float).to_numpy()
        pr = pr.loc[ok].astype(float).to_numpy()
        if len(yv) < 10:
            return f"Need ≥10 paired scored rows; got {len(yv)}."
        if len(np.unique(yv)) < 2:
            return "Outcome has only one class on the paired scored rows."

        ev = yv == 1
        nonev = yv == 0
        n1 = int(ev.sum())
        n0 = int(nonev.sum())
        idi = (pf[ev].mean() - pr[ev].mean()) - (pf[nonev].mean() - pr[nonev].mean())

        up = pf > pr
        down = pf < pr
        nri_events = (int((up & ev).sum()) - int((down & ev).sum())) / n1 if n1 else None
        nri_nonevents = (int((down & nonev).sum()) - int((up & nonev).sum())) / n0 if n0 else None
        nri_cont = (
            nri_events + nri_nonevents
            if nri_events is not None and nri_nonevents is not None else None
        )

        rows = [
            {"metric": "auc_full", "value": round(float(roc_auc_score(yv, pf)), 4)},
            {"metric": "auc_reduced", "value": round(float(roc_auc_score(yv, pr)), 4)},
            {"metric": "idi", "value": round(float(idi), 5)},
            {"metric": "nri_continuous", "value": None if nri_cont is None else round(float(nri_cont), 5)},
            {"metric": "nri_events", "value": None if nri_events is None else round(float(nri_events), 5)},
            {"metric": "nri_nonevents", "value": None if nri_nonevents is None else round(float(nri_nonevents), 5)},
        ]
        cuts = [float(t) for t in (nri_thresholds or []) if 0.0 < float(t) < 1.0]
        for c in cuts:
            up_c = (pf >= c) & (pr < c)
            down_c = (pf < c) & (pr >= c)
            ev_move = (int((up_c & ev).sum()) - int((down_c & ev).sum())) / n1 if n1 else None
            nonev_move = (int((down_c & nonev).sum()) - int((up_c & nonev).sum())) / n0 if n0 else None
            cat_nri = (
                ev_move + nonev_move
                if ev_move is not None and nonev_move is not None else None
            )
            rows.append({
                "metric": f"nri_category@{round(c, 3)}",
                "value": None if cat_nri is None else round(float(cat_nri), 5),
            })
        table = pd.DataFrame(rows)

        name = (label or "").strip() or f"ml_reclassification_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title="Reclassification — IDI / NRI (full vs reduced scores)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Reclassification '{name}': IDI={round(float(idi), 5)}, "
            f"continuous NRI={None if nri_cont is None else round(float(nri_cont), 5)}, "
            f"n={len(yv):,} ({n1:,} events). Does not fit — compared two "
            f"probability columns."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 20)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 20)}"

    def cox_ph_assumptions(
        self,
        duration_column: str,
        event_column: str,
        event_values: Any,
        covariates: Any,
        where: str = "",
        reference_levels: Any = None,
        penalizer: Any = 0.0,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Proportional-hazards assumption test (frozen tool, lifelines Schoenfeld).

        Fits a ``lifelines.CoxPHFitter`` on the derived time/event + covariates,
        then runs ``lifelines.statistics.proportional_hazard_test`` (scaled
        Schoenfeld residuals, rank time-transform). Returns a per-covariate table
        (test_statistic, p, violates_ph=p<0.05) — the PH check the protocol
        requires before trusting the Cox hazard ratios.

        ``reference_levels`` and ``penalizer`` mirror :meth:`cox_ph` and exist for
        one reason: the test describes A MODEL, not a dataset. Fitted on a different
        specification than the ``cox_ph`` being reported, its verdict is about a
        model nobody published — and the baseline choice is not cosmetic here, since
        it decides which dummy columns the design even has.

        On a MULTIPLY IMPUTED input the test is run inside each draw and averaged,
        with ``violates_ph`` the verdict of the MAJORITY of draws; testing the
        stacked draws as one cohort would inflate every statistic m-fold and fail
        PH for essentially every covariate.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from lifelines import CoxPHFitter
            from lifelines.statistics import proportional_hazard_test
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        dcol = (duration_column or "").strip()
        ecol = (event_column or "").strip()
        if not dcol or not ecol:
            return "Error: 'duration_column' and 'event_column' are required."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return 'Error: \'event_values\' must list the event value(s), e.g. ["Dead"].'
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr
        try:
            pen = max(0.0, float(penalizer or 0.0))
        except Exception:
            pen = 0.0
        src = (source or "seer").strip() or "seer"

        draws = _mi_draw_ids(self.con, src, where, imputation_column)
        if draws:
            return self._mi_pool_tool(
                "cox_ph_assumptions",
                draws=draws, imputation_column=imputation_column, where=where,
                key_cols=("covariate",),
                title="Cox PH assumption (Schoenfeld) test, averaged over imputations",
                label=label,
                kwargs=dict(
                    duration_column=duration_column, event_column=event_column,
                    event_values=event_values, covariates=covariates, source=src,
                    reference_levels=reference_levels, penalizer=pen,
                ),
            )

        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        cov_map: Dict[str, str] = {}
        sel = [
            f"TRY_CAST({_q(dcol)} AS DOUBLE) AS _t",
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e",
        ]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(dcol)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(dcol)} AS DOUBLE) >= 0"
        )
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        # Complete-case FIRST, encode second. The other order leaves a dummy for a
        # level that survived only in the dropped rows, and that all-zero column is
        # what turns this test into "delta contains nan value(s)".
        n_loaded = len(df)
        miss_mask, missing_by_cov = _incomplete_rows(df, cov_map)
        if miss_mask.any():
            df = df[~miss_mask].reset_index(drop=True)
        if len(df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)

        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            return str(e)
        unrepresented = _unrepresented_covariates(cov_map, features)
        X, features, const_cols, dep_cols = _prune_unidentifiable(X, features)
        if not features:
            return (
                "Error: no identifiable covariate column is left — every one is "
                f"single-valued in this cohort ({list(const_cols) or unrepresented}). "
                "Drop them from 'covariates', or widen 'where' so they actually vary."
            )

        model_df = pd.concat(
            [df[["_t", "_e"]].reset_index(drop=True), X.reset_index(drop=True)], axis=1
        ).dropna()
        if len(model_df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)
        if int(model_df["_e"].sum()) == 0:
            return "No events in the cohort — check 'event_values' / the event column."

        design_note = _design_note(
            n_loaded, len(model_df), missing_by_cov, const_cols, dep_cols, unrepresented
        )
        if design_note:
            logger.warning("[seer] cox_ph_assumptions: %s", design_note)

        try:
            cph = CoxPHFitter(penalizer=pen)
            cph.fit(model_df, duration_col="_t", event_col="_e")
        except Exception as e:
            return f"Error fitting Cox model: {e}"
        try:
            ph = proportional_hazard_test(cph, model_df, time_transform="rank")
            summ = ph.summary
        except Exception as e:
            return f"Error running proportional-hazard test: {e}"

        rows: List[Dict[str, Any]] = []
        for cov, r in summ.iterrows():
            p = float(r.get("p", float("nan")))
            rows.append(
                {
                    "covariate": str(cov),
                    "test_statistic": round(float(r.get("test_statistic", float("nan"))), 5),
                    "p": round(p, 6),
                    "violates_ph": bool(p < 0.05),
                }
            )
        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"cox_ph_assumptions_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Cox PH assumption (Schoenfeld) test",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        n_viol = int(table["violates_ph"].sum()) if len(table) else 0
        stats = (
            f"PH assumption test '{name}' on n={len(model_df):,} "
            f"({int(model_df['_e'].sum()):,} events): {n_viol}/{len(table)} "
            f"covariate(s) violate PH (p<0.05)."
            + (f" Cohort/design: {design_note}." if design_note else "")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\nSchoenfeld test:\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\nSchoenfeld test:\n{_fmt_rows_for_llm(table, 40)}"

    def cox_time_varying(
        self,
        id_column: str,
        start_column: str,
        stop_column: str,
        event_column: str,
        covariates: Any,
        input: str = "seer",
        event_values: Any = None,
        where: str = "",
        imputation_column: str = "",
        label: str = "",
    ) -> str:
        """Time-varying Cox regression (frozen tool, lifelines).

        Consumes a LONG-format (counting-process) table — one row per subject ×
        interval with ``id``, ``start``, ``stop``, an event flag, and
        time-varying ``covariates``. The long table must already exist as a
        registered view (``input``; e.g. built earlier via ``seer_sql`` with an
        ``output_name``). Fits ``lifelines.CoxTimeVaryingFitter`` and returns a
        hazard-ratio table. ``event_values`` (optional) maps a categorical event
        column to 0/1; otherwise the event column is cast to int. A MULTIPLY
        IMPUTED long table (``_imputation``) is fitted draw by draw and pooled by
        Rubin's rules.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from lifelines import CoxTimeVaryingFitter
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        idc = (id_column or "").strip()
        sc = (start_column or "").strip()
        pc = (stop_column or "").strip()
        ec = (event_column or "").strip()
        src = (input or "seer").strip() or "seer"
        if not (idc and sc and pc and ec):
            return "Error: 'id_column', 'start_column', 'stop_column', 'event_column' are required."
        covs = [str(c) for c in (covariates or []) if str(c).strip()]
        if not covs:
            return "Error: 'covariates' (at least one) are required."

        draws = _mi_draw_ids(self.con, src, where, imputation_column)
        if draws:
            return self._mi_pool_tool(
                "cox_time_varying",
                draws=draws, imputation_column=imputation_column, where=where,
                key_cols=("covariate",),
                title="Time-varying Cox hazard ratios (multiple-imputation pooled)",
                label=label,
                kwargs=dict(
                    id_column=id_column, start_column=start_column,
                    stop_column=stop_column, event_column=event_column,
                    covariates=covariates, input=src, event_values=event_values,
                ),
            )

        if event_values is not None:
            if isinstance(event_values, str):
                event_values = [event_values]
            ev = [str(v) for v in (event_values or [])]
            in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in ev)
            event_sql = f"CASE WHEN {_q(ec)} IN ({in_list}) THEN 1 ELSE 0 END AS _e"
        else:
            event_sql = f"CAST(TRY_CAST({_q(ec)} AS DOUBLE) AS INTEGER) AS _e"

        cov_map: Dict[str, str] = {}
        sel = [
            f"{_q(idc)} AS _id",
            f"TRY_CAST({_q(sc)} AS DOUBLE) AS _start",
            f"TRY_CAST({_q(pc)} AS DOUBLE) AS _stop",
            event_sql,
        ]
        for i, c in enumerate(covs):
            a = f"x{i}"
            cov_map[a] = c
            sel.append(f"{_q(c)} AS {a}")
        sql = (
            f"SELECT {', '.join(sel)} FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(sc)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(pc)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(pc)} AS DOUBLE) > TRY_CAST({_q(sc)} AS DOUBLE)"
        )
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building long-format table from '{src}': {e}"
        if len(df) == 0:
            return (
                f"No valid intervals in '{src}' (need stop > start). Build the "
                "long/counting-process table first (e.g. seer_sql with output_name)."
            )

        # Complete-case on the INTERVAL rows, before encoding — same reason as the
        # other Cox tools, except the unit dropped here is an interval, so a subject
        # can lose part of their follow-up rather than all of it.
        n_loaded = len(df)
        miss_mask, missing_by_cov = _incomplete_rows(df, cov_map)
        if miss_mask.any():
            df = df[~miss_mask].reset_index(drop=True)
        if len(df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)

        X, features = _design_matrix(df, list(cov_map.keys()), cov_map)
        unrepresented = _unrepresented_covariates(cov_map, features)
        X, features, const_cols, dep_cols = _prune_unidentifiable(X, features)
        if not features:
            return (
                "Error: no identifiable covariate column is left — every one is "
                f"single-valued across these intervals "
                f"({list(const_cols) or unrepresented})."
            )

        long_df = pd.concat(
            [df[["_id", "_start", "_stop", "_e"]].reset_index(drop=True), X.reset_index(drop=True)],
            axis=1,
        ).dropna()
        if len(long_df) == 0:
            return _empty_cohort_reason(n_loaded, missing_by_cov)
        if int(long_df["_e"].sum()) == 0:
            return "No events across intervals — check 'event_column' / 'event_values'."

        design_note = _design_note(
            n_loaded, len(long_df), missing_by_cov, const_cols, dep_cols, unrepresented
        )
        if design_note:
            logger.warning("[seer] cox_time_varying: %s", design_note)

        try:
            ctv = CoxTimeVaryingFitter()
            ctv.fit(
                long_df,
                id_col="_id",
                event_col="_e",
                start_col="_start",
                stop_col="_stop",
            )
        except Exception as e:
            return f"Error fitting time-varying Cox model: {e}"

        summ = ctv.summary
        rows: List[Dict[str, Any]] = []
        for cov, r in summ.iterrows():
            rows.append(
                {
                    "covariate": str(cov),
                    "coef": round(float(r.get("coef", float("nan"))), 5),
                    "se": round(float(r.get("se(coef)", float("nan"))), 5),
                    "hazard_ratio": round(float(r.get("exp(coef)", float("nan"))), 5),
                    "hr_lower95": round(float(r.get("exp(coef) lower 95%", float("nan"))), 5),
                    "hr_upper95": round(float(r.get("exp(coef) upper 95%", float("nan"))), 5),
                    "z": round(float(r.get("z", float("nan"))), 4),
                    "p": round(float(r.get("p", float("nan"))), 6),
                }
            )
        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"cox_tv_{self._n + 1}"
        # Parquet-out contract (like mann_whitney_u): materialize + export the
        # hazard-ratio table and reuse the URI in the persist layer.
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Time-varying Cox hazard ratios",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        n_subjects = int(long_df["_id"].nunique())
        stats = (
            f"Time-varying Cox '{name}' fitted on {len(long_df):,} intervals "
            f"across {n_subjects:,} subjects ({int(long_df['_e'].sum()):,} events)."
            + (f" Cohort/design: {design_note}." if design_note else "")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\nHazard ratios:\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\nHazard ratios:\n{_fmt_rows_for_llm(table, 40)}"

    def logrank_test(
        self,
        time_column: str,
        event_column: str,
        event_values: Any,
        group_column: str,
        group_values: Any = None,
        where: str = "",
        t_0: float = -1,
        weightings: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Log-rank test on a PARQUET cohort — a SEER-template wrapper over
        ``lifelines.statistics.logrank_test``.

        SEER-template contract: every tool receives the parquet-backed cohort
        (the ``source`` DuckDB view) plus test parameters — NEVER raw Python
        arrays. ``logrank_test(durations_A, durations_B, event_observed_A,
        event_observed_B, ...)`` expects two independent survival samples, so
        this wrapper does the parquet→samples CONVERSION *inside* the wrapper,
        BEFORE the real function is called:

          1. Pull the follow-up time (``time_column`` cast to DOUBLE), an event
             indicator (1 if ``event_column`` ∈ ``event_values``) and the arm
             label (``group_column``) from ``source`` (optionally narrowed by
             ``where``), dropping rows with a null/negative time.
          2. Choose the two arms: ``group_values``=[A, B] if given, else the two
             most frequent labels; split into (durations_A, event_observed_A) and
             (durations_B, event_observed_B).
          3. Call ``logrank_test(dA, dB, event_observed_A=eA,
             event_observed_B=eB, t_0=..., weightings=...)``.

        Original lifelines signature (from officialdocs)::

            lifelines.statistics.logrank_test(durations_A, durations_B,
                event_observed_A=None, event_observed_B=None, t_0=-1,
                weights_A=None, weights_B=None, weightings=None, **kwargs)

        ``weights_A``/``weights_B`` (per-row case weights) are not exposed — the
        cohort carries one row per patient. Returns a one-row result table
        (per-arm n + events, the chi-square test statistic, dof and p-value).
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from lifelines.statistics import logrank_test as _logrank
        except Exception as e:  # pragma: no cover
            return f"Error: lifelines / pandas unavailable ({e})."

        tcol = (time_column or "").strip()
        ecol = (event_column or "").strip()
        gcol = (group_column or "").strip()
        if not tcol or not ecol or not gcol:
            return "Error: 'time_column', 'event_column' and 'group_column' are required."
        if isinstance(event_values, str):
            event_values = [event_values]
        event_values = [str(v) for v in (event_values or [])]
        if not event_values:
            return 'Error: \'event_values\' must list the event value(s), e.g. ["Dead"].'
        wtg = (weightings or "").strip().lower()
        # 'fleming-harrington' is intentionally NOT allowed: lifelines requires
        # extra p/q kwargs for it, which this JSON-only wrapper cannot pass.
        if wtg not in ("", "wilcoxon", "tarone-ware", "peto"):
            return (
                "Error: 'weightings' must be '' (standard), 'wilcoxon', "
                "'tarone-ware' or 'peto'."
            )

        # ── parquet → (time, event, group) frame ────────────────────────
        in_list = ", ".join("'" + v.replace("'", "''") + "'" for v in event_values)
        src = (source or "seer").strip() or "seer"
        sql = (
            f"SELECT TRY_CAST({_q(tcol)} AS DOUBLE) AS _t, "
            f"CASE WHEN {_q(ecol)} IN ({in_list}) THEN 1 ELSE 0 END AS _e, "
            f"CAST({_q(gcol)} AS VARCHAR) AS _g FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(tcol)} AS DOUBLE) IS NOT NULL "
            f"AND TRY_CAST({_q(tcol)} AS DOUBLE) >= 0 AND {_q(gcol)} IS NOT NULL"
        )
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        # ── pick the two arms ───────────────────────────────────────────
        if isinstance(group_values, str):
            group_values = [group_values]
        if group_values:
            arms = [str(v) for v in group_values][:2]
            if len(arms) < 2:
                return (
                    "Error: 'group_values' must name TWO groups to compare, "
                    'e.g. ["Surgery", "No surgery"].'
                )
        else:
            counts = df["_g"].value_counts()
            if len(counts) < 2:
                return (
                    f'Only one distinct value of "{_bare(gcol)}" in the cohort — '
                    "the log-rank test needs two groups. Set 'group_values' or widen the cohort."
                )
            arms = [str(counts.index[0]), str(counts.index[1])]

        a = df[df["_g"] == arms[0]]
        b = df[df["_g"] == arms[1]]
        if len(a) == 0 or len(b) == 0:
            return (
                f"One arm is empty (n_{arms[0]}={len(a):,}, n_{arms[1]}={len(b):,}). "
                f'Check the labels of "{_bare(gcol)}" and \'group_values\'.'
            )

        # ── the actual lifelines.statistics.logrank_test call ───────────
        try:
            res = _logrank(
                a["_t"].to_numpy(),
                b["_t"].to_numpy(),
                event_observed_A=a["_e"].to_numpy(),
                event_observed_B=b["_e"].to_numpy(),
                t_0=float(t_0) if t_0 is not None else -1,
                weightings=wtg or None,
            )
        except Exception as e:
            return f"Error running logrank_test: {e}"

        test_stat = float(getattr(res, "test_statistic", float("nan")))
        p_val = float(getattr(res, "p_value", float("nan")))
        # Two-arm log-rank statistic is chi-square with 1 degree of freedom.
        dof = 1
        table = pd.DataFrame(
            [
                {
                    "time_column": _bare(tcol),
                    "event_column": _bare(ecol),
                    "group_column": _bare(gcol),
                    "group_a": arms[0],
                    "n_a": int(len(a)),
                    "events_a": int(a["_e"].sum()),
                    "group_b": arms[1],
                    "n_b": int(len(b)),
                    "events_b": int(b["_e"].sum()),
                    "test_statistic": round(test_stat, 5),
                    "dof": dof,
                    "p_value": round(p_val, 8),
                    "t_0": float(t_0) if t_0 is not None else -1,
                    "weightings": wtg or "standard",
                }
            ]
        )
        name = (label or "").strip() or f"logrank_test_{self._n + 1}"
        # Parquet-out contract (identical to mann_whitney_u): materialize the full
        # result, write it to S3 as a single parquet, RETURN that path, and let
        # the graph's persist layer reuse the URI (no second copy).
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Log-rank test",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Log-rank test '{name}': survival of \"{arms[0]}\" (n={len(a):,}, "
            f"events={int(a['_e'].sum()):,}) vs \"{arms[1]}\" (n={len(b):,}, "
            f"events={int(b['_e'].sum()):,}); chi2={test_stat:.4g}, p={p_val:.4g} "
            f"(weightings='{wtg or 'standard'}')."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}"
        return f"{stats} (parquet export unavailable)\n{_fmt_rows_for_llm(table, 5)}"

    def mann_whitney_u(
        self,
        value_column: str,
        group_column: str,
        group_values: Any = None,
        where: str = "",
        alternative: str = "two-sided",
        use_continuity: bool = True,
        method: str = "auto",
        nan_policy: str = "omit",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Mann-Whitney U rank test on a PARQUET cohort — a SEER-template wrapper
        over ``scipy.stats.mannwhitneyu``.

        SEER-template contract: every tool receives the parquet-backed cohort
        (the ``source`` DuckDB view) plus test parameters — NEVER raw Python
        arrays. ``scipy.stats.mannwhitneyu(x, y, ...)`` expects two independent
        1-D samples, so this wrapper does the parquet→samples CONVERSION *inside*
        the wrapper, BEFORE the real function is called:

          1. Pull ``value_column`` (cast to DOUBLE) and ``group_column`` from
             ``source`` (optionally narrowed by ``where``), dropping null values.
          2. Choose the two arms: ``group_values``=[A, B] if given, else the two
             most frequent labels in ``group_column``; split the rows into
             sample ``x`` (arm A) and sample ``y`` (arm B).
          3. Call ``mannwhitneyu(x, y, use_continuity=..., alternative=...,
             method=..., nan_policy=...)`` on those 1-D samples.

        Original scipy signature (from officialdocs)::

            scipy.stats.mannwhitneyu(x, y, use_continuity=True,
                alternative='two-sided', axis=0, method='auto', *,
                nan_policy='propagate', keepdims=False)

        ``axis``/``keepdims`` are irrelevant here (the wrapper always builds two
        1-D samples), so they are not exposed.

        Returns a one-row result table (arm labels + n + median per arm, the U
        statistic and the p-value) registered as the node's output relation.
        """
        try:
            import numpy as np  # noqa: F401
            import pandas as pd
            from scipy.stats import mannwhitneyu
        except Exception as e:  # pragma: no cover
            return f"Error: scipy / pandas unavailable ({e})."

        vcol = (value_column or "").strip()
        gcol = (group_column or "").strip()
        if not vcol or not gcol:
            return "Error: 'value_column' and 'group_column' are required."

        alt = (alternative or "two-sided").strip().lower()
        if alt not in ("two-sided", "less", "greater"):
            return "Error: 'alternative' must be 'two-sided', 'less' or 'greater'."
        meth = (method or "auto").strip().lower()
        if meth not in ("auto", "asymptotic", "exact"):
            return "Error: 'method' must be 'auto', 'asymptotic' or 'exact'."
        npol = (nan_policy or "omit").strip().lower()
        if npol not in ("propagate", "omit", "raise"):
            return "Error: 'nan_policy' must be 'propagate', 'omit' or 'raise'."

        # ── parquet → tidy (value, group) frame ─────────────────────────
        src = (source or "seer").strip() or "seer"
        sql = (
            f"SELECT TRY_CAST({_q(vcol)} AS DOUBLE) AS _v, "
            f"CAST({_q(gcol)} AS VARCHAR) AS _g FROM {_q(src)} "
            f"WHERE TRY_CAST({_q(vcol)} AS DOUBLE) IS NOT NULL "
            f"AND {_q(gcol)} IS NOT NULL"
        )
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        # ── pick the two arms ───────────────────────────────────────────
        if isinstance(group_values, str):
            group_values = [group_values]
        if group_values:
            arms = [str(v) for v in group_values][:2]
            if len(arms) < 2:
                return (
                    "Error: 'group_values' must name TWO groups to compare, "
                    'e.g. ["Chemotherapy", "No chemotherapy"].'
                )
        else:
            counts = df["_g"].value_counts()
            if len(counts) < 2:
                return (
                    f'Only one distinct value of "{_bare(gcol)}" in the cohort — '
                    "Mann-Whitney U needs two groups. Set 'group_values' or widen the cohort."
                )
            arms = [str(counts.index[0]), str(counts.index[1])]

        x = df.loc[df["_g"] == arms[0], "_v"].to_numpy()
        y = df.loc[df["_g"] == arms[1], "_v"].to_numpy()
        if x.size == 0 or y.size == 0:
            return (
                f"One arm is empty (n_{arms[0]}={x.size:,}, n_{arms[1]}={y.size:,}). "
                f'Check the labels of "{_bare(gcol)}" and \'group_values\'.'
            )

        # ── the actual scipy.stats.mannwhitneyu call ───────────────────
        try:
            res = mannwhitneyu(
                x,
                y,
                use_continuity=bool(use_continuity),
                alternative=alt,
                method=meth,
                nan_policy=npol,
            )
        except Exception as e:
            return f"Error running mannwhitneyu: {e}"

        u_stat = float(getattr(res, "statistic", float("nan")))
        p_val = float(getattr(res, "pvalue", float("nan")))
        table = pd.DataFrame(
            [
                {
                    "value_column": _bare(vcol),
                    "group_column": _bare(gcol),
                    "group_a": arms[0],
                    "n_a": int(x.size),
                    "median_a": round(float(np.median(x)), 5) if x.size else None,
                    "group_b": arms[1],
                    "n_b": int(y.size),
                    "median_b": round(float(np.median(y)), 5) if y.size else None,
                    "u_statistic": round(u_stat, 5),
                    "p_value": round(p_val, 8),
                    "alternative": alt,
                    "method": meth,
                }
            ]
        )
        name = (label or "").strip() or f"mann_whitney_u_{self._n + 1}"
        # Parquet-out contract: materialize the full result, write it to S3 as a
        # single parquet, and RETURN that parquet path (the tool's canonical
        # output). The table is still surfaced as a preview deliverable (with the
        # parquet path attached) for the workspace, and the graph's persist layer
        # reuses this URI instead of copying the relation again.
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name,
            table,
            len(table),
            title="Mann-Whitney U test",
            storage_path=parquet_uri,
            parquet_uri=parquet_uri,
        )
        stats = (
            f"Mann-Whitney U '{name}': \"{_bare(vcol)}\" between "
            f"\"{arms[0]}\" (n={x.size:,}) and \"{arms[1]}\" (n={y.size:,}); "
            f"U={u_stat:.4g}, p={p_val:.4g} (alternative='{alt}', method='{meth}')."
        )
        if parquet_uri:
            # Path-first return so the tool's output is the parquet artifact.
            return f"{parquet_uri}\n{stats}"
        # S3 unavailable (e.g. local dev): fall back to the descriptive result.
        return f"{stats} (parquet export unavailable)\n{_fmt_rows_for_llm(table, 5)}"

    def chi2_contingency(
        self,
        row_column: str,
        col_column: str,
        row_values: Any = None,
        col_values: Any = None,
        where: str = "",
        correction: bool = True,
        lambda_: Any = None,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Chi-square test of independence on a PARQUET cohort — a SEER-template
        wrapper over ``scipy.stats.chi2_contingency``.

        SEER-template contract: every tool receives the parquet-backed cohort
        (the ``source`` DuckDB view) plus test parameters — NEVER a pre-built
        matrix. scipy expects ``observed``, an R×C contingency table, so this
        wrapper does the parquet→table CONVERSION *inside* the wrapper, BEFORE
        the real function is called:

          1. Cross-tabulate two categorical columns from ``source`` — a grouped
             ``COUNT(*)`` over (``row_column``, ``col_column``), optionally
             narrowed by ``where`` (nulls dropped).
          2. Pivot the counts into the R×C ``observed`` matrix; optionally keep
             / order categories with ``row_values`` / ``col_values`` and drop
             all-zero rows/cols. Require at least a 2×2 table.
          3. Call ``chi2_contingency(observed, correction=..., lambda_=...)``.

        Original scipy signature (from officialdocs)::

            scipy.stats.chi2_contingency(observed, correction=True,
                lambda_=None, *, method=None)

        ``method`` (a ResamplingMethod object) is not exposed — it cannot be
        expressed as a JSON parameter — so the default asymptotic p-value is used.

        Returns a one-row result table (table dims + N, chi-square statistic,
        dof, p-value, and Cramér's V effect size) registered as the node's
        parquet output.
        """
        try:
            import numpy as np
            import pandas as pd
            from scipy.stats import chi2_contingency as _chi2
        except Exception as e:  # pragma: no cover
            return f"Error: scipy / pandas unavailable ({e})."

        rcol = (row_column or "").strip()
        ccol = (col_column or "").strip()
        if not rcol or not ccol:
            return "Error: 'row_column' and 'col_column' are required."

        lam = lambda_
        if isinstance(lam, str):
            lam = lam.strip() or None

        # ── parquet → grouped counts → R×C contingency table ────────────
        src = (source or "seer").strip() or "seer"
        sql = (
            f"SELECT CAST({_q(rcol)} AS VARCHAR) AS _r, "
            f"CAST({_q(ccol)} AS VARCHAR) AS _c, COUNT(*) AS _n FROM {_q(src)} "
            f"WHERE {_q(rcol)} IS NOT NULL AND {_q(ccol)} IS NOT NULL"
        )
        w = (where or "").strip()
        if w:
            sql += f" AND ({w})"
        sql += " GROUP BY 1, 2"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building contingency table: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        def _wanted(vals: Any) -> Optional[List[str]]:
            if vals is None:
                return None
            if isinstance(vals, str):
                vals = [vals]
            out = [str(v) for v in vals if str(v).strip()]
            return out or None

        row_keep = _wanted(row_values)
        col_keep = _wanted(col_values)
        if row_keep is not None:
            df = df[df["_r"].isin(row_keep)]
        if col_keep is not None:
            df = df[df["_c"].isin(col_keep)]
        if len(df) == 0:
            return (
                "No rows left after applying 'row_values' / 'col_values'. "
                "Check the exact category labels."
            )

        tab = df.pivot_table(
            index="_r", columns="_c", values="_n", aggfunc="sum", fill_value=0
        )
        # Preserve requested category ordering when provided.
        if row_keep is not None:
            tab = tab.reindex(index=[v for v in row_keep if v in tab.index])
        if col_keep is not None:
            tab = tab.reindex(columns=[v for v in col_keep if v in tab.columns])
        tab = tab.fillna(0)
        # Drop all-zero margins that would make the test undefined.
        tab = tab.loc[tab.sum(axis=1) > 0, tab.sum(axis=0) > 0]
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            return (
                f"Contingency table is {tab.shape[0]}×{tab.shape[1]} — chi-square needs "
                f"at least 2×2. Widen the cohort or pick columns with ≥2 categories each."
            )

        observed = tab.to_numpy(dtype=float)

        # ── the actual scipy.stats.chi2_contingency call ───────────────
        try:
            res = _chi2(observed, correction=bool(correction), lambda_=lam)
        except Exception as e:
            return f"Error running chi2_contingency: {e}"

        chi2_stat = float(getattr(res, "statistic", float("nan")))
        p_val = float(getattr(res, "pvalue", float("nan")))
        dof = int(getattr(res, "dof", 0))
        n_total = int(observed.sum())
        k = min(tab.shape)
        cramers_v = (
            float(np.sqrt(chi2_stat / (n_total * (k - 1))))
            if n_total > 0 and k > 1
            else None
        )
        table = pd.DataFrame(
            [
                {
                    "row_column": _bare(rcol),
                    "col_column": _bare(ccol),
                    "n": n_total,
                    "n_rows": int(tab.shape[0]),
                    "n_cols": int(tab.shape[1]),
                    "chi2_statistic": round(chi2_stat, 5),
                    "dof": dof,
                    "p_value": round(p_val, 8),
                    "cramers_v": round(cramers_v, 5) if cramers_v is not None else None,
                    "lambda_": str(lam) if lam is not None else "pearson",
                    "correction": bool(correction),
                }
            ]
        )
        name = (label or "").strip() or f"chi2_contingency_{self._n + 1}"
        # Parquet-out contract (identical to mann_whitney_u): materialize the full
        # result, write it to S3 as a single parquet, RETURN that path, and let
        # the graph's persist layer reuse the URI (no second copy).
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name,
            table,
            len(table),
            title="Chi-square test of independence",
            storage_path=parquet_uri,
            parquet_uri=parquet_uri,
        )
        stats = (
            f"Chi-square '{name}': \"{_bare(rcol)}\" × \"{_bare(ccol)}\" "
            f"({tab.shape[0]}×{tab.shape[1]}, N={n_total:,}); "
            f"chi2={chi2_stat:.4g}, dof={dof}, p={p_val:.4g}"
            + (f", Cramér's V={cramers_v:.3g}" if cramers_v is not None else "")
            + "."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}"
        return f"{stats} (parquet export unavailable)\n{_fmt_rows_for_llm(table, 5)}"

    def table1(
        self,
        columns: Any = None,
        groupby: str = "",
        categorical: Any = None,
        nonnormal: Any = None,
        order: Any = None,
        rename: Any = None,
        limit: Any = None,
        decimals: Any = None,
        pval: bool = True,
        smd: bool = True,
        missing: bool = True,
        overall: bool = True,
        label_suffix: bool = True,
        include_null: bool = False,
        where: str = "",
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Baseline-characteristics "Table 1" on a PARQUET cohort — a SEER-template
        wrapper over the ``tableone`` library (``tableone.TableOne``).

        SEER-template contract: the tool receives the parquet-backed cohort (the
        ``source`` DuckDB view) plus a variable spec — NEVER a pre-built frame.
        ``TableOne`` needs a tidy DataFrame + column lists, so the wrapper does the
        parquet→frame CONVERSION inside itself BEFORE the real call:

          1. SELECT the requested ``columns`` (+ ``groupby``) from ``source``
             (optionally narrowed by ``where``).
          2. Build ``TableOne(df, columns=…, categorical=…, groupby=…,
             nonnormal=…, order/rename/limit/decimals=…, pval=…, smd=…)`` — the
             standard baseline table (per-group columns with p-values + SMD when a
             ``groupby`` is given; median [IQR] for ``nonnormal`` continuous vars).
          3. Flatten TableOne's MultiIndex result into a plain tidy table.

        A baseline table counts PATIENTS, so a multiply imputed input (an
        ``_imputation`` column) is narrowed to ONE draw instead of reporting m
        stacked copies as N — unless the draw index is itself the ``groupby``.
        Returns the formatted Table 1 registered as the node's parquet output.
        """
        try:
            import pandas as pd
            from tableone import TableOne
        except Exception as e:  # pragma: no cover
            return f"Error: tableone / pandas unavailable ({e}). Install with `pip install tableone`."

        def _as_list(v: Any) -> Optional[List[str]]:
            if v is None:
                return None
            if isinstance(v, str):
                v = [v]
            out = [str(x) for x in v if str(x).strip()]
            return out or None

        def _as_dict(v: Any) -> Optional[Dict[str, Any]]:
            return v if isinstance(v, dict) and v else None

        cols = _as_list(columns)
        if not cols:
            return "Error: 'columns' (the variables to summarize) is required."
        gb = (groupby or "").strip()
        cat = [c for c in (_as_list(categorical) or []) if c in cols]
        nonnorm = [c for c in (_as_list(nonnormal) or []) if c in cols]

        # ── parquet → tidy cohort frame ─────────────────────────────────
        src = (source or "seer").strip() or "seer"
        select_cols = list(dict.fromkeys(cols + ([gb] if gb else [])))
        sql = f"SELECT {', '.join(_q(c) for c in select_cols)} FROM {_q(src)}"
        w = (where or "").strip()
        mi_note = ""
        mi_col = _mi_column(imputation_column)
        draws = _mi_draw_ids(self.con, src, w, imputation_column)
        if draws and mi_col != _bare(gb):
            w = _mi_where(w, draws[0], imputation_column)
            mi_note = (
                f" Input holds {len(draws)} imputation draw(s) of the same patients; "
                f"this table describes draw {draws[0]} so N counts patients rather than "
                f"{len(draws)}× the cohort."
            )
        if w:
            sql += f" WHERE ({w})"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error building the Table 1 cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows). Verify column values."

        # ── the actual tableone.TableOne call ───────────────────────────
        kwargs: Dict[str, Any] = dict(
            columns=cols,
            categorical=(cat or None),
            nonnormal=(nonnorm or None),
            pval=bool(pval) and bool(gb),   # p-values require a grouping variable
            smd=bool(smd) and bool(gb),     # SMD requires a grouping variable
            missing=bool(missing),
            overall=bool(overall),
            label_suffix=bool(label_suffix),
            include_null=bool(include_null),
        )
        if gb:
            kwargs["groupby"] = gb
        for k, v in (("order", order), ("rename", rename), ("limit", limit), ("decimals", decimals)):
            d = _as_dict(v)
            if d:
                kwargs[k] = d
        try:
            t1 = TableOne(df, **kwargs)
        except TypeError:
            # Older/newer tableone may not accept every flag — retry without the
            # optional ones rather than failing the node.
            for opt in ("include_null", "label_suffix"):
                kwargs.pop(opt, None)
            try:
                t1 = TableOne(df, **kwargs)
            except Exception as e:
                return f"Error running TableOne: {e}"
        except Exception as e:
            return f"Error running TableOne: {e}"

        # ── flatten TableOne's MultiIndex frame → plain tidy table ──────
        try:
            tab = t1.tableone.copy()
        except Exception:
            tab = getattr(t1, "tableone", None)
        if tab is None:
            return "Error: TableOne produced no result table."
        try:
            if hasattr(tab.columns, "to_flat_index"):
                flat: List[str] = []
                for col in tab.columns.to_flat_index():
                    if isinstance(col, tuple):
                        flat.append(" ".join(str(c) for c in col if str(c) != "").strip())
                    else:
                        flat.append(str(col))
                tab.columns = flat
            tab = tab.reset_index()
            ren: Dict[Any, str] = {}
            idx_names = iter(["Variable", "Level"])
            for c in list(tab.columns):
                cs = str(c)
                if cs == "" or cs.startswith("level_") or cs == "index":
                    nxt = next(idx_names, None)
                    if nxt:
                        ren[c] = nxt
            if ren:
                tab = tab.rename(columns=ren)
            # TableOne mixes strings + numbers per cell → coerce to a clean,
            # parquet-safe object frame (NaN → None).
            tab = tab.astype(object).where(pd.notna(tab), None)
        except Exception as e:
            logger.warning("[seer] table1 flatten failed (%s) — using raw TableOne frame", e)

        name = (label or "").strip() or f"table1_{self._n + 1}"
        # Parquet-out contract (identical to chi2_contingency): materialize the
        # full result, write it to S3 as a single parquet, RETURN that path.
        self._materialize_output(name, tab)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name,
            tab,
            len(tab),
            title="Table 1. Baseline characteristics",
            storage_path=parquet_uri,
            parquet_uri=parquet_uri,
        )
        stats = (
            f"Table 1 '{name}': {len(cols)} variable(s)"
            + (f' grouped by "{_bare(gb)}"' if gb else " (overall)")
            + f", N={len(df):,}."
            + mi_note
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}"
        return f"{stats} (parquet export unavailable)\n{_fmt_rows_for_llm(tab, 8)}"

    # ── PARQUET → Plotly figure wrappers (clinical charts) ──────────────
    # SEER-template contract: a plot tool receives the parquet-backed cohort
    # (the DuckDB ``source`` view) plus column/style params — NEVER raw arrays or
    # a pre-built DataFrame. ``plotly.express.<fn>(data_frame, x=, y=, ...)`` needs
    # a tidy DataFrame plus column NAMES, so each wrapper does the parquet→frame
    # CONVERSION *inside* itself BEFORE calling the real px function (pull the
    # referenced columns from ``source``, cast/aggregate/drop-nulls as the chart
    # requires), then renders the returned Figure to PNG. Parquet-out contract:
    # the plotted tidy frame is materialized + exported as the node's Parquet
    # output and the PNG is surfaced as a `figure` deliverable.

    def _finalize_figure(self, name: str, title: str, plot_df, image, *, stats: str) -> str:
        """Shared parquet-out + figure-deliverable finalizer for ALL plot wrappers
        (plotly and matplotlib). ``image`` is the already-rendered
        {image_uri, image_url} dict (or None on render failure).

        (1) materialize the plotted tidy frame as the node's DuckDB relation and
        export it to S3 as Parquet (parquet-out); (2) register the PNG as a
        ``figure`` deliverable; (3) return a path-first message so the tool's
        canonical output is the Parquet artifact.
        """
        self._materialize_output(name, plot_df)
        parquet_uri = self._export_parquet(name)
        extra: Dict[str, Any] = {"kind": "figure", "title": title}
        if image:
            extra.update(image)
        if parquet_uri:
            extra["storage_path"] = parquet_uri
            extra["parquet_uri"] = parquet_uri
        self._register_deliverable(name, plot_df, len(plot_df), **extra)
        img_note = (
            " A PNG chart was rendered and will be shown in the UI (do not paste "
            "any URL)."
            if image
            else " (figure PNG unavailable — chart engine could not rasterize)."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}{img_note}"
        return f"{stats}{img_note} (parquet export unavailable)\n{_fmt_rows_for_llm(plot_df, 5)}"

    # ── causal inference: the ATT family (frozen tools) ──────────────────
    # These are GENERALIZED, not one-shot: `att_estimate` answers one method,
    # `att_estimate_multi` takes the method list, `att_sensitivity` takes the
    # specification list. A protocol that says "estimate the ATT four ways" or
    # "repeat under six analytic choices" is ONE node with a list parameter —
    # never N sibling nodes, which is how sibling nodes silently drift apart.

    def _causal_frame(
        self,
        *,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str = "",
        outcome_values: Any = None,
        where: str = "",
        source: str = "seer",
        reference_levels: Any = None,
        keep_work: bool = False,
        imputation_column: Any = None,
    ):
        """Load + encode the cohort every ``att_*`` tool works on → ``(ctx, err)``.

        ``ctx["frame"]`` holds ``_att_id`` / ``_treat`` / optional ``_y`` beside
        the one-hot encoded covariate columns named in ``ctx["features"]``, with
        incomplete rows dropped (complete-case, the protocol's primary rule).
        ``keep_work=True`` additionally leaves the full-width cohort in a scratch
        relation (``ctx["work"]``) so per-patient columns can be joined back; the
        caller MUST drop it.

        A stack of imputation draws (an ``_imputation`` column) is carried as
        ``_mi`` and enumerated in ``ctx["draws"]`` — encoded ONCE so every draw
        shares one covariate layout, then sliced per draw by :meth:`_ctx_draw`.
        """
        import pandas as pd

        tcol = _bare(treatment_column)
        if not tcol:
            return None, "Error: 'treatment_column' is required."
        if isinstance(treatment_values, str):
            treatment_values = [treatment_values]
        tvals = [str(v) for v in (treatment_values or [])]
        if not tvals:
            return None, (
                "Error: 'treatment_values' must list ONLY the TREATED arm's value(s) — "
                "control is everyone else."
            )
        covs = [_bare(c) for c in (covariates or []) if _bare(c)]
        if not covs:
            return None, "Error: 'covariates' (at least one confounder) are required."
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return None, rerr

        # A binary outcome is declared by naming its positive value(s); without
        # them the column is read as numeric and the ATT is a mean difference.
        ycol = _bare(outcome_column)
        binary, yexpr = True, ""
        if ycol:
            if isinstance(outcome_values, str):
                outcome_values = [outcome_values]
            yvals = [str(v) for v in (outcome_values or [])]
            if yvals:
                in_y = ", ".join("'" + v.replace("'", "''") + "'" for v in yvals)
                yexpr = f"CASE WHEN CAST({_q(ycol)} AS VARCHAR) IN ({in_y}) THEN 1 ELSE 0 END"
            else:
                yexpr = f"TRY_CAST({_q(ycol)} AS DOUBLE)"
                binary = False

        src = (source or "seer").strip() or "seer"
        in_t = ", ".join("'" + v.replace("'", "''") + "'" for v in tvals)
        w = str(where or "").strip()
        base = (
            f"(SELECT *, ROW_NUMBER() OVER () AS _att_id FROM {_q(src)}"
            + (f" WHERE ({w})" if w else "")
            + ")"
        )
        work = ""
        if keep_work:
            work = f"_att_work_{abs(hash((src, w, tcol, tuple(covs)))) % 10_000_000}"
            try:
                self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS SELECT * FROM {base}")
            except Exception as e:
                return None, f"Error building cohort: {e}"
            base = _q(work)

        mi_col = _mi_column(imputation_column)
        has_mi = (
            not _mi_disabled(imputation_column)
            and _has_column(self.con, src, mi_col)
        )
        cov_map: Dict[str, str] = {}
        sel = [
            "_att_id",
            f"CASE WHEN CAST({_q(tcol)} AS VARCHAR) IN ({in_t}) THEN 1 ELSE 0 END AS _treat",
        ]
        if has_mi:
            sel.append(f"{_q(mi_col)} AS _mi")
        if yexpr:
            sel.append(f"{yexpr} AS _y")
        for i, c in enumerate(covs):
            alias = f"x{i}"
            cov_map[alias] = c
            sel.append(f"{_q(c)} AS {alias}")
        sql = f"SELECT {', '.join(sel)} FROM {base} LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            self._drop_relation(work)
            return None, f"Error building cohort: {e}"
        if len(df) == 0:
            self._drop_relation(work)
            return None, "Cohort is empty after filtering (0 rows). Verify column values."

        try:
            X, features = _design_matrix(df, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            self._drop_relation(work)
            return None, str(e)
        if not features:
            self._drop_relation(work)
            return None, "Error: no usable covariate columns after encoding."

        keep = ["_att_id", "_treat"] + (["_mi"] if has_mi else []) + (["_y"] if yexpr else [])
        loaded = pd.concat(
            [df[keep].reset_index(drop=True), X.reset_index(drop=True)], axis=1
        )
        frame = loaded.dropna()
        if len(frame) == 0:
            self._drop_relation(work)
            return None, (
                "Cohort is empty after dropping incomplete rows — no patient has "
                "every covariate observed. Impute first (impute_missing) or drop the "
                "covariate that is never recorded."
            )
        attrition = _att_attrition(df, loaded, frame, cov_map)
        frame["_treat"] = frame["_treat"].astype(int)
        if frame["_treat"].nunique() < 2:
            self._drop_relation(work)
            return None, (
                "Both treated and control patients are required (one arm is empty). "
                "Check that 'treatment_values' copies the data's values verbatim."
            )
        draws: List[Any] = []
        if has_mi:
            draws = sorted(frame["_mi"].dropna().unique().tolist())
            if len(draws) < 2:
                draws = []
        ctx = {
            "work": work, "frame": frame, "features": features, "binary": binary,
            "treatment": tcol, "outcome": ycol, "covariates": covs,
            "n": len(frame), "n_loaded": len(df), "draws": draws,
            "attrition": attrition,
            # Kept so an infeasibility message can name the filter that emptied an arm:
            # a complete-case `where` is applied before the cohort is even loaded, so
            # the attrition counts alone cannot see it.
            "where": w,
        }
        return ctx, None

    @staticmethod
    def _ctx_draw(ctx: Dict[str, Any], draw: Any) -> Dict[str, Any]:
        """The same prepared frame restricted to ONE imputation draw (mice's ``with``)."""
        frame = ctx["frame"]
        sub = dict(ctx)
        sub["frame"] = frame[frame["_mi"] == draw]
        sub["n"] = len(sub["frame"])
        sub["draws"] = []
        return sub

    def _mi_pool_tool(
        self,
        op: str,
        *,
        draws: Sequence[Any],
        imputation_column: Any,
        where: str,
        key_cols: Sequence[str],
        title: str,
        label: str,
        kwargs: Dict[str, Any],
        max_rows: int = 40,
    ) -> str:
        """Run a frozen model tool INSIDE each imputation draw, then pool (Rubin).

        mice's ``with()`` + ``pool()`` for the tools whose result is a long
        coefficient table: the tool runs UNCHANGED on each completed dataset —
        its own design matrix, its own fit, its own covariance — and the m tables
        are combined term by term by :func:`_pool_model_tables`. Fitting the
        stacked draws as one cohort instead would count every patient m times and
        report standard errors ~√m too small.

        Only the pooled table is materialized, exported and registered; the
        per-draw runs are scratch and are cleaned up.
        """
        m = len(draws)
        method = getattr(self, op)
        tables: List[Any] = []
        failures: List[str] = []
        first_summary = ""
        tmp_names: List[str] = []
        keep_deliverables = list(self.deliverables)
        keep_n = self._n
        keep_suppress = self._suppress_export
        self._suppress_export = True
        try:
            for i, d in enumerate(draws, start=1):
                _emit_tool_progress(f"{op}: imputation {i}/{m}")
                tmp = f"_mi_{op}_{i}"
                out = str(method(
                    **kwargs,
                    where=_mi_where(where, d, imputation_column),
                    imputation_column="none",
                    label=tmp,
                ))
                if tmp not in self._materialized_outputs:
                    failures.append(f"draw {d}: {out.strip().splitlines()[0][:200]}")
                    continue
                tmp_names.append(tmp)
                tables.append(self.con.execute(f"SELECT * FROM {_q(tmp)}").fetchdf())
                if not first_summary:
                    first_summary = out.strip().splitlines()[0]
        finally:
            self._suppress_export = keep_suppress
            self.deliverables = keep_deliverables
            self._n = keep_n
            for tmp in tmp_names:
                self._materialized_outputs.discard(tmp)
                self._drop_relation(tmp)
        if not tables:
            return (
                f"Error: {op} failed in every one of the {m} imputation draws — "
                + "; ".join(failures[:3])
            )
        table = _pool_model_tables(tables, key_cols)
        if not len(table):
            return f"Error: {op} produced no poolable rows across the {m} imputation draws."

        name = (label or "").strip() or f"{op}_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title=title,
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        how = (
            "every coefficient was estimated INSIDE each completed dataset and the "
            "estimates pooled by Rubin's rules, so the standard errors carry the "
            "imputation uncertainty"
            if "coef" in table.columns else
            "the statistic was recomputed INSIDE each completed dataset and the m "
            "results averaged (a true/false verdict is the majority of the draws)"
        )
        stats = (
            f"{op} '{name}' ran in {len(tables)}/{m} imputation draw(s): {how}, and every "
            f"n counts PATIENTS (not stacked rows). Per-draw run: {first_summary}"
        )
        if failures:
            stats += f" {len(failures)} draw(s) failed to fit and were skipped."
        out = f"{stats}\nPooled results:\n{_fmt_rows_for_llm(table, max_rows)}"
        if "fmi" in table.columns:
            out += (
                "\n'fmi' is the fraction of missing information per term — the share of "
                "the pooled variance contributed by disagreement BETWEEN draws. Rows "
                "WITHOUT a coefficient (joint/global Wald tests, assumption tests) carry "
                "the AVERAGE of the m per-draw statistics, so read them as a summary of "
                "the draws rather than as a pooled test."
            )
        if parquet_uri:
            return f"{parquet_uri}\n{out}"
        return out

    @staticmethod
    def _causal_arrays(ctx: Dict[str, Any]):
        """``(X, t, y)`` numpy views of a prepared causal frame."""
        import numpy as np

        frame = ctx["frame"]
        X = frame[ctx["features"]].to_numpy(dtype=float)
        t = frame["_treat"].to_numpy(dtype=int)
        y = (
            frame["_y"].to_numpy(dtype=float)
            if "_y" in frame.columns
            else np.zeros(len(frame), dtype=float)
        )
        return X, t, y

    def _causal_weight(
        self,
        *,
        estimand: str,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        weight_column: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Propensity weights for ``estimand`` + common-support flag, full cohort.

        Shared body of :meth:`att_weight` and :meth:`ate_weight`: the only thing
        the estimand changes is the weight formula, so the cohort encoding, the
        per-draw propensity fits, the diagnostics and the output shape stay one
        implementation rather than two that can drift.
        """
        import pandas as pd

        est = _estimand_key(estimand) or "att"
        name = (label or "").strip() or f"{est}_weighted_{self._n + 1}"
        wcol = _bare(weight_column) or _DEFAULT_WEIGHT_COLUMN[est]
        ctx, err = self._causal_frame(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, where=where, source=source,
            reference_levels=reference_levels, keep_work=True,
            imputation_column=imputation_column,
        )
        if err:
            return err
        assert ctx is not None
        work = ctx["work"]
        draws = list(ctx.get("draws") or [])
        pieces: List[Any] = []
        per_draw: List[Dict[str, Any]] = []
        n_dropped = 0
        for d in (draws or [None]):
            sub = ctx if d is None else self._ctx_draw(ctx, d)
            X, t, _ = self._causal_arrays(sub)
            try:
                ps = _fit_propensity(X, t, seed=int(random_state), clip_bounds=clip_bounds)
            except Exception as e:
                self._drop_relation(work)
                where_ = "" if d is None else f" (imputation {d})"
                return f"Error fitting the propensity model{where_}: {e}"
            w = _causal_weight_vector(ps, t, estimand=est)
            keep = _overlap_mask(ps, t, trim=trim)
            n_dropped += int((~keep).sum())
            pieces.append(pd.DataFrame({
                "_att_id": sub["frame"]["_att_id"].to_numpy(),
                "propensity_score": ps,
                wcol: w,
                "overlap_flag": keep.astype(int),
            }))
            for arm, mask in (("treated", t == 1), ("control", t == 0)):
                wa = w[mask]
                if wa.size == 0:
                    continue
                per_draw.append({
                    "arm": arm,
                    "n": int(mask.sum()),
                    "n_in_overlap": int((mask & keep).sum()),
                    "weighted_n": float(wa.sum()),
                    "ess": float(wa.sum() ** 2 / (wa**2).sum()) if (wa**2).sum() > 0 else 0.0,
                    "wmin": float(wa.min()),
                    "wmax": float(wa.max()),
                    "wmean": float(wa.mean()),
                })
        wdf = pd.concat(pieces, ignore_index=True) if len(pieces) > 1 else pieces[0]
        tmp = f"_attw_{abs(hash(name)) % 10_000_000}"
        only_overlap = str(restrict_to_overlap).strip().lower() in ("true", "1", "yes")
        try:
            self.con.register(tmp, wdf)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT c.* EXCLUDE (_att_id), w.propensity_score, w.{_q(wcol)}, w.overlap_flag "
                f"FROM {_q(work)} c JOIN {tmp} w USING (_att_id)"
                + (" WHERE w.overlap_flag = 1" if only_overlap else "")
            )
            self._materialized_outputs.add(name)
            n_out = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0])
        except Exception as e:
            return f"Error materializing the weighted cohort: {e}"
        finally:
            try:
                self.con.unregister(tmp)
            except Exception:
                pass
            self._drop_relation(work)

        # Averaged over draws, so every figure is on the PATIENT scale; the
        # weight range takes the extremes any draw produced.
        m = max(1, len(draws))
        rows: List[Dict[str, Any]] = []
        for arm in ("treated", "control"):
            parts = [p for p in per_draw if p["arm"] == arm]
            if not parts:
                continue
            k = len(parts)
            row: Dict[str, Any] = {
                "arm": arm,
                "n": int(round(sum(p["n"] for p in parts) / k)),
                "n_in_overlap": int(round(sum(p["n_in_overlap"] for p in parts) / k)),
                "weighted_n": round(sum(p["weighted_n"] for p in parts) / k, 2),
                "effective_sample_size": round(sum(p["ess"] for p in parts) / k, 1),
                "weight_min": round(min(p["wmin"] for p in parts), 5),
                "weight_max": round(max(p["wmax"] for p in parts), 5),
                "weight_mean": round(sum(p["wmean"] for p in parts) / k, 5),
            }
            if m > 1:
                row["n_imputations"] = m
            rows.append(row)
        diag = pd.DataFrame(rows)
        self._register_deliverable(
            name, diag, len(diag),
            title=f"{est.upper()} weight diagnostics (ESS, weight range)",
        )
        stats = (
            f"{est.upper()} weighting '{name}': {int(round(n_out / m)):,} patients "
            f"carry '{wcol}' "
            f"(dropped outside common support: {int(round(n_dropped / m)):,}"
            + (", excluded from the output" if only_overlap else ", flagged only")
            + f"; clip_bounds={_clip_pair(clip_bounds)}, trim={trim})."
        )
        if m > 1:
            stats += (
                f" The propensity model was fitted separately in each of {m} imputation "
                f"draw(s); the output keeps '{_mi_column(imputation_column)}' ({n_out:,} rows "
                f"total) so the downstream estimator pools instead of counting each patient "
                f"{m} times. Diagnostics above are per draw."
            )
        return f"{stats}\nWeight diagnostics:\n{_fmt_rows_for_llm(diag, 10)}"

    def att_weight(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        weight_column: str = "att_weight",
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """ATT propensity weights + common-support flag on the FULL cohort.

        Fits P(treated | covariates) and attaches ``propensity_score``, the ATT
        weight (1 for the treated, PS/(1−PS) for controls) and ``overlap_flag``
        to every patient. These weights make the CONTROLS look like the TREATED,
        which is the estimand a "what did the treatment do to those who received
        it" question asks — use ``ate_weight`` when the question is what it would
        do to everyone.

        OUTPUT is the input cohort plus those three columns (or only the
        common-support rows when ``restrict_to_overlap`` is set), so downstream
        weighted analyses consume it directly. The deliverable is the weight
        diagnostic table (per-arm n, weighted n, effective sample size, range).

        On a multiply imputed input the propensity model is fitted SEPARATELY in
        each draw — every row carries its own draw's score and weight, and the
        draw index survives in the output so the downstream estimator can pool.
        The diagnostics are reported per draw (patient scale), not summed over
        the stack.
        """
        return self._causal_weight(
            estimand="att",
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, where=where, clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap, weight_column=weight_column,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def ate_weight(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        estimand: str = "ate",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        weight_column: str = "",
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """ATE / ATO propensity weights + common-support flag on the FULL cohort.

        The population-effect sibling of ``att_weight``, built on the SAME
        propensity specification so a weighted cohort and the ``ate_estimate``
        that consumes it cannot disagree about the adjustment set.

        ``estimand="ate"`` (default) attaches 1/PS for the treated and 1/(1−PS)
        for the controls, so both arms stand in for the whole cohort.
        ``estimand="ato"`` attaches the bounded overlap weights (1−PS treated,
        PS control), which is the right choice when some propensity scores sit
        near 0 or 1 and the ATE weights would explode.

        OUTPUT is the input cohort plus ``propensity_score``, the weight column
        (``ate_weight`` / ``overlap_weight`` unless ``weight_column`` renames it)
        and ``overlap_flag``. Distinct from ``iptw_weight``, which is the
        ``iptw-survival`` implementation feeding the IPTW survival tools; use
        this one to stay on the same propensity fit as the ate_* estimators.
        """
        est = _estimand_key(estimand)
        if est == "att":
            return (
                "Error: ate_weight targets a POPULATION estimand. Use att_weight for "
                "the ATT, or pass estimand=\"ate\" / \"ato\"."
            )
        if not est:
            return (
                f"Error: unknown estimand '{estimand}'. Choose \"ate\" or \"ato\"."
            )
        return self._causal_weight(
            estimand=est,
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, where=where, clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap, weight_column=weight_column,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def _causal_run(
        self,
        ctx: Dict[str, Any],
        *,
        method: str,
        estimand: str = "att",
        clip_bounds: Any,
        trim: float,
        restrict_to_overlap: Any,
        match_ratio: int,
        caliper: float,
        n_bootstrap: int,
        random_state: int,
    ) -> Dict[str, Any]:
        """One causal estimate off a prepared frame → a result row (never raises).

        A failed method returns a row carrying ``error`` instead of aborting the
        node, so one bad arm of a multi-method / multi-specification run does not
        throw away the arms that did estimate.
        """
        import numpy as np

        est = _estimand_key(estimand) or "att"
        X, t, y = self._causal_arrays(ctx)
        if str(restrict_to_overlap).strip().lower() in ("true", "1", "yes") or float(trim or 0) > 0:
            try:
                ps0 = _fit_propensity(X, t, seed=int(random_state), clip_bounds=clip_bounds)
                mask = _overlap_mask(ps0, t, trim=trim)
                X, t, y = X[mask], t[mask], y[mask]
            except Exception:
                pass
        attrition = ctx.get("attrition") or {}
        row: Dict[str, Any] = {
            # Carried on the row because the ATT, the ATE and the ATO are different
            # numbers on the same data: a reader (or a downstream combine) that sees
            # only `effect` cannot tell which question was answered.
            "estimand": est.upper(),
            "method": str(method).lower(),
            "estimator": _estimator_label(method, est),
            # Post-trim, so a specification that restricts to overlap reports the
            # cohort it actually estimated on rather than the one it started from.
            "n_analyzed": int(len(t)),
        }
        # The cohort flow, so the reader can see WHERE the patients went: loaded ->
        # complete (listwise deletion) -> analyzed (common support) — plus how many
        # were KEPT with a covariate that was never recorded.
        for key in _ATT_FLOW_KEYS:
            value = attrition.get(key)
            if value is None or (isinstance(value, str) and not value):
                continue
            row[key] = value if isinstance(value, str) else int(value)

        arms = np.asarray(t).astype(int)
        n_treated_arm, n_control_arm = int((arms == 1).sum()), int((arms == 0).sum())
        if min(n_treated_arm, n_control_arm) < _ATT_MIN_ARM:
            # Not a result. Reporting a number here invites it to be quoted as
            # "the complete-case estimate" when what the data actually said is that
            # this adjustment set cannot be evaluated on these patients.
            row["feasible"] = False
            row["n_treated"], row["n_control"] = n_treated_arm, n_control_arm
            row["error"] = (
                f"INFEASIBLE, not estimated: only {n_treated_arm} treated and "
                f"{n_control_arm} control patient(s) remain (minimum {_ATT_MIN_ARM} per "
                f"arm). {_att_infeasible_cause(attrition, ctx.get('where'))} "
                f"Report this as a missingness "
                f"diagnostic, not as an effect estimate."
            )
            return row
        row["feasible"] = True
        try:
            res = _causal_effect_with_ci(
                X, t, y, method=method, estimand=est, binary=bool(ctx["binary"]),
                seed=int(random_state), clip_bounds=clip_bounds,
                ratio=int(match_ratio), caliper=float(caliper),
                n_bootstrap=int(n_bootstrap),
            )
        except Exception as e:
            row["error"] = str(e)
            return row
        row.update({
            "n_treated": res["n_treated"], "n_control": res["n_control"],
            "mu_treated": res["mu1"], "mu_control": res["mu0"],
            "effect": res["effect"],
            "effect_lower95": res.get("effect_lower95"),
            "effect_upper95": res.get("effect_upper95"),
            "effect_se": res.get("effect_se"),
            "ratio": res.get("ratio"),
            "n_bootstrap": res.get("n_bootstrap"),
        })
        lo, hi = row.get("effect_lower95"), row.get("effect_upper95")
        row["significant"] = None if (lo is None or hi is None) else bool(lo > 0 or hi < 0)
        return _round_causal_row(row)

    def _causal_run_pooled(
        self,
        ctx: Dict[str, Any],
        *,
        progress: str = "ATT",
        **run_args: Any,
    ) -> Dict[str, Any]:
        """One estimate PER IMPUTATION DRAW, combined by Rubin's rules → one row.

        This is ``with()`` + ``pool()``: the estimator runs inside each completed
        dataset — its own propensity fit, its own overlap restriction, its own
        bootstrap — and the m results are combined so the CI carries the
        imputation uncertainty. Patient counts are reported PER DRAW, which is
        the unique-patient count rather than m copies of it.
        """
        draws = list(ctx.get("draws") or [])
        if len(draws) < 2:
            return self._causal_run(ctx, **run_args)

        m = len(draws)
        requested = run_args.get("n_bootstrap")
        reps = _mi_reps(requested, m)
        per: List[Dict[str, Any]] = []
        for i, d in enumerate(draws, start=1):
            args = dict(run_args)
            args["n_bootstrap"] = reps
            _emit_tool_progress(
                f"{progress} — imputation {i}/{m} (bootstrap={reps})"
            )
            per.append(self._causal_run(self._ctx_draw(ctx, d), **args))

        ok = [r for r in per if r.get("effect") is not None]
        if not ok:
            first = next((r.get("error") for r in per if r.get("error")), "")
            infeasible = all(r.get("feasible") is False for r in per)
            out: Dict[str, Any] = {
                "estimand": (_estimand_key(run_args.get("estimand")) or "att").upper(),
                "method": str(run_args.get("method", "")).lower(),
                "n_imputations": m,
                "feasible": not infeasible,
                "error": (
                    first if infeasible
                    else f"no imputation draw produced an estimate ({first})"
                ),
            }
            for key in _ATT_FLOW_KEYS:
                if per and per[0].get(key) is not None:
                    out[key] = per[0][key]
            return out

        pooled = _rubin_pool(
            [r["effect"] for r in ok],
            [None if r.get("effect_se") is None else float(r["effect_se"]) ** 2 for r in ok],
        )
        mu1 = _mean_or_none([r.get("mu_treated") for r in ok])
        mu0 = _mean_or_none([r.get("mu_control") for r in ok])
        row: Dict[str, Any] = {
            "estimand": ok[0].get("estimand"),
            "method": ok[0]["method"],
            "estimator": ok[0]["estimator"],
            # Per draw = per patient. Averaged because a draw-specific overlap
            # restriction can keep slightly different rows in each one.
            "n_analyzed": int(round(_mean_or_none([r.get("n_analyzed") for r in ok]) or 0)),
            "n_treated": int(round(_mean_or_none([r.get("n_treated") for r in ok]) or 0)),
            "n_control": int(round(_mean_or_none([r.get("n_control") for r in ok]) or 0)),
            "mu_treated": mu1,
            "mu_control": mu0,
            "effect": pooled.get("estimate"),
            "effect_lower95": pooled.get("ci_lower"),
            "effect_upper95": pooled.get("ci_upper"),
            "effect_se": pooled.get("se"),
            "ratio": (mu1 / mu0) if (ctx.get("binary") and mu0 and mu0 > 0 and mu1 is not None) else None,
            # Replicates are split across the draws so m draws cost what one used to,
            # which makes the per-draw count SMALLER than the number asked for. Report
            # all three, or a request for 100 that ran 20x50 reads as "only 50 ran".
            "n_bootstrap": reps,
            "n_bootstrap_per_draw": reps,
            "n_bootstrap_requested": int(requested or 0),
            "n_bootstrap_total": int(reps) * len(ok),
            "n_imputations": m,
            "n_imputations_used": len(ok),
            "variance_method": "rubin" if pooled.get("within_variance") else "rubin_between_only",
            "fmi": pooled.get("fmi"),
        }
        # Listwise deletion happens once, before the draws are split, so the flow is
        # identical in every draw and survives pooling verbatim.
        for key in _ATT_FLOW_KEYS:
            if ok[0].get(key) is not None:
                row[key] = ok[0][key]
        row["feasible"] = True
        lo, hi = row["effect_lower95"], row["effect_upper95"]
        row["significant"] = None if (lo is None or hi is None) else bool(lo > 0 or hi < 0)
        return _round_causal_row(row)

    def _causal_estimate(
        self,
        *,
        estimand: str,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        outcome_values: Any = None,
        method: str = "ipw",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Shared body of :meth:`att_estimate` / :meth:`ate_estimate`."""
        import pandas as pd

        ctx, err = self._causal_frame(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            outcome_values=outcome_values, where=where, source=source,
            reference_levels=reference_levels, imputation_column=imputation_column,
        )
        if err:
            return err
        assert ctx is not None
        if not _bare(outcome_column):
            return "Error: 'outcome_column' is required."
        est = _estimand_key(estimand) or "att"
        tag = est.upper()
        _emit_tool_progress(
            f"{tag} {method} (n={ctx.get('n', '?')}, bootstrap={n_bootstrap})"
        )
        row = self._causal_run_pooled(
            ctx, progress=f"{tag} {method}",
            method=method, estimand=est, clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap, match_ratio=match_ratio,
            caliper=caliper, n_bootstrap=n_bootstrap, random_state=random_state,
        )
        if row.get("error"):
            return f"Error estimating the {tag} ({method}): {row['error']}"
        table = pd.DataFrame([row])
        name = (label or "").strip() or f"{est}_estimate_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title=f"{tag} — {_estimator_label(method, est)}",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"{tag} '{name}' ({method}, outcome '{ctx['outcome']}'): "
            f"{row['effect']} (95% CI {row.get('effect_lower95')} to "
            f"{row.get('effect_upper95')}) on n={row['n_analyzed']:,} "
            f"({row['n_treated']:,} treated)."
            + _att_flow_note(row)
            + _mi_note(row)
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 10)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 10)}"

    def att_estimate(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        outcome_values: Any = None,
        method: str = "ipw",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """ONE average treatment effect on the treated (ATT) by ONE method.

        Estimates the counterfactual means in the TREATED — ``mu_treated`` (what
        happened) and ``mu_control`` (what would have happened untreated) — and
        their difference, with a percentile bootstrap CI that re-fits the
        propensity/outcome model in every replicate.

        ``method``: ``ipw`` (ATT weights), ``gcomp`` (outcome regression
        standardized to the treated), ``psm`` (nearest-neighbour matching) or
        ``aipw`` (doubly robust). For SEVERAL methods use ``att_estimate_multi``
        — one node, one stacked table — and for the same method under several
        analytic choices use ``att_sensitivity``. For the effect in the WHOLE
        cohort rather than the treated, use ``ate_estimate``.

        On a MULTIPLY IMPUTED input the ATT is estimated inside each draw and
        pooled by Rubin's rules; ``n_treated`` then counts patients, not
        patient×draw rows.
        """
        return self._causal_estimate(
            estimand="att",
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            outcome_values=outcome_values, method=method, where=where,
            clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap, match_ratio=match_ratio,
            caliper=caliper, n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def ate_estimate(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        outcome_values: Any = None,
        method: str = "ipw",
        estimand: str = "ate",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """ONE average treatment effect in the WHOLE cohort (ATE) by ONE method.

        The population-effect sibling of ``att_estimate``: instead of asking what
        treatment did to the people who got it, it asks what it would do if
        everyone were treated versus nobody. ``mu_treated`` / ``mu_control`` are
        therefore both counterfactual means over the same population, and their
        difference is the ATE.

        ``method``: ``ipw`` (1/PS and 1/(1−PS) weights), ``gcomp`` (outcome
        regression standardized to every patient) or ``aipw`` (doubly robust).
        ``psm`` is NOT available — matching without replacement builds a control
        group for the treated, so it only identifies the ATT.

        ``estimand="ato"`` switches to the OVERLAP population (bounded weights),
        which is the estimand to prefer when propensity scores approach 0 or 1:
        the ATE's 1/PS weights then hand a handful of patients most of the
        estimate. It answers a narrower question — the effect among patients who
        could plausibly have received either arm — so say so in the report.

        On a MULTIPLY IMPUTED input the estimate runs inside each draw and is
        pooled by Rubin's rules.
        """
        est = _estimand_key(estimand)
        if est == "att":
            return (
                "Error: ate_estimate targets a POPULATION estimand. Use att_estimate "
                "for the ATT, or pass estimand=\"ate\" / \"ato\"."
            )
        if not est:
            return f"Error: unknown estimand '{estimand}'. Choose \"ate\" or \"ato\"."
        if str(method or "").strip().lower() not in _estimand_methods(est):
            return (
                f"Error: method '{method}' cannot identify the {est.upper()}. Choose "
                f"one of {sorted(_estimand_methods(est))} — matching (psm) builds a "
                f"control group FOR THE TREATED, so it only identifies the ATT."
            )
        return self._causal_estimate(
            estimand=est,
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            outcome_values=outcome_values, method=method, where=where,
            clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap,
            n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def _causal_estimate_multi(
        self,
        *,
        estimand: str,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        methods: Any = None,
        outcome_values: Any = None,
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Shared body of :meth:`att_estimate_multi` / :meth:`ate_estimate_multi`."""
        import pandas as pd

        est = _estimand_key(estimand) or "att"
        tag = est.upper()
        legal = _estimand_methods(est)
        if isinstance(methods, str):
            methods = [methods]
        wanted = [str(m).strip().lower() for m in (methods or []) if str(m).strip()]
        if not wanted:
            wanted = list(legal)
        unknown = [m for m in wanted if m not in legal]
        if unknown:
            return (
                f"Error: method(s) {unknown} cannot identify the {tag}. Choose from "
                f"{sorted(legal)}."
                + (
                    " Matching (psm) builds a control group FOR THE TREATED, so it "
                    "only identifies the ATT."
                    if any(m == "psm" for m in unknown) else ""
                )
            )
        if not _bare(outcome_column):
            return "Error: 'outcome_column' is required."

        ctx, err = self._causal_frame(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            outcome_values=outcome_values, where=where, source=source,
            reference_levels=reference_levels, imputation_column=imputation_column,
        )
        if err:
            return err
        assert ctx is not None

        rows: List[Dict[str, Any]] = []
        n_methods = len(wanted)
        for i, m in enumerate(wanted, start=1):
            _emit_tool_progress(
                f"{tag} multi {i}/{n_methods} {m} "
                f"(n={ctx.get('n', '?')}, bootstrap={n_bootstrap})"
            )
            t0 = time.monotonic()
            rows.append(self._causal_run_pooled(
                ctx, progress=f"{tag} multi {i}/{n_methods} {m}",
                method=m, estimand=est, clip_bounds=clip_bounds, trim=trim,
                restrict_to_overlap=restrict_to_overlap, match_ratio=match_ratio,
                caliper=caliper, n_bootstrap=n_bootstrap, random_state=random_state,
            ))
            _emit_tool_progress(
                f"{tag} multi {i}/{n_methods} {m} done ({time.monotonic() - t0:.0f}s)"
            )
        ok = [r for r in rows if r.get("effect") is not None]
        if not ok:
            return (
                "Error: no method produced an estimate — "
                + "; ".join(f"{r['method']}: {r.get('error')}" for r in rows)
            )
        primary = ok[0]["effect"]
        for r in rows:
            if r.get("effect") is not None:
                r["effect_minus_primary"] = round(float(r["effect"]) - float(primary), 5)
        table = pd.DataFrame(rows)

        name = (label or "").strip() or f"{est}_multi_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title=f"{tag} by estimation method",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        spread = max(float(r["effect"]) for r in ok) - min(float(r["effect"]) for r in ok)
        per_method = ", ".join("{}={}".format(r["method"], r["effect"]) for r in ok)
        stats = (
            f"{tag} '{name}' across {len(ok)}/{len(rows)} method(s) on "
            f"n={ok[0]['n_analyzed']:,}: estimates span {round(spread, 5)} ({per_method})."
            + _att_flow_note(ok[0])
            + _mi_note(ok[0])
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 20)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 20)}"

    def att_estimate_multi(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        methods: Any = None,
        outcome_values: Any = None,
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """The SAME ATT estimated by EVERY method in ``methods`` — one table.

        The loop version of ``att_estimate``: the cohort is encoded once and each
        method in ``methods`` (``ipw`` / ``gcomp`` / ``psm`` / ``aipw``) is run
        against that identical frame, so the estimates are genuinely comparable
        and the "do the four approaches agree?" row-by-row table is the node's
        output. The FIRST method is the primary analysis; every other row also
        reports its difference from it.

        A multiply imputed input is pooled per method, so every row reports the
        same patient-level n.
        """
        return self._causal_estimate_multi(
            estimand="att",
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column, methods=methods,
            outcome_values=outcome_values, where=where, clip_bounds=clip_bounds,
            trim=trim, restrict_to_overlap=restrict_to_overlap,
            match_ratio=match_ratio, caliper=caliper, n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def ate_estimate_multi(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        methods: Any = None,
        outcome_values: Any = None,
        estimand: str = "ate",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """The SAME ATE estimated by EVERY method in ``methods`` — one table.

        The loop version of ``ate_estimate``: one identically-encoded cohort, one
        row per method in ``methods`` (``ipw`` / ``gcomp`` / ``aipw``; ``psm`` is
        ATT-only and is rejected), each reporting its difference from the first.
        Bind this ONCE instead of one ``ate_estimate`` node per method.

        ``estimand="ato"`` runs the same sweep on the overlap population.
        """
        est = _estimand_key(estimand)
        if est == "att":
            return (
                "Error: ate_estimate_multi targets a POPULATION estimand. Use "
                "att_estimate_multi for the ATT, or pass estimand=\"ate\" / \"ato\"."
            )
        if not est:
            return f"Error: unknown estimand '{estimand}'. Choose \"ate\" or \"ato\"."
        return self._causal_estimate_multi(
            estimand=est,
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column, methods=methods,
            outcome_values=outcome_values, where=where, clip_bounds=clip_bounds,
            trim=trim, restrict_to_overlap=restrict_to_overlap,
            n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def _causal_sensitivity(
        self,
        *,
        estimand: str,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        specifications: Any = None,
        outcome_values: Any = None,
        method: str = "ipw",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Shared body of :meth:`att_sensitivity` / :meth:`ate_sensitivity`."""
        import pandas as pd

        est = _estimand_key(estimand) or "att"
        tag = est.upper()
        legal = _estimand_methods(est)
        if isinstance(specifications, dict):
            specifications = [specifications]
        specs = [s for s in (specifications or []) if isinstance(s, dict)]
        if not specs:
            return (
                'Error: \'specifications\' must be a non-empty list of override objects, '
                'e.g. [{"label":"primary"},{"label":"trim 1%","trim":0.01}].'
            )
        if not _bare(outcome_column):
            return "Error: 'outcome_column' is required."
        # Validate every specification's method UP FRONT, the way the multi tool
        # validates `methods`. Left to the estimator, a misspelled override (e.g.
        # "g_computation" for `gcomp`) only kills its own row: the node still succeeds
        # and the sensitivity table quietly ships one specification short.
        wanted = {str(method or "ipw").strip().lower()}
        wanted |= {
            str(s.get("method")).strip().lower() for s in specs if s.get("method")
        }
        unknown = sorted(w for w in wanted if w not in legal)
        if unknown:
            return (
                f"Error: method(s) {unknown} cannot identify the {tag}. Choose from "
                f"{sorted(legal)} (a specification's 'method' override uses the "
                f"same names as the node's own 'method')."
            )
        # A specification may switch the ESTIMAND (the ATE vs. the overlap
        # population is a real robustness question), but only to one this tool
        # family owns — otherwise the table mixes two questions under one primary.
        bad_est = sorted({
            str(s.get("estimand")) for s in specs
            if s.get("estimand") and _estimand_key(s.get("estimand")) not in _ESTIMAND_FAMILY[est]
        })
        if bad_est:
            return (
                f"Error: 'estimand' override(s) {bad_est} are not available here. "
                f"Choose from {sorted(_ESTIMAND_FAMILY[est])}."
            )

        base = {
            "treatment_column": treatment_column, "treatment_values": treatment_values,
            "covariates": covariates, "outcome_column": outcome_column,
            "outcome_values": outcome_values, "where": where, "source": source,
            "reference_levels": reference_levels,
            "imputation_column": imputation_column,
        }
        run_defaults = {
            "method": method, "estimand": est, "clip_bounds": clip_bounds, "trim": trim,
            "restrict_to_overlap": restrict_to_overlap, "match_ratio": match_ratio,
            "caliper": caliper, "n_bootstrap": n_bootstrap, "random_state": random_state,
        }
        # Rebuilding the cohort is the expensive half, so cache it on the keys
        # that actually change it (filter / covariates / outcome coding).
        cache: Dict[Any, Any] = {}
        rows: List[Dict[str, Any]] = []
        for i, spec in enumerate(specs):
            frame_args = dict(base)
            for k in ("where", "covariates", "outcome_values", "outcome_column",
                      "treatment_values", "reference_levels"):
                if k in spec:
                    frame_args[k] = spec[k]
            key = json.dumps(
                {k: frame_args[k] for k in sorted(frame_args)}, sort_keys=True, default=str
            )
            title = str(spec.get("label") or f"specification {i + 1}")
            if key not in cache:
                cache[key] = self._causal_frame(**frame_args)
            ctx, err = cache[key]
            if err:
                rows.append({"specification": title, "error": err})
                continue
            run_args = dict(run_defaults)
            for k in run_args:
                if k in spec:
                    run_args[k] = spec[k]
            _emit_tool_progress(
                f"{tag} sensitivity {i + 1}/{len(specs)} {title} "
                f"({run_args['method']}, bootstrap={run_args['n_bootstrap']})"
            )
            t0 = time.monotonic()
            row = self._causal_run_pooled(
                ctx, progress=f"{tag} sensitivity {i + 1}/{len(specs)} {title}",
                **run_args
            )
            _emit_tool_progress(
                f"{tag} sensitivity {i + 1}/{len(specs)} {title} "
                f"done ({time.monotonic() - t0:.0f}s)"
            )
            row["specification"] = title
            rows.append(row)

        ok = [r for r in rows if r.get("effect") is not None]
        if not ok:
            return (
                "Error: no specification produced an estimate — "
                + "; ".join(f"{r.get('specification')}: {r.get('error')}" for r in rows)
            )
        primary = float(ok[0]["effect"])
        for r in rows:
            if r.get("effect") is not None:
                r["effect_minus_primary"] = round(float(r["effect"]) - primary, 5)
        lead = ["specification", "estimand", "method", "feasible",
                "n_loaded", "n_complete", "n_analyzed", "n_imputations",
                "n_treated", "n_control",
                "mu_treated", "mu_control", "effect", "effect_lower95",
                "effect_upper95", "effect_minus_primary"]
        table = pd.DataFrame(rows)
        table = table[[c for c in lead if c in table.columns]
                      + [c for c in table.columns if c not in lead]]

        name = (label or "").strip() or f"{est}_sensitivity_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title=f"{tag} sensitivity to analytic specification",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        spread = max(float(r["effect"]) for r in ok) - min(float(r["effect"]) for r in ok)
        flips = sum(1 for r in ok if float(r["effect"]) * primary < 0)
        infeasible = [r for r in rows if r.get("feasible") is False]
        stats = (
            f"{tag} sensitivity '{name}': {len(ok)}/{len(rows)} specification(s) estimated, "
            f"effects span {round(spread, 5)} around a primary of {round(primary, 5)}"
            + (f"; {flips} change the direction of the effect." if flips else "; none reverse the direction.")
            + (
                f" {len(infeasible)} specification(s) were NOT estimated because an arm "
                f"was emptied by missing covariates — read those as missingness "
                f"diagnostics, not as effects: "
                + "; ".join(str(r.get("specification")) for r in infeasible) + "."
                if infeasible else ""
            )
            + _att_flow_note(ok[0])
            + _mi_note(ok[0])
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 30)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 30)}"

    def att_sensitivity(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        specifications: Any = None,
        outcome_values: Any = None,
        method: str = "ipw",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        match_ratio: int = 1,
        caliper: float = 0.2,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """RE-ESTIMATE the ATT under every analytic choice in ``specifications``.

        The loop version over SPECIFICATIONS rather than methods: each entry is
        an override of this node's own arguments — ``{"label": "trim 1%",
        "trim": 0.01}``, ``{"label": "no stage adjustment", "covariates": [...]}``,
        ``{"label": "complete cases only", "where": "..."}``, ``{"label": "AIPW",
        "method": "aipw"}`` — and the cohort is rebuilt only when the override
        actually changes it. The first specification is the PRIMARY analysis;
        every other row reports its difference from it, which is exactly the
        "is the conclusion robust to how we analysed it" table.
        """
        return self._causal_sensitivity(
            estimand="att",
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            specifications=specifications, outcome_values=outcome_values,
            method=method, where=where, clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap, match_ratio=match_ratio,
            caliper=caliper, n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    def ate_sensitivity(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        outcome_column: str,
        specifications: Any = None,
        outcome_values: Any = None,
        method: str = "ipw",
        estimand: str = "ate",
        where: str = "",
        clip_bounds: Any = None,
        trim: float = 0.0,
        restrict_to_overlap: Any = False,
        n_bootstrap: int = 200,
        reference_levels: Any = None,
        random_state: int = 42,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """RE-ESTIMATE the ATE under every analytic choice in ``specifications``.

        The population-effect sibling of ``att_sensitivity``, with the same
        contract: the node's own arguments are the PRIMARY analysis, each entry in
        ``specifications`` changes ONE thing, and every row reports its difference
        from the first. Method overrides are limited to ``ipw`` / ``gcomp`` /
        ``aipw`` because ``psm`` cannot identify a population effect.

        A specification may also override ``estimand`` to ``"ato"``, which is the
        honest way to show what the overlap population says when the ATE's 1/PS
        weights are dominated by a few near-deterministic patients.
        """
        est = _estimand_key(estimand)
        if est == "att":
            return (
                "Error: ate_sensitivity targets a POPULATION estimand. Use "
                "att_sensitivity for the ATT, or pass estimand=\"ate\" / \"ato\"."
            )
        if not est:
            return f"Error: unknown estimand '{estimand}'. Choose \"ate\" or \"ato\"."
        return self._causal_sensitivity(
            estimand=est,
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, outcome_column=outcome_column,
            specifications=specifications, outcome_values=outcome_values,
            method=method, where=where, clip_bounds=clip_bounds, trim=trim,
            restrict_to_overlap=restrict_to_overlap,
            n_bootstrap=n_bootstrap,
            reference_levels=reference_levels, random_state=random_state,
            imputation_column=imputation_column, label=label, source=source,
        )

    # ── covariate balance (single + loop over scenarios) ─────────────────

    def _balance_rows(
        self,
        *,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        weight_column: str,
        where: str,
        source: str,
        imputation_column: Any = None,
        cat_var: Any = None,
        cont_var: Any = None,
    ):
        """ASDs for one population, averaged over imputation draws when present.

        Balance is a property of each COMPLETED dataset, so it is computed inside
        every draw and averaged — the convention MatchThem / cobalt follow. On the
        stacked table it would instead be computed once over m copies of every
        patient, which understates nothing but reports an n that does not exist.
        """
        draws = _mi_draw_ids(self.con, source, where, imputation_column)
        args = dict(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, weight_column=weight_column, source=source,
            cat_var=cat_var, cont_var=cont_var,
        )
        if not draws:
            return self._balance_rows_one(where=where, **args)

        per: List[List[Dict[str, Any]]] = []
        for d in draws:
            rows, err = self._balance_rows_one(
                where=_mi_where(where, d, imputation_column), **args
            )
            if err:
                return None, f"imputation {d}: {err}"
            per.append(rows)
        if not per:
            return None, "No imputation draw produced a balance table."

        merged: List[Dict[str, Any]] = []
        for base in per[0]:
            key = (base["variable"], base["level"])
            matches = [
                r for rows in per for r in rows if (r["variable"], r["level"]) == key
            ]
            asd = _mean_or_none([r.get("asd") for r in matches])
            row = {
                "variable": base["variable"],
                "level": base["level"],
                "type": base["type"],
                "treated": _round_or_none(_mean_or_none([r.get("treated") for r in matches]), 5),
                "control": _round_or_none(_mean_or_none([r.get("control") for r in matches]), 5),
                "asd": _round_or_none(asd, 4),
                "balanced": None if asd is None else bool(asd < 0.1),
                "n_imputations": len(per),
            }
            merged.append(row)
        return merged, None

    def _balance_rows_one(
        self,
        *,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        weight_column: str,
        where: str,
        source: str,
        cat_var: Any = None,
        cont_var: Any = None,
    ):
        """Absolute standardized differences for one population → ``(rows, err)``.

        Continuous covariates get one row; categorical covariates get one row per
        level (a single "SMD" for a multi-level factor hides which level is out of
        balance). Weighted means are compared against the UNWEIGHTED pooled SD,
        which is the convention that keeps before/after ASDs on one scale.
        """
        import numpy as np
        import pandas as pd

        tcol = _bare(treatment_column)
        covs = [_bare(c) for c in (covariates or []) if _bare(c)]
        if not tcol or not covs:
            return None, "Error: 'treatment_column' and 'covariates' are required."
        if isinstance(treatment_values, str):
            treatment_values = [treatment_values]
        tvals = [str(v) for v in (treatment_values or [])]
        if not tvals:
            return None, "Error: 'treatment_values' must list the TREATED arm's value(s)."

        wcol = _bare(weight_column)
        in_t = ", ".join("'" + v.replace("'", "''") + "'" for v in tvals)
        sel = [f"CASE WHEN CAST({_q(tcol)} AS VARCHAR) IN ({in_t}) THEN 1 ELSE 0 END AS _treat"]
        sel.append(
            f"TRY_CAST({_q(wcol)} AS DOUBLE) AS _w" if wcol else "1.0 AS _w"
        )
        for i, c in enumerate(covs):
            sel.append(f"{_q(c)} AS x{i}")
        src = (source or "seer").strip() or "seer"
        sql = f"SELECT {', '.join(sel)} FROM {_q(src)}"
        w = str(where or "").strip()
        if w:
            sql += f" WHERE ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return None, f"Error reading covariates for balance: {e}"
        if len(df) == 0:
            return None, "Cohort is empty after filtering (0 rows)."
        df = df[df["_w"].notna()]
        t = df["_treat"].to_numpy(dtype=int) == 1
        wt = df["_w"].to_numpy(dtype=float)
        if not t.any() or not (~t).any():
            return None, "Both treated and control patients are required."

        def _wmean(vals, mask):
            v, ww = np.asarray(vals, dtype=float)[mask], wt[mask]
            keep = np.isfinite(v) & np.isfinite(ww) & (ww > 0)
            if not keep.any():
                return None
            return float(np.average(v[keep], weights=ww[keep]))

        forced_cat = {_bare(c) for c in (cat_var or []) if _bare(c)}
        forced_cont = {_bare(c) for c in (cont_var or []) if _bare(c)}

        rows: List[Dict[str, Any]] = []
        for i, c in enumerate(covs):
            col = df[f"x{i}"]
            num = pd.to_numeric(col, errors="coerce")
            as_cat = c in forced_cat or (
                c not in forced_cont and float(num.notna().mean()) < 0.8
            )
            if not as_cat:
                v = num.to_numpy(dtype=float)
                m1, m0 = _wmean(v, t), _wmean(v, ~t)
                pooled = float(
                    ((np.nanvar(v[t]) + np.nanvar(v[~t])) / 2.0) ** 0.5
                )
                asd = abs(m1 - m0) / pooled if (pooled > 0 and m1 is not None and m0 is not None) else None
                rows.append({
                    "variable": c, "level": None, "type": "continuous",
                    "treated": None if m1 is None else round(m1, 5),
                    "control": None if m0 is None else round(m0, 5),
                    "asd": None if asd is None else round(float(asd), 4),
                })
                continue
            text = col.astype("string").fillna("Unknown").replace("", "Unknown")
            for lv in sorted(str(v) for v in text.dropna().unique()):
                ind = (text == lv).to_numpy().astype(float)
                p1, p0 = _wmean(ind, t), _wmean(ind, ~t)
                if p1 is None or p0 is None:
                    continue
                pooled = ((p1 * (1 - p1) + p0 * (1 - p0)) / 2.0) ** 0.5
                rows.append({
                    "variable": c, "level": lv, "type": "categorical",
                    "treated": round(p1, 5), "control": round(p0, 5),
                    "asd": round(abs(p1 - p0) / pooled, 4) if pooled > 0 else None,
                })
        for r in rows:
            r["balanced"] = None if r["asd"] is None else bool(r["asd"] < 0.1)
        return rows, None

    def covariate_balance(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        weight_column: str = "",
        where: str = "",
        cat_var: Any = None,
        cont_var: Any = None,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Absolute standardized differences for ONE population/weighting.

        Reports, per covariate (and per level for categoricals), the treated and
        control means/proportions and their ASD, flagging ``balanced`` at the
        conventional |ASD| < 0.1. Pass ``weight_column`` (from ``att_weight`` /
        ``iptw_weight``) to score the WEIGHTED pseudo-population; omit it for the
        crude cohort. To report several populations side by side — crude vs
        weighted vs trimmed — use ``covariate_balance_multi``, which is one node
        instead of one node per scenario.
        """
        import pandas as pd

        rows, err = self._balance_rows(
            treatment_column=treatment_column, treatment_values=treatment_values,
            covariates=covariates, weight_column=weight_column, where=where,
            source=source, imputation_column=imputation_column,
            cat_var=cat_var, cont_var=cont_var,
        )
        if err:
            return err
        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"covariate_balance_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title="Covariate balance (absolute standardized differences)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        bad = int(sum(1 for r in rows if r.get("asd") is not None and r["asd"] >= 0.1))
        m_used = int(rows[0].get("n_imputations") or 1) if rows else 1
        stats = (
            f"Covariate balance '{name}': {len(rows)} comparison(s), {bad} with |ASD| ≥ 0.1"
            + (f" (weighted by '{weight_column}')." if _bare(weight_column) else " (unweighted).")
            + (f" Computed inside each of {m_used} imputation draw(s) and averaged."
               if m_used > 1 else "")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 40)}"

    def covariate_balance_multi(
        self,
        treatment_column: str,
        treatment_values: Any,
        covariates: Any,
        scenarios: Any = None,
        where: str = "",
        cat_var: Any = None,
        cont_var: Any = None,
        imputation_column: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Balance for EVERY population in ``scenarios`` — one stacked table.

        The loop version of ``covariate_balance``. Each scenario is
        ``{"label": "...", "weight_column"?: "...", "where"?: "..."}``, so the
        canonical before/after table is one node:
        ``[{"label":"Crude"},{"label":"ATT-weighted","weight_column":"att_weight"}]``.
        Rows carry a ``scenario`` column and the ASD of the FIRST scenario as
        ``asd_reference``, which is what a Table 1 "before vs after" prints.
        """
        import pandas as pd

        if isinstance(scenarios, dict):
            scenarios = [scenarios]
        specs = [s for s in (scenarios or []) if isinstance(s, dict)]
        if not specs:
            return (
                'Error: \'scenarios\' must be a non-empty list, e.g. '
                '[{"label":"Crude"},{"label":"ATT-weighted","weight_column":"att_weight"}].'
            )
        all_rows: List[Dict[str, Any]] = []
        failures: List[str] = []
        reference: Dict[Any, Any] = {}
        for i, spec in enumerate(specs):
            title = str(spec.get("label") or f"scenario {i + 1}")
            rows, err = self._balance_rows(
                treatment_column=treatment_column, treatment_values=treatment_values,
                covariates=covariates,
                weight_column=str(spec.get("weight_column") or ""),
                where=str(spec.get("where") or where or ""), source=source,
                imputation_column=imputation_column,
                cat_var=cat_var, cont_var=cont_var,
            )
            if err:
                failures.append(f"{title}: {err}")
                continue
            for r in rows:
                key = (r["variable"], r["level"])
                if i == 0:
                    reference[key] = r["asd"]
                r["scenario"] = title
                r["asd_reference"] = reference.get(key)
                all_rows.append(r)
        if not all_rows:
            return "Error: no scenario produced a balance table — " + "; ".join(failures)

        lead = ["scenario", "variable", "level", "type", "treated", "control",
                "asd", "asd_reference", "balanced"]
        table = pd.DataFrame(all_rows)
        table = table[[c for c in lead if c in table.columns]
                      + [c for c in table.columns if c not in lead]]
        name = (label or "").strip() or f"covariate_balance_multi_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title="Covariate balance by scenario (ASD before vs after)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        per = {
            s: int(sum(1 for r in all_rows if r["scenario"] == s and (r.get("asd") or 0) >= 0.1))
            for s in dict.fromkeys(r["scenario"] for r in all_rows)
        }
        stats = (
            f"Covariate balance '{name}': "
            + "; ".join(f"{k} → {v} covariate(s) with |ASD| ≥ 0.1" for k, v in per.items())
            + (" Skipped: " + "; ".join(failures) if failures else "")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 40)}"

    # ── unmeasured-confounding / bias analysis ───────────────────────────

    def evalue(
        self,
        estimate: Any,
        ci_lower: Any = None,
        ci_upper: Any = None,
        scale: str = "rr",
        baseline_risk: Any = None,
        rare_outcome: Any = False,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """E-value for ONE effect estimate (VanderWeele & Ding).

        The E-value is the minimum association — on the risk-ratio scale — that
        an unmeasured confounder would need with BOTH the exposure and the
        outcome to explain the estimate away. Reports it for the point estimate
        and for the confidence limit nearest the null (the number that decides
        whether the finding is fragile).

        ``scale``: ``rr`` / ``hr`` (used as-is), ``or`` (√OR unless
        ``rare_outcome``), or ``rd`` — a risk difference, which needs
        ``baseline_risk`` (the control-arm risk) to be put on the ratio scale.
        To sweep a RANGE of confounder strengths instead of a single threshold,
        use ``bias_sensitivity``.
        """
        import pandas as pd

        def _num(v):
            try:
                return None if v is None or str(v).strip() == "" else float(v)
            except (TypeError, ValueError):
                return None

        est, lo, hi = _num(estimate), _num(ci_lower), _num(ci_upper)
        if est is None:
            return "Error: 'estimate' is required (the observed effect estimate)."
        kind = str(scale or "rr").strip().lower()
        rare = str(rare_outcome).strip().lower() in ("true", "1", "yes")

        def _to_rr(v):
            if v is None:
                return None
            if kind in ("rr", "hr"):
                return v
            if kind == "or":
                return v if rare else (v**0.5 if v > 0 else None)
            if kind == "rd":
                base = _num(baseline_risk)
                if base is None or base <= 0:
                    return None
                return (base + v) / base
            return None

        if kind == "rd" and _num(baseline_risk) is None:
            return "Error: scale='rd' needs 'baseline_risk' (the control-arm risk) to form a ratio."
        rr = _to_rr(est)
        if rr is None or rr <= 0:
            return f"Error: cannot put estimate {est} on the risk-ratio scale for scale='{kind}'."
        # The limit that matters is the one closest to the null: if it is on the
        # far side of 1 the CI already includes no effect, and the E-value is 1.
        limits = [x for x in (_to_rr(lo), _to_rr(hi)) if x is not None and x > 0]
        near = min(limits, key=lambda v: abs(v - 1.0)) if limits else None
        ci_ev = 1.0 if (near is not None and ((rr > 1 and near <= 1) or (rr < 1 and near >= 1))) \
            else _evalue_from_ratio(near)

        table = pd.DataFrame([{
            "scale": kind,
            "estimate": round(est, 6),
            "ci_lower": lo, "ci_upper": hi,
            "risk_ratio_scale": round(float(rr), 6),
            "evalue_point": _evalue_from_ratio(rr),
            "evalue_ci": None if ci_ev is None else round(float(ci_ev), 4),
        }])
        name = (label or "").strip() or f"evalue_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="E-value (unmeasured confounding)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"E-value '{name}': an unmeasured confounder would need risk ratios of at least "
            f"{table.loc[0, 'evalue_point']} with both exposure and outcome to explain the "
            f"estimate away ({table.loc[0, 'evalue_ci']} for the confidence limit)."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 5)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 5)}"

    def bias_sensitivity(
        self,
        estimate: Any,
        ci_lower: Any = None,
        ci_upper: Any = None,
        scenarios: Any = None,
        grid: Any = None,
        scale: str = "rr",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Bias-adjust an estimate across a GRID of unmeasured-confounder strengths.

        The loop version of ``evalue``: for each scenario — ``{"label": "...",
        "rr_confounder_outcome": 2.0, "rr_confounder_exposure": 1.5}`` — the
        Ding & VanderWeele bounding factor gives the most the estimate could be
        biased, and the row reports the bias-adjusted estimate and CI plus
        whether the finding survives (``still_significant``). Omit ``scenarios``
        and a symmetric grid is swept instead (``grid`` = the strengths applied to
        both associations), which locates the TIPPING POINT where the CI first
        crosses the null.
        """
        import pandas as pd

        def _num(v):
            try:
                return None if v is None or str(v).strip() == "" else float(v)
            except (TypeError, ValueError):
                return None

        est, lo, hi = _num(estimate), _num(ci_lower), _num(ci_upper)
        if est is None or est <= 0:
            return "Error: 'estimate' must be a positive ratio (RR / OR / HR)."
        if isinstance(scenarios, dict):
            scenarios = [scenarios]
        specs = [s for s in (scenarios or []) if isinstance(s, dict)]
        if not specs:
            if isinstance(grid, (int, float, str)):
                grid = [grid]
            strengths = [_num(g) for g in (grid or [])]
            strengths = [g for g in strengths if g and g >= 1.0]
            if not strengths:
                strengths = [1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
            specs = [
                {"label": f"RR_UD = RR_EU = {g}",
                 "rr_confounder_outcome": g, "rr_confounder_exposure": g}
                for g in strengths
            ]

        protective = est < 1.0

        # Bias moves the estimate TOWARD the null, so an estimate above 1 is
        # divided by the bounding factor and one below 1 is multiplied by it.
        def _adjust(v, bf):
            if v is None or v <= 0:
                return None
            return round(v * bf if protective else v / bf, 6)

        rows: List[Dict[str, Any]] = []
        tipping: Optional[str] = None
        for i, spec in enumerate(specs):
            ud = _num(spec.get("rr_confounder_outcome")) or 1.0
            eu = _num(spec.get("rr_confounder_exposure")) or 1.0
            bf = _bounding_factor(max(ud, 1.0), max(eu, 1.0))
            adj, adj_lo, adj_hi = _adjust(est, bf), _adjust(lo, bf), _adjust(hi, bf)
            limits = [x for x in (adj_lo, adj_hi) if x is not None]
            survives = (
                bool(all(x > 1 for x in limits)) if (limits and not protective)
                else bool(all(x < 1 for x in limits)) if limits
                else None
            )
            row = {
                "scenario": str(spec.get("label") or f"scenario {i + 1}"),
                "rr_confounder_outcome": round(max(ud, 1.0), 4),
                "rr_confounder_exposure": round(max(eu, 1.0), 4),
                "bounding_factor": round(float(bf), 5),
                "adjusted_estimate": adj,
                "adjusted_ci_lower": adj_lo,
                "adjusted_ci_upper": adj_hi,
                "still_significant": survives,
            }
            if survives is False and tipping is None:
                tipping = row["scenario"]
            rows.append(row)

        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"bias_sensitivity_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title="Unmeasured-confounding bias analysis (tipping point)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Bias analysis '{name}' over {len(rows)} scenario(s) "
            f"(observed {round(est, 5)}, E-value {_evalue_from_ratio(est)}): "
            + (f"the finding first loses significance at '{tipping}'."
               if tipping else "no scenario overturns the finding.")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 30)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 30)}"

    # ── cohort QC + missing data (loop tools) ────────────────────────────

    def attrition_table(
        self,
        steps: Any = None,
        distinct_column: str = "",
        where: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """CONSORT-style inclusion/exclusion flow over a LIST of criteria.

        ``steps`` is the loop axis — ``[{"label": "Diagnosed 2010-2019",
        "where": "..."}, {"label": "Known stage", "where": "..."}]`` — and each
        criterion is applied CUMULATIVELY on top of the ones before it, so the
        table reads exactly as the flow diagram does: how many entered, how many
        each rule removed, how many survived. Pass ``distinct_column`` (a patient
        id) to count subjects alongside rows.
        """
        import pandas as pd

        if isinstance(steps, dict):
            steps = [steps]
        items = [s for s in (steps or []) if isinstance(s, dict)]
        if not items:
            return (
                'Error: \'steps\' must be a non-empty list of {"label","where"} objects, '
                'applied cumulatively in order.'
            )
        src = (source or "seer").strip() or "seer"
        dcol = _bare(distinct_column)

        def _count(pred: str):
            sql = "SELECT COUNT(*) AS n"
            if dcol:
                sql += f", COUNT(DISTINCT {_q(dcol)}) AS n_subjects"
            sql += f" FROM {_q(src)}"
            if pred:
                sql += f" WHERE ({pred})"
            row = self.con.execute(sql).fetchone()
            return int(row[0]), (int(row[1]) if dcol else None)

        pred = str(where or "").strip()
        try:
            n, subj = _count(pred)
        except Exception as e:
            return f"Error counting the source cohort: {e}"
        rows: List[Dict[str, Any]] = [{
            "step": 0, "criterion": "Source cohort",
            "expression": pred or f"all rows of {src}",
            "n_before": None, "n_after": n, "n_excluded": None,
            "pct_excluded": None, "n_subjects": subj,
        }]
        for i, spec in enumerate(items, start=1):
            cond = str(spec.get("where") or "").strip()
            title = str(spec.get("label") or f"step {i}")
            if not cond:
                rows.append({"step": i, "criterion": title, "expression": "",
                             "error": "missing 'where'"})
                continue
            pred = f"({pred}) AND ({cond})" if pred else cond
            before = n
            try:
                n, subj = _count(pred)
            except Exception as e:
                rows.append({"step": i, "criterion": title, "expression": cond,
                             "error": str(e)})
                break  # the chain is cumulative — a broken rule invalidates the rest
            rows.append({
                "step": i, "criterion": title, "expression": cond,
                "n_before": before, "n_after": n, "n_excluded": before - n,
                "pct_excluded": round(100.0 * (before - n) / before, 2) if before else None,
                "n_subjects": subj,
            })

        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"attrition_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Cohort attrition (inclusion/exclusion flow)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        start = int(rows[0]["n_after"])
        stats = (
            f"Attrition '{name}': {start:,} → {n:,} after {len(items)} criterion(s) "
            f"({start - n:,} excluded, "
            f"{round(100.0 * (start - n) / start, 1) if start else 0}%)."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 30)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 30)}"

    def data_quality(
        self,
        columns: Any = None,
        date_order: Any = None,
        where: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Missingness + temporal-consistency report over LISTS of checks.

        Two loop axes in one node: ``columns`` gets a missingness / cardinality
        row each, and ``date_order`` gets a violation count each — a rule is
        ``{"earlier": "Diagnosis date", "later": "Treatment date", "label": "..."}``
        and counts the rows where the later field precedes the earlier one.
        Values are compared as dates when both cast, otherwise as numbers, so
        year-only SEER fields work without pre-parsing.
        """
        import pandas as pd

        cols = [_bare(c) for c in (columns or []) if _bare(c)]
        if isinstance(date_order, dict):
            date_order = [date_order]
        rules = [r for r in (date_order or []) if isinstance(r, dict)]
        if not cols and not rules:
            return "Error: pass 'columns' (missingness checks) and/or 'date_order' rules."

        src = (source or "seer").strip() or "seer"
        w = str(where or "").strip()
        tail = f" FROM {_q(src)}" + (f" WHERE ({w})" if w else "")
        rows: List[Dict[str, Any]] = []

        if cols:
            sel = ["COUNT(*) AS _n"]
            for i, c in enumerate(cols):
                blank = f"({_q(c)} IS NULL OR TRIM(CAST({_q(c)} AS VARCHAR)) = '')"
                sel.append(f"SUM(CASE WHEN {blank} THEN 1 ELSE 0 END) AS miss{i}")
                sel.append(f"COUNT(DISTINCT {_q(c)}) AS distinct{i}")
            try:
                probe = self.con.execute(f"SELECT {', '.join(sel)}{tail}").fetchdf().iloc[0]
            except Exception as e:
                return f"Error profiling columns: {e}"
            n = int(probe["_n"] or 0)
            for i, c in enumerate(cols):
                miss = int(probe[f"miss{i}"] or 0)
                rows.append({
                    "check": "missingness", "variable": c, "n": n,
                    "n_flagged": miss,
                    "pct_flagged": round(100.0 * miss / n, 2) if n else None,
                    "n_distinct": int(probe[f"distinct{i}"] or 0),
                    "detail": "null or blank",
                })

        for j, rule in enumerate(rules, start=1):
            a, b = _bare(rule.get("earlier") or ""), _bare(rule.get("later") or "")
            title = str(rule.get("label") or f"{b} before {a}")
            if not a or not b:
                rows.append({"check": "temporal_order", "variable": title,
                             "detail": "rule needs both 'earlier' and 'later'"})
                continue
            da, db = f"TRY_CAST({_q(a)} AS DATE)", f"TRY_CAST({_q(b)} AS DATE)"
            na, nb = f"TRY_CAST({_q(a)} AS DOUBLE)", f"TRY_CAST({_q(b)} AS DOUBLE)"
            comparable = (
                f"CASE WHEN {da} IS NOT NULL AND {db} IS NOT NULL THEN 1 "
                f"WHEN {na} IS NOT NULL AND {nb} IS NOT NULL THEN 1 ELSE 0 END"
            )
            violated = (
                f"CASE WHEN {da} IS NOT NULL AND {db} IS NOT NULL THEN "
                f"(CASE WHEN {db} < {da} THEN 1 ELSE 0 END) "
                f"WHEN {na} IS NOT NULL AND {nb} IS NOT NULL THEN "
                f"(CASE WHEN {nb} < {na} THEN 1 ELSE 0 END) ELSE 0 END"
            )
            try:
                got = self.con.execute(
                    f"SELECT SUM({comparable}) AS cmp, SUM({violated}) AS bad{tail}"
                ).fetchone()
            except Exception as e:
                rows.append({"check": "temporal_order", "variable": title, "detail": str(e)})
                continue
            cmp_n, bad = int(got[0] or 0), int(got[1] or 0)
            rows.append({
                "check": "temporal_order", "variable": title, "n": cmp_n,
                "n_flagged": bad,
                "pct_flagged": round(100.0 * bad / cmp_n, 2) if cmp_n else None,
                "n_distinct": None,
                "detail": f"'{b}' precedes '{a}'",
            })

        table = pd.DataFrame(rows)
        name = (label or "").strip() or f"data_quality_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Data quality (missingness + temporal order)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        worst = max((r for r in rows if r.get("pct_flagged") is not None),
                    key=lambda r: r["pct_flagged"], default=None)
        stats = (
            f"Data quality '{name}': {len(cols)} column(s) profiled, {len(rules)} order rule(s)"
            + (f"; worst is '{worst['variable']}' at {worst['pct_flagged']}% flagged." if worst else ".")
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 40)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 40)}"

    def impute_missing(
        self,
        columns: Any = None,
        method: str = "mice",
        n_imputations: int = 1,
        max_iter: int = 10,
        add_indicator: Any = True,
        where: str = "",
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Fill missing values in ``columns`` and return the completed cohort.

        ``method='mice'`` runs sklearn's chained-equations ``IterativeImputer``
        on the numeric columns (categoricals take the modal level);
        ``'median'`` / ``'mode'`` are the simple single-value fallbacks. Setting
        ``n_imputations`` above 1 is the loop axis: m posterior draws are stacked
        into one table with an ``_imputation`` index (1…m), so a downstream
        analysis can be run per draw and pooled instead of pretending one
        completed dataset carries no imputation uncertainty.

        ``add_indicator`` keeps a ``<column>_missing`` flag per imputed column,
        which the protocol needs to report how much of each variable was filled.
        """
        import numpy as np
        import pandas as pd

        cols = [_bare(c) for c in (columns or []) if _bare(c)]
        if not cols:
            return "Error: 'columns' (the variables to impute) are required."
        how = str(method or "mice").strip().lower()
        if how not in ("mice", "median", "mode"):
            return "Error: 'method' must be \"mice\", \"median\" or \"mode\"."
        try:
            m = max(1, int(n_imputations))
        except (TypeError, ValueError):
            m = 1
        if how != "mice":
            m = 1  # a deterministic fill has nothing to vary across draws
        flags = str(add_indicator).strip().lower() in ("true", "1", "yes")

        src = (source or "seer").strip() or "seer"
        sql = f"SELECT * FROM {_q(src)}"
        w = str(where or "").strip()
        if w:
            sql += f" WHERE ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error reading the cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows)."
        unknown = [c for c in cols if c not in df.columns]
        if unknown:
            return f"Error: column(s) {unknown} are not in this input. Available: {list(df.columns)[:30]}"

        # Blank strings are missing values in SEER exports; normalize them first
        # so the imputer sees NaN rather than a bogus "" category.
        numeric, categorical = [], []
        for c in cols:
            col = df[c].replace(r"^\s*$", np.nan, regex=True) if df[c].dtype == object else df[c]
            df[c] = col
            num = pd.to_numeric(col, errors="coerce")
            (numeric if float(num.notna().mean()) >= 0.8 else categorical).append(c)
        before = {c: int(df[c].isna().sum()) for c in cols}
        # Chained equations condition each variable on the OTHERS; with a single
        # numeric column there is nothing to condition on, so every posterior
        # draw collapses to the same mean fill. Say so rather than handing back m
        # identical copies that look like multiple imputation.
        degenerate = m > 1 and len(numeric) < 2
        indicators = pd.DataFrame(
            {f"{c}_missing": df[c].isna().astype(int) for c in cols}, index=df.index
        ) if flags else None

        copies: List[Any] = []
        if how == "mice" or m > 1:
            _emit_tool_progress(
                f"Impute {how} — {m} draw(s), {len(df):,} rows, "
                f"{len(numeric)} numeric / {len(categorical)} categorical"
            )
        t_imp = time.monotonic()
        for k in range(m):
            if m > 1:
                _emit_tool_progress(f"Impute {how} draw {k + 1}/{m}")
            out = df.copy()
            if numeric:
                num_block = out[numeric].apply(pd.to_numeric, errors="coerce")
                if how == "mice":
                    try:
                        from sklearn.experimental import enable_iterative_imputer  # noqa: F401
                        from sklearn.impute import IterativeImputer

                        imputer = IterativeImputer(
                            max_iter=int(max_iter), sample_posterior=(m > 1),
                            random_state=int(random_state) + k,
                        )
                        filled = imputer.fit_transform(num_block)
                    except Exception as e:
                        logger.warning("[seer] impute: MICE failed (%s) — falling back to median", e)
                        filled = num_block.fillna(num_block.median()).to_numpy()
                else:
                    filled = num_block.fillna(num_block.median()).to_numpy()
                out[numeric] = pd.DataFrame(filled, columns=numeric, index=out.index)
            for c in categorical:
                mode = out[c].dropna()
                out[c] = out[c].fillna(mode.mode().iloc[0] if len(mode.mode()) else "Unknown")
            if indicators is not None:
                out = pd.concat([out, indicators], axis=1)
            if m > 1:
                out["_imputation"] = k + 1
            copies.append(out)
        if how == "mice" or m > 1:
            _emit_tool_progress(f"Impute {how} done ({time.monotonic() - t_imp:.0f}s)")
        result = pd.concat(copies, ignore_index=True) if m > 1 else copies[0]

        name = (label or "").strip() or f"imputed_{self._n + 1}"
        self._materialize_output(name, result)
        parquet_uri = self._export_parquet(name)
        summary = pd.DataFrame([
            {
                "variable": c,
                "type": "numeric" if c in numeric else "categorical",
                "n": len(df),
                "n_missing_before": before[c],
                "pct_missing_before": round(100.0 * before[c] / len(df), 2),
                "n_missing_after": int(result[c].isna().sum()),
                "method": how if c in numeric else "mode",
            }
            for c in cols
        ])
        self._register_deliverable(
            name, summary, len(summary), title="Imputation summary (missingness before/after)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"Imputation '{name}' ({how}, m={m}): {len(cols)} variable(s) filled, "
            f"output has {len(result):,} row(s)"
            + (f" across {m} imputations (column '_imputation')." if m > 1 else ".")
        )
        if degenerate:
            stats += (
                " WARNING: only one numeric column was imputed, so the chained "
                "equations have nothing to condition on and the draws are identical — "
                "add the other numeric variables to 'columns' for real multiple imputation."
            )
        return f"{stats}\nMissingness:\n{_fmt_rows_for_llm(summary, 40)}"

    # --- PROGNOSTIC MODELS (published risk calculators, not fitted here) ------

    def predict_breast_os(
        self,
        age_start: Any = None,
        size: Any = None,
        grade: Any = None,
        nodes: Any = None,
        er: Any = None,
        her2: Any = 9,
        ki67: Any = 9,
        screen: Any = 2,
        generation: Any = 0,
        horm: Any = 0,
        traz: Any = 0,
        bis: Any = 0,
        year: int = 10,
        on_invalid: str = "skip",
        allow_unknown_grade_er_neg: Any = False,
        where: str = "",
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Score EVERY patient in the cohort with PREDICT Breast v2.1 and return
        the cohort with the predictions appended.

        A published prognostic model, not something fitted on this cohort: the
        coefficients are fixed (see ``tool/predict_breast.py``, ported from CRAN
        ``nhs.predict`` 1.4.0 and pinned to it by golden-case tests).

        What it writes is ``year``-year survival WITH SURGERY ALONE — the
        untreated baseline, which does not move when the therapy flags move —
        plus the INCREMENTAL benefit of each therapy added in the model's order:
        hormone, then chemotherapy, then trastuzumab, then bisphosphonate. The
        four benefits sum to the total gain over surgery alone, none of them is a
        standalone effect, and each is exactly zero unless its flag says the
        therapy was given.

        Every model variable is bound either to a cohort column or to a constant,
        and which of the two happened is reported for all twelve — a cohort with
        no bisphosphonate column is normal, but a constant must never pass for
        data. Patients outside the model's domain are NOT dropped silently: they
        keep a reason in ``predict_ineligible`` and come back with NaN
        predictions, counted per reason in the summary.
        """
        import pandas as pd

        try:
            from tool import predict_breast as pbm
        except ImportError:  # bare-path fallback (agent_core_python on sys.path)
            import predict_breast as pbm  # type: ignore

        try:
            horizon = int(year)
        except (TypeError, ValueError):
            return f"Error: 'year' must be an integer 1-{pbm.MAX_YEAR}, got {year!r}."
        if not 1 <= horizon <= pbm.MAX_YEAR:
            return (f"Error: 'year' must be between 1 and {pbm.MAX_YEAR} "
                    f"(the model's horizon), got {horizon}.")
        mode = str(on_invalid or "skip").strip().lower()
        if mode not in ("skip", "fail"):
            return "Error: 'on_invalid' must be \"skip\" or \"fail\"."
        allow_unknown = str(allow_unknown_grade_er_neg).strip().lower() in (
            "true", "1", "yes"
        )

        src = (source or "seer").strip() or "seer"
        sql = f"SELECT * FROM {_q(src)}"
        w = str(where or "").strip()
        if w:
            sql += f" WHERE ({w})"
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error reading the cohort: {e}"
        if len(df) == 0:
            return "Cohort is empty after filtering (0 rows)."

        out_cols = {m: f"predict_{m}_{horizon}y" for m in pbm.METRICS}
        clash = [c for c in (*out_cols.values(), "predict_ineligible")
                 if c in df.columns]
        if clash:
            return (f"Error: column(s) {clash} already exist in this input — "
                    f"scoring would overwrite them. Use a different 'year', or "
                    f"drop them in an upstream sql node.")

        bound = {
            "age_start": age_start, "size": size, "grade": grade, "nodes": nodes,
            "er": er, "her2": her2, "ki67": ki67, "screen": screen,
            "generation": generation, "horm": horm, "traz": traz, "bis": bis,
        }
        try:
            values, binding = pbm.resolve_bindings(df, bound)
        except pbm.PredictInputError as e:
            return f"Error: {e}"

        reason = pbm.eligibility(values, allow_unknown_grade_er_neg=allow_unknown)
        n_bad = int((reason != "").sum())
        reasons = pbm.reason_counts(reason)
        if n_bad and mode == "fail":
            return (
                f"Error: {n_bad:,} of {len(df):,} patient(s) fall outside the "
                f"PREDICT v2.1 domain and 'on_invalid' is \"fail\".\n"
                f"{_fmt_rows_for_llm(reasons, 20)}"
            )
        if n_bad == len(df):
            return (
                f"Error: no patient could be scored — all {len(df):,} row(s) are "
                f"outside the PREDICT v2.1 domain. The model needs age 25-85, "
                f"size in mm, grade 1/2/3/9, node count, and ER coded 0/1; recode "
                f"them in an upstream sql node.\n{_fmt_rows_for_llm(reasons, 20)}"
            )

        n_ok = len(df) - n_bad
        _emit_tool_progress(
            f"PREDICT Breast v2.1 — {n_ok:,} of {len(df):,} patient(s), "
            f"{horizon}-year horizon"
        )
        t0 = time.monotonic()
        scored = pbm.predict_os_frame(
            values, year=horizon, reason=reason, progress=_emit_tool_progress,
        )
        _emit_tool_progress(
            f"PREDICT Breast v2.1 done ({time.monotonic() - t0:.0f}s)"
        )

        result = df.copy()
        for metric, col in out_cols.items():
            result[col] = scored[metric]
        result["predict_ineligible"] = [str(r) for r in reason]

        name = (label or "").strip() or f"predict_breast_{self._n + 1}"
        self._materialize_output(name, result)
        parquet_uri = self._export_parquet(name)

        # Every row carries the cohort flow, so the exclusion count is readable
        # off the table itself and a defaulted variable cannot pass unnoticed.
        defaulted = [
            f"{b['variable']}={b['value']}" for b in binding
            if b["bound_to"] in ("constant", "default")
        ]
        flow = {
            "n_rows": len(df),
            "n_scored": n_ok,
            "n_ineligible": n_bad,
            "ineligible_reasons": "; ".join(
                f"{r.reason} (n={r.n_rows})" for r in reasons.itertuples()
            ) or "none",
            "fixed_values": "; ".join(defaulted) or "none",
        }
        rows = []
        for metric, col in out_cols.items():
            s = pd.to_numeric(result[col], errors="coerce").dropna()
            rows.append({
                "metric": col,
                "unit": "% surviving" if metric == "os" else "percentage points",
                **flow,
                "mean": round(float(s.mean()), 2) if len(s) else None,
                "sd": round(float(s.std(ddof=1)), 2) if len(s) > 1 else None,
                "median": round(float(s.median()), 2) if len(s) else None,
                "p25": round(float(s.quantile(0.25)), 2) if len(s) else None,
                "p75": round(float(s.quantile(0.75)), 2) if len(s) else None,
                "min": round(float(s.min()), 2) if len(s) else None,
                "max": round(float(s.max()), 2) if len(s) else None,
            })
        summary = pd.DataFrame(rows)
        self._register_deliverable(
            name, summary, len(summary),
            title=f"PREDICT Breast v2.1 — {horizon}-year survival and therapy benefit",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )

        bind_txt = ", ".join(
            f"{b['variable']}←{b['value']}"
            + (" [fixed]" if b["bound_to"] in ("constant", "default") else "")
            for b in binding
        )
        stats = (
            f"PREDICT Breast v2.1 '{name}': scored {n_ok:,} of {len(df):,} "
            f"patient(s) at {horizon} years"
            + (f", {n_bad:,} left unscored." if n_bad else ".")
        )
        note = (
            f" '{out_cols['os']}' is survival with SURGERY ALONE, not survival "
            "under treatment; add the benefits to it for that. The four benefits "
            "are INCREMENTAL in the order hormone → chemo → trastuzumab → "
            "bisphosphonate, and each is zero unless its flag says the therapy was "
            "given — report them as added gains, never as independent effects. "
            "Label results as v2.1: it is not the version on breast.predict.nhs.uk."
        )
        parts = [stats + note, f"Bindings: {bind_txt}"]
        if n_bad:
            parts.append(f"Unscored:\n{_fmt_rows_for_llm(reasons, 20)}")
        parts.append(f"Predictions:\n{_fmt_rows_for_llm(summary, 10)}")
        return "\n".join(parts)

    def _sklearn_any_estimator(
        self,
        model: str,
        *,
        random_state: int = 42,
        l1_ratio: float = 0.5,
        cv_folds: int = 10,
        n_estimators: int = 500,
        max_depth: int = 3,
        learning_rate: float = 0.1,
        class_weight: Any = None,
        C: float = 1.0,
        max_iter: int = 2000,
        nu: float = 0.5,
        kernel: str = "rbf",
        n_neighbors: int = 5,
        penalty: str = "l2",
        alpha: float = 1.0,
        loss: str = "hinge",
        min_samples_leaf: int = 20,
        max_leaf_nodes: int = 31,
        l2_regularization: float = 0.0,
        n_iter_no_change: int = 10,
        average: bool = False,
    ):
        """Resolve a CV/compare model key: catalog class name or legacy alias."""
        key = str(model or "").strip()
        if key in _SKLEARN_CATALOG:
            return _sklearn_catalog_estimator(
                key,
                random_state=random_state,
                l1_ratio=l1_ratio,
                cv_folds=cv_folds,
                n_estimators=n_estimators,
                max_depth=max_depth,
                learning_rate=learning_rate,
                class_weight=class_weight,
                C=C,
                max_iter=max_iter,
                nu=nu,
                kernel=kernel,
                n_neighbors=n_neighbors,
                penalty=penalty,
                alpha=alpha,
                loss=loss,
                min_samples_leaf=min_samples_leaf,
                max_leaf_nodes=max_leaf_nodes,
                l2_regularization=l2_regularization,
                n_iter_no_change=n_iter_no_change,
                average=average,
            )
        return _sklearn_estimator(
            key,
            random_state=random_state,
            l1_ratio=l1_ratio,
            cv_folds=cv_folds,
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            class_weight=class_weight,
        )

    def _ml_load_table(
        self,
        source: str,
        *,
        where: str = "",
        split_column: str = "",
        split_value: str = "test",
    ):
        """Load an upstream parquet/view. Never fits. Error string on failure."""
        src = (source or "seer").strip() or "seer"
        sql = f"SELECT * FROM {_q(src)}"
        clauses: List[str] = []
        w = (where or "").strip()
        if w:
            clauses.append(f"({w})")
        sc = str(split_column or "").strip()
        sv = str(split_value or "test").strip() or "test"
        if sc:
            esc = sv.replace("'", "''")
            clauses.append(f"LOWER(CAST({_q(sc)} AS VARCHAR)) = LOWER('{esc}')")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" LIMIT {_MODEL_MAX_ROWS}"
        try:
            df = self.con.execute(sql).fetchdf()
        except Exception as e:
            return f"Error reading '{src}': {e}"
        if df is None or df.empty:
            extra = f" with {sc}={sv!r}" if sc else ""
            return f"No rows in '{src}'{extra} after filters."
        return df

    @staticmethod
    def _ml_binary_y(series, outcome_values: Any):
        """1 if the cell is in ``outcome_values`` (string-compared), else 0."""
        import pandas as pd

        if isinstance(outcome_values, str):
            outcome_values = [outcome_values]
        positives = {str(v) for v in (outcome_values or [])}
        if not positives:
            return None, 'Error: \'outcome_values\' must list the positive-class value(s).'
        y = series.map(lambda v: pd.NA if pd.isna(v) else int(str(v) in positives))
        return y, None

    def _ml_read_scores(
        self,
        *,
        outcome_column: str,
        outcome_values: Any,
        source: str,
        where: str = "",
        probability_column: str = "predicted_probability",
        score_column: str = "predicted_score",
        split_column: str = "",
        split_value: str = "test",
        require_probability: bool = False,
    ):
        """Read y and predicted scores from an already-scored dataset. Never fits."""
        import pandas as pd

        oc = str(outcome_column or "").strip()
        if not oc:
            return "Error: 'outcome_column' is required."
        df = self._ml_load_table(
            source, where=where, split_column=split_column, split_value=split_value,
        )
        if isinstance(df, str):
            return df
        if oc not in df.columns:
            return f"outcome_column '{oc}' is not in the scored dataset."
        yser, yerr = self._ml_binary_y(df[oc], outcome_values)
        if yerr:
            return yerr
        pcol = str(probability_column or "predicted_probability").strip() or "predicted_probability"
        scol = str(score_column or "predicted_score").strip() or "predicted_score"
        used = pcol if pcol in df.columns else (scol if scol in df.columns else "")
        if not used:
            return (
                f"No score column '{pcol}' or '{scol}'. Fit a model tool first "
                f"(LogisticRegression, RandomForestClassifier, …) so the dataset "
                f"carries predicted_probability."
            )
        if require_probability and used != pcol:
            return (
                f"'{pcol}' is missing. Calibration / decision-curve / Brier need "
                f"predicted probabilities from an upstream model tool, not a "
                f"decision score alone."
            )
        scores = pd.to_numeric(df[used], errors="coerce")
        ok = scores.notna() & yser.notna()
        y = yser.loc[ok].astype(int).to_numpy()
        p = scores.loc[ok].astype(float).to_numpy()
        if len(y) < 8:
            return f"Need ≥8 scored rows with a known outcome; got {len(y)}."
        if int(y.sum()) == 0 or int(y.sum()) == len(y):
            return "Outcome has only one class after filtering scored rows."
        sc = str(split_column or "").strip()
        return y, p, {
            "n": int(len(y)),
            "n_event": int(y.sum()),
            "score_column": used,
            "is_probability": used == pcol,
            "split_column": sc,
            "split_value": (str(split_value or "test").strip() or "test") if sc else "",
        }

    # ── prediction: scoring + cross-validated performance ────────────────

    def ml_predict(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        model: str = "elasticnet_logistic",
        predict_source: str = "",
        predict_where: str = "",
        probability_column: str = "predicted_probability",
        threshold: Any = None,
        where: str = "",
        reference_levels: Any = None,
        l1_ratio: float = 0.5,
        cv_folds: int = 10,
        n_estimators: int = 500,
        max_depth: int = 3,
        learning_rate: float = 0.1,
        class_weight: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Unregistered. Model tools already write predicted_probability on the training cohort.

        Fit a classifier on one cohort and SCORE a cohort, per patient.

        The other ``ml_*`` tools return model-level tables; this one returns a
        DATASET — the scored cohort with a ``predicted_probability`` column (plus
        ``predicted_class`` when ``threshold`` is given) — which is what a risk
        score has to produce before it can be grouped, compared or plotted.

        The model is fitted on ``source`` (this node's first input, optionally
        narrowed by ``where``) and applied to ``predict_source``; leave that
        empty to score the same cohort, or name an earlier dataset (e.g. the
        holdout, or an external validation table) to score that instead. Rows
        whose predictors are incomplete keep every column and get a NULL
        probability rather than being silently dropped.
        """
        import numpy as np
        import pandas as pd

        res = self._ml_fit_frame(
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            source=source,
        )
        if isinstance(res, str):
            return res
        X, y, features = res
        try:
            est, _kind = _sklearn_estimator(
                model, random_state=random_state, l1_ratio=l1_ratio, cv_folds=cv_folds,
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate,
                class_weight=self._ml_class_weight(class_weight),
            )
        except ValueError as e:
            return str(e)
        try:
            est.fit(X, y)
        except Exception as e:
            return f"Error fitting {model}: {e}"

        covs = [str(c) for c in (predictors or []) if str(c).strip()]
        refs, rerr = _reference_map(reference_levels, covs)
        if rerr:
            return rerr
        target = _bare(predict_source) or ((source or "seer").strip() or "seer")
        pw = str(predict_where or "").strip()
        base = (
            f"(SELECT *, ROW_NUMBER() OVER () AS _pred_id FROM {_q(target)}"
            + (f" WHERE ({pw})" if pw else "")
            + ")"
        )
        work = f"_pred_work_{abs(hash((target, pw))) % 10_000_000}"
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(work)} AS SELECT * FROM {base}")
        except Exception as e:
            return f"Error reading the scoring cohort '{target}': {e}"

        cov_map: Dict[str, str] = {}
        sel = ["_pred_id"]
        for i, c in enumerate(covs):
            alias = f"x{i}"
            cov_map[alias] = c
            sel.append(f"{_q(c)} AS {alias}")
        try:
            sdf = self.con.execute(
                f"SELECT {', '.join(sel)} FROM {_q(work)} LIMIT {_MODEL_MAX_ROWS}"
            ).fetchdf()
        except Exception as e:
            self._drop_relation(work)
            return f"Error reading predictors from '{target}': {e}"
        try:
            Xs, _feats = _design_matrix(sdf, list(cov_map.keys()), cov_map, refs)
        except ValueError as e:
            self._drop_relation(work)
            return str(e)
        # Align the scoring design to the TRAINING features: a level absent from
        # the scoring data must still contribute its (zero) column, and a level
        # the model never saw folds into the reference rather than shifting the
        # matrix and producing predictions for the wrong coefficients.
        Xs = Xs.reindex(columns=features, fill_value=0.0).astype(float)
        valid = Xs.notna().all(axis=1).to_numpy()
        proba = np.full(len(sdf), np.nan, dtype=float)
        if valid.any():
            try:
                proba[valid] = _ml_predict_proba(est, Xs[valid])
            except Exception as e:
                self._drop_relation(work)
                return f"Error scoring '{target}': {e}"

        pcol = _bare(probability_column) or "predicted_probability"
        scored = pd.DataFrame({"_pred_id": sdf["_pred_id"].to_numpy(), pcol: proba})
        cut = None
        if threshold is not None and str(threshold).strip() != "":
            try:
                cut = float(threshold)
            except (TypeError, ValueError):
                cut = None
        if cut is not None:
            scored["predicted_class"] = np.where(
                np.isnan(proba), None, (proba >= cut).astype(int)
            )

        name = (label or "").strip() or f"ml_predictions_{self._n + 1}"
        tmp = f"_pred_{abs(hash(name)) % 10_000_000}"
        extra = f", p.{_q(pcol)}" + (", p.predicted_class" if cut is not None else "")
        try:
            self.con.register(tmp, scored)
            self.con.execute(
                f"CREATE OR REPLACE TABLE {_q(name)} AS "
                f"SELECT c.* EXCLUDE (_pred_id){extra} "
                f"FROM {_q(work)} c LEFT JOIN {tmp} p USING (_pred_id)"
            )
            self._materialized_outputs.add(name)
            n_out = int(self.con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0])
        except Exception as e:
            return f"Error materializing the scored cohort: {e}"
        finally:
            try:
                self.con.unregister(tmp)
            except Exception:
                pass
            self._drop_relation(work)

        finite = proba[np.isfinite(proba)]
        summary = pd.DataFrame([{
            "model": _ML_MODELS.get(model, model),
            "n_train": int(len(y)),
            "n_scored": int(valid.sum()),
            "n_unscored": int(len(sdf) - valid.sum()),
            "prob_min": round(float(finite.min()), 5) if finite.size else None,
            "prob_median": round(float(np.median(finite)), 5) if finite.size else None,
            "prob_max": round(float(finite.max()), 5) if finite.size else None,
            "threshold": cut,
        }])
        self._register_deliverable(
            name, summary, len(summary), title="Predicted risk (scoring summary)"
        )
        stats = (
            f"Scored '{target}' with {_ML_MODELS.get(model, model)} → '{name}': "
            f"{n_out:,} row(s), {int(valid.sum()):,} with a probability in '{pcol}'"
            + (f" (class cut at {cut})." if cut is not None else ".")
        )
        return f"{stats}\n{_fmt_rows_for_llm(summary, 5)}"

    def _ml_oof_metrics(
        self,
        X,
        y,
        *,
        model: str,
        n_splits: int,
        random_state: int,
        l1_ratio: float,
        cv_folds: int,
        n_estimators: int,
        max_depth: int,
        learning_rate: float,
        class_weight: Any,
    ) -> Dict[str, Any]:
        """Out-of-fold discrimination + calibration for one model.

        Cross-validated rather than apparent: every patient is scored by a model
        that never saw them, which is the only version of these numbers that
        transfers to a new patient. Returns a row (with ``error`` on failure).
        """
        import numpy as np
        from sklearn.metrics import brier_score_loss, roc_auc_score
        from sklearn.model_selection import StratifiedKFold

        row: Dict[str, Any] = {"model": model, "model_name": _ML_MODELS.get(model, model)}
        try:
            folds = max(2, int(n_splits))
        except (TypeError, ValueError):
            folds = 5
        try:
            oof = np.full(len(y), np.nan, dtype=float)
            skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=int(random_state))
            ya = np.asarray(y).astype(int)
            Xa = np.asarray(X, dtype=float)
            for train_i, test_i in skf.split(Xa, ya):
                est, _kind = self._sklearn_any_estimator(
                    model, random_state=random_state, l1_ratio=l1_ratio, cv_folds=cv_folds,
                    n_estimators=n_estimators, max_depth=max_depth,
                    learning_rate=learning_rate, class_weight=class_weight,
                )
                est.fit(Xa[train_i], ya[train_i])
                oof[test_i] = _ml_predict_proba(est, Xa[test_i])
        except Exception as e:
            row["error"] = str(e)
            return row

        ok = np.isfinite(oof)
        yv, pv = ya[ok], np.clip(oof[ok], 1e-6, 1 - 1e-6)
        row["n"] = int(ok.sum())
        row["n_events"] = int((yv == 1).sum())
        row["folds"] = folds
        try:
            row["auc"] = round(float(roc_auc_score(yv, pv)), 4)
        except Exception:
            row["auc"] = None
        try:
            row["brier"] = round(float(brier_score_loss(yv, pv)), 5)
        except Exception:
            row["brier"] = None
        # Calibration: intercept + slope of the logistic recalibration of the
        # linear predictor. Slope < 1 means the predictions are over-dispersed.
        lp = np.log(pv / (1 - pv)).reshape(-1, 1)
        row["calibration_intercept"] = row["calibration_slope"] = None
        try:
            import statsmodels.api as sm

            fit = sm.Logit(yv, sm.add_constant(lp.ravel(), has_constant="add")).fit(disp=0)
            row["calibration_intercept"] = round(float(fit.params[0]), 4)
            row["calibration_slope"] = round(float(fit.params[1]), 4)
        except Exception:
            # statsmodels is optional here — an unpenalized sklearn fit gives the
            # same two numbers, and a missing calibration slope would quietly
            # remove the one metric that says whether the risks are usable.
            try:
                from sklearn.linear_model import LogisticRegression

                fit = LogisticRegression(C=1e6, solver="lbfgs", max_iter=2000).fit(lp, yv)
                row["calibration_intercept"] = round(float(fit.intercept_[0]), 4)
                row["calibration_slope"] = round(float(fit.coef_.ravel()[0]), 4)
            except Exception:
                pass
        row["citl"] = round(float(yv.mean() - pv.mean()), 5)
        try:
            cut = _ml_youden_threshold(yv, pv)
            row.update(_ml_threshold_metrics(yv, pv, cut))
        except Exception:
            pass
        return row

    def ml_cv_performance(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        model: str = "elasticnet_logistic",
        n_splits: int = 5,
        where: str = "",
        reference_levels: Any = None,
        l1_ratio: float = 0.5,
        cv_folds: int = 10,
        n_estimators: int = 500,
        max_depth: int = 3,
        learning_rate: float = 0.1,
        class_weight: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """K-fold OUT-OF-FOLD performance of ONE model (discrimination + calibration).

        Reports AUC, Brier score, calibration-in-the-large, calibration
        intercept/slope and the sensitivity/specificity/PPV/NPV at Youden's cut,
        all from predictions made on held-out folds. This is a learning
        procedure: it refits ``model`` each fold. It is not "evaluate an already
        fitted model" — that is :meth:`ml_classifier_performance` on a scored
        dataset. To compare SEVERAL specs on the same folds, use
        ``ml_compare``.
        """
        import pandas as pd

        if not _ml_is_known_model(model):
            return f"Unknown model '{model}'. Choose one of {_ml_known_model_keys()}."
        res = self._ml_fit_frame(
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            source=source,
        )
        if isinstance(res, str):
            return res
        X, y, features = res
        _emit_tool_progress(f"ML CV {model} ({n_splits}-fold, n={len(y):,})")
        t0 = time.monotonic()
        row = self._ml_oof_metrics(
            X, y, model=model, n_splits=n_splits, random_state=random_state,
            l1_ratio=l1_ratio, cv_folds=cv_folds, n_estimators=n_estimators,
            max_depth=max_depth, learning_rate=learning_rate,
            class_weight=self._ml_class_weight(class_weight),
        )
        _emit_tool_progress(f"ML CV {model} done ({time.monotonic() - t0:.0f}s)")
        if row.get("error"):
            return f"Error cross-validating {model}: {row['error']}"
        row["n_features"] = len(features)
        table = pd.DataFrame([row])

        name = (label or "").strip() or f"ml_cv_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table),
            title=f"{_ML_MODELS.get(model, model)} — {row['folds']}-fold cross-validated performance",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        stats = (
            f"{_ML_MODELS.get(model, model)} '{name}': {row['folds']}-fold OOF AUC="
            f"{row.get('auc')}, Brier={row.get('brier')}, calibration slope="
            f"{row.get('calibration_slope')} on n={row.get('n'):,}."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 5)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 5)}"

    def ml_compare(
        self,
        outcome_column: str,
        outcome_values: Any,
        predictors: Any,
        models: Any = None,
        n_splits: int = 5,
        where: str = "",
        reference_levels: Any = None,
        l1_ratio: float = 0.5,
        cv_folds: int = 10,
        n_estimators: int = 500,
        max_depth: int = 3,
        learning_rate: float = 0.1,
        class_weight: Any = None,
        random_state: int = 42,
        label: str = "",
        source: str = "seer",
    ) -> str:
        """Cross-validate EVERY model in ``models`` on ONE cohort — one table.

        The loop version of ``ml_cv_performance``: the design matrix is built
        once and each algorithm is scored on the SAME folds, so the AUC / Brier /
        calibration comparison is like-for-like rather than an artefact of
        different splits. Rows are sorted by AUC and carry ``rank``, which is the
        model-selection table the protocol asks for.
        """
        import pandas as pd

        if isinstance(models, str):
            models = [models]
        wanted = [str(m).strip() for m in (models or []) if str(m).strip()]
        if not wanted:
            wanted = [
                "LogisticRegressionCV",
                "RandomForestClassifier",
                "GradientBoostingClassifier",
            ]
        unknown = [m for m in wanted if not _ml_is_known_model(m)]
        if unknown:
            return f"Unknown model(s) {unknown}. Choose from {_ml_known_model_keys()}."

        res = self._ml_fit_frame(
            outcome_column=outcome_column, outcome_values=outcome_values,
            predictors=predictors, where=where, reference_levels=reference_levels,
            source=source,
        )
        if isinstance(res, str):
            return res
        X, y, features = res

        rows: List[Dict[str, Any]] = []
        n_models = len(wanted)
        for i, m in enumerate(wanted, start=1):
            _emit_tool_progress(f"ML compare {i}/{n_models} {m} (cv={n_splits})")
            t0 = time.monotonic()
            row = self._ml_oof_metrics(
                X, y, model=m, n_splits=n_splits, random_state=random_state,
                l1_ratio=l1_ratio, cv_folds=cv_folds, n_estimators=n_estimators,
                max_depth=max_depth, learning_rate=learning_rate,
                class_weight=self._ml_class_weight(class_weight),
            )
            _emit_tool_progress(
                f"ML compare {i}/{n_models} {m} done ({time.monotonic() - t0:.0f}s)"
            )
            row["n_features"] = len(features)
            rows.append(row)
        scored = [r for r in rows if r.get("auc") is not None]
        if not scored:
            return (
                "Error: no model could be cross-validated — "
                + "; ".join(f"{r['model']}: {r.get('error')}" for r in rows)
            )
        scored.sort(key=lambda r: r["auc"], reverse=True)
        for i, r in enumerate(scored, start=1):
            r["rank"] = i
        table = pd.DataFrame(scored + [r for r in rows if r.get("auc") is None])
        lead = ["rank", "model", "model_name", "n", "n_events", "folds", "auc", "brier",
                "calibration_slope", "calibration_intercept", "citl"]
        table = table[[c for c in lead if c in table.columns]
                      + [c for c in table.columns if c not in lead]]

        name = (label or "").strip() or f"ml_compare_{self._n + 1}"
        self._materialize_output(name, table)
        parquet_uri = self._export_parquet(name)
        self._register_deliverable(
            name, table, len(table), title="Model comparison (cross-validated)",
            storage_path=parquet_uri, parquet_uri=parquet_uri,
        )
        best = scored[0]
        stats = (
            f"Model comparison '{name}': {len(scored)}/{len(rows)} model(s) cross-validated on "
            f"n={best.get('n'):,}; best is {best['model_name']} (AUC={best['auc']}, "
            f"Brier={best.get('brier')})."
        )
        if parquet_uri:
            return f"{parquet_uri}\n{stats}\n{_fmt_rows_for_llm(table, 20)}"
        return f"{stats}\n{_fmt_rows_for_llm(table, 20)}"

    # ── deliverable bookkeeping ─────────────────────────────────────────
    def _register_deliverable(self, name: str, df, total: int, **extra: Any) -> Dict[str, Any]:
        self._n += 1
        # De-dupe by name: last write wins.
        self.deliverables = [d for d in self.deliverables if d.get("name") != name]
        deliverable = _df_to_deliverable(name, df, total)
        deliverable.setdefault("kind", "table")
        deliverable.update(extra)
        self.deliverables.append(deliverable)
        return deliverable

    def _materialize_output(self, out_name: str, df) -> None:
        """Register the FULL result table as a queryable DuckDB relation named
        ``out_name`` so downstream nodes can consume it and it is persisted +
        profiled like any dataset (not truncated to a 200-row preview)."""
        import pandas as pd

        name = (out_name or "").strip()
        if not name:
            return
        frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        tmp = f"_mat_{abs(hash(name)) % 10_000_000}"
        self.con.register(tmp, frame)
        try:
            self.con.execute(f"CREATE OR REPLACE TABLE {_q(name)} AS SELECT * FROM {tmp}")
            self._materialized_outputs.add(name)
        finally:
            try:
                self.con.unregister(tmp)
            except Exception:
                pass

    def _export_parquet(self, name: str) -> Optional[str]:
        """Write the materialized relation ``name`` to S3 as a single Parquet
        file and return its ``s3://`` URI (SEER-template parquet-out contract).

        Used by frozen tools whose canonical output IS a parquet artifact (e.g.
        ``mann_whitney_u``): the tool writes the parquet itself and returns the
        path, and the graph's persist layer reuses this URI instead of copying
        the relation a second time. Best-effort — returns None on any failure so
        the tool still surfaces its table deliverable. Path mirrors
        :func:`persist_step_output`:
        ``s3://<seer-bucket>/seer_outputs/<user>/<note>/<name>_<ts>.parquet``.
        """
        import time as _time

        from utils.storage.bucket import parse_s3_uri

        rel = (name or "").strip()
        if not rel:
            return None
        if getattr(self, "_suppress_export", False):
            return None
        try:
            bucket, _ = parse_s3_uri(seer_db_uri())
        except Exception:
            bucket = None
        if not bucket:
            logger.warning("[seer] export '%s': no S3 bucket resolved; parquet write skipped.", rel)
            return None
        key = f"seer_outputs/{self.user_id}/{self.note_id}/{rel}_{int(_time.time())}.parquet"
        try:
            uri = _copy_relation_to_s3(
                self.con, rel, key, bucket=bucket, fmt="parquet"
            )
            if not uri:
                logger.warning("[seer] export '%s': S3 upload returned no URI", rel)
                return None
            logger.info("[seer] export '%s' → %s", rel, uri)
            return uri
        except Exception as e:
            logger.warning("[seer] export '%s' parquet write failed: %s", rel, e)
            return None

    def _drop_relation(self, name: str) -> None:
        """Best-effort drop of a scratch table/view (idempotent)."""
        if not name:
            return
        for kind in ("TABLE", "VIEW"):
            try:
                self.con.execute(f"DROP {kind} IF EXISTS {_q(name)}")
            except Exception:
                pass

    def _render_km_png(self, km_df, name: str, title: str) -> Optional[Dict[str, str]]:
        """Render the KM life-table as a step survival curve PNG, upload it to
        S3, and return {image_uri, image_url}. Best-effort — returns None on
        any failure so the table deliverable still surfaces.
        """
        try:
            import io
            import time as _time

            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=140)
            has_group = "group" in km_df.columns
            groups = list(km_df["group"].unique()) if has_group else [None]
            for g in groups:
                sub = km_df[km_df["group"] == g] if has_group else km_df
                sub = sub.sort_values("time_months")
                lbl = str(g) if has_group else "overall"
                ax.step(
                    sub["time_months"], sub["survival_probability"],
                    where="post", linewidth=1.8, label=lbl,
                )
                if "ci_lower" in sub.columns and "ci_upper" in sub.columns:
                    ax.fill_between(
                        sub["time_months"], sub["ci_lower"], sub["ci_upper"],
                        step="post", alpha=0.15, linewidth=0,
                    )
            ax.set_xlabel("Months since diagnosis")
            ax.set_ylabel("Survival probability")
            ax.set_ylim(0, 1.02)
            ax.set_title(title or "Kaplan-Meier survival")
            ax.grid(True, alpha=0.25)
            if has_group:
                ax.legend(loc="best", fontsize=8, frameon=False)
            fig.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            data = buf.getvalue()

            from utils.storage.bucket import (
                generate_presigned_url_from_uri,
                parse_s3_uri,
                upload_bytes,
            )

            bucket = None
            try:
                bucket, _ = parse_s3_uri(self.parquet_uri)
            except Exception:
                bucket = None
            key = f"seer_figures/{self.user_id}/{self.note_id}/{name}_{int(_time.time())}.png"
            uri = upload_bytes(data, key, bucket=bucket, content_type="image/png")
            url = generate_presigned_url_from_uri(uri, expires_in=86400)
            return {"image_uri": uri, "image_url": url}
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] KM figure render/upload failed: %s", e)
            return None

    def _render_mpl_png(self, fig, name: str) -> Optional[Dict[str, str]]:
        """Rasterize a matplotlib Figure to PNG, upload it to S3, and return
        {image_uri, image_url}. Best-effort — returns None on any failure so the
        parquet/table deliverable still surfaces. Mirrors :meth:`_render_km_png`.
        """
        try:
            import io
            import time as _time

            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=140)
            data = buf.getvalue()
            try:
                import matplotlib.pyplot as plt

                plt.close(fig)
            except Exception:
                pass
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] matplotlib PNG render failed: %s", e)
            return None
        try:
            from utils.storage.bucket import (
                generate_presigned_url_from_uri,
                parse_s3_uri,
                upload_bytes,
            )

            bucket = None
            try:
                bucket, _ = parse_s3_uri(self.parquet_uri)
            except Exception:
                bucket = None
            key = f"seer_figures/{self.user_id}/{self.note_id}/{name}_{int(_time.time())}.png"
            uri = upload_bytes(data, key, bucket=bucket, content_type="image/png")
            url = generate_presigned_url_from_uri(uri, expires_in=86400)
            return {"image_uri": uri, "image_url": url}
        except Exception as e:  # pragma: no cover
            logger.warning("[seer] matplotlib PNG upload failed: %s", e)
            return None

    # ── provider-neutral tool specs ─────────────────────────────────────
    def specs(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "basic_glm",
                "description": "Basic Gaussian, Bernoulli or Poisson GLM with explicit input validation.",
                "parameters": {
                    "type": "object",
                    "required": ["outcome_column", "covariates"],
                    "properties": {
                        "outcome_column": {"type": "string"},
                        "covariates": {"type": "array", "items": {"type": "string"}},
                        "family": {"type": "string", "enum": ["gaussian", "binomial", "poisson"]},
                        "categorical": {"type": "array", "items": {"type": "string"}},
                        "reference_levels": {"type": "object"},
                        "missing": {"type": "string", "enum": ["raise", "drop"]},
                        "max_iter": {"type": "integer", "minimum": 1},
                        "tolerance": {"type": "number", "exclusiveMinimum": 0},
                        "where": {"type": "string"},
                        "source": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "invoke": self.basic_glm,
            },
            {
                "name": "seer_schema",
                "description": (
                    "List SEER columns (name + type). Pass a keyword to filter "
                    "(e.g. 'ER', 'HER2', 'subtype', 'survival'). Call this FIRST "
                    "to find exact column names — they contain spaces and must be "
                    "double-quoted in SQL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "Substring to filter columns (optional)."}
                    },
                },
                "invoke": self.seer_schema,
            },
            {
                "name": "seer_value_counts",
                "description": (
                    "Show the distinct values (with counts) of a column. Use this "
                    "to discover exact category labels BEFORE filtering — e.g. TNBC "
                    "is \"Breast Subtype (2010+)\" = 'HR-/HER2-', not the literal 'TNBC'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string", "description": "Column name (no quotes needed)."},
                        "top_n": {"type": "integer", "description": "Max distinct values (default 25)."},
                    },
                    "required": ["column"],
                },
                "invoke": self.seer_value_counts,
            },
            {
                "name": "seer_sql",
                "description": (
                    "Run a read-only DuckDB SELECT/WITH query over the 'seer' view "
                    "(4.8M rows). Double-quote every column identifier. Prefer GROUP "
                    "BY aggregations; never select raw rows from the full table. Pass "
                    "'output_name' to save the result as a named deliverable table."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "A single SELECT/WITH statement."},
                        "output_name": {"type": "string", "description": "Save result as this deliverable/view name (optional)."},
                    },
                    "required": ["query"],
                },
                "invoke": self.seer_sql,
            },
            {
                "name": "duckdb_query",
                "description": (
                    "Execute a raw read-only DuckDB query (SELECT/WITH) passed as "
                    "input against the 'seer' view (and any views created earlier). "
                    "Double-quote column identifiers. Results are capped to a row "
                    "'limit'. Use for quick ad-hoc lookups; it does NOT save a "
                    "deliverable (use seer_sql with 'output_name' for that)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "A single read-only SELECT/WITH statement."},
                        "limit": {"type": "integer", "description": f"Max rows to return (default/cap {MATERIALIZE_ROW_CAP})."},
                    },
                    "required": ["query"],
                },
                "invoke": self.duckdb_query,
            },
            {
                "name": "kaplan_meier",
                "description": (
                    "Compute a Kaplan-Meier survival curve over the SEER table. "
                    "For SEER use time_column=\"Survival months\", "
                    "event_column=\"Vital status recode (study cutoff used)\", "
                    "event_values=[\"Dead\"]. Provide a 'where' filter to define the "
                    "cohort (e.g. TNBC) and optional 'group_by' columns to compare "
                    "curves. Returns a life-table (time_months, n_at_risk, n_events, "
                    "survival_probability, CI) as a deliverable."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_column": {"type": "string", "description": "Numeric follow-up time column, e.g. \"Survival months\"."},
                        "event_column": {"type": "string", "description": "Status column, e.g. \"Vital status recode (study cutoff used)\"."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Values of event_column counted as an event, e.g. [\"Dead\"].",
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter (double-quote columns). Optional."},
                        "group_by": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Column(s) to stratify curves by. Optional.",
                        },
                        "label": {"type": "string", "description": "Deliverable name for the KM table. Optional."},
                    },
                    "required": ["time_column", "event_column", "event_values"],
                },
                "invoke": self.kaplan_meier,
            },
            {
                "name": "competing_risk_cif",
                "description": (
                    "Competing-risk cumulative incidence via the Aalen-Johansen "
                    "estimator (lifelines). Use INSTEAD of kaplan_meier whenever "
                    "patients can die of an unrelated cause: 1-KM treats those "
                    "competing deaths as censoring and OVERSTATES the cumulative "
                    "incidence. Patients are split into event of interest "
                    "('event_values', cause 1), competing event "
                    "('competing_values', cause 2) and censored (everything else); "
                    "one CIF is estimated per group_column level. For SEER "
                    "cancer-specific analyses use event_column=\"SEER "
                    "cause-specific death classification\" with "
                    "event_values=[\"Dead (attributable to this cancer dx)\"] and "
                    "competing_values=[\"Alive or dead of other cause\"]-style "
                    "labels. Returns the tidy CIF curve table + a stepped CIF "
                    "figure, and reports the CIF at each requested timepoint with "
                    "the between-group absolute risk difference."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_column": {"type": "string", "description": "Numeric follow-up time, e.g. \"Survival months\"."},
                        "event_column": {"type": "string", "description": "Column recording the cause/outcome status."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Value(s) of the EVENT OF INTEREST (cause 1), verbatim.",
                        },
                        "competing_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Value(s) of the COMPETING event (cause 2), verbatim — e.g. "
                                "death from another cause. Required: without a competing "
                                "event use kaplan_meier instead."
                            ),
                        },
                        "group_column": {"type": "string", "description": "Estimate one CIF per level of this column. Optional."},
                        "group_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Restrict to these group_column levels (verbatim). Optional.",
                        },
                        "cif_time_points": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": (
                                "Horizons at which to report the CIF, in the duration column's "
                                "unit — e.g. [60] for 5-year cumulative incidence. With exactly "
                                "two groups the absolute risk difference is reported too."
                            ),
                        },
                        "weights_column": {
                            "type": "string",
                            "description": (
                                "Per-patient weight column for an ADJUSTED CIF — pass the 'iptw' "
                                "column from iptw_weight and feed this node that weighted cohort."
                            ),
                        },
                        "both_causes": {
                            "type": "boolean",
                            "description": (
                                "Also plot the competing event's CIF (default true), which is how "
                                "competing-risk figures are normally reported."
                            ),
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "title": {"type": "string", "description": "Figure title. Optional."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": [
                        "duration_column", "event_column", "event_values", "competing_values",
                    ],
                },
                "invoke": self.competing_risk_cif,
            },
            {
                "name": "propensity_score_match",
                "description": (
                    "Propensity-score matching for causal comparisons (powered by "
                    "psmpy). Fits a logistic PS model for 'treatment_column' in "
                    "'treatment_values' on 'covariates', then KNN matching on the PS "
                    "logit — 1:1 within 'caliper' (× SD of the logit) or 1:'ratio'. "
                    "Categorical covariates are one-hot encoded automatically. Its "
                    "output is the matched patient cohort (input columns + a _treat "
                    "flag); the covariate-balance table (standardized mean "
                    "differences before vs after matching) is the deliverable."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "treatment_column": {"type": "string", "description": "Column defining treatment vs control."},
                        "treatment_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Value(s) of treatment_column that mark the TREATED arm.",
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Columns to balance on (numeric or categorical).",
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "caliper": {"type": "number", "description": "Caliper as a multiple of SD(logit PS). Default 0.2."},
                        "ratio": {"type": "integer", "description": "Controls matched per treated (default 1)."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": ["treatment_column", "treatment_values", "covariates"],
                },
                "invoke": self.propensity_score_match,
            },
            {
                "name": "propensity_score_match_multi",
                "description": (
                    "Multi-arm (K≥3) 1:1:…:1 propensity-score matching (Rassen-style). "
                    "Fits a multinomial logistic GPS for 'treatment_column' across "
                    "ordered 'arms', then greedily matches K-tuples by Euclidean "
                    "GPS-vector distance with component-wise logit calipers "
                    "('caliper'×SD of logit P(arm) within that arm, default 0.6). "
                    "Optional 'exact_columns' define hard strata; 'tolerance_columns' "
                    "(dict col→tol or list of {column,tolerance}) constrain numeric "
                    "within-tolerance matches (e.g. age±2, year±2). OUTPUT is the "
                    "matched patient cohort (equal n per arm + `_arm` index); pairwise "
                    "covariate-balance SMDs (before vs after, every arm pair) are the "
                    "deliverable. For binary two-arm matching use "
                    "propensity_score_match instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "treatment_column": {
                            "type": "string",
                            "description": "Column whose values identify the K treatment arms.",
                        },
                        "arms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Ordered list of ≥3 distinct treatment_column values to "
                                "match 1:1:…:1 (copy labels verbatim)."
                            ),
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Columns for the multinomial PS model (numeric or categorical).",
                        },
                        "exact_columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Columns that must match exactly within each K-tuple (hard strata).",
                        },
                        "tolerance_columns": {
                            "description": (
                                "Numeric within-tolerance constraints as {column: tol} or "
                                "[{column, tolerance}, …] (e.g. {\"Age\": 2})."
                            ),
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "caliper": {
                            "type": "number",
                            "description": "Per-arm caliper as a multiple of SD(logit PS). Default 0.6.",
                        },
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": ["treatment_column", "arms", "covariates"],
                },
                "invoke": self.propensity_score_match_multi,
            },
            {
                "name": "iptw_weight",
                "description": (
                    "Inverse-probability-of-treatment weighting (powered by "
                    "iptw-survival). Fits a logistic propensity model for "
                    "'treatment_column' in 'treatment_values' given the covariates "
                    "and attaches 'propensity_score' + an 'iptw' weight to EVERY "
                    "patient — nobody is discarded, unlike propensity_score_match, "
                    "so the estimand stays the population-level ATE (or ATO with "
                    "weight_type='overlap'). Its output is the full weighted cohort "
                    "(input columns + propensity_score + iptw); the covariate-balance "
                    "table (SMD before vs after weighting) is the deliverable. Pass "
                    "the resulting cohort to a downstream node that consumes the "
                    "weight column."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "treatment_column": {"type": "string", "description": "Column defining treatment vs control."},
                        "treatment_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Value(s) of treatment_column that mark the TREATED arm, copied verbatim from the data.",
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Confounders to adjust for. Typed automatically: numeric "
                                "columns are continuous, the rest categorical (blanks "
                                "become an 'Unknown' level)."
                            ),
                        },
                        "cont_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Force these covariates to be treated as CONTINUOUS. Use "
                                "for numeric fields stored as text (e.g. an age recode)."
                            ),
                        },
                        "cat_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be treated as CATEGORICAL. Optional.",
                        },
                        "binary_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be treated as BINARY (exactly 2 levels). Optional.",
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "weight_type": {
                            "type": "string",
                            "enum": ["iptw", "overlap"],
                            "description": (
                                "'iptw' (default) targets the ATE; 'overlap' targets the "
                                "ATO and is more stable when propensity scores are extreme."
                            ),
                        },
                        "stabilized": {
                            "type": "boolean",
                            "description": "Stabilize IPTW by the marginal treatment probability (default true). Ignored for overlap weights.",
                        },
                        "clip_bounds": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Trim propensity scores to [lower, upper], e.g. [0.01, 0.99]. Optional.",
                        },
                        "normalize": {
                            "type": "string",
                            "enum": ["by_group", "overall"],
                            "description": "Overlap weights only: rescale weights within each arm ('by_group') or overall. Optional.",
                        },
                        "random_state": {"type": "integer", "description": "Seed for the propensity model. Default 42."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": ["treatment_column", "treatment_values", "covariates"],
                },
                "invoke": self.iptw_weight,
            },
            {
                "name": "iptw_kaplan_meier",
                "description": (
                    "IPTW-adjusted Kaplan-Meier curves with bootstrap 95% CIs "
                    "(iptw-survival). Fits the weighting model, estimates a WEIGHTED "
                    "KM curve per arm and bootstraps 'n_bootstrap' resamples, "
                    "refitting the propensity model in each so the CI reflects "
                    "weight-estimation uncertainty. Use this instead of kaplan_meier "
                    "whenever the two arms must be confounder-adjusted. Produces the "
                    "adjusted survival figure plus its curve table (time, "
                    "treatment/control estimate + lower_ci + upper_ci). This tool "
                    "does its OWN weighting — feed it the unweighted cohort."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "treatment_column": {"type": "string", "description": "Column defining treatment vs control."},
                        "treatment_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Value(s) of treatment_column that mark the TREATED arm.",
                        },
                        "duration_column": {"type": "string", "description": "Numeric follow-up time, e.g. \"Survival months\"."},
                        "event_column": {"type": "string", "description": "Status column, e.g. \"Vital status recode (study cutoff used)\"."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Values of event_column counted as an event, e.g. [\"Dead\"].",
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Confounders the weights adjust for (auto-typed).",
                        },
                        "cont_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be CONTINUOUS. Optional.",
                        },
                        "cat_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be CATEGORICAL. Optional.",
                        },
                        "binary_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be BINARY. Optional.",
                        },
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "weight_type": {
                            "type": "string",
                            "enum": ["iptw", "overlap"],
                            "description": "'iptw' (default, ATE) or 'overlap' (ATO).",
                        },
                        "stabilized": {"type": "boolean", "description": "Stabilized IPTW (default true)."},
                        "clip_bounds": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Trim propensity scores to [lower, upper]. Optional.",
                        },
                        "n_bootstrap": {
                            "type": "integer",
                            "description": (
                                "Bootstrap resamples for the CI (default 200). Each one "
                                "refits the propensity model, so raise it only for small "
                                "cohorts."
                            ),
                        },
                        "random_state": {"type": "integer", "description": "Bootstrap/model seed. Default 42."},
                        "title": {"type": "string", "description": "Figure title. Optional."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": [
                        "treatment_column", "treatment_values", "duration_column",
                        "event_column", "event_values", "covariates",
                    ],
                },
                "invoke": self.iptw_kaplan_meier,
            },
            {
                "name": "iptw_survival_metrics",
                "description": (
                    "IPTW-adjusted, non-parametric survival metrics with bootstrap "
                    "95% CIs (iptw-survival). After weighting, reports per-arm "
                    "survival probability at each 'psurv_time_points' value, "
                    "restricted mean survival time at each 'rmst_time_points' horizon "
                    "and median survival — plus the treated-minus-control DIFFERENCE, "
                    "i.e. the absolute risk difference / RMST gain that a Cox hazard "
                    "ratio cannot express. No proportional-hazards assumption. Use it "
                    "for questions like 'adjusted 5-year survival and its absolute "
                    "difference'. Returns one tidy row per group × metric × timepoint. "
                    "This tool does its OWN weighting — feed it the unweighted cohort."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "treatment_column": {"type": "string", "description": "Column defining treatment vs control."},
                        "treatment_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Value(s) of treatment_column that mark the TREATED arm.",
                        },
                        "duration_column": {"type": "string", "description": "Numeric follow-up time, e.g. \"Survival months\"."},
                        "event_column": {"type": "string", "description": "Status column, e.g. \"Vital status recode (study cutoff used)\"."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Values of event_column counted as an event, e.g. [\"Dead\"].",
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Confounders the weights adjust for (auto-typed).",
                        },
                        "cont_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be CONTINUOUS. Optional.",
                        },
                        "cat_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be CATEGORICAL. Optional.",
                        },
                        "binary_var": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Force these covariates to be BINARY. Optional.",
                        },
                        "psurv_time_points": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": (
                                "Timepoints for adjusted survival probability, in the "
                                "duration column's unit — e.g. [60, 120] months for "
                                "5- and 10-year survival."
                            ),
                        },
                        "rmst_time_points": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Horizons for restricted mean survival time, e.g. [60].",
                        },
                        "median_time": {"type": "boolean", "description": "Also report median survival (default true)."},
                        "where": {"type": "string", "description": "SQL boolean cohort filter. Optional."},
                        "weight_type": {
                            "type": "string",
                            "enum": ["iptw", "overlap"],
                            "description": "'iptw' (default, ATE) or 'overlap' (ATO).",
                        },
                        "stabilized": {"type": "boolean", "description": "Stabilized IPTW (default true)."},
                        "clip_bounds": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Trim propensity scores to [lower, upper]. Optional.",
                        },
                        "n_bootstrap": {
                            "type": "integer",
                            "description": "Bootstrap resamples for the CIs (default 200).",
                        },
                        "random_state": {"type": "integer", "description": "Bootstrap/model seed. Default 42."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": [
                        "treatment_column", "treatment_values", "duration_column",
                        "event_column", "event_values", "covariates",
                    ],
                },
                "invoke": self.iptw_survival_metrics,
            },
            {
                "name": "cox_ph",
                "description": (
                    "Cox proportional-hazards regression (lifelines). Derives an "
                    "event indicator (1 if event_column ∈ event_values), one-hot "
                    "encodes categorical 'covariates', and fits a Cox model — "
                    "optionally stratified by 'strata'. For SEER use "
                    "duration_column=\"Survival months\", "
                    "event_column=\"Vital status recode (study cutoff used)\", "
                    "event_values=[\"Dead\"]. Returns a hazard-ratio table "
                    "(coef, HR, 95% CI, z, p) plus concordance. Rows missing any "
                    "covariate are dropped before encoding, and covariate columns "
                    "that end up constant or redundant are dropped and named in the "
                    "summary — do not hand-write 'IS NOT NULL' filters for them."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "duration_column": {"type": "string", "description": "Numeric follow-up time, e.g. \"Survival months\"."},
                        "event_column": {"type": "string", "description": "Status column, e.g. \"Vital status recode (study cutoff used)\"."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Values of event_column counted as an event, e.g. [\"Dead\"].",
                        },
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Predictor columns (numeric or categorical).",
                        },
                        "where": {
                            "type": "string",
                            "description": (
                                "SQL boolean cohort filter for the CLINICAL cohort "
                                "definition. Optional. Do not add 'IS NOT NULL' guards "
                                "for the covariates — the tool drops incomplete rows "
                                "itself and reports how many."
                            ),
                        },
                        "strata": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Column(s) to stratify the baseline hazard by. Optional.",
                        },
                        "weights_column": {
                            "type": "string",
                            "description": (
                                "Per-patient weight column for an IPTW-WEIGHTED Cox — pass the "
                                "'iptw' column produced by iptw_weight and give this node that "
                                "weighted cohort as its input. Robust variance turns on "
                                "automatically."
                            ),
                        },
                        "robust": {
                            "type": "boolean",
                            "description": (
                                "Robust (sandwich) standard errors. Defaults to true when "
                                "weights_column is set, false otherwise."
                            ),
                        },
                        "cluster_column": {
                            "type": "string",
                            "description": (
                                "Column identifying correlated observation clusters (e.g. "
                                "registry, hospital) for clustered robust SEs. Optional."
                            ),
                        },
                        "interactions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Interaction (effect-modification) terms, each naming two "
                                "columns that are ALSO in 'covariates', e.g. "
                                "[\"Radiation recode * Age recode\"]. Every interaction gets a "
                                "joint Wald test over its whole block — the only valid p-value "
                                "for a categorical interaction spanning several dummies."
                            ),
                        },
                        "penalizer": {
                            "type": "number",
                            "description": (
                                "Ridge penalty (e.g. 0.1) to stabilize a collinear or wide "
                                "one-hot design that fails to converge. Default 0."
                            ),
                        },
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": ["duration_column", "event_column", "event_values", "covariates"],
                },
                "invoke": self.cox_ph,
            },
            {
                "name": "cox_time_varying",
                "description": (
                    "Time-varying (counting-process) Cox regression (lifelines). "
                    "Consumes a LONG-format table — one row per subject × interval "
                    "with id/start/stop/event + time-varying covariates — that must "
                    "already exist as a view ('input'; build it first with seer_sql "
                    "+ output_name). Fits CoxTimeVaryingFitter and returns a "
                    "hazard-ratio table. Use 'event_values' to map a categorical "
                    "event column to 0/1, else it is cast to int."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id_column": {"type": "string", "description": "Subject identifier column in the long table."},
                        "start_column": {"type": "string", "description": "Interval start time column."},
                        "stop_column": {"type": "string", "description": "Interval stop time column (must be > start)."},
                        "event_column": {"type": "string", "description": "Event flag/status column for the interval."},
                        "covariates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Time-varying predictor columns (numeric or categorical).",
                        },
                        "input": {"type": "string", "description": "Long-format view name (default 'seer')."},
                        "event_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional value(s) of event_column counted as an event.",
                        },
                        "where": {"type": "string", "description": "SQL boolean filter on the long table. Optional."},
                        "label": {"type": "string", "description": "Deliverable name. Optional."},
                    },
                    "required": ["id_column", "start_column", "stop_column", "event_column", "covariates"],
                },
                "invoke": self.cox_time_varying,
            },
        ]

    def run(self, name: str, args: Dict[str, Any]) -> str:
        spec = next((s for s in self.specs() if s["name"] == name), None)
        if spec is None:
            return (
                f"Error: unknown tool '{name}'. Available: seer_schema, "
                "seer_value_counts, seer_sql, duckdb_query, kaplan_meier, "
                "propensity_score_match, cox_ph, cox_time_varying."
            )
        try:
            return str(spec["invoke"](**(args or {})))
        except TypeError as e:
            return f"Error: bad arguments for {name}: {e}"
        except Exception as e:
            return f"Error in {name}: {e}"


def _dump_yaml(d: Dict[str, Any]) -> str:
    """Render a config dict as YAML, or ``""`` when PyYAML is unavailable.

    The YAML text is a convenience view; the structured dict is the contract (it is
    what gets stored as BSON). Degrading the render keeps the structure intact
    instead of losing the whole catalog to a missing optional dependency.
    """
    try:
        import yaml
    except Exception:  # noqa: BLE001
        return ""
    try:
        return yaml.safe_dump(
            d, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
    except Exception:  # noqa: BLE001
        # A value PyYAML cannot represent (a pandas Timestamp in a head preview, a
        # numpy scalar) must not escape. The caller is attaching metadata to a node
        # that already PASSED verification, and letting the render raise took that
        # node's whole registration down with it — ledger document, catalog pointer,
        # stored params/plan/spec/schema — leaving the exported parquet on S3 with
        # nothing pointing at it, so no later delta could restore that input.
        return ""


def build_kedro_yaml(config: Dict[str, Any], parquet_uri: str) -> Dict[str, Any]:
    """Render a planned pipeline config into real Kedro conf YAML.

    Produces ``conf/base/catalog.yml`` (the base SEER parquet + one dataset per
    pipeline output) and ``conf/base/parameters.yml`` (per-node params), so the
    plan follows Kedro's declarative config convention. The rendered strings are
    empty when PyYAML is unavailable; ``catalog_struct`` is always built.

    Also returns ``catalog_struct`` — the structured catalog dict — so the graph
    can incrementally attach per-artifact execution metadata (head / profile /
    producer) as each step passes verification (see :func:`attach_catalog_metadata`).
    """
    steps = config.get("pipeline") or []
    finals = set(config.get("final_outputs") or [])
    # Preserve any metadata already attached to a prior render (re-plan / revise).
    prev = config.get("catalog_struct") if isinstance(config.get("catalog_struct"), dict) else {}

    catalog: Dict[str, Any] = {
        "seer": {
            "type": "pandas.ParquetDataset",
            "filepath": parquet_uri,
        }
    }
    params: Dict[str, Any] = {}
    for s in steps:
        out = s.get("output")
        if not out:
            continue
        # Final outputs persist to CSV; intermediates stay in memory.
        if out in finals:
            entry: Dict[str, Any] = {
                "type": "pandas.CSVDataset",
                "filepath": f"data/07_model_output/{out}.csv",
            }
        else:
            entry = {"type": "MemoryDataset"}
        # Carry forward execution metadata captured on a previous render.
        prev_meta = (prev.get(out) or {}).get("metadata") if isinstance(prev.get(out), dict) else None
        if prev_meta:
            entry["metadata"] = prev_meta
        catalog[out] = entry
        node_params = s.get("params") or {}
        if node_params:
            params[s.get("name") or out] = node_params

    return {
        "catalog_yaml": _dump_yaml(catalog),
        "parameters_yaml": _dump_yaml(params) if params else "{}\n",
        "catalog_struct": catalog,
    }


def build_catalog_metadata(
    spec: Dict[str, Any],
    ref: Dict[str, Any],
    *,
    head: Optional[List[Dict[str, Any]]] = None,
    head_rows: int = 5,
    caveat: str = "",
) -> Dict[str, Any]:
    """Build the per-artifact ``metadata`` block written into a catalog entry.

    Captures — for next-round planning and error debugging — WHAT produced the
    artifact (op/tool + inputs + params), its shape/location, a small ``head``
    preview and the data ``profile`` (both only for tabular outputs).
    """
    op = str(spec.get("op") or "")
    out = str(spec.get("output") or "")
    is_analysis = op in ANALYSIS_OPS
    produced_by: Dict[str, Any] = {
        ("tool" if is_analysis else "op"): op,
        "kind": "frozen_analysis_tool" if is_analysis else "sql_transform",
        "step": spec.get("name") or out,
        "inputs": spec.get("inputs") or ["seer"],
        "params": spec.get("params") or {},
    }
    authored = spec.get("authored_params")
    if isinstance(authored, dict) and authored:
        produced_by["authored_params"] = authored
    deliverable = spec.get("deliverable") if isinstance(spec.get("deliverable"), dict) else {}
    if deliverable and (deliverable.get("code") or deliverable.get("title") or deliverable.get("name")):
        produced_by["deliverable"] = {
            k: deliverable[k]
            for k in ("code", "name", "title", "kind")
            if deliverable.get(k)
        }
    md: Dict[str, Any] = {
        "produced_by": produced_by,
        "row_count": ref.get("row_count"),
        "col_count": len(ref.get("columns") or []),
        "columns": ref.get("columns") or [],
    }
    if ref.get("uri"):
        md["storage_path"] = ref.get("uri")
        md["format"] = ref.get("format")
    else:
        md["storage"] = "live DuckDB view (profile-only; data not exported)"
    # Tabular outputs → head preview + data profile (skip when neither exists).
    head_list = [dict(r) for r in (head or [])][:head_rows]
    if head_list:
        md["head"] = head_list
    if ref.get("profile_text"):
        md["profile"] = ref["profile_text"]
    if caveat:
        md["caveat"] = caveat
    return md


def attach_catalog_metadata(
    catalog_struct: Dict[str, Any],
    output_name: str,
    metadata: Dict[str, Any],
    *,
    description: str = "",
) -> str:
    """Attach execution-result ``metadata`` to one catalog entry (mutating
    ``catalog_struct``) and return the re-rendered catalog.yml string.

    ``description`` is written only when the entry has none yet (skip if already
    present), per requirement.
    """
    entry = catalog_struct.get(output_name)
    if not isinstance(entry, dict):
        entry = {"type": "MemoryDataset"}
        catalog_struct[output_name] = entry
    meta = dict(entry.get("metadata") or {})
    if description and not meta.get("description"):
        meta["description"] = description
    meta.update(metadata)
    entry["metadata"] = meta
    return _dump_yaml(catalog_struct)


def tool_specs_to_openai(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": s["name"], "description": s["description"], "parameters": s["parameters"]},
        }
        for s in specs
    ]


def tool_specs_to_bedrock(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"toolSpec": {"name": s["name"], "description": s["description"], "inputSchema": {"json": s["parameters"]}}}
        for s in specs
    ]
