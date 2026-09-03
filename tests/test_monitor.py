import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monitor import (  # noqa: E402
    RfiState,
    Urgency,
    build_notifications,
    classify_all,
    classify_rfi,
    classify_state,
    classify_urgency,
    group_by_responsible,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SANDBOX_RFIS = json.loads((FIXTURES / "rfis_sandbox.json").read_text(encoding="utf-8"))
# 2026-09-03 matches the date the fixture was exported (ambiente.md), so the
# due_date-relative assertions below line up with the recorded scenario.
TODAY = date(2026, 9, 3)


def rfi_by_number(rfis, number):
    return next(r for r in rfis if r["number"] == number)


def make_rfi(
    *,
    rfi_id=1,
    number="1",
    subject="subject",
    due_date="2026-09-03",
    status="open",
    time_resolved=None,
    ball_in_court=None,
    rfi_manager=None,
    answered=False,
):
    return {
        "id": rfi_id,
        "number": number,
        "subject": subject,
        "due_date": due_date,
        "status": status,
        "time_resolved": time_resolved,
        "ball_in_court": ball_in_court,
        "rfi_manager": rfi_manager,
        "questions": [
            {"body": "q", "answers": ["a"] if answered else []}
        ],
    }


ASSIGNEE = {"id": 100299, "name": "Test Architect"}
MANAGER = {"id": 99519, "name": "API Support"}


# ---------------------------------------------------------------------------
# classify_state
# ---------------------------------------------------------------------------

class TestClassifyState:
    def test_closed_by_status(self):
        rfi = make_rfi(status="closed")
        assert classify_state(rfi) == RfiState.CLOSED

    def test_closed_by_time_resolved(self):
        rfi = make_rfi(status="open", time_resolved="2026-09-02T20:05:29Z")
        assert classify_state(rfi) == RfiState.CLOSED

    def test_awaiting_reply_when_no_answers(self):
        rfi = make_rfi(answered=False)
        assert classify_state(rfi) == RfiState.AWAITING_REPLY

    def test_awaiting_acceptance_when_answered_but_open(self):
        rfi = make_rfi(answered=True, status="open", time_resolved=None)
        assert classify_state(rfi) == RfiState.AWAITING_ACCEPTANCE

    def test_real_closed_rfi_from_sandbox(self):
        rfi = rfi_by_number(SANDBOX_RFIS, "6")
        assert classify_state(rfi) == RfiState.CLOSED

    def test_real_open_rfis_from_sandbox_are_awaiting_reply(self):
        for number in ("1", "2", "3", "4", "5"):
            rfi = rfi_by_number(SANDBOX_RFIS, number)
            assert classify_state(rfi) == RfiState.AWAITING_REPLY


# ---------------------------------------------------------------------------
# classify_urgency
# ---------------------------------------------------------------------------

class TestClassifyUrgency:
    def test_overdue(self):
        assert classify_urgency(date(2026, 9, 1), TODAY) == Urgency.OVERDUE

    def test_due_today_is_critical(self):
        assert classify_urgency(TODAY, TODAY) == Urgency.CRITICAL

    def test_due_in_two_days_is_critical(self):
        assert classify_urgency(date(2026, 9, 5), TODAY) == Urgency.CRITICAL

    def test_due_in_three_days_is_attention(self):
        assert classify_urgency(date(2026, 9, 6), TODAY) == Urgency.ATTENTION

    def test_due_in_seven_days_is_attention(self):
        assert classify_urgency(date(2026, 9, 10), TODAY) == Urgency.ATTENTION

    def test_due_in_eight_days_is_fine(self):
        assert classify_urgency(date(2026, 9, 11), TODAY) == Urgency.FINE


# ---------------------------------------------------------------------------
# classify_rfi (single-RFI end-to-end: state + urgency + responsible)
# ---------------------------------------------------------------------------

class TestClassifyRfi:
    def test_closed_rfi_dropped(self):
        rfi = make_rfi(status="closed", due_date="2026-09-01")
        assert classify_rfi(rfi, TODAY) is None

    def test_fine_urgency_dropped(self):
        rfi = make_rfi(due_date="2026-09-20", ball_in_court=ASSIGNEE)
        assert classify_rfi(rfi, TODAY) is None

    def test_awaiting_reply_responsible_is_ball_in_court(self):
        rfi = make_rfi(
            due_date="2026-09-01", ball_in_court=ASSIGNEE, rfi_manager=MANAGER
        )
        result = classify_rfi(rfi, TODAY)
        assert result.state == RfiState.AWAITING_REPLY
        assert result.responsible_id == ASSIGNEE["id"]

    def test_awaiting_acceptance_responsible_is_rfi_manager(self):
        rfi = make_rfi(
            due_date="2026-09-01",
            answered=True,
            ball_in_court=ASSIGNEE,
            rfi_manager=MANAGER,
        )
        result = classify_rfi(rfi, TODAY)
        assert result.state == RfiState.AWAITING_ACCEPTANCE
        assert result.responsible_id == MANAGER["id"]

    def test_missing_responsible_dropped_not_crashed(self):
        # ball_in_court can be null in real Procore data (see rfis.json #6
        # after close) -- must not raise even on an overdue/open RFI.
        rfi = make_rfi(due_date="2026-09-01", ball_in_court=None)
        assert classify_rfi(rfi, TODAY) is None


# ---------------------------------------------------------------------------
# classify_all / group_by_responsible / build_notifications
# ---------------------------------------------------------------------------

class TestGroupingAndNotifications:
    def test_empty_input_produces_no_notifications(self):
        assert build_notifications([], TODAY) == {}

    def test_all_closed_or_fine_produces_no_notifications(self):
        rfis = [
            make_rfi(status="closed", due_date="2026-09-01"),
            make_rfi(due_date="2026-09-30", ball_in_court=ASSIGNEE),
        ]
        assert build_notifications(rfis, TODAY) == {}

    def test_groups_by_responsible_not_by_rfi(self):
        rfis = [
            make_rfi(
                rfi_id=1, number="1", due_date="2026-09-01", ball_in_court=ASSIGNEE
            ),
            make_rfi(
                rfi_id=2, number="2", due_date="2026-09-04", ball_in_court=ASSIGNEE
            ),
        ]
        groups = group_by_responsible(classify_all(rfis, TODAY))
        assert list(groups.keys()) == [ASSIGNEE["name"]]
        assert len(groups[ASSIGNEE["name"]]) == 2

    def test_awaiting_reply_and_acceptance_go_to_different_people(self):
        rfis = [
            make_rfi(
                rfi_id=1,
                number="1",
                due_date="2026-09-01",
                ball_in_court=ASSIGNEE,
                rfi_manager=MANAGER,
                answered=False,
            ),
            make_rfi(
                rfi_id=2,
                number="2",
                due_date="2026-09-01",
                ball_in_court=ASSIGNEE,
                rfi_manager=MANAGER,
                answered=True,
            ),
        ]
        groups = group_by_responsible(classify_all(rfis, TODAY))
        assert set(groups.keys()) == {ASSIGNEE["name"], MANAGER["name"]}

    def test_sorted_most_urgent_first_within_group(self):
        rfis = [
            make_rfi(
                rfi_id=1, number="1", due_date="2026-09-05", ball_in_court=ASSIGNEE
            ),
            make_rfi(
                rfi_id=2, number="2", due_date="2026-09-01", ball_in_court=ASSIGNEE
            ),
        ]
        groups = group_by_responsible(classify_all(rfis, TODAY))
        ordered_numbers = [c.number for c in groups[ASSIGNEE["name"]]]
        assert ordered_numbers == ["2", "1"]

    def test_message_mentions_state_label_for_awaiting_acceptance(self):
        rfis = [
            make_rfi(
                due_date="2026-09-01",
                ball_in_court=ASSIGNEE,
                rfi_manager=MANAGER,
                answered=True,
            )
        ]
        notifications = build_notifications(rfis, TODAY)
        message = notifications[MANAGER["name"]]
        assert "awaiting your acceptance" in message

    def test_real_sandbox_fixture_produces_expected_groups(self):
        # As of the 2026-09-02 export (see ambiente.md): #1 overdue/open,
        # #2 overdue/open, #3 due today, #4 due in 1 day, #5 due in 9 days
        # (dropped, > 7 days out), #6 closed (dropped). All open ones have
        # no answers yet -> awaiting_reply, responsible = ball_in_court.
        notifications = build_notifications(SANDBOX_RFIS, TODAY)
        # RFI #5 is due 2026-09-12 (9 days out from 2026-09-03) -> fine, dropped.
        all_numbers = "".join(notifications.values())
        assert "#5" not in all_numbers
        assert "#6" not in all_numbers
        assert notifications  # #1-4 should produce at least one notification
