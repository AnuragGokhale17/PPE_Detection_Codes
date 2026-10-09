"""Operational commands.

    python -m app.cli create-admin first.last@solargroup.com
    python -m app.cli import-cameras ../legacy/camera_list_v4.json ../legacy/camera_list_v4_newplants.json
    python -m app.cli import-recipients seed/recipients.json --plant CHAKDOH
    python -m app.cli export-cameras out.json
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

from app.db.session import SessionLocal
from app.services import accounts, config_io
from app.services.runtime import bump_config_version


def create_admin(email: str) -> int:
    password = getpass.getpass("Password (14+ chars, upper, lower, number, special): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        existing = accounts.get_user_by_email(db, email)
        if existing:
            error = accounts.change_password(db, existing, password)
            if error:
                print(error, file=sys.stderr)
                return 1
            existing.role = "admin"
            existing.is_active = True
            db.commit()
            print(f"Updated {existing.email}: role=admin, password reset.")
            return 0
        user, error = accounts.create_user(db, email, password, "admin")
        if error:
            print(error, file=sys.stderr)
            return 1
        print(f"Created admin {user.email}.")
        return 0


def import_cameras(paths: list[str], disabled: bool, keep_existing: bool) -> int:
    with SessionLocal() as db:
        for path in paths:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            result = config_io.import_camera_json(db, data, enable_new=not disabled, update_existing=not keep_existing)
            print(f"{path}: {json.dumps(result)}")
        bump_config_version(db, "cli import-cameras")
        db.commit()
    return 0


def import_recipients(path: str, plant: str | None) -> int:
    seed = json.loads(Path(path).read_text(encoding="utf-8"))
    with SessionLocal() as db:
        try:
            result = config_io.import_recipients(db, seed, plant_name=plant)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        db.commit()
    print(f"Imported {result['recipients']} recipients.")
    for key, label in (
        ("created_houses", "Production houses created because only the recipient list names them"),
        ("houses_without_cameras", "Houses with recipients but no cameras (check for name mismatches)"),
        ("houses_without_recipients", "Houses with cameras but no recipients (alerts go nowhere)"),
    ):
        if result[key]:
            print(f"{label}: {', '.join(result[key])}")
    return 0


def export_cameras(path: str) -> int:
    with SessionLocal() as db:
        data = config_io.export_camera_json(db, include_disabled=True)
    Path(path).write_text(json.dumps(data, indent=4), encoding="utf-8")
    print(f"Wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create an admin, or promote and reset an existing user")
    p.add_argument("email")

    p = sub.add_parser("import-cameras", help="Merge legacy camera_list_*.json files into the database")
    p.add_argument("paths", nargs="+")
    p.add_argument("--disabled", action="store_true", help="Create new cameras disabled")
    p.add_argument("--keep-existing", action="store_true", help="Don't overwrite cameras that already exist")

    p = sub.add_parser("import-recipients", help="Load alert recipients from seed/recipients.json")
    p.add_argument("path")
    p.add_argument("--plant", help="Plant the production houses belong to (needed when there are several)")

    p = sub.add_parser("export-cameras", help="Write the camera config in the legacy JSON format")
    p.add_argument("path")

    args = parser.parse_args()
    if args.command == "create-admin":
        return create_admin(args.email)
    if args.command == "import-cameras":
        return import_cameras(args.paths, args.disabled, args.keep_existing)
    if args.command == "import-recipients":
        return import_recipients(args.path, args.plant)
    if args.command == "export-cameras":
        return export_cameras(args.path)
    return 2


if __name__ == "__main__":
    sys.exit(main())
