import smtplib
import logging
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_report(jobs: list[dict], config: dict):
    email_cfg = config["email"]

    if not jobs and not email_cfg.get("send_if_empty", False):
        logger.info("No new jobs and send_if_empty=false — skipping email")
        return

    if not email_cfg.get("smtp_user") or not email_cfg.get("to_address"):
        logger.warning("Email not configured — printing report to console instead")
        _print_report(jobs)
        return

    if not email_cfg.get("smtp_password"):
        logger.warning(
            "SMTP password not set (smtp_password_env / SMTP_PASSWORD) — "
            "printing report to console instead"
        )
        _print_report(jobs)
        return

    subject = f"Job Hunt Report {date.today()} — {len(jobs)} new listing(s)"
    html = _build_html(jobs)
    plain = _build_plain(jobs)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["smtp_user"]
    msg["To"] = email_cfg["to_address"]
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
            server.sendmail(
                email_cfg["smtp_user"],
                email_cfg["to_address"],
                msg.as_string(),
            )
        logger.info(f"Email sent to {email_cfg['to_address']} with {len(jobs)} jobs")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        _print_report(jobs)


def _build_html(jobs: list[dict]) -> str:
    if not jobs:
        return "<p>No new job listings found today.</p>"

    rows = ""
    for job in jobs:
        salary = _fmt_salary(job)
        roles = _fmt_roles(job)
        rows += f"""
        <tr>
          <td><a href="{job['url']}">{job['title']}</a></td>
          <td>{job['company']}</td>
          <td>{job['location']}</td>
          <td>{salary}</td>
          <td>{roles}</td>
          <td>{job['category']}</td>
          <td>{job['created'][:10] if job['created'] else ''}</td>
        </tr>"""

    return f"""
    <html><body>
    <h2>New Job Listings — {date.today()}</h2>
    <p>{len(jobs)} new listing(s) matched your filters.</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
      <thead style="background:#f0f0f0">
        <tr><th>Title</th><th>Company</th><th>Location</th><th>Salary</th><th>Matched Roles</th><th>Category</th><th>Posted</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </body></html>"""


def _build_plain(jobs: list[dict]) -> str:
    if not jobs:
        return "No new job listings found today."

    lines = [f"New Job Listings — {date.today()}", f"{len(jobs)} new listing(s)\n"]
    for i, job in enumerate(jobs, 1):
        lines.append(f"{i}. {job['title']} @ {job['company']}")
        lines.append(f"   Location: {job['location']}")
        lines.append(f"   Salary:   {_fmt_salary(job)}")
        lines.append(f"   Roles:    {_fmt_roles(job)}")
        lines.append(f"   URL:      {job['url']}")
        lines.append("")
    return "\n".join(lines)


def _fmt_salary(job: dict) -> str:
    lo, hi = job.get("salary_min"), job.get("salary_max")
    if lo and hi:
        return f"£{lo:,.0f} – £{hi:,.0f}"
    if lo:
        return f"£{lo:,.0f}+"
    if hi:
        return f"up to £{hi:,.0f}"
    return "Not specified"


def _fmt_roles(job: dict) -> str:
    roles = job.get("matched_roles")
    if isinstance(roles, list) and roles:
        return ", ".join(str(r) for r in roles)
    return "Default"


def _print_report(jobs: list[dict]):
    print(_build_plain(jobs))
