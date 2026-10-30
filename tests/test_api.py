"""End-to-end API tests: HTTP in, JSON out, real database underneath."""

from sqlalchemy import func, select

from app.models import Comment


def create_user(client, name="Asha", email="asha@example.com"):
    response = client.post("/users", json={"name": name, "email": email})
    assert response.status_code == 201, response.text
    return response.json()


def create_ticket(client, **overrides):
    payload = {"title": "Printer on fire", **overrides}
    response = client.post("/tickets", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def patch_ticket(client, ticket_id, **changes):
    return client.patch(f"/tickets/{ticket_id}", json=changes)


# --- health -------------------------------------------------------------------


def test_health_reports_database_up(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


# --- users --------------------------------------------------------------------


def test_create_and_fetch_user(client):
    created = create_user(client)
    assert created["email"] == "asha@example.com"
    fetched = client.get(f"/users/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Asha"


def test_duplicate_email_is_rejected_case_insensitively(client):
    create_user(client, email="asha@example.com")
    response = client.post("/users", json={"name": "Other", "email": "ASHA@example.com"})
    assert response.status_code == 409
    assert response.json()["error"] == "duplicate"


def test_invalid_email_is_422(client):
    response = client.post("/users", json={"name": "Asha", "email": "not-an-email"})
    assert response.status_code == 422


def test_missing_user_is_404_with_error_body(client):
    response = client.get("/users/999")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


# --- creating and reading tickets ----------------------------------------------


def test_create_ticket_applies_defaults(client):
    ticket = create_ticket(client)
    assert ticket["status"] == "open"
    assert ticket["priority"] == "medium"
    assert ticket["assignee_id"] is None


def test_create_ticket_validates_input(client):
    assert client.post("/tickets", json={"title": ""}).status_code == 422
    assert client.post("/tickets", json={"title": "x", "priority": "urgent"}).status_code == 422


def test_create_ticket_with_unknown_assignee_is_404(client):
    response = client.post("/tickets", json={"title": "x", "assignee_id": 999})
    assert response.status_code == 404


def test_missing_ticket_is_404(client):
    response = client.get("/tickets/999")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


# --- listing ------------------------------------------------------------------


def test_list_paginates_newest_first_with_total(client):
    for i in range(5):
        create_ticket(client, title=f"T{i}")

    first = client.get("/tickets", params={"limit": 2, "offset": 0}).json()
    assert first["total"] == 5
    assert [t["title"] for t in first["items"]] == ["T4", "T3"]

    last = client.get("/tickets", params={"limit": 2, "offset": 4}).json()
    assert [t["title"] for t in last["items"]] == ["T0"]


def test_list_filters_by_status_and_assignee(client):
    user = create_user(client)
    a = create_ticket(client, title="A", assignee_id=user["id"])
    create_ticket(client, title="B")
    patch_ticket(client, a["id"], status="in_progress")

    by_status = client.get("/tickets", params={"status": "in_progress"}).json()
    assert [t["title"] for t in by_status["items"]] == ["A"]
    assert by_status["total"] == 1

    by_assignee = client.get("/tickets", params={"assignee_id": user["id"]}).json()
    assert [t["title"] for t in by_assignee["items"]] == ["A"]


def test_list_includes_assignee_name_and_comment_count(client):
    user = create_user(client, name="Asha")
    ticket = create_ticket(client, assignee_id=user["id"])
    for body in ("first", "second"):
        client.post(f"/tickets/{ticket['id']}/comments", json={"author_id": user["id"], "body": body})
    create_ticket(client, title="Unassigned, no comments")

    items = client.get("/tickets").json()["items"]
    by_title = {t["title"]: t for t in items}
    assert by_title["Printer on fire"]["assignee_name"] == "Asha"
    assert by_title["Printer on fire"]["comment_count"] == 2
    assert by_title["Unassigned, no comments"]["assignee_name"] is None
    assert by_title["Unassigned, no comments"]["comment_count"] == 0


def test_list_rejects_out_of_range_parameters(client):
    assert client.get("/tickets", params={"limit": 0}).status_code == 422
    assert client.get("/tickets", params={"limit": 101}).status_code == 422
    assert client.get("/tickets", params={"offset": -1}).status_code == 422
    assert client.get("/tickets", params={"status": "bogus"}).status_code == 422


def test_stats_counts_every_status(client):
    a = create_ticket(client)
    create_ticket(client)
    patch_ticket(client, a["id"], status="in_progress")

    stats = client.get("/tickets/stats").json()
    assert stats == {"open": 1, "in_progress": 1, "resolved": 0, "closed": 0}


# --- updating: the status state machine ------------------------------------------


def test_full_lifecycle_is_allowed(client):
    ticket = create_ticket(client)
    for status in ("in_progress", "resolved", "closed"):
        response = patch_ticket(client, ticket["id"], status=status)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status


def test_invalid_transition_is_409_and_changes_nothing(client):
    ticket = create_ticket(client)
    response = patch_ticket(client, ticket["id"], status="resolved")  # open -> resolved is not allowed
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_transition"
    assert client.get(f"/tickets/{ticket['id']}").json()["status"] == "open"


def test_closed_tickets_cannot_be_reopened(client):
    ticket = create_ticket(client)
    patch_ticket(client, ticket["id"], status="closed")
    assert patch_ticket(client, ticket["id"], status="open").status_code == 409


def test_setting_the_current_status_is_a_noop(client):
    ticket = create_ticket(client)
    assert patch_ticket(client, ticket["id"], status="open").status_code == 200


def test_patch_updates_only_the_fields_sent(client):
    ticket = create_ticket(client, description="keep me")
    response = patch_ticket(client, ticket["id"], title="New title", priority="high")
    body = response.json()
    assert body["title"] == "New title"
    assert body["priority"] == "high"
    assert body["description"] == "keep me"


def test_assign_then_unassign_with_null(client):
    user = create_user(client)
    ticket = create_ticket(client)
    assigned = patch_ticket(client, ticket["id"], assignee_id=user["id"]).json()
    assert assigned["assignee_id"] == user["id"]
    unassigned = patch_ticket(client, ticket["id"], assignee_id=None).json()
    assert unassigned["assignee_id"] is None


def test_failed_patch_leaves_the_ticket_untouched(client):
    ticket = create_ticket(client, title="Original")
    response = patch_ticket(client, ticket["id"], title="Changed", assignee_id=999)
    assert response.status_code == 404
    assert client.get(f"/tickets/{ticket['id']}").json()["title"] == "Original"


def test_patch_missing_ticket_is_404(client):
    assert patch_ticket(client, 999, title="x").status_code == 404


# --- comments ------------------------------------------------------------------


def test_comments_appear_on_the_ticket_in_order(client):
    user = create_user(client)
    ticket = create_ticket(client)
    for body in ("first", "second", "third"):
        response = client.post(
            f"/tickets/{ticket['id']}/comments", json={"author_id": user["id"], "body": body}
        )
        assert response.status_code == 201

    detail = client.get(f"/tickets/{ticket['id']}").json()
    assert [c["body"] for c in detail["comments"]] == ["first", "second", "third"]


def test_comment_requires_existing_ticket_and_author(client):
    user = create_user(client)
    ticket = create_ticket(client)
    no_ticket = client.post("/tickets/999/comments", json={"author_id": user["id"], "body": "x"})
    no_author = client.post(f"/tickets/{ticket['id']}/comments", json={"author_id": 999, "body": "x"})
    assert no_ticket.status_code == 404
    assert no_author.status_code == 404


def test_empty_comment_body_is_422(client):
    user = create_user(client)
    ticket = create_ticket(client)
    response = client.post(
        f"/tickets/{ticket['id']}/comments", json={"author_id": user["id"], "body": ""}
    )
    assert response.status_code == 422


# --- deleting ------------------------------------------------------------------


def test_deleting_a_ticket_removes_its_comments(client, db):
    user = create_user(client)
    ticket = create_ticket(client)
    client.post(f"/tickets/{ticket['id']}/comments", json={"author_id": user["id"], "body": "bye"})

    assert client.delete(f"/tickets/{ticket['id']}").status_code == 204
    assert client.get(f"/tickets/{ticket['id']}").status_code == 404
    assert db.scalar(select(func.count()).select_from(Comment)) == 0
