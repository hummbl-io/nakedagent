"""Bounded local SQLite reservation ledger; not an exactly-once effect system.

An unfinished reservation remains spent and indeterminate after reopening.
No automatic retry/refund/re-enrollment. Protect the database outside the worker.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from contract import digest


class Reservations:
    def __init__(self, path, contract, *, create=False):
        self.path = Path(path).resolve()
        self.binding = digest(contract)
        self.maximum = contract["max_actions"]
        if create:
            # Never silently overwrite or initialize an existing state file.
            with self.path.open("xb"):
                pass
            with self._connection() as db:
                db.execute("CREATE TABLE run (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL, maximum INTEGER NOT NULL, revoked INTEGER NOT NULL)")
                db.execute("CREATE TABLE actions (id TEXT PRIMARY KEY, digest TEXT NOT NULL, phase TEXT NOT NULL, result TEXT)")
                db.execute("INSERT INTO run VALUES (1,?,?,0)", (self.binding, self.maximum))
                db.execute("PRAGMA user_version=1")
        with self._connection() as db:
            self._verify(db)

    @contextmanager
    def _connection(self):
        # mode=rw refuses missing storage rather than resetting budgets after deletion.
        db = sqlite3.connect(self.path.as_uri()+"?mode=rw", uri=True, timeout=10)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _verify(self, db):
        if db.execute("PRAGMA user_version").fetchone() != (1,):
            raise ValueError("unsupported reservation schema")
        row = db.execute("SELECT binding, maximum FROM run WHERE id=1").fetchone()
        if row != (self.binding, self.maximum):
            raise ValueError("reservation contract mismatch")

    def reserve(self, action):
        # Full action authorization belongs to the broker. IDs/digests bind retries.
        if (type(action) is not dict or type(action.get("action_id")) is not str
                or not 1 <= len(action["action_id"]) <= 128
                or action.get("contract_sha256") != self.binding):
            return "malformed_or_unbound"
        with self._connection() as db:
            self._verify(db)
            if db.execute("SELECT revoked FROM run WHERE id=1").fetchone()[0]:
                return "durably_revoked"
            previous = db.execute("SELECT digest FROM actions WHERE id=?", (action["action_id"],)).fetchone()
            if previous:
                return "durable_replay" if previous[0] == digest(action) else "action_id_collision"
            if db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] >= self.maximum:
                return "durable_budget_exhausted"
            db.execute("INSERT INTO actions VALUES (?,?,'reserved',NULL)", (action["action_id"], digest(action)))
        return None

    def finish(self, action, result):
        with self._connection() as db:
            self._verify(db)
            cursor = db.execute("UPDATE actions SET phase='finished',result=? WHERE id=? AND digest=? AND phase='reserved'",
                                (json.dumps(result, sort_keys=True), action["action_id"], digest(action)))
            if cursor.rowcount != 1:
                raise ValueError("reservation absent or already finalized")

    def revoke(self):
        with self._connection() as db:
            self._verify(db)
            db.execute("UPDATE run SET revoked=1 WHERE id=1")

    def snapshot(self):
        with self._connection() as db:
            self._verify(db)
            records = db.execute("SELECT id,phase,result FROM actions ORDER BY id").fetchall()
            return {"binding": self.binding, "maximum": self.maximum,
                    "revoked": bool(db.execute("SELECT revoked FROM run WHERE id=1").fetchone()[0]),
                    "spent_reservations": len(records),
                    "actions": [{"action_id": a, "status": "indeterminate" if p == "reserved" else "finished",
                                 "result": json.loads(r) if r is not None else None} for a,p,r in records]}


def dispatch_reserved(store, broker, action):
    """A reservation is an attempt ceiling, including denied/failed attempts.

    Failures after reservation do not refund. Storage failure after an effect
    must be surfaced as indeterminate, never rewritten as 'no effect happened'.
    """
    if (type(action) is not dict or action.get("operation") != "read_fixture"
            or action.get("resource") != "lab:public-fixture"):
        result = {"decision": "deny", "reasons": ["unsupported_effect_scope"]}
        broker.chain.append("durable-admission-denied", result)
        return result
    reason = store.reserve(action)
    if reason:
        result = {"decision": "deny", "reasons": [reason], "action_id": action.get("action_id")}
        broker.chain.append("durable-admission-denied", result)
        return result
    broker.chain.append("durable-reservation", {"action_id": action["action_id"], "binding": store.binding})
    result = broker.dispatch(action)
    store.finish(action, result)
    broker.chain.append("durable-finalization", {"action_id": action["action_id"], "decision": result["decision"]})
    return result
