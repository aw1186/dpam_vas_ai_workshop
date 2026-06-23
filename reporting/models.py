"""Data models for the Fund Reporting Hub."""
from django.db import models

LANGS = {
    "EN": "English",
    "FR": "Français",
    "DE": "Deutsch",
    "IT": "Italiano",
    "ES": "Español",
}
LANG_CHOICES = [(k, v) for k, v in LANGS.items()]

TEAMS = ["VAS", "Fund Accounting", "Risk", "Compliance"]

REPORT_STATUSES = ["Pending", "In Review", "Validated", "Rejected"]
STATUS_CHOICES = [(s, s) for s in REPORT_STATUSES]

CONTROL_STATUS_CHOICES = [("pass", "pass"), ("warn", "warn"), ("fail", "fail")]
VALIDATION_STATE_CHOICES = [
    ("pending", "pending"),
    ("approved", "approved"),
    ("rejected", "rejected"),
]
NOTE_TYPE_CHOICES = [("note", "note"), ("disclaimer", "disclaimer")]

CONTROL_DEFS = [
    {"id": "nav_recon", "name": "NAV reconciliation", "desc": "NAV vs. fund accounting ledger"},
    {"id": "holdings", "name": "Holdings completeness", "desc": "All positions present & priced"},
    {"id": "perf", "name": "Performance consistency", "desc": "Returns tie to NAV time series"},
    {"id": "fx", "name": "FX rates source check", "desc": "Rates match official close"},
    {"id": "prior", "name": "Prior period continuity", "desc": "Opening = prior closing balances"},
    {"id": "disclos", "name": "Disclosure completeness", "desc": "Mandatory disclosures present"},
]


class Report(models.Model):
    id = models.CharField(primary_key=True, max_length=20)
    fund = models.CharField(max_length=200)
    isin = models.CharField(max_length=20)
    type = models.CharField(max_length=80)
    period = models.CharField(max_length=10)  # YYYY-MM-DD
    lang = models.CharField(max_length=2, choices=LANG_CHOICES, default="EN")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.id} — {self.fund}"

    @property
    def lang_name(self):
        return LANGS.get(self.lang, self.lang)

    @property
    def fail_count(self):
        return self.controls.filter(status="fail").count()

    @property
    def warn_count(self):
        return self.controls.filter(status="warn").count()

    @property
    def control_badge(self):
        if self.fail_count:
            return ("red", f"{self.fail_count} fail")
        if self.warn_count:
            return ("amber", f"{self.warn_count} warn")
        return ("green", "All pass")

    @property
    def validation_summary(self):
        vals = list(self.validations.all())
        rejected = sum(1 for v in vals if v.state == "rejected")
        approved = sum(1 for v in vals if v.state == "approved")
        if rejected:
            return ("red", f"{rejected} rejected")
        return ("grey", f"{approved}/{len(vals)} signed")


class Control(models.Model):
    report = models.ForeignKey(Report, related_name="controls", on_delete=models.CASCADE)
    control_id = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    descr = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=CONTROL_STATUS_CHOICES, default="pass")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.report_id}/{self.control_id}: {self.status}"


class Validation(models.Model):
    report = models.ForeignKey(Report, related_name="validations", on_delete=models.CASCADE)
    team = models.CharField(max_length=40)
    state = models.CharField(max_length=10, choices=VALIDATION_STATE_CHOICES, default="pending")
    signed_by = models.CharField(max_length=80, blank=True, default="")
    signed_at = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.report_id}/{self.team}: {self.state}"


class Note(models.Model):
    report = models.ForeignKey(Report, related_name="notes", on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=NOTE_TYPE_CHOICES, default="note")
    author = models.CharField(max_length=80)
    created_at = models.CharField(max_length=20)
    text = models.TextField()

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.type} on {self.report_id}"


class Chat(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=160)
    sub = models.CharField(max_length=160, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class Message(models.Model):
    chat = models.ForeignKey(Chat, related_name="messages", on_delete=models.CASCADE)
    who = models.CharField(max_length=80)
    is_me = models.BooleanField(default=False)
    text = models.TextField()
    created_at = models.CharField(max_length=20)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.who}: {self.text[:30]}"
