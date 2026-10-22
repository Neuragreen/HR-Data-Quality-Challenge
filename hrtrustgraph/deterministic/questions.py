"""A small, explicit question vocabulary backed by calculated reports."""
import re


def answer_question(reports, text):
    text = " ".join(str(text).casefold().split())
    if re.fullmatch(r"(?:how many active employees (?:are (?:there )?)?in dubai|active employees in dubai|dubai active headcount)\??", text):
        key, sources = "active_headcount_dubai", ["core_hr"]
    elif re.fullmatch(r"(?:how many leavers have enabled accounts|leavers with enabled accounts|leaver access exceptions)\??", text):
        key, sources = "leaver_enabled_accounts", ["core_hr", "access_directory"]
    elif re.fullmatch(r"(?:how many payroll (?:profiles|records) (?:have (?:conflicts|discrepancies)|need reconciliation)|payroll reconciliation (?:exceptions|conflicts)|payroll discrepancies)\??", text):
        key, sources = "payroll_reconciliation", ["core_hr", "payroll"]
    else:
        raise ValueError("Try ‘How many active employees in Dubai?’, ‘How many leavers have enabled accounts?’ or ‘How many payroll profiles have conflicts?’ These are the three supported report questions.")
    report = reports[key]
    return {"report_id": key, "answer": report["value"] if report["availability"] == "available" else None, "availability": report["availability"], "sources": sources, "as_of": report["as_of"], "definition": report["definition"], "unresolved_cases": len(report["unresolved"]), "contributing_record_count": len(report["contributors"]), "contributing_record_sample": report["contributors"][:5], "assurance": report.get("assurance"), "language_model_used": False}
