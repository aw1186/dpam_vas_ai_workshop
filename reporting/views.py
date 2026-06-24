"""Views for the Fund Reporting Hub."""
import random
from datetime import datetime

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ChatForm, MessageForm, NoteForm, ReportForm
from .models import (
    CONTROL_DEFS,
    LANGS,
    REPORT_STATUSES,
    TEAMS,
    Chat,
    Control,
    Message,
    Note,
    Report,
    Validation,
)

CURRENT_USER = "A. Weber"

# Tables exposed by the generic Database admin page.
DB_MODELS = {
    "reports": Report,
    "controls": Control,
    "validations": Validation,
    "notes": Note,
    "chats": Chat,
    "messages": Message,
}


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def dashboard(request):
    reports = Report.objects.all()
    total = reports.count()
    pending = reports.filter(status__in=["Pending", "In Review"]).count()
    validated = reports.filter(status="Validated").count()
    failing = reports.filter(controls__status="fail").distinct().count()

    cards = [
        {"label": "Total reports", "value": total, "bar": "blue", "delta": ""},
        {"label": "Awaiting validation", "value": pending, "bar": "amber", "delta": "Needs attention"},
        {"label": "Validated", "value": validated, "bar": "green", "delta": "Released-ready"},
        {"label": "With failing controls", "value": failing, "bar": "red", "delta": "Review controls"},
    ]

    team_progress = []
    for t in TEAMS:
        rel = Validation.objects.filter(team=t)
        done = rel.filter(state="approved").count()
        n = rel.count()
        pct = round(done / n * 100) if n else 0
        team_progress.append({"team": t, "done": done, "total": n, "pct": pct})

    control_summary = []
    for d in CONTROL_DEFS:
        qs = Control.objects.filter(control_id=d["id"])
        p = qs.filter(status="pass").count()
        w = qs.filter(status="warn").count()
        f = qs.filter(status="fail").count()
        tot = p + w + f or 1
        control_summary.append({
            "name": d["name"], "pass": p, "warn": w, "fail": f,
            "pct": round(p / tot * 100),
        })

    return render(request, "dashboard.html", {
        "active": "dashboard",
        "cards": cards,
        "team_progress": team_progress,
        "control_summary": control_summary,
        "pending": pending,
    })


# --------------------------------------------------------------------------
# Reports list + detail
# --------------------------------------------------------------------------
def _nav_pending():
    return Report.objects.filter(status__in=["Pending", "In Review"]).count()


def reports_list(request):
    qs = Report.objects.all()
    search = request.GET.get("search", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()
    lang = request.GET.get("lang", "").strip()
    status = request.GET.get("status", "").strip()

    if search:
        qs = qs.filter(Q(fund__icontains=search) | Q(isin__icontains=search))
    if date_from:
        qs = qs.filter(period__gte=date_from)
    if date_to:
        qs = qs.filter(period__lte=date_to)
    if lang:
        qs = qs.filter(lang=lang)
    if status:
        qs = qs.filter(status=status)

    return render(request, "reports.html", {
        "active": "reports",
        "reports": qs,
        "langs": LANGS,
        "statuses": REPORT_STATUSES,
        "filters": {"search": search, "from": date_from, "to": date_to,
                    "lang": lang, "status": status},
        "pending": _nav_pending(),
    })


def report_detail(request, pk):
    report = get_object_or_404(Report, pk=pk)
    return render(request, "report_detail.html", {
        "active": "reports",
        "report": report,
        "note_form": NoteForm(),
        "teams": report.validations.all(),
        "statuses": REPORT_STATUSES,
        "pending": _nav_pending(),
    })


def report_create(request):
    if request.method == "POST":
        form = ReportForm(request.POST)
        if form.is_valid():
            report = form.save()
            # default controls + validations
            for d in CONTROL_DEFS:
                Control.objects.create(
                    report=report, control_id=d["id"], name=d["name"],
                    descr=d["desc"], status="pass")
            for t in TEAMS:
                Validation.objects.create(report=report, team=t, state="pending")
            messages.success(request, f"Created report {report.id}.")
            return redirect("report_detail", pk=report.id)
    else:
        # suggest next id
        nums = []
        for r in Report.objects.values_list("id", flat=True):
            try:
                nums.append(int(str(r).split("-")[-1]))
            except ValueError:
                pass
        nxt = (max(nums) + 1) if nums else 1001
        form = ReportForm(initial={"id": f"R-{nxt}"})
    return render(request, "report_form.html", {
        "active": "reports", "form": form, "mode": "create",
        "pending": _nav_pending(),
    })


def report_edit(request, pk):
    report = get_object_or_404(Report, pk=pk)
    if request.method == "POST":
        form = ReportForm(request.POST, instance=report, editing=True)
        if form.is_valid():
            form.save()
            messages.success(request, f"Saved report {report.id}.")
            return redirect("report_detail", pk=report.id)
    else:
        form = ReportForm(instance=report, editing=True)
    return render(request, "report_form.html", {
        "active": "reports", "form": form, "mode": "edit", "report": report,
        "pending": _nav_pending(),
    })


@require_POST
def report_delete(request, pk):
    report = get_object_or_404(Report, pk=pk)
    rid = report.id
    report.delete()
    messages.success(request, f"Deleted report {rid}.")
    return redirect("reports")


@require_POST
def report_set_status(request, pk):
    report = get_object_or_404(Report, pk=pk)
    status = request.POST.get("status")
    if status in REPORT_STATUSES:
        report.status = status
        report.save()
        if status == "Validated":
            for v in report.validations.filter(state="pending"):
                v.state = "approved"
                v.signed_by = CURRENT_USER
                v.signed_at = now_stamp()
                v.save()
        messages.success(request, f"Status set to {status}.")
    return redirect("report_detail", pk=pk)


@require_POST
def validation_set(request, pk, vid):
    report = get_object_or_404(Report, pk=pk)
    validation = get_object_or_404(Validation, pk=vid, report=report)
    state = request.POST.get("state")
    if state in ("approved", "rejected", "pending"):
        validation.state = state
        validation.signed_by = CURRENT_USER if state != "pending" else ""
        validation.signed_at = now_stamp() if state != "pending" else ""
        validation.save()
        states = list(report.validations.values_list("state", flat=True))
        if "rejected" in states:
            report.status = "Rejected"
        elif states and all(s == "approved" for s in states):
            report.status = "Validated"
        else:
            report.status = "In Review"
        report.save()
        messages.success(request, f"{validation.team} → {state}.")
    return redirect("report_detail", pk=pk)


@require_POST
def note_add(request, pk):
    report = get_object_or_404(Report, pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.report = report
        note.author = CURRENT_USER
        note.created_at = now_stamp()
        note.save()
        messages.success(request, "Note added.")
    return redirect("report_detail", pk=pk)


@require_POST
def note_delete(request, pk, nid):
    note = get_object_or_404(Note, pk=nid, report_id=pk)
    note.delete()
    messages.success(request, "Note deleted.")
    return redirect("report_detail", pk=pk)


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------
def controls_view(request):
    all_controls = Control.objects.all()
    p = all_controls.filter(status="pass").count()
    w = all_controls.filter(status="warn").count()
    f = all_controls.filter(status="fail").count()
    tot = p + w + f or 1
    cards = [
        {"label": "Total control runs", "value": tot, "bar": "blue"},
        {"label": "Passed", "value": f"{p} ({round(p/tot*100)}%)", "bar": "green"},
        {"label": "Warnings", "value": w, "bar": "amber"},
        {"label": "Failures", "value": f, "bar": "red"},
    ]
    catalogue = []
    for d in CONTROL_DEFS:
        flagged = (Control.objects
                   .filter(control_id=d["id"], status__in=["fail", "warn"])
                   .select_related("report")
                   .order_by("-status")[:4])
        catalogue.append({
            "name": d["name"], "desc": d["desc"],
            "flagged": [{"rid": c.report_id, "fund": c.report.fund, "status": c.status}
                        for c in flagged],
        })

    # Include RDF/SPARQL RM rules (control_id matches the rule id).
    from .fundlink_rdf import RULE_DEFS
    for d in RULE_DEFS:
        flagged = (Control.objects
                   .filter(control_id=d["id"], status__in=["fail", "warn"])
                   .select_related("report")
                   .order_by("-status")[:4])
        catalogue.append({
            "name": f"{d['name']} (RDF)", "desc": d["descr"],
            "flagged": [{"rid": c.report_id, "fund": c.report.fund, "status": c.status}
                        for c in flagged],
        })

    return render(request, "controls.html", {
        "active": "controls", "cards": cards, "catalogue": catalogue,
        "pending": _nav_pending(),
    })


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
def chat_view(request, chat_id=None):
    chats = Chat.objects.all()
    if chat_id is None and chats:
        chat_id = chats[0].id
    current = chats.filter(id=chat_id).first() if chat_id else None
    return render(request, "chat.html", {
        "active": "chat", "chats": chats, "current": current,
        "msg_form": MessageForm(), "chat_form": ChatForm(),
        "pending": _nav_pending(),
    })


@require_POST
def chat_send(request, chat_id):
    chat = get_object_or_404(Chat, pk=chat_id)
    text = request.POST.get("text", "").strip()
    if text:
        Message.objects.create(
            chat=chat, who="You", is_me=True, text=text,
            created_at=datetime.now().strftime("%H:%M"))
        replies = [
            "Thanks, looking into it now.",
            "Noted — I'll get back to you shortly.",
            "Confirmed, the figures look consistent.",
            "Could you also include the FX breakdown?",
            "Received, will validate against the ledger.",
        ]
        who = chat.sub.replace("with ", "") if chat.sub else "Desk"
        Message.objects.create(
            chat=chat, who=who, is_me=False, text=random.choice(replies),
            created_at=datetime.now().strftime("%H:%M"))
    return redirect("chat_detail", chat_id=chat_id)


@require_POST
def chat_create(request):
    name = request.POST.get("name", "").strip()
    if name:
        cid = "C" + datetime.now().strftime("%Y%m%d%H%M%S")
        chat = Chat.objects.create(id=cid, name="Ad-hoc: " + name,
                                   sub="with reporting desk")
        Message.objects.create(
            chat=chat, who="You", is_me=True, text="Request: " + name,
            created_at=datetime.now().strftime("%H:%M"))
        return redirect("chat_detail", chat_id=cid)
    return redirect("chat")


@require_POST
def chat_delete(request, chat_id):
    chat = get_object_or_404(Chat, pk=chat_id)
    chat.delete()
    messages.success(request, "Conversation deleted.")
    return redirect("chat")


# --------------------------------------------------------------------------
# Database admin (generic CRUD over every table)
# --------------------------------------------------------------------------
def _model_fields(model):
    return [f.name for f in model._meta.fields]


def database_view(request, table="reports"):
    if table not in DB_MODELS:
        table = "reports"
    model = DB_MODELS[table]
    fields = _model_fields(model)
    rows = []
    for obj in model.objects.all():
        rows.append({"pk": obj.pk, "values": [getattr(obj, f) for f in fields]})
    return render(request, "database.html", {
        "active": "database",
        "tables": list(DB_MODELS.keys()),
        "table": table,
        "fields": fields,
        "rows": rows,
        "pending": _nav_pending(),
    })


def _editable_fields(model):
    """Field names that can be edited (skip auto PK for integer-PK models)."""
    out = []
    for f in model._meta.fields:
        if f.auto_created and f.primary_key:
            continue
        out.append(f)
    return out


def database_form(request, table, pk=None):
    if table not in DB_MODELS:
        return redirect("database")
    model = DB_MODELS[table]
    instance = get_object_or_404(model, pk=pk) if pk is not None else None
    edit_fields = _editable_fields(model)

    if request.method == "POST":
        data = {}
        for f in edit_fields:
            raw = request.POST.get(f.name, "")
            if f.get_internal_type() == "BooleanField":
                data[f.name] = raw in ("on", "true", "1", "True")
            else:
                data[f.name] = raw
        try:
            if instance is None:
                # handle FK fields and char PK
                obj = model()
                for f in edit_fields:
                    _assign(obj, f, data[f.name])
                obj.save()
            else:
                for f in edit_fields:
                    _assign(instance, f, data[f.name])
                instance.save()
            messages.success(request, f"Saved row in {table}.")
            return redirect("database_table", table=table)
        except Exception as exc:  # surface DB/validation errors
            messages.error(request, f"Error: {exc}")

    # build field descriptors for template
    field_defs = []
    for f in edit_fields:
        value = getattr(instance, f.attname, "") if instance else ""
        field_defs.append({
            "name": f.name,
            "value": value,
            "is_bool": f.get_internal_type() == "BooleanField",
            "is_fk": f.is_relation,
        })
    return render(request, "table_form.html", {
        "active": "database",
        "table": table,
        "field_defs": field_defs,
        "mode": "edit" if instance else "create",
        "pending": _nav_pending(),
    })


def _assign(obj, field, raw):
    if field.is_relation:
        setattr(obj, field.attname, raw or None)
    elif field.get_internal_type() == "BooleanField":
        setattr(obj, field.name, bool(raw))
    else:
        setattr(obj, field.name, raw)


@require_POST
def database_delete(request, table, pk):
    if table in DB_MODELS:
        model = DB_MODELS[table]
        obj = get_object_or_404(model, pk=pk)
        obj.delete()
        messages.success(request, f"Deleted row from {table}.")
    return redirect("database_table", table=table)


@require_POST
def database_reset(request):
    from django.core.management import call_command
    call_command("seed", reset=True)
    messages.success(request, "Demo data reset to seed state.")
    return redirect("database_table", table="reports")


# --------------------------------------------------------------------------
# FundLink (Oracle data warehouse)
# --------------------------------------------------------------------------
def fundlink_view(request):
    from . import fundlink

    status_ok, status_msg = fundlink.test_connection()
    columns, rows, error, sql = None, None, None, ""
    sparql, sparql_cols, sparql_rows, sparql_error = "", None, None, None
    rule_results = None
    question, nl_sql, nl_cols, nl_rows, nl_error = "", "", None, None, None

    if request.method == "POST":
        action = request.POST.get("action", "sql")

        if action == "sql":
            sql = request.POST.get("sql", "").strip()
            if sql:
                try:
                    columns, raw_rows = fundlink.run_query(sql)
                    rows = [[("" if v is None else v) for v in r] for r in raw_rows]
                except Exception as exc:  # surface DB/validation errors in the UI
                    error = str(exc)

        elif action == "ask":
            question = request.POST.get("question", "").strip()
            if question:
                from . import nl2sql
                result = nl2sql.ask(question)
                nl_sql = result["sql"]
                nl_cols = result["columns"]
                nl_rows = result["rows"]
                nl_error = result["error"]

        elif action == "sparql":
            sparql = request.POST.get("sparql", "").strip()
            if sparql:
                try:
                    from . import fundlink_rdf
                    graph = fundlink_rdf.load(limit=500, active_only=True)
                    sparql_cols, sparql_rows = fundlink_rdf.run_sparql(graph, sparql)
                except Exception as exc:
                    sparql_error = str(exc)

        elif action == "run_rules":
            try:
                rule_results = _run_rdf_rules()
                applied = sum(r["applied"] for r in rule_results)
                messages.success(
                    request,
                    f"RM rules evaluated. {applied} control(s) recorded against reports.",
                )
            except Exception as exc:
                sparql_error = str(exc)

    return render(request, "fundlink.html", {
        "active": "fundlink",
        "status_ok": status_ok,
        "status_msg": status_msg,
        "columns": columns,
        "rows": rows,
        "error": error,
        "sql": sql,
        "question": question,
        "nl_sql": nl_sql,
        "nl_cols": nl_cols,
        "nl_rows": nl_rows,
        "nl_error": nl_error,
        "sparql": sparql,
        "sparql_cols": sparql_cols,
        "sparql_rows": sparql_rows,
        "sparql_error": sparql_error,
        "rule_results": rule_results,
        "pending": _nav_pending(),
    })


def _run_rdf_rules():
    """Build the RDF graph, run RM rules, and record results as Controls.

    For each rule violation whose ISIN matches an existing Report, a Control
    row is created/updated. Returns a per-rule summary for the UI.
    """
    from . import fundlink_rdf

    graph = fundlink_rdf.load(limit=500, active_only=True)
    results = fundlink_rdf.run_rules(graph)

    # Map ISIN -> reports so we can attach controls.
    summary = []
    for rule in results:
        applied = 0
        matched_reports = Report.objects.filter(isin__in=rule["violations"])
        for report in matched_reports:
            Control.objects.update_or_create(
                report=report,
                control_id=rule["id"],
                defaults={
                    "name": rule["name"],
                    "descr": rule["descr"],
                    "status": rule["severity"],
                },
            )
            applied += 1
        # Reports that satisfy the rule -> mark pass.
        ok_reports = Report.objects.exclude(isin__in=rule["violations"])
        for report in ok_reports:
            Control.objects.update_or_create(
                report=report,
                control_id=rule["id"],
                defaults={
                    "name": rule["name"],
                    "descr": rule["descr"],
                    "status": "pass",
                },
            )
        summary.append({
            "id": rule["id"],
            "name": rule["name"],
            "descr": rule["descr"],
            "severity": rule["severity"],
            "violation_count": len(rule["violations"]),
            "applied": applied,
        })
    return summary


