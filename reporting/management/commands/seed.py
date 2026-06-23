"""Seed the database with the original Fund Reporting Hub demo data."""
from django.core.management.base import BaseCommand
from django.db import transaction

from reporting.models import (
    CONTROL_DEFS,
    TEAMS,
    Chat,
    Control,
    Message,
    Note,
    Report,
    Validation,
)

SEED_REPORTS = [
    {"id": "R-1001", "fund": "Aurora Global Equity Fund", "isin": "LU1234567890", "type": "Monthly NAV Report", "period": "2026-05-31", "lang": "EN"},
    {"id": "R-1002", "fund": "Helios European Bond Fund", "isin": "LU2233445566", "type": "Factsheet", "period": "2026-05-31", "lang": "FR"},
    {"id": "R-1003", "fund": "Meridian Emerging Markets", "isin": "IE00BX1234Z5", "type": "Quarterly Report", "period": "2026-03-31", "lang": "DE"},
    {"id": "R-1004", "fund": "Cobalt Multi-Asset Fund", "isin": "LU9988776655", "type": "Monthly NAV Report", "period": "2026-05-31", "lang": "IT"},
    {"id": "R-1005", "fund": "Vertex Short Duration Credit", "isin": "LU5566778899", "type": "Investor Statement", "period": "2026-04-30", "lang": "ES"},
    {"id": "R-1006", "fund": "Aurora Global Equity Fund", "isin": "LU1234567890", "type": "Quarterly Report", "period": "2026-03-31", "lang": "EN"},
    {"id": "R-1007", "fund": "Solstice Infrastructure Fund", "isin": "LU1122334455", "type": "Annual Report", "period": "2025-12-31", "lang": "FR"},
    {"id": "R-1008", "fund": "Helios European Bond Fund", "isin": "LU2233445566", "type": "Monthly NAV Report", "period": "2026-05-31", "lang": "DE"},
    {"id": "R-1009", "fund": "Polaris Sustainable Equity", "isin": "LU7766554433", "type": "Factsheet", "period": "2026-05-31", "lang": "EN"},
    {"id": "R-1010", "fund": "Meridian Emerging Markets", "isin": "IE00BX1234Z5", "type": "Investor Statement", "period": "2026-04-30", "lang": "IT"},
    {"id": "R-1011", "fund": "Cobalt Multi-Asset Fund", "isin": "LU9988776655", "type": "Quarterly Report", "period": "2026-03-31", "lang": "ES"},
    {"id": "R-1012", "fund": "Vertex Short Duration Credit", "isin": "LU5566778899", "type": "Monthly NAV Report", "period": "2026-05-31", "lang": "EN"},
]


def seed_controls(report_id):
    """Deterministic pseudo-random control states (ports the original JS logic)."""
    h = 0
    for ch in report_id:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    out = []
    for i, d in enumerate(CONTROL_DEFS):
        r = (h >> (i * 3)) & 7
        status = "pass" if r < 5 else ("warn" if r < 7 else "fail")
        out.append({**d, "status": status})
    return out


class Command(BaseCommand):
    help = "Seed the database with demo fund reporting data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete existing data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            Message.objects.all().delete()
            Chat.objects.all().delete()
            Note.objects.all().delete()
            Validation.objects.all().delete()
            Control.objects.all().delete()
            Report.objects.all().delete()
            self.stdout.write("Existing data cleared.")

        if Report.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Reports already exist; skipping. Use --reset to reseed."))
            return

        for r in SEED_REPORTS:
            controls = seed_controls(r["id"])
            if r["id"] in ("R-1006", "R-1007"):
                status = "Validated"
            elif r["id"] in ("R-1002", "R-1009"):
                status = "In Review"
            else:
                status = "Pending"

            report = Report.objects.create(
                id=r["id"], fund=r["fund"], isin=r["isin"], type=r["type"],
                period=r["period"], lang=r["lang"], status=status,
            )
            for c in controls:
                Control.objects.create(
                    report=report, control_id=c["id"], name=c["name"],
                    descr=c["desc"], status=c["status"],
                )
            for t in TEAMS:
                Validation.objects.create(
                    report=report, team=t,
                    state="approved" if status == "Validated" else "pending",
                )

        Note.objects.create(
            report=Report.objects.get(id="R-1001"), type="note",
            author="M. Rossi (VAS)", created_at="2026-06-18 09:14",
            text="NAV ties out to FA ledger. Awaiting Risk sign-off before release.",
        )
        Note.objects.create(
            report=Report.objects.get(id="R-1003"), type="disclaimer",
            author="Compliance", created_at="2026-06-15 16:02",
            text="Past performance is not a reliable indicator of future results. "
                 "Figures are unaudited.",
        )

        chats = [
            ("C1", "Ad-hoc: Aurora attribution", "with Risk team", [
                ("M. Rossi (Risk)", False, "Can you pull a sector attribution for Aurora Global Equity, May close?", "09:02"),
                ("You", True, "Sure — EN or FR version?", "09:05"),
                ("M. Rossi (Risk)", False, "EN is fine. Need it before the 2pm committee.", "09:06"),
            ]),
            ("C2", "Ad-hoc: Helios YTD figures", "with Fund Accounting", [
                ("L. Bianchi (FA)", False, "Helios YTD return looks off vs last month, can you double check the FX source?", "Yesterday"),
            ]),
            ("C3", "VAS clarification — Cobalt", "with VAS control", [
                ("VAS Desk", False, "Holdings completeness flagged a warning on Cobalt. Missing one private placement?", "Mon"),
            ]),
        ]
        for cid, name, sub, msgs in chats:
            chat = Chat.objects.create(id=cid, name=name, sub=sub)
            for who, is_me, text, at in msgs:
                Message.objects.create(
                    chat=chat, who=who, is_me=is_me, text=text, created_at=at)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Report.objects.count()} reports and {Chat.objects.count()} chats."))
