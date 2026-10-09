"""Permission catalogue.

`role` stays admin | user. Admins implicitly hold every permission; everyone else
gets DEFAULT_PERMISSIONS plus whatever an admin grants from the users screen.
"""
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"


class Permission(str, Enum):
    DASHBOARD_VIEW = "dashboard.view"
    VIOLATIONS_REVIEW = "violations.review"
    ANNOTATIONS_CREATE = "annotations.create"
    ANNOTATIONS_APPROVE = "annotations.approve"
    CONFIG_CAMERAS = "config.cameras"
    CONFIG_PPE = "config.ppe"
    CONFIG_RECIPIENTS = "config.recipients"
    TRAINING_MANAGE = "training.manage"
    USERS_MANAGE = "users.manage"


PERMISSION_INFO: dict[Permission, dict] = {
    Permission.DASHBOARD_VIEW: {
        "label": "View dashboard",
        "description": "Dashboard, notifications and Excel export",
        "grantable": True,
    },
    Permission.VIOLATIONS_REVIEW: {
        "label": "Review detections",
        "description": "Mark detections as correct, false positive or wrong class",
        "grantable": True,
    },
    Permission.ANNOTATIONS_CREATE: {
        "label": "Annotate images",
        "description": "Draw boxes, upload images and capture camera snapshots",
        "grantable": True,
    },
    Permission.ANNOTATIONS_APPROVE: {
        "label": "Approve annotations",
        "description": "Accept labelled images into the training pool",
        "grantable": True,
    },
    Permission.CONFIG_CAMERAS: {
        "label": "Manage cameras",
        "description": "Add or edit plants, production houses, areas and cameras",
        "grantable": True,
    },
    Permission.CONFIG_PPE: {
        "label": "Manage PPE rules",
        "description": "Required PPE per area, class names and confidence thresholds",
        "grantable": True,
    },
    Permission.CONFIG_RECIPIENTS: {
        "label": "Manage alert recipients",
        "description": "Email recipients per production house",
        "grantable": True,
    },
    Permission.TRAINING_MANAGE: {
        "label": "Retrain models",
        "description": "Build datasets, run training and promote models (admins only for now)",
        "grantable": False,
    },
    Permission.USERS_MANAGE: {
        "label": "Manage users",
        "description": "Users, permissions and the audit log",
        "grantable": False,
    },
}

DEFAULT_PERMISSIONS: frozenset[Permission] = frozenset({Permission.DASHBOARD_VIEW})
GRANTABLE_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p, info in PERMISSION_INFO.items() if info["grantable"]
)


def effective_permissions(role: str, granted: set[str]) -> set[str]:
    if role == Role.ADMIN.value:
        return {p.value for p in Permission}
    allowed = {p.value for p in GRANTABLE_PERMISSIONS}
    return {p.value for p in DEFAULT_PERMISSIONS} | (set(granted) & allowed)
