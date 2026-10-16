"""Predict & Win tests. Run: python -m unittest tests.test_predict -v"""
import os
import tempfile
import time
import unittest

_tmp = tempfile.mkdtemp()
os.environ["AGENT_DB"] = os.path.join(_tmp, "test.db")
os.environ.pop("DASHBOARD_TOKEN", None)

from core import predict, store  # noqa: E402
from platforms import eventweb  # noqa: E402

try:
    from platforms import dashboard  # noqa: E402
except Exception:  # dashboard imports optional AI SDKs; admin tests are skipped without them
    dashboard = None


def reset():
    c = store.conn()
    with store._lock:
        c.executescript("DELETE FROM pw_players; DELETE FROM pw_questions; DELETE FROM pw_picks; DELETE FROM kv WHERE key='pw_settings';")
        c.commit()
    predict._bust()


class PredictTests(unittest.TestCase):
    def setUp(self):
        predict._db()
        reset()
        predict.save_settings(show_leaderboard=True)
        self.web = eventweb.app.test_client()

    def join(self, handle, name="Player", ip="1.1.1.1"):
        r = self.web.post("/predict/api/join", json={"handle": handle, "name": name, "consent": True},
                          headers={"CF-Connecting-IP": ip + handle})
        return r

    def tok(self, handle):
        r = self.join(handle)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()["token"]

    class _R:
        def __init__(self, code):
            self.status_code = code

    def pick(self, tok, qid, opt):
        """Single pick through the game logic (the public API only takes full submissions)."""
        try:
            predict.pick(tok, qid, opt)
            return self._R(200)
        except predict.GameError as e:
            return self._R(e.code)

    def test_join_normalises_and_stores_only_hash(self):
        r = self.join("https://www.instagram.com/Some.Player_1/?hl=en")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertEqual(j["player"]["handle"], "some.player_1")
        row = store.conn().execute("SELECT token_hash FROM pw_players").fetchone()
        self.assertNotEqual(row["token_hash"], j["token"])
        self.assertEqual(len(row["token_hash"]), 64)
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_join_requires_consent_and_valid_handle(self):
        r = self.web.post("/predict/api/join", json={"handle": "abc", "name": "A", "consent": False})
        self.assertEqual(r.status_code, 400)
        r = self.web.post("/predict/api/join", json={"handle": "bad handle!", "name": "A", "consent": True})
        self.assertEqual(r.status_code, 400)

    def test_duplicate_handle_rejected_until_released(self):
        self.tok("dup")
        r = self.join("@DUP", ip="2.2.2.2")
        self.assertEqual(r.status_code, 409)
        pid = store.conn().execute("SELECT id FROM pw_players WHERE handle='dup'").fetchone()["id"]
        predict.player_action(pid, "release")
        self.assertEqual(self.join("dup", ip="3.3.3.3").status_code, 200)

    def test_pick_before_close_and_rejected_after(self):
        t = self.tok("alice")
        qid = predict.add_question("other", "Q?", ["A", "B"], time.time() + 3600)
        self.assertEqual(self.pick(t, qid, "Z").status_code, 400)        # not an option
        self.assertEqual(self.pick(t, qid, "B").status_code, 200)
        self.assertEqual(self.pick(t, qid, "A").status_code, 409)        # picks are final
        predict.update_question(qid, "close_ts", time.time() - 1)
        r = self.pick(t, qid, "A")
        self.assertEqual(r.status_code, 409)
        me = self.web.post("/predict/api/me", json={}, headers={"X-PW-Token": t}).get_json()
        self.assertEqual(me["picks"][str(qid)], "B")
        self.assertEqual(self.pick("wrong-token", qid, "A").status_code, 401)

    def test_lock_now_rejects_picks(self):
        t = self.tok("bob")
        qid = predict.add_question("other", "Q?", ["A", "B"], time.time() + 3600)
        predict.update_question(qid, "lock")
        self.assertEqual(self.pick(t, qid, "A").status_code, 409)
        predict.update_question(qid, "reopen")
        self.assertEqual(self.pick(t, qid, "A").status_code, 200)

    def test_resolve_and_underdog_scoring(self):
        toks = [self.tok(f"p{i}") for i in range(4)]
        qid = predict.add_question("other", "Q?", ["A", "B"], time.time() + 3600)
        self.pick(toks[0], qid, "A")
        for t in toks[1:]:
            self.pick(t, qid, "B")
        predict.update_question(qid, "close_ts", time.time() - 1)
        predict.resolve(qid, "A")
        b = self.web.get("/predict/api/board").get_json()
        top = b["boards"]["all"]
        self.assertEqual(top[0]["handle"], "p0")
        self.assertEqual(top[0]["pts"], 175)          # 100 + 100 * (1 - 1/4)
        self.assertEqual(len(top), 1)                 # zero-point players are not listed
        q = next(q for q in b["questions"] if q["id"] == qid)
        self.assertEqual(q["worth"], 175)

    def test_top10_and_day_boards(self):
        toks = [self.tok(f"u{i:02d}") for i in range(12)]
        q1 = predict.add_question("match", "D1", ["A", "B"], time.time() + 3600, day=1)
        q2 = predict.add_question("match", "D2", ["A", "B"], time.time() + 3600, day=2)
        for t in toks:
            self.pick(t, q1, "A")
        self.pick(toks[5], q2, "B")
        for q in (q1, q2):
            predict.update_question(q, "close_ts", time.time() - 1)
        predict.resolve(q1, "A")
        predict.resolve(q2, "B")
        b = self.web.get("/predict/api/board").get_json()
        self.assertEqual(len(b["boards"]["all"]), 10)
        self.assertEqual(b["boards"]["all"][0]["handle"], "u05")
        self.assertEqual([r["handle"] for r in b["boards"]["2"]], ["u05"])
        me = self.web.post("/predict/api/me", json={}, headers={"X-PW-Token": toks[11]}).get_json()
        self.assertEqual(me["ranks"]["all"]["rank"], 12)      # ties: earlier joiners rank higher

    def test_profile_hides_open_picks(self):
        t = self.tok("carol")
        open_q = predict.add_question("other", "Open", ["A", "B"], time.time() + 3600)
        shut_q = predict.add_question("other", "Shut", ["A", "B"], time.time() + 3600)
        self.pick(t, open_q, "A")
        self.pick(t, shut_q, "B")
        predict.update_question(shut_q, "lock")
        p = self.web.get("/predict/api/profile/carol").get_json()
        titles = [x["title"] for x in p["picks"]]
        self.assertEqual(titles, ["Shut"])
        self.assertEqual(self.web.get("/predict/api/profile/nobody").status_code, 404)

    def test_hidden_players_leave_board(self):
        t = self.tok("mal")
        qid = predict.add_question("other", "Q", ["A", "B"], time.time() + 3600)
        self.pick(t, qid, "A")
        predict.update_question(qid, "answer", "A")
        pid = store.conn().execute("SELECT id FROM pw_players WHERE handle='mal'").fetchone()["id"]
        predict.player_action(pid, "hide")
        self.assertEqual(predict.board()["boards"]["all"], [])

    def test_create_match_day_makes_six(self):
        ids = predict.create_match_day(1)
        self.assertEqual(len(ids), 6)
        qs = predict.questions()
        self.assertEqual(qs[0]["title"], "Day 1 · Match 1: Who wins?")
        self.assertEqual(len(qs[0]["options"]), 16)
        self.assertEqual(qs[0]["style"], "dropdown")
        self.assertEqual(qs[0]["close_ts"], predict.ist_ts("2026-10-16", "16:00"))
        self.assertEqual(predict.create_match_day(1), [])     # no duplicates

    def test_tracker_resolution(self):
        qid = predict.create_peak(1)
        st = {"peak": 812000, "days": [{"day": "Fri 16 Oct", "peak": 455000}], "official_live": False,
              "last_broadcast": {"end": predict.ist_ts("2026-10-16", "20:00")}}
        q = predict.get_question(qid)
        self.assertEqual(predict.tracker_answer(q, st), "400K-500K")
        ev_peak = predict.add_question("peak", "Tournament peak", predict.bucket_labels(), time.time() - 1, 0, "PEAK",
                                       meta={"scope": "event", "buckets": predict.settings()["buckets"], "date": "2026-10-18"})
        self.assertEqual(predict.tracker_answer(predict.get_question(ev_peak), st), "800K-850K")
        rec = predict.create_record()
        self.assertEqual(predict.tracker_answer(predict.get_question(rec), st), "Yes")
        done = predict.auto_resolve(st, now=predict.ist_ts("2026-10-16", "20:31"))
        self.assertEqual(done, [qid])
        self.assertEqual(predict.get_question(qid)["answer"], "400K-500K")

    def test_event_and_day_sets(self):
        ids = predict.create_event_set()
        self.assertEqual(len(ids), 8)
        self.assertEqual(predict.create_event_set(), [])
        for qid in ids:                                  # everything closes 4 PM IST on Day 1
            self.assertEqual(predict.get_question(qid)["close_ts"], predict.ist_ts("2026-10-16", "16:00"))
        peak = predict.get_question(ids[-1])
        self.assertEqual(peak["options"][0], "Under 400K")
        self.assertIn("800K-850K", peak["options"])
        self.assertEqual(peak["options"][-1], "850K+")
        predict.add_question("team", "Old question", ["A", "B"], time.time() + 99)
        r = predict.sync_event_set()
        self.assertEqual(r["removed"], ["Old question"])
        self.assertEqual(len(predict.questions()), 8)

    def test_multi_pick_scoring(self):
        a, b = self.tok("ma"), self.tok("mb")
        qid = predict.add_question("multi", "Top 3", ["A", "B", "C", "D", "E"], time.time() + 3600, 0, "TOP 3",
                                   meta={"pick": 3})
        self.assertEqual(self.pick(a, qid, ["A", "B"]).status_code, 400)       # must pick exactly 3
        self.assertEqual(self.pick(a, qid, ["A", "B", "C"]).status_code, 200)
        self.assertEqual(self.pick(b, qid, ["A", "D", "E"]).status_code, 200)
        predict.update_question(qid, "lock")
        predict.resolve(qid, ["A", "B", "D"])
        top = predict.board()["boards"]["all"]
        pts = {r["handle"]: r["pts"] for r in top}
        # A: picked by 2/2 -> 100/3 each; B: 1/2 -> 150/3; D: 1/2 -> 150/3
        self.assertEqual(pts["ma"], round(100 / 3 + 150 / 3))
        self.assertEqual(pts["mb"], round(100 / 3 + 150 / 3))

    def test_ranked_top3_keeps_tap_order(self):
        t = self.tok("rk")
        ids = predict.create_event_set()
        top3 = ids[1]
        self.assertEqual(self.pick(t, top3, ["Soul", "GodLike", "Nebula"]).status_code, 200)
        me = self.web.post("/predict/api/me", json={}, headers={"X-PW-Token": t}).get_json()
        self.assertEqual(me["picks"][str(top3)], ["Soul", "GodLike", "Nebula"])
        self.assertEqual(self.pick(t, top3, ["Soul", "GodLike", "TAG"]).status_code, 409)

    def test_text_answer_matching(self):
        a, b, c = self.tok("ta"), self.tok("tb"), self.tok("tc")
        qid = predict.add_question("text", "Top eliminator", [], time.time() + 3600, 0, "TOP ELIMINATOR")
        self.pick(a, qid, "Jonathan ")
        self.pick(b, qid, "jonathan")
        self.pick(c, qid, "Goblin")
        self.assertEqual(predict.board()["questions"][0]["pct"], {})        # hidden until locked (and < 20 players)
        predict.update_question(qid, "lock")
        predict.resolve(qid, "Jonathan, Jonny")
        pts = {r["handle"]: r["pts"] for r in predict.board()["boards"]["all"]}
        self.assertEqual(pts, {"ta": 133, "tb": 133})

    def test_public_board_hides_player_numbers(self):
        a, b, c = self.tok("na"), self.tok("nb"), self.tok("nc")
        qid = predict.add_question("other", "Q", ["A", "B"], time.time() + 3600)
        self.pick(a, qid, "A"); self.pick(b, qid, "A"); self.pick(c, qid, "B")
        j = self.web.get("/predict/api/board").get_json()
        self.assertNotIn("players", j)
        q = j["questions"][0]
        self.assertNotIn("counts", q); self.assertNotIn("total", q)
        self.assertEqual(q["pct"], {})                       # hidden below 20 players
        predict.MIN_CROWD = 3
        try:
            predict._bust()
            q = self.web.get("/predict/api/board?x=1").get_json()["questions"][0]
            self.assertEqual(q["pct"], {})                   # open question: only players who answered see it
            me = self.web.post("/predict/api/me", json={}, headers={"X-PW-Token": a}).get_json()
            self.assertEqual(me["crowd"][str(qid)], {"A": 67, "B": 33})
            predict.update_question(qid, "lock")
            q = self.web.get("/predict/api/board?x=2").get_json()["questions"][0]
            self.assertEqual(q["pct"], {"A": 67, "B": 33})
        finally:
            predict.MIN_CROWD = 20
        me = self.web.post("/predict/api/me", json={}, headers={"X-PW-Token": a}).get_json()
        self.assertNotIn("of", me)

    def test_one_account_per_connection(self):
        r1 = self.web.post("/predict/api/join", json={"handle": "first", "consent": True}, headers={"CF-Connecting-IP": "9.9.9.9"})
        r2 = self.web.post("/predict/api/join", json={"handle": "second", "consent": True}, headers={"CF-Connecting-IP": "9.9.9.9"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 409)
        row = store.conn().execute("SELECT net FROM pw_players WHERE handle='first'").fetchone()
        self.assertNotIn("9.9.9.9", row["net"])                 # only a keyed hash is kept

    def test_submit_requires_every_question(self):
        t = self.tok("sub")
        q1 = predict.add_question("other", "Q1", ["A", "B"], time.time() + 3600)
        q2 = predict.add_question("multi", "Q2", ["A", "B", "C", "D"], time.time() + 3600, meta={"pick": 2})
        h = {"X-PW-Token": t}
        r = self.web.post("/predict/api/submit", json={"picks": {str(q1): "A"}}, headers=h)
        self.assertEqual(r.status_code, 400)
        r = self.web.post("/predict/api/submit", json={"picks": {str(q1): "A", str(q2): ["A"]}}, headers=h)
        self.assertEqual(r.status_code, 400)                    # multi needs exactly 2
        self.assertEqual(store.conn().execute("SELECT COUNT(*) FROM pw_picks").fetchone()[0], 0)
        r = self.web.post("/predict/api/submit", json={"picks": {str(q1): "A", str(q2): ["B", "C"]}}, headers=h)
        self.assertEqual(r.status_code, 200)
        r = self.web.post("/predict/api/submit", json={"picks": {str(q1): "B", str(q2): ["A", "C"]}}, headers=h)
        self.assertEqual(r.status_code, 409)                    # nothing left; picks are final
        self.assertEqual(self.web.post("/predict/api/pick", json={"qid": q1, "option": "B"}, headers=h).status_code, 404)

    def test_leaderboard_hidden_until_owner_turns_it_on(self):
        predict.save_settings(show_leaderboard=False)
        j = self.web.get("/predict/api/board?lb=1").get_json()
        self.assertFalse(j["leaderboard"])
        self.assertEqual(j["boards"], {})

    def test_display_name_optional(self):
        r = self.web.post("/predict/api/join", json={"handle": "noname", "name": "", "consent": True},
                          headers={"CF-Connecting-IP": "8.8.4.4"})
        self.assertEqual(r.status_code, 200)

    def test_public_cache_headers(self):
        self.assertIn("max-age=5", self.web.get("/predict/api/board").headers["Cache-Control"])
        r = self.web.get("/predict")
        self.assertIn('property="og:image"', r.get_data(as_text=True))

    @unittest.skipIf(dashboard is None, "dashboard dependencies not installed")
    def test_admin_local_only(self):
        c = dashboard.app.test_client()
        self.assertEqual(c.get("/predict", environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code, 403)
        self.assertEqual(c.post("/api/predict/matchday", json={"day": 1},
                                environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code, 403)
        r = c.post("/api/predict/matchday", json={"day": 2}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["created"]), 6)
        self.assertEqual(c.get("/predict", environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
