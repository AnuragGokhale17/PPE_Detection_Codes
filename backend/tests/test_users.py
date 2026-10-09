from tests.conftest import PASSWORD


def _admin_client(client, make_user, login):
    make_user("boss.admin@solargroup.com", role="admin")
    login(client, "boss.admin@solargroup.com")
    return client


def test_regular_user_cannot_manage_users(client, make_user, login):
    make_user()
    login(client)
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/audit-logs").status_code == 403


def test_admin_has_every_permission(client, make_user, login):
    make_user("boss.admin@solargroup.com", role="admin")
    me = login(client, "boss.admin@solargroup.com").json()
    assert "training.manage" in me["permissions"]
    assert "users.manage" in me["permissions"]


def test_admin_grants_and_revokes_permissions(client, make_user, login, mailbox):
    from fastapi.testclient import TestClient

    from app.main import app

    worker = make_user()
    admin = _admin_client(client, make_user, login)

    r = admin.put(f"/api/users/{worker.id}/permissions", json={"permissions": ["config.cameras", "violations.review"]})
    assert r.status_code == 200
    assert r.json()["granted"] == ["config.cameras", "violations.review"]

    # Grants apply to the user's next request without signing out
    with TestClient(app) as user_client:
        login(user_client)
        assert set(user_client.get("/api/auth/me").json()["permissions"]) == {
            "dashboard.view",
            "config.cameras",
            "violations.review",
        }
        admin.put(f"/api/users/{worker.id}/permissions", json={"permissions": []})
        assert user_client.get("/api/auth/me").json()["permissions"] == ["dashboard.view"]


def test_admin_only_permissions_cannot_be_granted(client, make_user, login):
    worker = make_user()
    admin = _admin_client(client, make_user, login)
    r = admin.put(f"/api/users/{worker.id}/permissions", json={"permissions": ["training.manage"]})
    assert r.status_code == 400


def test_create_user_enforces_domain_and_policy(client, make_user, login):
    admin = _admin_client(client, make_user, login)
    r = admin.post("/api/users", json={"email": "x@gmail.com", "password": PASSWORD})
    assert r.status_code == 400
    r = admin.post("/api/users", json={"email": "new.person@solargroup.com", "password": "weak"})
    assert r.status_code == 400
    r = admin.post(
        "/api/users",
        json={"email": "new.person@solargroup.com", "password": PASSWORD, "permissions": ["annotations.create"]},
    )
    assert r.status_code == 201
    assert r.json()["granted"] == ["annotations.create"]


def test_admin_cannot_lock_themselves_out(client, make_user, login):
    admin = _admin_client(client, make_user, login)
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert admin.delete(f"/api/users/{me['id']}").status_code == 400


def test_deactivation_ends_sessions_and_is_audited(client, make_user, login):
    from fastapi.testclient import TestClient

    from app.main import app

    worker = make_user()
    admin = _admin_client(client, make_user, login)
    with TestClient(app) as user_client:
        login(user_client)
        admin.patch(f"/api/users/{worker.id}", json={"is_active": False})
        assert user_client.get("/api/auth/me").status_code == 401

    logs = admin.get("/api/audit-logs", params={"q": "deactivated"}).json()
    assert logs["total"] == 1
    assert logs["items"][0]["action"] == "Update User"


def test_delete_user(client, make_user, login):
    worker = make_user()
    admin = _admin_client(client, make_user, login)
    assert admin.delete(f"/api/users/{worker.id}").status_code == 204
    emails = [u["email"] for u in admin.get("/api/users").json()]
    assert worker.email not in emails
