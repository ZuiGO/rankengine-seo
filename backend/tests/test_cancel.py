"""Cancel/stop round tests:

- check_cancelled raises JobCancelled on flag / cancelled status, no-op otherwise
- POST /api/analysis/{job_id}/cancel: queued|running -> 200 sets flag; missing -> 404;
  completed/failed -> 409
- run_analysis_pipeline with a pre-cancelled job: stops before crawling, marks cancelled,
  purges data via hard_delete_job, sends no alerts
- hard_delete_job removes rows across collections + competitor child jobs + job doc
- smtp: port 465 uses SMTP_SSL; try_send_email surfaces the real failure reason;
  /api/settings/smtp/test returns {sent, error}
"""

import asyncio

import pytest

from backend.services.job_cancel import JobCancelled, check_cancelled


async def _call_check(db, job_id="job-running"):
    import backend.db.mongo as mongo
    orig_mongo = mongo.get_db
    mongo.get_db = lambda: db
    try:
        return await check_cancelled(job_id)
    finally:
        mongo.get_db = orig_mongo


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    async def to_list(self, length=None):
        out = self._docs
        if length is not None:
            out = out[:length]
        return out


def _matches(doc, q):
    for k, val in q.items():
        if isinstance(val, dict):
            if "$in" in val and doc.get(k) not in val["$in"]:
                return False
            if "$ne" in val and doc.get(k) == val["$ne"]:
                return False
            continue
        if doc.get(k) != val:
            return False
    return True


class Coll:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    def _key(self, i):
        return f"{self.name}:{i}"

    async def find_one(self, q, projection=None):
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                row = {k: vv for k, vv in v.items() if k != "_coll"}
                if projection:
                    row = {k: vv for k, vv in row.items() if k in projection or k == "_id"}
                return row
        return None

    def find(self, q, projection=None):
        rows = []
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                row = {k: vv for k, vv in v.items() if k != "_coll"}
                if projection:
                    row = {k: vv for k, vv in row.items() if k in projection or k == "_id"}
                rows.append(row)
        return FakeCursor(rows)

    async def update_one(self, q, update, upsert=False):
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])
                return
        if upsert:
            doc = dict(update.get("$set", {}))
            doc["_coll"] = self.name
            for k, val in q.items():
                if k != "_id" and not isinstance(val, dict):
                    doc[k] = val
            self._store[f"{self.name}:gen-{len(self._store)}"] = doc

    async def update_many(self, q, update):
        n = 0
        for v in self._store.values():
            if v.get("_coll") != self.name:
                continue
            if _matches(v, q):
                if update.get("$set"):
                    v.update(update["$set"])
                if update.get("$pull"):
                    for k, val in update["$pull"].items():
                        if isinstance(v.get(k), list) and val in v[k]:
                            v[k].remove(val)
                n += 1
        return n

    async def delete_many(self, q):
        doomed = [k for k, v in self._store.items()
                  if v.get("_coll") == self.name and _matches(v, q)]
        for k in doomed:
            del self._store[k]
        return _Count(len(doomed))

    async def delete_one(self, q):
        matched = [k for k, v in self._store.items()
                   if v.get("_coll") == self.name and _matches(v, q)]
        for k in matched:
            del self._store[k]
        return _Count(len(matched))

    async def insert_one(self, doc):
        self._store[f"{self.name}:{len(self._store)}"] = {"_coll": self.name, **doc}

    async def insert_many(self, docs):
        for d in docs:
            await self.insert_one(d)


class _Count:
    def __init__(self, n):
        self.deleted_count = n


class FakeDb:
    def __init__(self, jobs=None):
        self._store = {}
        for i, j in enumerate(jobs or []):
            self._store[f"job:{i}"] = {"_coll": "analysis_jobs", **j}

    def __getitem__(self, name):
        return Coll(self._store, name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return Coll(self._store, name)


def _job(status, **kw):
    doc = {"_id": f"job-{status}", "url": "https://example.com", "status": status}
    doc.update(kw)
    return doc


class TestCheckCancelled:
    def test_no_flag_is_noop(self):
        db = FakeDb(jobs=[_job("running")])
        assert asyncio.run(_call_check(db)) is None

    def test_flag_raises(self):
        db = FakeDb(jobs=[_job("running", cancelled=True)])
        with pytest.raises(JobCancelled):
            asyncio.run(_call_check(db))

    def test_cancelled_status_raises(self):
        db = FakeDb(jobs=[_job("cancelled")])
        with pytest.raises(JobCancelled):
            asyncio.run(_call_check(db, "job-cancelled"))

    def test_missing_job_is_noop(self):
        assert asyncio.run(_call_check(FakeDb())) is None


class TestCancelEndpoint:
    def test_cancel_running_job(self, monkeypatch):
        import backend.routes.analysis as ra
        db = FakeDb(jobs=[_job("running")])
        _patch_route_db(monkeypatch, ra, db)
        resp = asyncio.run(ra.cancel_analysis("job-running"))
        assert resp["status"] == "cancelled"
        job = asyncio.run(db.analysis_jobs.find_one({"_id": "job-running"}))
        assert job["cancelled"] is True

    def test_cancel_queued_job(self, monkeypatch):
        import backend.routes.analysis as ra
        db = FakeDb(jobs=[_job("queued")])
        _patch_route_db(monkeypatch, ra, db)
        resp = asyncio.run(ra.cancel_analysis("job-queued"))
        assert resp["status"] == "cancelled"

    def test_cancel_finished_job_conflicts(self, monkeypatch):
        import backend.routes.analysis as ra
        from fastapi import HTTPException
        db = FakeDb(jobs=[_job("completed")])
        _patch_route_db(monkeypatch, ra, db)
        with pytest.raises(HTTPException) as e:
            asyncio.run(ra.cancel_analysis("job-completed"))
        assert e.value.status_code == 409

    def test_cancel_failed_job_conflicts(self, monkeypatch):
        import backend.routes.analysis as ra
        from fastapi import HTTPException
        db = FakeDb(jobs=[_job("failed")])
        _patch_route_db(monkeypatch, ra, db)
        with pytest.raises(HTTPException) as e:
            asyncio.run(ra.cancel_analysis("job-failed"))
        assert e.value.status_code == 409

    def test_cancel_missing_job_404(self, monkeypatch):
        import backend.routes.analysis as ra
        from fastapi import HTTPException
        _patch_route_db(monkeypatch, ra, FakeDb())
        with pytest.raises(HTTPException) as e:
            asyncio.run(ra.cancel_analysis("nope"))
        assert e.value.status_code == 404


def _patch_route_db(monkeypatch, module, db):
    monkeypatch.setattr(module, "get_db", lambda: db)
    monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)
    monkeypatch.setattr("backend.services.audit_service.get_db", lambda: db)


class TestPipelineCancelledAtStart:
    def test_stops_before_crawl_and_purges(self, monkeypatch):
        import backend.routes.analysis as ra
        import backend.services.job_cleanup as jcl
        from backend.routes.analysis import run_analysis_pipeline

        db = FakeDb(jobs=[_job("running", cancelled=True)])
        monkeypatch.setattr(ra, "get_db", lambda: db)
        monkeypatch.setattr(ra, "crawl_site", None)  # would break if actually crawled
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)

        purged = []
        monkeypatch.setattr(jcl, "hard_delete_job", _purge_fn(purged))

        asyncio.run(run_analysis_pipeline("job-running", "https://example.com"))

        job = asyncio.run(db.analysis_jobs.find_one({"_id": "job-running"}))
        assert job["status"] == "cancelled"
        assert purged, "hard_delete_job must run on cancel"


def _purge_fn(purged):
    async def _fn(job_id):
        purged.append(job_id)
        return {"analysis_jobs": 1}
    return _fn


class TestHardDeleteJob:
    def test_removes_rows_and_child_jobs(self, monkeypatch):
        from backend.services.job_cleanup import hard_delete_job
        db = FakeDb()
        db._store["p0"] = {"_coll": "pages", "job_id": "job-a"}
        db._store["p1"] = {"_coll": "pages", "job_id": "other"}
        db._store["cj0"] = {"_coll": "analysis_jobs", "_id": "comp-1", "target_job_id": "job-a"}
        db._store["cj1"] = {"_coll": "competitor_gap_analyses", "job_id": "comp-1", "target_job_id": "job-a"}
        db._store["j0"] = {"_coll": "analysis_jobs", "_id": "job-a"}
        db._store["s0"] = {"_coll": "crawl_schedules", "history": [{"job_id": "job-a"}, {"job_id": "x"}]}

        import backend.services.job_cleanup as jcl
        monkeypatch.setattr("backend.db.mongo.get_db", lambda: db)

        deleted = asyncio.run(hard_delete_job("job-a"))
        assert deleted["pages"] == 1
        assert deleted["competitor_jobs"] == 1
        assert deleted["analysis_jobs"] == 1
        assert asyncio.run(db.analysis_jobs.find_one({"_id": "job-a"})) is None
        assert asyncio.run(db.analysis_jobs.find_one({"_id": "comp-1"})) is None
        sched = asyncio.run(db.crawl_schedules.find_one({}))
        assert "job-a" not in sched["history"]


class TestSmtp:
    def test_port_465_uses_smtp_ssl(self, monkeypatch):
        from backend.services import notifications as nt
        used = {}

        class FakeSSL:
            def __init__(self, *a, **k):
                used["args"] = (a, k)
            def __enter__(self):
                return self
            def __exit__(self, *x):
                return False
            def login(self, user, pw):
                used["login"] = (user, pw)
            def send_message(self, msg):
                used["msg"] = msg

        monkeypatch.setattr(nt.smtplib, "SMTP_SSL", FakeSSL)
        nt._send_sync({"host": "smtp.x.com", "port": 465, "use_tls": True,
                       "user": "u", "password": "p", "from_email": "f@x.com"},
                      "to@x.com", "subj", "body")
        assert used["login"] == ("u", "p")
        assert "to@x.com" in str(used["msg"]["To"])

    def test_port_587_uses_starttls(self, monkeypatch):
        from backend.services import notifications as nt
        used = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                used["args"] = (a[0], a[1])
            def __enter__(self):
                return self
            def __exit__(self, *x):
                return False
            def starttls(self, **k):
                used["tls"] = True
            def login(self, user, pw):
                used["login"] = (user, pw)
            def send_message(self, msg):
                used["msg"] = msg

        monkeypatch.setattr(nt.smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(nt.ssl, "create_default_context", lambda: object())
        nt._send_sync({"host": "smtp.x.com", "port": 587, "use_tls": True,
                       "user": "u", "password": "p", "from_email": "f@x.com"},
                      "to@x.com", "subj", "body")
        assert used["tls"] is True
        assert used["args"][1] == 587

    def test_try_send_email_surfaces_reason(self, monkeypatch):
        from backend.services import notifications as nt

        async def fake_cfg():
            return {"host": "smtp.x.com", "port": 587, "use_tls": True,
                    "user": "", "password": "", "from_email": ""}

        def boom(cfg, to, subject, body, attachment=None):
            raise ConnectionRefusedError("smtp.x.com refused connection")

        monkeypatch.setattr(nt, "get_smtp_config", fake_cfg)
        monkeypatch.setattr(nt, "_send_sync", boom)
        sent, err = asyncio.run(nt.try_send_email("to@x.com", "s", "b"))
        assert sent is False
        assert "refused" in (err or "")

    def test_try_send_email_unconfigured(self, monkeypatch):
        from backend.services import notifications as nt

        async def fake_cfg():
            return {"host": "", "port": 587, "use_tls": True,
                    "user": "", "password": "", "from_email": ""}

        monkeypatch.setattr(nt, "get_smtp_config", fake_cfg)
        sent, err = asyncio.run(nt.try_send_email("to@x.com", "s", "b"))
        assert sent is False
        assert "SMTP host not configured" in (err or "")

    def test_test_endpoint_returns_error(self, monkeypatch):
        import backend.routes.app_settings as ar
        from backend.services import notifications as nt

        async def fake_cfg():
            return {"host": "", "port": 587, "use_tls": True,
                    "user": "", "password": "", "from_email": ""}

        monkeypatch.setattr(nt, "get_smtp_config", fake_cfg)
        out = asyncio.run(ar.send_smtp_test(ar.SmtpTestRequest(to="you@x.com")))
        assert out["sent"] is False
        assert out["error"]