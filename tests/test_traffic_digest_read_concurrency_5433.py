"""#5433 — the traffic digest's read path does less work, and says the same thing.

The 2026-10-30 post-deploy dry run took 90.9 s against a 72 s bar (60 % of the 120 s
timeout): load_logs 62.8 s, parse_aggregate 12.4 s, and ~12 s of untimed subscribe-
attempt pass. The same week parses in 0.65 s on a laptop, so at 256 MB the Lambda runs
pure Python ~19x slower: the run is CPU-bound, and a wider fan-out alone cannot buy it.
Three changes, each pinned here:

  * the listing starts each CloudFront distribution prefix at the window start minus a
    delivery slack, instead of paging through all ~90 days of retained logs;
  * both log parsers decode a field only after the line survives the filters that do
    not need it — and their output is byte-identical to the pre-#5433 parsers;
  * the fan-out is wider, and the S3 client's connection pool is sized from the SAME
    constant as the worker count.
"""

import gzip
import io
import json
import os
import random
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import traffic_digest_lambda as td  # noqa: E402

# ── The pre-#5433 parsers, verbatim (the identity oracle) ────────────────────────────


def _ref_is_page(uri):
    u = uri.lower()
    if u.startswith("/assets/") or u.startswith("/api/") or u.startswith("/legacy/"):
        return False
    if any(u.endswith(ext) for ext in td._NON_PAGE):
        return False
    return True


def _ref_parse_cf_log(text):
    out = []
    fields = None
    for line in text.splitlines():
        if line.startswith("#Fields:"):
            fields = line.split(":", 1)[1].strip().split()
            continue
        if line.startswith("#") or not line.strip():
            continue
        if not fields:
            continue
        parts = line.split("\t")
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        method = row.get("cs-method", "")
        status = row.get("sc-status", "")
        uri = urllib.parse.unquote(row.get("cs-uri-stem", ""))
        ua = urllib.parse.unquote(row.get("cs(User-Agent)", row.get("cs-user-agent", "")))
        ref = urllib.parse.unquote(row.get("cs(Referer)", row.get("cs-referer", "")))
        ip = row.get("c-ip", "")
        date = row.get("date", "")
        if method != "GET" or status not in ("200", "304"):
            continue
        if not _ref_is_page(uri) or td._is_bot(ua):
            continue
        out.append(
            {
                "date": date,
                "uri": uri,
                "ref": ref,
                "vkey": td._ipkey(ip, ua),
                "utm": td._has_utm_source(row.get("cs-uri-query", "")),
            }
        )
    return out


def _ref_parse_subscribe_attempts(text):
    page_views = attempts = successes = 0
    fields = None
    for line in text.splitlines():
        if line.startswith("#Fields:"):
            fields = line.split(":", 1)[1].strip().split()
            continue
        if line.startswith("#") or not line.strip():
            continue
        if not fields:
            continue
        parts = line.split("\t")
        if len(parts) < len(fields):
            continue
        row = dict(zip(fields, parts))
        method = row.get("cs-method", "")
        status = row.get("sc-status", "")
        uri = urllib.parse.unquote(row.get("cs-uri-stem", ""))
        ua = urllib.parse.unquote(row.get("cs(User-Agent)", row.get("cs-user-agent", "")))
        if td._is_bot(ua):
            continue
        if method == "GET" and status in ("200", "304") and td._norm_page(uri) == td._SUBSCRIBE_PAGE:
            page_views += 1
        elif method == "POST" and uri == "/api/subscribe":
            attempts += 1
            if status.startswith("2"):
                successes += 1
    return {"page_views": page_views, "attempts": attempts, "successes": successes}


# ── A fixture that exercises every filter and every header shape ─────────────────────


def _fixture_files():
    """Deterministic CloudFront-shaped log texts: the standard header, the legacy
    `cs-user-agent`/`cs-referer` names, a duplicated column, a header without
    `cs-uri-query`, an empty `#Fields:`, rows before any header, short rows, blanks,
    comments — and values that only a decode-then-filter order classifies correctly
    (a percent-encoded bot word, an encoded /subscribe/ path, an encoded utm key)."""
    rng = random.Random(5433)
    std = "date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent) cs-uri-query".split()
    headers = [
        std,
        "date time c-ip cs-method cs-uri-stem sc-status cs-referer cs-user-agent cs-uri-query".split(),
        std + ["sc-status"],  # duplicate: the LAST column wins, as dict(zip()) did
        [f for f in std if f != "cs-uri-query"],
        [],  # `#Fields:` with nothing after it → every row is skipped
    ]
    uris = [
        "/",
        "/index.html",
        "/data/sleep/",
        "/cockpit/",
        "/journal/essays/org-chart-of-one/index.html",
        "/subscribe/",
        "/subscribe/index.html",
        "/sub%73cribe/",
        "/api/subscribe",
        "/api/subscribe/",
        "/API/journey",
        "/assets/css/tokens.css",
        "/legacy/old/",
        "/fonts/x.WOFF2",
        "/caf%C3%A9/",
        "/a%2Fb/",
        "/feed.xml",
    ]
    uas = [
        "Mozilla/5.0%20(Macintosh;%20Intel%20Mac%20OS%20X)",
        "Mozilla/5.0%20(iPhone)",
        "Googlebot/2.1",
        "Mozilla/5.0%20(compatible;%20Go%62ot)",  # decodes to a bot
        "curl/8.1",
        "HeadlessChrome",
        "-",
    ]
    refs = [
        "-",
        "https://www.reddit.com/r/qs",
        "https://news.ycombinator.com/item%3Fid%3D1",
        "https://averagejoematt.com/",
        "android-app://x",
    ]
    queries = ["-", "utm_source=hn", "utm%5Fsource=reddit", "xutm_source=1", "utm_source=", "a=1&utm_source=x"]
    texts = []
    for header in headers:
        for _ in range(4):
            lines = ["#Version: 1.0"]
            if rng.random() < 0.3:  # rows before any header are skipped
                lines.append("\t".join(["2026-10-20", "12:00:00", "1.1.1.1", "GET", "h", "/", "200", "-", "Mozilla", "-"]))
            lines.append("#Fields: " + " ".join(header))
            for _ in range(150):
                vals = {
                    "date": rng.choice(["2026-10-20", "2026-10-21", "2026-10-22"]),
                    "time": "12:00:00",
                    "c-ip": rng.choice(["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]),
                    "cs-method": rng.choice(["GET", "GET", "GET", "POST", "HEAD", "OPTIONS"]),
                    "cs(Host)": "averagejoematt.com",
                    "cs-uri-stem": rng.choice(uris),
                    "sc-status": rng.choice(["200", "200", "304", "404", "201", "206", "500"]),
                    "cs(Referer)": rng.choice(refs),
                    "cs-referer": rng.choice(refs),
                    "cs(User-Agent)": rng.choice(uas),
                    "cs-user-agent": rng.choice(uas),
                    "cs-uri-query": rng.choice(queries),
                }
                cells, seen = [], set()
                for f in header:  # a repeated column gets its own value, so "last wins" is observable
                    cells.append(vals[f] if f not in seen else rng.choice(["200", "404", "304"]))
                    seen.add(f)
                cells = cells or ["x"] * 10
                roll = rng.random()
                if roll < 0.04:
                    cells = cells[:-2]  # short row → skipped
                elif roll < 0.07:
                    cells = cells + ["extra"]  # long row → parsed, extra ignored
                lines.append("\t".join(cells))
                if rng.random() < 0.03:
                    lines.append(rng.choice(["", "   ", "# a comment"]))
            texts.append("\n".join(lines) + "\n")
    return texts


def test_parsers_are_byte_identical_to_the_pre_5433_parsers():
    texts = _fixture_files()
    ref_records = [r for t in texts for r in _ref_parse_cf_log(t)]
    new_records = [r for t in texts for r in td.parse_cf_log(t)]
    # the fixture really discriminates: pages survive, and so does every rejection reason
    assert 100 < len(ref_records) < sum(t.count("\n") for t in texts) / 2
    assert any(r["utm"] for r in ref_records) and any(not r["utm"] for r in ref_records)
    assert new_records == ref_records
    assert json.dumps(td.aggregate(new_records)) == json.dumps(td.aggregate(ref_records))

    ref_attempts = [_ref_parse_subscribe_attempts(t) for t in texts]
    new_attempts = [td.parse_subscribe_attempts(t) for t in texts]
    for shape in range(4):  # every non-empty header shape counts something (4 files per shape)
        assert sum(sum(a.values()) for a in ref_attempts[4 * shape : 4 * shape + 4]), f"header shape {shape} counted nothing"
    assert not any(sum(a.values()) for a in ref_attempts[16:]), "an empty #Fields: header must skip every row"
    assert new_attempts == ref_attempts
    assert td.aggregate_subscribe_attempts(texts) == {k: sum(a[k] for a in ref_attempts) for k in ("page_views", "attempts", "successes")}


def test_mutation_control_the_identity_check_sees_a_filter_change(monkeypatch):
    """Drop one bot word from the filter: the new parser must stop matching the oracle
    computed under the real filter — the identity test is not vacuous."""
    texts = _fixture_files()
    expected = [r for t in texts for r in _ref_parse_cf_log(t)]
    monkeypatch.setattr(td, "_BOT_RE", tuple(b for b in td._BOT_RE if b != "bot"))
    assert [r for t in texts for r in td.parse_cf_log(t)] != expected


def test_parsers_decode_only_surviving_lines(monkeypatch):
    """The CPU win, as a count: a week that is mostly assets must not percent-decode
    three fields on every line. The pre-#5433 parser is the mutation control."""
    calls = {"n": 0}
    real = urllib.parse.unquote

    def counting(s, *a, **k):
        calls["n"] += 1
        return real(s, *a, **k)

    header = "#Fields: date time c-ip cs-method cs(Host) cs-uri-stem sc-status cs(Referer) cs(User-Agent) cs-uri-query\n"
    asset = "\t".join(["2026-10-20", "1", "1.1.1.1", "GET", "h", "/assets/app.js", "200", "-", "Mozilla/5.0%20(Mac)", "-"])
    page = "\t".join(["2026-10-20", "1", "1.1.1.1", "GET", "h", "/", "200", "-", "Mozilla/5.0%20(Mac)", "-"])
    text = header + "\n".join([asset] * 90 + [page] * 10) + "\n"
    monkeypatch.setattr(urllib.parse, "unquote", counting)

    assert len(td.parse_cf_log(text)) == 10
    new_calls, calls["n"] = calls["n"], 0
    assert new_calls == 100 + 2 * 10  # the stem of every GET-200 line; UA + referer of the 10 pages

    assert len(_ref_parse_cf_log(text)) == 10
    assert calls["n"] == 3 * 100  # pre-#5433: three decodes on every line
    calls["n"] = 0

    td.parse_subscribe_attempts(text)
    assert calls["n"] == 100  # the stem only — no page here is /subscribe/, so no UA decode


# ── The listing skips retained history it cannot use ─────────────────────────────────


class _ListingS3:
    """An honest list_objects_v2: Prefix, Delimiter (CommonPrefixes), StartAfter and
    1,000-entry pages, over `objects` = [(key, last_modified)]. Counts every entry it
    returns — the listing's cost is proportional to that."""

    def __init__(self, objects):
        self.objects = sorted(objects)
        self.entries_returned = 0
        self.calls = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix, Delimiter=None, StartAfter=None):
        self.calls.append({"Prefix": Prefix, "Delimiter": Delimiter, "StartAfter": StartAfter})
        entries, seen_prefixes = [], set()
        for key, modified in self.objects:
            if not key.startswith(Prefix) or (StartAfter is not None and key <= StartAfter):
                continue
            rest = key[len(Prefix) :]
            if Delimiter and Delimiter in rest:
                cp = Prefix + rest[: rest.index(Delimiter) + 1]
                if cp not in seen_prefixes:
                    seen_prefixes.add(cp)
                    entries.append(("cp", cp))
                continue
            entries.append(("obj", (key, modified)))
        for i in range(0, max(len(entries), 1), 1000):
            chunk = entries[i : i + 1000]
            self.entries_returned += len(chunk)
            yield {
                "Contents": [{"Key": e[1][0], "LastModified": e[1][1]} for e in chunk if e[0] == "obj"],
                "CommonPrefixes": [{"Prefix": e[1]} for e in chunk if e[0] == "cp"],
            }


def _retained_bucket(run_at):
    """90 days of a distribution's hourly logs (two files an hour, each delivered 5 min
    to 30 h after its hour), a second distribution, and keys that are not CF logs."""
    rng = random.Random(90)
    objs = []
    for dist in ("E3S424OXQZ8NBE", "E2ABCDEF012345"):
        for h in range(90 * 24):
            hour = run_at - timedelta(hours=h)
            for n in range(2 if dist.startswith("E3") else 1):
                delay = timedelta(minutes=5) if rng.random() < 0.97 else timedelta(hours=30)
                objs.append((f"cf/{dist}.{hour:%Y-%m-%d-%H}.{rng.getrandbits(32):08x}.gz", min(hour + delay, run_at)))
    objs.append(("cf/README", run_at))  # no '.' at all → a top-level Contents entry
    objs.append(("cf/manual-export.2020-01-01.gz", run_at))  # not distribution-shaped → listed in full
    objs.append(("other/E3S424OXQZ8NBE.2026-10-29-00.x.gz", run_at))  # outside LOG_PREFIX
    return objs


def _full_listing_reference(objs, start_dt):
    return [k for k, m in sorted(objs) if k.startswith(td.LOG_PREFIX) and m >= start_dt]


def test_window_listing_matches_the_full_listing_and_skips_history(monkeypatch):
    monkeypatch.setattr(td, "LOG_BUCKET", "b")
    monkeypatch.setattr(td, "LOG_PREFIX", "cf/")
    run_at = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    start_dt = run_at - timedelta(days=td.DAYS)
    objs = _retained_bucket(run_at)
    s3 = _ListingS3(objs)

    keys = td._list_window_keys(s3, start_dt)

    assert keys == _full_listing_reference(objs, start_dt)
    listed = set(keys)
    late = [
        k
        for k, m in objs
        if k in listed
        and k.startswith("cf/E")
        and m - datetime.strptime(k.split(".")[1], "%Y-%m-%d-%H").replace(tzinfo=timezone.utc) > timedelta(hours=24)
    ]
    assert late, "the fixture must carry a late-delivered log inside the window"
    assert "cf/README" in listed and "cf/manual-export.2020-01-01.gz" in listed
    window_days = td.DAYS + td.LOG_DELIVERY_SLACK_DAYS + 1
    assert s3.entries_returned <= window_days * 24 * 3 + 10, f"listed {s3.entries_returned} entries for a {window_days}-day window"
    assert s3.entries_returned < len(objs) / 5


def test_mutation_control_no_start_after_lists_the_whole_retention(monkeypatch):
    """With the distribution-prefix match disarmed the listing is still correct but pays
    for every retained key — the bound in the test above is what fails."""
    monkeypatch.setattr(td, "LOG_BUCKET", "b")
    monkeypatch.setattr(td, "_DISTRIBUTION_PREFIX_RE", td.re.compile(r"(?!)"))
    run_at = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    objs = _retained_bucket(run_at)
    s3 = _ListingS3(objs)
    keys = td._list_window_keys(s3, run_at - timedelta(days=td.DAYS))
    assert keys == _full_listing_reference(objs, run_at - timedelta(days=td.DAYS))
    assert s3.entries_returned > (len(objs) - 1) * 0.99


def test_mutation_control_zero_slack_drops_a_late_log(monkeypatch):
    """The slack is load-bearing: with none, a log delivered a day after its hour, and
    modified inside the window, is skipped — the identity assertion catches it."""
    monkeypatch.setattr(td, "LOG_BUCKET", "b")
    monkeypatch.setattr(td, "LOG_DELIVERY_SLACK_DAYS", 0)
    run_at = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    start_dt = run_at - timedelta(days=td.DAYS)
    late = (f"cf/E3S424OXQZ8NBE.{start_dt - timedelta(hours=20):%Y-%m-%d-%H}.late.gz", start_dt + timedelta(hours=4))
    objs = _retained_bucket(run_at) + [late]
    keys = td._list_window_keys(_ListingS3(objs), start_dt)
    assert late[0] in _full_listing_reference(objs, start_dt)
    assert late[0] not in keys


# ── One constant sizes both the fan-out and the client's pool ────────────────────────


def test_log_client_pool_matches_the_worker_count(monkeypatch):
    assert td.LOAD_LOG_WORKERS > 10, "botocore's default pool is 10 — #5433 widened the fan-out past it"
    assert td._log_s3_client().meta.config.max_pool_connections == td.LOAD_LOG_WORKERS
    monkeypatch.setattr(td, "LOAD_LOG_WORKERS", 7)  # mutation control: they move together
    assert td._log_s3_client().meta.config.max_pool_connections == 7


def test_handler_reads_logs_through_the_pooled_client(monkeypatch):
    """lambda_handler must build its S3 client with the matched pool — a bare
    boto3.client("s3") would queue 32 workers on 10 sockets."""
    seen = []
    body = gzip.compress(b"#Fields: date time c-ip cs-method cs-uri-stem sc-status\n")

    class _S3:
        def get_paginator(self, name):
            return self

        def paginate(self, **kw):
            yield {"Contents": [{"Key": "cf/x.gz", "LastModified": datetime.now(timezone.utc)}]}

        def get_object(self, Bucket, Key):
            if Bucket == td.LOG_BUCKET:
                return {"Body": io.BytesIO(body)}
            raise RuntimeError("ops artifact absent")

    class _Any:
        def __getattr__(self, name):
            return lambda **kw: {"MetricDataResults": [{"Values": []}], "Parameter": {"Value": "0"}}

    class _Boto3:
        def client(self, name, region_name=None, **kw):
            seen.append((name, kw.get("config")))
            return _S3() if name == "s3" else _Any()

        def resource(self, *a, **k):
            raise RuntimeError("no dynamodb in this fixture")

    monkeypatch.setattr(td, "LOG_BUCKET", "fake-log-bucket")
    monkeypatch.setattr(td, "boto3", _Boto3())
    assert td.lambda_handler({"dry_run": True}, None)["statusCode"] == 200
    s3_configs = [cfg for name, cfg in seen if name == "s3"]
    assert s3_configs and all(cfg is not None and cfg.max_pool_connections == td.LOAD_LOG_WORKERS for cfg in s3_configs)


def test_mutation_control_pool_check_fails_on_a_default_client():
    """A client built the pre-#5433 way carries botocore's default pool of 10, which the
    pool check above would reject."""
    import boto3

    assert boto3.client("s3", region_name="us-west-2").meta.config.max_pool_connections != td.LOAD_LOG_WORKERS
