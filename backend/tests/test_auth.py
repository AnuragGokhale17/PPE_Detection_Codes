from datetime import timedelta

from app.core.security import utcnow
from tests.conftest import PASSWORD


def test_full_login_flow_sets_session(client, make_user, mailbox):
    make_user()
    r = client.post("/api/auth/login", json={"email": "Jane.Doe@solargroup.com", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["otp_required"] is True
    assert "ppe_otp" in r.cookies

    # Not signed in until the OTP is verified
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/verify-otp", json={"otp": mailbox.otps["jane.doe@solargroup.com"]})
    assert r.status_code == 200
    assert r.json()["permissions"] == ["dashboard.view"]
    assert r.json()["name"] == "Jane Doe"

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    # Sliding idle timeout: each authenticated request re-issues the cookie
    assert "ppe_session" in r.cookies


def test_wrong_password_is_generic_and_locks_after_three(client, make_user):
    make_user()
    unknown = client.post("/api/auth/login", json={"email": "nobody@solargroup.com", "password": "x"})
    wrong = client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()

    client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": "x"})
    client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": "x"})
    # Locked now, even with the right password
    r = client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": PASSWORD})
    assert r.status_code == 423
    assert r.json()["detail"]["code"] == "locked"


def test_inactive_and_expired_accounts(client, make_user, db):
    user = make_user()
    user.is_active = False
    db.commit()
    r = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "inactive"

    user.is_active = True
    user.password_updated_at = utcnow() - timedelta(days=31)
    db.commit()
    r = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_expired"


def test_otp_attempts_are_limited(client, make_user, mailbox):
    make_user()
    client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": PASSWORD})
    real = mailbox.otps["jane.doe@solargroup.com"]
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(4):
        r = client.post("/api/auth/verify-otp", json={"otp": wrong})
        assert r.status_code == 400
    r = client.post("/api/auth/verify-otp", json={"otp": wrong})
    assert "Too many" in r.json()["detail"]["message"]
    # The code is burned; even the right one no longer works
    r = client.post("/api/auth/verify-otp", json={"otp": real})
    assert r.status_code == 400


def test_resend_is_rate_limited(client, make_user, mailbox):
    make_user()
    client.post("/api/auth/login", json={"email": "jane.doe@solargroup.com", "password": PASSWORD})
    r = client.post("/api/auth/resend-otp")
    assert r.status_code == 429


def test_password_reset_flow(client, make_user, mailbox, login):
    make_user()
    login(client)
    assert client.get("/api/auth/me").status_code == 200

    r = client.post("/api/auth/forgot-password", json={"email": "jane.doe@solargroup.com"})
    unknown = client.post("/api/auth/forgot-password", json={"email": "ghost@solargroup.com"})
    assert r.json() == unknown.json()

    link = mailbox.reset_links["jane.doe@solargroup.com"]
    assert link.startswith("http://frontend.test/reset-password/")
    token = link.rsplit("/", 1)[1]
    assert client.get(f"/api/auth/reset-password/{token}").json()["valid"] is True

    weak = client.post("/api/auth/reset-password", json={"token": token, "password": "short", "confirm_password": "short"})
    assert weak.status_code == 400

    reused = client.post(
        "/api/auth/reset-password", json={"token": token, "password": PASSWORD, "confirm_password": PASSWORD}
    )
    assert "reuse" in reused.json()["detail"]["message"]

    new_pw = "Another-Strong-Pass-7#"
    r = client.post("/api/auth/reset-password", json={"token": token, "password": new_pw, "confirm_password": new_pw})
    assert r.status_code == 200

    # Link is single-use: it is bound to the old password hash
    assert client.get(f"/api/auth/reset-password/{token}").json()["valid"] is False

    login(client, password=new_pw)
    assert client.get("/api/auth/me").status_code == 200


def test_password_change_invalidates_existing_sessions(client, make_user, login, db):
    user = make_user()
    login(client)
    from app.services import accounts

    assert accounts.change_password(db, user, "Brand-New-Password-9$") is None
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_session(client, make_user, login):
    make_user()
    login(client)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
