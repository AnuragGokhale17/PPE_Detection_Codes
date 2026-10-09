import io
from datetime import date, datetime, time

from openpyxl import load_workbook

from app.db.models import AlertRecipient, CameraHealth, EmailRecord, Plant, PpeEvent, ProductionHouse

DAY = date(2026, 10, 8)
RANGE = {"start_date": "2026-10-08", "end_date": "2026-10-08"}


def add_event(db, at: str, ph="PP-25", area="NITRATOR", cls="No Helmet", **kw):
    t = time.fromisoformat(at)
    e = PpeEvent(
        class1=cls,
        production_house=ph,
        area=area,
        date1=kw.pop("day", DAY),
        time1=t,
        image_url=f"https://ppes-siil.solargroup.com:9000/mybucket/october%2F{at.replace(':', '')}_{ph}.jpg",
        violation=kw.pop("violation", True),
        violator_count=kw.pop("violators", 1),
        **kw,
    )
    db.add(e)
    db.commit()
    return e


def test_summary_counts_shifts_dedup_and_false_positives(as_user, db):
    add_event(db, "07:00:00")  # Shift A
    add_event(db, "07:03:00")  # same area + class within 5 min -> de-duplicated
    add_event(db, "07:03:00", cls="No Gloves, No Mask")  # different class string: kept
    add_event(db, "15:00:00", ph="BULK", area="BAY", cls="no_helmet")  # Shift B, legacy spelling
    add_event(db, "23:30:00", ph="BULK", area="BAY", violators=2)  # Shift C
    add_event(db, "12:00:00", violation=False, review_status="false_positive")  # excluded
    db.add_all(
        [
            CameraHealth(camera_id="a", status=True, production_house="PP-25", area="X"),
            CameraHealth(camera_id="b", status=False, production_house="BULK", area="BAY", plant="CHAKDOH"),
        ]
    )
    db.commit()

    client = as_user()
    r = client.post("/api/dashboard/summary", json=RANGE)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["metrics"]["total_violations"] == 4
    assert data["metrics"]["false_positives"] == 1
    assert data["metrics"]["people_flagged"] == 5
    assert (data["metrics"]["cameras_online"], data["metrics"]["cameras_offline"]) == (1, 1)
    assert {x["name"]: x["value"] for x in data["charts"]["by_shift"]} == {"Shift A": 2, "Shift B": 1, "Shift C": 1}
    by_class = {x["name"]: x["value"] for x in data["charts"]["by_class"]}
    assert by_class["No Helmet"] == 3 and by_class["No Gloves"] == 1 and by_class["No Mask"] == 1
    assert data["charts"]["trend_unit"] == "hour"
    assert len(data["charts"]["trend"]) == 24
    assert data["camera_health"]["offline_cameras"][0]["area"] == "BAY"

    # Class filter matches inside multi-violation strings
    r = client.post("/api/dashboard/summary", json={**RANGE, "classes": ["No Mask"]})
    assert r.json()["metrics"]["total_violations"] == 1
    r = client.post("/api/dashboard/summary", json={**RANGE, "shifts": ["Shift C"]})
    assert r.json()["metrics"]["total_violations"] == 1


def test_events_paging_and_options(as_user, db):
    for minute in range(0, 60, 6):
        add_event(db, f"09:{minute:02d}:00")
    client = as_user()
    page = client.post("/api/dashboard/events", json={**RANGE, "page": 1, "page_size": 4}).json()
    assert page["total"] == 10
    assert [e["time"] for e in page["items"]] == ["09:30:00", "09:24:00", "09:18:00", "09:12:00"]
    assert page["items"][0]["classes"] == ["No Helmet"]

    opts = client.post("/api/dashboard/options", json=RANGE).json()
    assert opts["production_houses"] == ["PP-25"]
    assert opts["classes"][0] == "No Gloves"


def test_bad_ranges_rejected(as_user):
    client = as_user()
    assert client.post("/api/dashboard/summary", json={"start_date": "2026-10-09", "end_date": "2026-10-08"}).status_code == 422
    assert client.post("/api/dashboard/summary", json={"start_date": "2020-01-01", "end_date": "2026-10-08"}).status_code == 422


def test_daily_trend_for_long_ranges(as_user, db):
    add_event(db, "10:00:00", day=date(2026, 10, 1))
    add_event(db, "10:00:00", day=date(2026, 10, 3))
    data = as_user().post("/api/dashboard/summary", json={"start_date": "2026-10-01", "end_date": "2026-10-07"}).json()
    assert data["charts"]["trend_unit"] == "day"
    assert [p["value"] for p in data["charts"]["trend"]] == [1, 0, 1, 0, 0, 0, 0]


def test_excel_export(as_user, db):
    add_event(db, "08:00:00")
    add_event(db, "08:01:00", cls="No Helmet, No Mask")
    client = as_user()
    r = client.post("/api/dashboard/export", json=RANGE)
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Raw Data", "Summary", "By Production House", "By Area", "By Class"]
    assert wb["Raw Data"].max_row == 3
    assert client.post("/api/dashboard/export", json={"start_date": "2026-01-01", "end_date": "2026-01-01"}).status_code == 404


def test_notifications_tree_uses_recipient_designations(as_user, db):
    plant = Plant(name="CHAKDOH")
    db.add(plant)
    db.flush()
    house = ProductionHouse(plant_id=plant.id, name="BULK")
    db.add(house)
    db.flush()
    db.add(AlertRecipient(channel="violation", production_house_id=house.id, email="vaibhav.indurkar@solargroup.com", kind="to", designation="Bulk & Chemical"))
    for i, area in enumerate(["BAY", "BAY", "SILO"]):
        db.add(
            EmailRecord(
                class_label="No Helmet",
                production_house="BULK",
                area=area,
                to_recipients="vaibhav.indurkar@solargroup.com, incharge.cob@solargroup.com",
                insert_date=DAY,
                insert_time=time(9, i),
            )
        )
    db.commit()
    data = as_user().post("/api/notifications/summary", json=RANGE).json()
    assert data["metrics"]["total"] == 3
    assert data["metrics"]["top_recipient"] == {"name": "Vaibhav Indurkar", "count": 3}
    node = data["tree"][0]
    assert node["designation"] == "Bulk & Chemical"
    assert node["production_houses"][0]["areas"] == [{"name": "BAY", "value": 2}, {"name": "SILO", "value": 1}]
