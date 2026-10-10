"""What the customer would actually receive: WhatsApp-style alerts per urgent item and a weekly owner digest.
Pure text built from the engine's items, so it is identical in the server and in the static demo."""
import engine


def ar_days(n: int) -> str:
    if n == 1:
        return "يوم واحد"
    if n == 2:
        return "يومين"
    return f"{n} أيام" if 3 <= n <= 10 else f"{n} يومًا"


def _what(i: dict) -> str:
    if i["kind"] == "group":
        return f"{i['count']} × {i['title']}"
    if i["kind"] == "employee_doc":
        return f"{i['title']} — {i['employee']['name']} ({i['employee']['role']})"
    return i["title"]


def _when(i: dict) -> str:
    left = i["days_left"]
    if left < 0:
        return f"متأخر منذ {ar_days(-left)} (الاستحقاق {i['due_date']})"
    if left == 0:
        return f"يستحق اليوم ({i['due_date']})"
    return f"يستحق خلال {ar_days(left)} ({i['due_date']})"


def _text(i: dict) -> str:
    icon = "🔴" if i["status"] == "overdue" else "🟠"
    lines = [f"{icon} تنبيه امتثال — {i['branch_name']}", _what(i), _when(i),
             f"التعرض المالي التقديري: {i['penalty_sar']} ريال", f"الإجراء: {i['fix_steps'][0]}"]
    if i.get("vip_name"):
        lines.append(f"للتنفيذ نيابةً عنك: {i['vip_name']} (VIP)")
    return "\n".join(lines)


def message_text(i: dict) -> str:
    """The reminder text for one item (also what the one-tap reminder returns)."""
    return _text(i)


def build(org: dict, branches: list[dict], items: list[dict]) -> dict:
    picks = list(engine.urgent(items, 4))
    soon_emp = sorted((i for i in items if i["kind"] == "employee_doc" and i["status"] == "soon"),
                      key=lambda i: (i["days_left"], int(i["id"][2:])))
    picks += soon_emp[:2]
    messages = [dict(id=i["id"], channel="whatsapp", to=f"مدير {i['branch_name']}", status=i["status"],
                     days_left=i["days_left"], text=_text(i)) for i in picks]

    score = engine.score(items)
    cnt = engine.counts(items)
    scored = [(b["name"], engine.score([i for i in items if i["branch_id"] == b["id"]])) for b in branches]
    worst = None
    for name, s in scored:
        if worst is None or s < worst[1]:
            worst = (name, s)
    top = engine.urgent(items, 3)
    body = [f"مؤشر الجاهزية: {score} من 100",
            f"التعرض المالي للبنود المتأخرة: {engine.money_at_risk(items)} ريال",
            f"بنود متأخرة: {cnt['overdue']} — بنود تقترب: {cnt['soon']}"]
    if worst:
        body.append(f"أضعف فرع: {worst[0]} ({worst[1]} من 100)")
    if top:
        body.append("أهم ما يحتاج إجراءً هذا الأسبوع:")
        body += [f"{n}. {_what(i)} — {i['branch_name']}" for n, i in enumerate(top, start=1)]
    return dict(
        summary=dict(overdue_items=cnt["overdue"], penalty_sar=engine.money_at_risk(items)),
        messages=messages,
        digest=dict(channel="email", to="مالك المنشأة / مدير الموارد البشرية", subject=f"ملخص امتثال الأسبوعي — {org['name']}",
                    body="\n".join(body)))
