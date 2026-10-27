"""Query counts for the leave read paths, so an N+1 fails a build.

The budget is per request, not per row: each test adds rows and asserts the
count does not move with them. A forgotten `select_related`, or a configuration
read repeated inside the year-end sweep, shows up as a failure here rather than
as a slow screen in the week the leave year turns over.
"""
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from conftest import make_principal, make_session
from modules.leave.models import (
    LeaveBalance,
    LeaveLedgerEntry,
    LeavePolicy,
    LeaveRequest,
    LeaveRequestTransition,
    LeaveResumption,
    LeaveSubstituteAssignment,
    WorkflowTask,
)
from modules.leave.selectors import leave as sel
from modules.leave.services import year_end

pytestmark = pytest.mark.django_db

APPROVER = ("leave.request.view_self", "leave.request.create",
            "leave.request.delete", "leave.request.view",
            "leave.request.approve")
#: An approver who holds no wide `leave.request.view`, so `requests_for` scopes
#: them to their own leave plus what they have already acted on.
APPROVE_ONLY = ("leave.request.view_self", "leave.request.approve")

_reference = iter(range(1, 10_000))


def _client(stub_iam, permissions=APPROVER, uid=9, kind="faculty",
            roles=("HOD (CSE)",)):
    stub_iam(make_session(user_id=uid, kind=kind, permissions=permissions,
                          modules=("leave",), roles=roles))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Token abc")
    return c


def _request(user_id=None, status="approved"):
    n = next(_reference)
    return LeaveRequest.objects.create(
        category="el", status=status, user_id=user_id or 1000 + n,
        period_from=date(2026, 1, 5), period_to=date(2026, 1, 6),
        days_counted="2.00", reference=f"ELM-2026-{n:06d}")


@pytest.fixture
def cohort():
    """Five requests, each carrying every relation a serializer might follow:
    a substitute assignment, a resumption and a routed task."""
    rows = []
    for _i in range(5):
        req = _request()
        LeaveSubstituteAssignment.objects.create(request=req, nominee_user_id=9,
                                                 status="nominated")
        LeaveResumption.objects.create(request=req, user_id=req.user_id,
                                       actual_date=date(2026, 1, 6))
        WorkflowTask.objects.create(request=req, step_order=0,
                                    step_kind="unit_head",
                                    task_class="leave.unit_head.review",
                                    assignee_role="HOD (CSE)")
        rows.append(req)
    LeaveBalance.objects.create(user_id=9, category="el", leave_year=2026,
                                entitled_days="30", used_days="2")
    LeaveLedgerEntry.objects.create(user_id=9, category="el", leave_year=2026,
                                    entry_type="credit", days="30")
    return rows


@pytest.mark.parametrize(("path", "budget"), [
    ("/api/v1/leave/substitutions", 1),
    ("/api/v1/leave/requests/mine", 1),
    ("/api/v1/leave/records", 1),
    ("/api/v1/leave/tasks", 1),
    ("/api/v1/leave/resumptions", 1),
    ("/api/v1/leave/balances", 1),
    ("/api/v1/leave/ledger", 1),
    ("/api/v1/leave/summary", 5),
])
def test_a_list_endpoint_stays_within_its_budget(
        stub_iam, cohort, django_assert_max_num_queries, path, budget):
    client = _client(stub_iam)
    with django_assert_max_num_queries(budget):
        assert client.get(path).status_code == 200


def test_a_request_detail_costs_the_same_however_long_its_history(
        stub_iam, django_assert_max_num_queries):
    """The history is the obvious per-row relation here, so it is pinned."""
    client = _client(stub_iam)
    req = _request(user_id=9)
    for _i in range(5):
        LeaveRequestTransition.objects.create(request=req, from_status="draft",
                                              to_status="submitted",
                                              action="send", actor_user_id=9)
    with django_assert_max_num_queries(2):
        assert client.get(f"/api/v1/leave/requests/{req.pk}").status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/leave/substitutions",
                                  "/api/v1/leave/records"])
def test_the_count_does_not_grow_with_the_rows(stub_iam, cohort, path):
    """The property that matters: five more rows, no more queries."""
    client = _client(stub_iam)

    with CaptureQueriesContext(connection) as first:
        client.get(path)

    for _i in range(5):
        _request()

    with CaptureQueriesContext(connection) as second:
        client.get(path)

    assert len(second) == len(first), (
        f"{len(first)} queries for 5 rows, {len(second)} for 10 — "
        f"a relation is being fetched per row")


def test_an_approver_sees_their_own_leave_and_what_they_acted_on():
    """The scoped read carries no duplicate per transition and no row the
    approver has never touched — the two ways a join-based version goes wrong."""
    actor = make_principal(user_id=9, permissions=APPROVE_ONLY, kind="faculty",
                           roles=("HOD (CSE)",), modules=("leave",))
    own = _request(user_id=9, status="draft")
    acted_on = _request(user_id=55)
    for _i in range(3):
        LeaveRequestTransition.objects.create(request=acted_on,
                                              from_status="draft",
                                              to_status="approved",
                                              action="approve", actor_user_id=9)
    _untouched = _request(user_id=66)

    with CaptureQueriesContext(connection) as ctx:
        ids = list(sel.requests_for(actor).values_list("id", flat=True))

    assert set(ids) == {own.pk, acted_on.pk}
    assert len(ids) == len(set(ids)), "a request appeared once per transition"
    assert len(ctx) == 1


def _year_with_accounts(n: int) -> None:
    LeavePolicy.objects.create(leave_year=2026, is_current=True,
                               entitlements={"el": "30"})
    for i in range(n):
        LeaveBalance.objects.create(user_id=1000 + i, category="el",
                                    leave_year=2026, entitled_days="30",
                                    used_days="2")


@pytest.mark.parametrize("accounts", [1, 8])
def test_year_end_reads_the_policy_a_fixed_number_of_times(accounts):
    """The next year's policy is one read for the sweep, not one per account."""
    _year_with_accounts(accounts)

    with CaptureQueriesContext(connection) as ctx:
        year_end.run(leave_year=2026)

    policy_reads = [q for q in ctx.captured_queries if "leave_policy" in q["sql"]]
    assert len(policy_reads) <= 3, (
        f"{len(policy_reads)} policy reads for {accounts} account(s) — "
        f"the year-end sweep is resolving configuration per account")
