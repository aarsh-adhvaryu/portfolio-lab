"""S85 E6: Telegram upgraded. A fake Bot API (tests/fake_telegram.py) and stand-ins for the chat agent's entrance (tests/stub_entrance.py); no network, no model."""
import threading
from datetime import datetime

import duckdb
import pytest

from fake_telegram import FakeTelegram
from stub_entrance import StubCards, StubGateway, StubIntake, StubStore

from pflab.hq import phone, rules
from pflab.pm import store
from pflab.service import bot, tg_api, tg_entrance, telegram as tgm
from pflab.service.tg_entrance import Entrance, _Mods

NOW = datetime(2026, 11, 13, 9, 0)
PDF = b"%PDF-1.4 synthetic test pdf"


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


@pytest.fixture
def fake():
    return FakeTelegram()


def make(fake, tmp_path, *, intake=None, **mods):
    mm = {"intake": intake or StubIntake(), "store": StubStore(), "cards": StubCards(), "gateway": StubGateway(), **mods}
    api = tg_api.TgApi(fake.token, fake.chat_id, fake.transport, fake.downloader, sleep=lambda s: None)
    ent = Entrance(api, 42, mods=_Mods(**mm), legacy=lambda t: f"legacy: {t}", inbox_dir=tmp_path / "inbox")
    return ent, mm


def run(con, fake, ent, now=NOW):
    ups, fake.queue = fake.queue, []
    return bot.process(con, ups, "42", lambda t: None, lambda t: "OLD PATH", now, entrance=ent)


# ---- files ---------------------------------------------------------------------------------------------------------------------

def test_a_pdf_is_downloaded_handed_to_the_intake_and_the_reply_is_posted_on_telegram(con, fake, tmp_path):
    def script(call):
        call["reply"]("Reading the document", call["msg_id"], False)
        call["reply"]("Read it: linked to the Synthetic Co storyline.", call["msg_id"], True)
    intake = StubIntake(script)
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_document(1, "results q2.pdf", PDF, caption="what changes for me?")
    run(con, fake, ent)
    (c,) = intake.calls
    assert c["channel"] == "telegram" and c["text"] == "what changes for me?" and c["model"] is None and c["thinking"] is None
    assert c["attachments"][0]["name"] == "results q2.pdf" and c["attachments"][0]["mime"] == "application/pdf"
    assert c["seen_bytes"] == [PDF]                                                     # the file was in place while the intake worked
    assert fake.texts() == ["Read it: linked to the Synthetic Co storyline."]           # the progress line was deleted, the answer stays
    assert [m["deleted"] for m in fake.shown] == [True, False]
    assert not (tmp_path / "inbox" / "1").exists()                                      # the scratch copy is gone once the intake has answered
    assert con.execute("SELECT kind, outcome FROM tg_files_s85").fetchone() == ("document", "downloaded")
    assert tgm.undelivered(con) == 0


def test_a_photo_goes_in_its_largest_size(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_photo(2, b"\xff\xd8 big jpeg bytes", caption="the chart")
    run(con, fake, ent)
    (c,) = intake.calls
    assert c["attachments"][0]["name"] == "photo_2.jpg" and c["attachments"][0]["mime"] == "image/jpeg" and c["seen_bytes"] == [b"\xff\xd8 big jpeg bytes"]


def test_a_25_mb_file_gets_the_laptop_line_and_is_not_downloaded(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_document(3, "huge.pdf", b"x", size=25 * 1024 * 1024)
    run(con, fake, ent)
    assert fake.texts() == [tg_entrance.BIG_LINE] and "send it from the laptop" in tg_entrance.BIG_LINE
    assert "getFile" not in fake.methods() and not fake.downloaded and not intake.calls
    assert con.execute("SELECT outcome FROM tg_files_s85").fetchone()[0] == "too_big"


def test_a_file_whose_size_is_unknown_and_refused_by_getfile_also_gets_the_line(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_document(4, "huge.pdf", b"x", size=None)
    fake.files["file-4"]["too_big"] = True
    run(con, fake, ent)
    assert fake.texts() == [tg_entrance.BIG_LINE] and not fake.downloaded and not intake.calls


def test_a_voice_note_gets_one_line(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_voice(5)
    run(con, fake, ent)
    assert fake.texts() == [tg_entrance.VOICE_LINE] and not intake.calls and "getFile" not in fake.methods()


def test_a_failed_download_says_so_and_the_intake_is_not_called(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_document(6, "a.pdf", PDF)
    fake.downloader = lambda url, dest, mx: (_ for _ in ()).throw(RuntimeError("socket closed"))
    ent.api.downloader = fake.downloader
    run(con, fake, ent)
    assert fake.texts() == [tg_entrance.FETCH_LINE] and not intake.calls
    assert con.execute("SELECT outcome FROM tg_files_s85").fetchone()[0] == "fetch_failed"


def test_an_intake_that_cannot_take_a_message_is_told_plainly_and_the_scratch_file_goes(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path, intake=StubIntake(raises=RuntimeError("queue closed")))
    fake.add_document(7, "a.pdf", PDF)
    run(con, fake, ent)
    assert fake.texts() == [tg_entrance.BUSY_LINE] and not list((tmp_path / "inbox").rglob("*.pdf"))


def test_a_refused_file_is_not_kept_in_the_scratch_folder(con, fake, tmp_path):
    """The intake refuses a personal statement and answers once: the scratch copy must be gone then (nothing of it is stored by this window)."""
    def script(call):
        call["reply"]("That looks like a bank statement; I do not read those.", call["msg_id"], True)
    ent, _ = make(fake, tmp_path, intake=StubIntake(script))
    fake.add_document(8, "statement.pdf", PDF)
    run(con, fake, ent)
    assert not list((tmp_path / "inbox").rglob("*.pdf")) and fake.texts() == ["That looks like a bank statement; I do not read those."]


# ---- text, replies, progress ---------------------------------------------------------------------------------------------------

def test_plain_words_go_to_the_intake_not_the_old_path(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_text(10, "why did gold fall today?")
    assert run(con, fake, ent) == 0
    assert intake.calls[0]["text"] == "why did gold fall today?" and intake.calls[0]["channel"] == "telegram" and not fake.shown


def test_progress_is_one_message_edited_in_place_and_the_final_answer_is_a_new_message(fake, tmp_path):
    t = [0.0]
    ent, _ = make(fake, tmp_path)
    ent._mono = lambda: t[0]
    reply = ent.make_reply()
    reply("Reading", 77, False)
    t[0] = 0.5
    reply("Checking 3 sources", 77, False)                                           # too soon after the last edit: skipped, not queued
    t[0] = 3.0
    reply("Checking 3 sources", 77, False)
    t[0] = 6.0
    reply("The answer: nothing changes for you.", 77, True)
    assert fake.methods().count("sendMessage") == 2 and fake.methods().count("editMessageText") == 1
    assert [m["text"] for m in fake.shown] == ["Checking 3 sources", "The answer: nothing changes for you."]
    assert [m["deleted"] for m in fake.shown] == [True, False]


def test_a_long_answer_is_split_at_4096(fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    long = "\n".join(f"line {i}: " + "x" * 90 for i in range(130))
    ent.make_reply()(long, 5, True)
    parts = fake.texts()
    assert len(parts) >= 3 and all(len(p) <= 4096 for p in parts) and "\n".join(parts) == long


def test_actions_become_buttons_on_the_final_answer(fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    ent.make_reply()("Pause gold buys until 20 Nov?", 5, True, actions=[{"id": "undo:12", "label": "Undo"}])
    kb = fake.shown[-1]["markup"]["inline_keyboard"]
    assert kb == [[{"text": "Undo", "callback_data": "undo:12"}]]


def test_a_reply_never_raises_into_the_worker_and_a_send_is_retried_once(fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    fake.fail("sendMessage", 1)
    ent.make_reply()("Hello", 1, True)                                               # first send fails (network), the retry delivers
    assert fake.texts() == ["Hello"]
    fake.fail("sendMessage", 5)
    ent.make_reply()("Lost to the network", 2, True)                                 # no exception; the chat store still holds it
    assert fake.texts() == ["Hello"]


def test_the_token_never_appears_in_an_error(fake):
    api = tg_api.TgApi(fake.token, 42, fake.transport, fake.downloader, sleep=lambda s: None)
    fake.fail("sendMessage", 1)
    with pytest.raises(tg_api.TgError) as e:
        api.send_message("x")
    assert "TOK-SECRET" not in str(e.value) and "ConnectionError" in str(e.value)


# ---- commands --------------------------------------------------------------------------------------------------------------------------

def test_new_starts_a_new_telegram_chat(con, fake, tmp_path):
    ent, mm = make(fake, tmp_path)
    fake.add_text(20, "/new")
    run(con, fake, ent)
    assert mm["store"].new_chats == [("New chat", "telegram")] and "New chat started" in fake.texts()[0]


def test_model_opus_then_a_message_uses_opus(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_text(30, "/model opus")
    fake.add_text(31, "/think high")
    fake.add_text(32, "should I change my gold share?")
    run(con, fake, ent)
    assert intake.calls[0]["model"] == "opus" and intake.calls[0]["thinking"] == "high"
    fake.add_text(33, "/model auto")
    fake.add_text(34, "/think auto")
    fake.add_text(35, "and now?")
    run(con, fake, ent, NOW)
    assert intake.calls[1]["model"] is None and intake.calls[1]["thinking"] is None


def test_model_names_resolve_by_key_or_model_id_and_unknown_is_refused(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    fake.add_text(40, "/model claude-haiku-5-5")
    fake.add_text(41, "/model gpt-9")
    fake.add_text(42, "/think extreme")
    run(con, fake, ent)
    assert ent.prefs(con) == ("haiku", None)
    t = fake.texts()
    assert "No model called gpt-9" in t[1] and "haiku, sonnet, opus" in t[1] and "low, medium, high, max" in t[2]


def test_model_alone_shows_a_picker_and_a_press_sets_it(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    fake.add_text(50, "/model")
    run(con, fake, ent)
    kb = fake.shown[0]["markup"]["inline_keyboard"]
    assert [b["callback_data"] for b in kb[0]] == ["mdl:auto", "mdl:haiku", "mdl:sonnet", "mdl:opus"]
    assert [b["callback_data"] for b in kb[1]] == ["thk:low", "thk:medium", "thk:high", "thk:max", "thk:auto"]
    fake.add_callback(51, "mdl:sonnet", message_id=fake.shown[0]["id"])
    fake.add_callback(52, "thk:max", message_id=fake.shown[0]["id"])
    run(con, fake, ent)
    assert ent.prefs(con) == ("sonnet", "max")
    assert "Model: sonnet. Thinking: max." in fake.shown[0]["text"] and fake.shown[0]["edits"] == 2 and len(fake.answered) == 2


def test_the_picker_lists_the_models_of_the_engine_in_use(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path, gateway=StubGateway(models=[{"key": "mini", "model": "x-mini"}, {"key": "big", "model": "x-big"}], engine="other"))
    fake.add_text(60, "/model")
    run(con, fake, ent)
    assert [b["callback_data"] for b in fake.shown[0]["markup"]["inline_keyboard"][0]] == ["mdl:auto", "mdl:mini", "mdl:big"]


def test_help_status_and_retired_commands(con, fake, tmp_path):
    intake = StubIntake()
    intake.queue = [{"state": "working", "progress": "reading results.pdf"}, {"state": "done", "progress": ""}]
    ent, _ = make(fake, tmp_path, intake=intake)
    for i, t in enumerate(["/help", "/status", "/networth", "/research SYN", "/calc 2+2", "/memory gold"], start=70):
        fake.add_text(i, t)
    run(con, fake, ent)
    help_, status, nw, rs, calc, mem = fake.texts()
    assert all(c in help_ for c in ("/new", "/model", "/think", "/status", "/help")) and "/networth" not in help_ and "/research" not in help_
    assert "Working on 1 thing" in status and "reading results.pdf" in status and "Engine in use: claude" in status
    assert nw == rs == calc == tg_entrance.UNKNOWN_LINE
    assert mem == "legacy: /memory gold"                                                  # a kept command goes to the legacy path
    assert con.execute("SELECT count(*) FROM outbox WHERE kind='reply' AND status='sent'").fetchone()[0] == 6


# ---- buttons ---------------------------------------------------------------------------------------------------------------------------

def test_a_yes_on_a_card_answers_it_and_removes_the_buttons(con, fake, tmp_path):
    ent, mm = make(fake, tmp_path)
    fake.add_callback(80, "card:7:yes", message_id=5)
    fake.add_callback(81, "card:8:no", message_id=6)
    run(con, fake, ent)
    assert mm["cards"].answers == [(7, "yes", "telegram"), (8, "no", "telegram")]
    assert [m for c, m in fake.calls if c == "editMessageReplyMarkup"] and fake.answered[0][1] == "Noted: Yes."
    assert "Noted: Yes." in fake.texts()


def test_a_card_that_fails_tells_him_and_nothing_breaks(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path, cards=StubCards(raises=LookupError("gone")))
    fake.add_callback(82, "card:9:yes")
    assert run(con, fake, ent) == 1 and "that button failed" in fake.texts()[0]


def test_undo_on_a_rule_message_undoes_it(con, fake, tmp_path):
    r = rules.propose(con, NOW, "note", "Prefer large companies for the next quarter", {})
    assert r["made"]
    ent, _ = make(fake, tmp_path)
    fake.add_callback(90, f"undo:{r['rule_id']}")
    run(con, fake, ent)
    assert con.execute("SELECT status FROM hq_rules WHERE rule_id=?", [r["rule_id"]]).fetchone()[0] == "undone"
    assert "Undone" in fake.texts()[0]
    fake.add_callback(91, f"undo:{r['rule_id']}")
    run(con, fake, ent)
    assert "Nothing to undo" in fake.texts()[1]


def test_buttons_from_the_outbox_use_the_ids_this_module_answers(con, fake, tmp_path):
    """A proactive message with Yes/No goes out through the outbox with `actions_to_buttons`; pressing Yes reaches the card."""
    tgm.enqueue_with_buttons(con, "Change the gold target?", "question", tg_entrance.actions_to_buttons(
        [{"id": "card:21:yes", "label": "Yes"}, {"id": "card:21:no", "label": "No"}]), dedup_key="card:21", now=NOW)
    send = tgm.make_sender(type("S", (), {"has": lambda s, a, b: True, "get": lambda s, a, b: "TOK-SECRET" if b == "token" else "42", "redact": lambda s, t: t})(), fake.transport)
    assert tgm.flush(con, send, NOW)["sent"] == 1
    kb = fake.shown[0]["markup"]["inline_keyboard"]
    assert [b[0]["callback_data"] for b in kb] == ["card:21:yes", "card:21:no"]
    ent, mm = make(fake, tmp_path)
    fake.add_callback(95, kb[0][0]["callback_data"], message_id=fake.shown[0]["id"])
    run(con, fake, ent)
    assert mm["cards"].answers == [(21, "yes", "telegram")]


def test_the_old_question_buttons_still_reach_the_voice(con, fake, tmp_path):
    from pflab.agents import questions, voice
    q = questions.ask(con, "paper", "k1", "Hold the gold ETF?", NOW, default="keep", options=["keep", "sell"])
    ent, mm = make(fake, tmp_path)
    fake.add_callback(96, f"q:{q}:1")
    ups, fake.queue = fake.queue, []
    sent = []
    bot.process(con, ups, "42", sent.append, lambda t: "x", NOW, ack=lambda i, t: None, entrance=ent)
    assert voice.effective(con, "k1") == ("sell", "him") and mm["cards"].answers == []


# ---- who is served ---------------------------------------------------------------------------------------------------------------------

def test_only_his_chat_is_served(con, fake, tmp_path):
    intake = StubIntake()
    ent, mm = make(fake, tmp_path, intake=intake)
    fake.add_text(100, "send me everything", chat=99)
    fake.add_document(101, "a.pdf", PDF, chat=99)
    fake.add_text(102, "/new", chat=99)
    fake.add_callback(103, "card:7:yes", chat=99)
    fake.add_voice(104, chat=99)
    assert run(con, fake, ent) == 0
    assert not intake.calls and not mm["store"].new_chats and not mm["cards"].answers and not fake.shown and "getFile" not in fake.methods() and not fake.downloaded
    rows = con.execute("SELECT update_id, accepted, command FROM bot_updates ORDER BY 1").fetchall()
    assert rows == [(100, False, None), (101, False, None), (102, False, None), (103, False, None), (104, False, None)]       # logged, no text kept


def test_a_sticker_from_him_is_ignored_quietly(con, fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    fake.queue.append({"update_id": 110, "message": {"chat": {"id": 42}, "sticker": {"file_id": "s"}}})
    assert run(con, fake, ent) == 0 and not fake.shown


def test_each_update_is_handled_once(con, fake, tmp_path):
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    fake.add_text(120, "hello")
    ups = list(fake.queue)
    bot.process(con, ups, "42", lambda t: None, lambda t: "x", NOW, entrance=ent)
    bot.process(con, ups, "42", lambda t: None, lambda t: "x", NOW, entrance=ent)
    assert len(intake.calls) == 1


# ---- the poll ----------------------------------------------------------------------------------------------------------------------------

class RT:
    def __init__(self, con, tmp_path, fake):
        self._con, self.pm_dir = con, tmp_path
        self.settings = {"telegram_send": True}
        self.secrets = type("S", (), {"has": lambda s, a, b: True, "get": lambda s, a, b: fake.token if b == "token" else "42", "redact": lambda s, t: t})()

    def cursor(self):
        return self._con

    def clock(self):
        return NOW


def test_poll_once_runs_the_whole_path(con, fake, tmp_path):
    def script(call):
        call["reply"]("Reading", call["msg_id"], False)
        call["reply"]("Done: nothing new for you.", call["msg_id"], True)
    intake = StubIntake(script)
    ent, _ = make(fake, tmp_path, intake=intake)
    rt = RT(con, tmp_path, fake)
    fake.add_document(130, "note.pdf", PDF, caption="read this")
    phone.poll_once(rt, transport=fake.transport, entrance=ent)
    assert intake.calls[0]["text"] == "read this" and fake.texts() == ["Done: nothing new for you."]


def test_without_an_entrance_the_old_reply_path_serves(con, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(tg_entrance, "for_runtime", lambda *a, **k: None)         # the intake is not there (or Telegram is not set up)
    rt = RT(con, tmp_path, fake)
    fake.add_text(140, "/help")
    fake.add_text(141, "/networth")                                                  # retired: the bot's own handle says so
    assert phone.poll_once(rt, transport=fake.transport, entrance=None) == 2
    assert fake.texts()[0].startswith("Ask me anything") and fake.texts()[1].startswith("I don't know that command")


def test_the_phone_loop_survives_network_errors_and_backs_off(con, fake, tmp_path, monkeypatch):
    from pflab import guard
    monkeypatch.setattr(guard, "blocked", lambda *a, **k: None)
    monkeypatch.setattr(bot, "poll_transport", fake.transport)
    intake = StubIntake()
    ent, _ = make(fake, tmp_path, intake=intake)
    rt = RT(con, tmp_path, fake)
    rt._tg_entrance = ent
    fake.fail("getUpdates", 2)
    fake.add_text(150, "still there?")

    class Stop:
        def __init__(self):
            self.waits, self.polls = [], 0

        def is_set(self):
            return bool(intake.calls) or len(self.waits) > 6

        def wait(self, n):
            self.waits.append(n)

    stop = Stop()
    assert phone.loop(rt, stop, lock_path=tmp_path / "bot.lock") is None
    assert stop.waits == [5.0, 10.0] and intake.calls[0]["text"] == "still there?"           # two failures, doubling pauses, then the message is served


def test_for_runtime_needs_the_intake_and_keeps_one_entrance(fake, tmp_path):
    rt = RT(None, tmp_path, fake)
    assert tg_entrance.for_runtime(rt, fake.transport, None, _Mods(intake=object())) is None          # no submit(): the old path serves
    assert tg_entrance.for_runtime(rt, fake.transport, None, _Mods(intake=StubIntake())) is not None


def test_scratch_files_a_crash_left_behind_are_swept_after_a_day(fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    old = tmp_path / "inbox" / "1"
    old.mkdir(parents=True)
    (old / "a.pdf").write_bytes(PDF)
    import os
    stamp = (NOW.timestamp()) - 3 * 86400
    os.utime(old / "a.pdf", (stamp, stamp))
    os.utime(old, (stamp, stamp))
    ent.sweep_inbox(NOW)
    assert not old.exists()


def test_threads_can_reply_at_once(fake, tmp_path):
    ent, _ = make(fake, tmp_path)
    ts = [threading.Thread(target=lambda i=i: ent.make_reply()(f"answer {i}", 1000 + i, True)) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(fake.texts()) == sorted(f"answer {i}" for i in range(20))
