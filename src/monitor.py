#!/usr/bin/env python3
"""
monitor.py
==========

RFI deadline monitor for the Procore API.

Classifies each RFI into one of three states and notifies the person who
actually has to act next -- not whoever `ball_in_court` happens to point at,
which Procore does not update after an official reply (see README.md).

Stdlib only, no dependencies. The classification/grouping logic here takes
an already-parsed list of RFI dicts (as returned by
`GET /rest/v1.0/projects/{id}/rfis`) so it can be tested and reused without
a live API call.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from enum import Enum


class RfiState(Enum):
    AWAITING_REPLY = "awaiting_reply"
    AWAITING_ACCEPTANCE = "awaiting_acceptance"
    CLOSED = "closed"


class Urgency(Enum):
    OVERDUE = "overdue"
    CRITICAL = "critical"   # due in 0-2 days
    ATTENTION = "attention"  # due in 3-7 days
    FINE = "fine"            # due in >7 days -- dropped from notifications


@dataclass(frozen=True)
class ClassifiedRfi:
    rfi_id: int
    number: str
    subject: str
    due_date: date
    state: RfiState
    urgency: Urgency
    responsible_id: int
    responsible_name: str


def _has_answer(rfi: dict) -> bool:
    # `questions[].answers` is never populated by `GET /rfis` in the sandbox,
    # even when an official reply exists (confirmed against a real RFI with
    # a recorded official response -- see docs/api-notes.md). The real
    # signal is a reply from `GET /rfis/{id}/replies` marked `official`,
    # attached to the RFI dict as `replies` before classification.
    for reply in rfi.get("replies") or []:
        if reply.get("official"):
            return True
    return False


def classify_state(rfi: dict) -> RfiState:
    if rfi.get("status") == "closed" or rfi.get("time_resolved"):
        return RfiState.CLOSED
    if _has_answer(rfi):
        return RfiState.AWAITING_ACCEPTANCE
    return RfiState.AWAITING_REPLY


def classify_urgency(due_date: date, today: date) -> Urgency:
    days = (due_date - today).days
    if days < 0:
        return Urgency.OVERDUE
    if days <= 2:
        return Urgency.CRITICAL
    if days <= 7:
        return Urgency.ATTENTION
    return Urgency.FINE


def _ball_in_court_user(rfi: dict) -> dict | None:
    # `ball_in_court_role` says whether the ball actually sits with
    # assignees, the rfi_manager, or the creator -- it was never populated
    # in sandbox testing (Procore's own docs list it, our sandbox just
    # never returned it), so `ball_in_court` alone worked there. Handling
    # the three documented values here means a production project where
    # Procore does populate it won't silently point at the wrong person.
    role = rfi.get("ball_in_court_role")
    if role == "rfi_manager":
        return rfi.get("rfi_manager")
    if role == "creator":
        return rfi.get("creator")
    if role == "assignees":
        assignees = rfi.get("assignees") or []
        return assignees[0] if assignees else None
    # role absent (observed case) -- ball_in_court itself is the best signal.
    return rfi.get("ball_in_court")


def _responsible_for(rfi: dict, state: RfiState) -> dict | None:
    if state == RfiState.AWAITING_ACCEPTANCE:
        # Procore does not move ball_in_court after an official reply (see
        # README) -- the person who must act next is always rfi_manager,
        # not whatever ball_in_court/ball_in_court_role still points at.
        return rfi.get("rfi_manager")
    if state == RfiState.AWAITING_REPLY:
        return _ball_in_court_user(rfi)
    return None


def classify_rfi(rfi: dict, today: date) -> ClassifiedRfi | None:
    state = classify_state(rfi)
    if state == RfiState.CLOSED:
        return None

    due_date = date.fromisoformat(rfi["due_date"])
    urgency = classify_urgency(due_date, today)
    if urgency == Urgency.FINE:
        return None

    responsible = _responsible_for(rfi, state)
    if not responsible:
        return None

    return ClassifiedRfi(
        rfi_id=rfi["id"],
        number=rfi.get("number", "?"),
        subject=rfi.get("subject", ""),
        due_date=due_date,
        state=state,
        urgency=urgency,
        responsible_id=responsible["id"],
        responsible_name=responsible.get("name", responsible.get("login", "?")),
    )


def classify_all(rfis: list[dict], today: date | None = None) -> list[ClassifiedRfi]:
    today = today or date.today()
    classified = (classify_rfi(rfi, today) for rfi in rfis)
    return [c for c in classified if c is not None]


_STATE_LABEL = {
    RfiState.AWAITING_REPLY: "awaiting your reply",
    RfiState.AWAITING_ACCEPTANCE: "awaiting your acceptance",
}

_URGENCY_ORDER = {
    Urgency.OVERDUE: 0,
    Urgency.CRITICAL: 1,
    Urgency.ATTENTION: 2,
}


def group_by_responsible(
    classified: list[ClassifiedRfi],
) -> dict[str, list[ClassifiedRfi]]:
    groups: dict[str, list[ClassifiedRfi]] = {}
    for item in classified:
        groups.setdefault(item.responsible_name, []).append(item)
    for items in groups.values():
        items.sort(key=lambda c: (_URGENCY_ORDER[c.urgency], c.due_date))
    return groups


def build_notifications(rfis: list[dict], today: date | None = None) -> dict[str, str]:
    """Returns {responsible_name: message}. Empty dict if nothing to notify --
    silence when there's no news is intentional, not a bug."""
    today = today or date.today()
    classified = classify_all(rfis, today)
    groups = group_by_responsible(classified)

    notifications = {}
    for name, items in groups.items():
        lines = [f"{len(items)} RFI{'s' if len(items) != 1 else ''} need you:"]
        for item in items:
            days = (item.due_date - today).days
            when = (
                f"{-days} day{'s' if -days != 1 else ''} overdue"
                if days < 0
                else "due today"
                if days == 0
                else f"due in {days} day{'s' if days != 1 else ''}"
            )
            lines.append(
                f"  - RFI #{item.number} ({_STATE_LABEL[item.state]}, {when}): "
                f"{item.subject}"
            )
        notifications[name] = "\n".join(lines)

    return notifications


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("uso: python monitor.py <rfis.json>")

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        rfis = json.load(f)

    notifications = build_notifications(rfis)
    if not notifications:
        print("Nada a notificar.")
        return

    for name, message in notifications.items():
        print(f"=== {name} ===")
        print(message)
        print()


if __name__ == "__main__":
    main()
