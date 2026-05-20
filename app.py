import streamlit as st
import anthropic
import requests
import sqlite3
import json
import os
import re
import base64
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv("/Users/eugenelevinson/Desktop/VS Code Projects/.env")
except Exception:
    pass

def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

ANTHROPIC_KEY = _secret("ANTHROPIC_API_KEY")
ADZUNA_APP_ID = _secret("ADZUNA_APP_ID")
ADZUNA_APP_KEY = _secret("ADZUNA_APP_KEY")
DB_PATH            = os.path.join(os.path.dirname(__file__), "applications.db")
BASE_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "BASE_TEMPLATE.docx")

# ── Resume baseline (v3 — elevated content, locked format) ────────────────────
# Used by job scoring, cover letter generation, and resume coaching.
# Update this when bullet content changes in build_steve_resume_v3.py.
RESUME_TEXT = """Stanislav Spektor
925-639-3898 | s.spektor93@gmail.com | linkedin.com/in/stanislav-spektor

Tagline: Regulatory Compliance | Financial Close | ERP Systems | Process Engineering

Profile
10+ years at the center of financial compliance, close operations, and system infrastructure for a California state-designated regulatory authority.
Proven at engineering financial solutions that pass every audit, deploy without defect, and become the standard other accountants inherit.
Strong in financial controls and process engineering, building permanent fixes that survive audit cycles, leadership transitions, and system migrations.

Skills
Financial Close & Reporting | Regulatory Compliance | Budgeting & Forecasting | Variance Analysis
ERP Systems (Sage Intacct) | UAT & System Implementation | AR/AP Cycle Management | Assessment Reconciliation
Audit Preparation & Review | Financial Controls Design | Stakeholder Management | Process Standardization

Professional Experience

Workers' Compensation Insurance Rating Bureau of California
Designated Statistical Agent of the California Insurance Commissioner

Senior Accountant – Membership & Assessments: Jan 2022 – Feb 2026
- Directed compliance and regulatory submissions for 400+ member insurers, sustaining a zero-finding audit record across eight consecutive review cycles.
  (Became the organization's compliance audit authority, with no corrective actions, no material findings, and no exceptions filed during four years in role.)
- Deployed the organization's cloud billing platform end to end, authoring 250+ UAT test cases and delivering a zero-defect go-live on schedule.
  (Retired the legacy billing workflow entirely, replacing it with automated processing that has run without a reconciliation exception since launch.)
- Engineered a reconciliation process that eliminated 90% of the standing AR backlog, compressing period-end close from weeks of manual recovery to 3 days.
  (The redesigned process became the department's close standard, permanently removing backlog management from the monthly cycle.)

Member Services Accounting Specialist: Aug 2019 – Jan 2022
- Delivered complete close cycles across three consecutive fiscal years — monthly, quarterly, and year-end — with perfect accuracy and zero missed deadlines.
  (Completed every close package three days ahead of the departmental deadline, achieving 36 consecutive on-time deliveries across three fiscal years.)
- Maintained AR reconciliation within a 5-day post-close window for all accounts across 2.5 years without a single error or submission deadline missed.
  (Billing accuracy held above departmental targets every period, with not a single correction filed or reconciliation window missed on record.)
- Spearheaded UAT for the assessment calculation platform from initial test design through department-wide rollout, achieving full adoption in 30 days.
  (Authored the complete test scenario library, standardized for reuse, adopted as the QA framework for every subsequent platform launch.)

Accounting and Compliance Specialist: Oct 2017 – Aug 2019
- Built and maintained 25+ procedure documents to audit standards, passing two consecutive regulatory review cycles without a single finding.
  (Procedure library outlasted the role, adopted as the compliance baseline by three peer departments and institutionalized as the organizational standard.)
- Reduced recurring financial discrepancies 30% through systematic audit cycles, root cause analysis, and stakeholder-accountable corrective actions.
  (Converted a persistent 15-item discrepancy log into a stable 2-item baseline, then held it there through the end of tenure.)
- Managed financial data preparation, reconciliation, and validation across the full assessment cycle for a high-volume regulated member portfolio.
  (Built the reconciliation methodology that became department standard, applied unchanged by two successive accountants across the next four years.)

East Bay Nephrology Medical Group — Leading Nephrology Practice in Northern California
Contracted Accounting Consultant: Jul 2016 – Aug 2017
- Managed the full AP/AR cycle for 300+ monthly transactions at 98% accuracy, maintaining on-time close and zero billing disputes throughout the engagement.
  (Identified a chronic billing discrepancy that had gone undetected for over six months and corrected it within the first billing cycle of the engagement.)
- Led end-to-end ERP migration, designing the transition plan, training 10+ staff, and executing a zero-disruption go-live on schedule.
  (The migration cut the monthly close cycle in half, enabling the practice to deliver financial reports to leadership earlier than any prior period.)
- Closed every reporting period for practice leadership with zero errors and zero missed deadlines across the full 12-month engagement.
  (Earned a scope extension beyond the original contract, with leadership citing delivery consistency and error-free financial reporting as the basis.)

Education
B.A. Economics, University of California, Davis, 2016

Technical Skills
Software: Sage Intacct, Advanced Excel, Power BI, ADP, SharePoint
"""

st.set_page_config(page_title="Steve's Job Finder", page_icon="💼", layout="wide")

st.markdown("""
<style>
.score-high { color: #2ecc71; font-size: 1.4rem; font-weight: bold; }
.score-mid  { color: #f39c12; font-size: 1.4rem; font-weight: bold; }
.score-low  { color: #e74c3c; font-size: 1.4rem; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, company TEXT, location TEXT,
        url TEXT, salary TEXT,
        status TEXT DEFAULT 'Saved',
        notes TEXT DEFAULT '',
        saved_date TEXT,
        job_description TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ats_keyword_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_title TEXT,
        keywords TEXT,
        template TEXT,
        logged_date TEXT
    )""")
    conn.commit()
    conn.close()


def load_resume():
    return RESUME_TEXT


def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()

def _title_relevant(job_title, search_title):
    words = [w for w in search_title.lower().split() if len(w) > 3]
    jt = job_title.lower()
    return any(w in jt for w in words)

def _fetch_adzuna(title, location, min_salary):
    results, page = [], 1
    while True:
        params = {
            "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
            "what": title, "where": location,
            "results_per_page": 50, "sort_by": "relevance",
            "content-type": "application/json",
        }
        if min_salary:
            params["salary_min"] = min_salary
        try:
            r = requests.get(f"https://api.adzuna.com/v1/api/jobs/us/search/{page}", params=params, timeout=12)
            r.raise_for_status()
            batch = r.json().get("results", [])
            for j in batch:
                j["_source"] = "Adzuna"
            results.extend(batch)
            if len(batch) < 50: break
            page += 1
        except Exception:
            break
    return results

def _fetch_muse(title, location):
    results, page = [], 1
    while True:
        try:
            r = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"category": "Accounting & Finance", "level": "Senior Level", "page": page},
                timeout=10,
            )
            r.raise_for_status()
            data  = r.json()
            batch = data.get("results", [])
            for j in batch:
                jt = j.get("name", "")
                if not _title_relevant(jt, title):
                    continue
                locs = j.get("locations", [])
                loc_name = locs[0].get("name", "Not listed") if locs else "Not listed"
                results.append({
                    "title": jt,
                    "company": {"display_name": j.get("company", {}).get("name", "")},
                    "location": {"display_name": loc_name},
                    "description": _strip_html(j.get("contents", "")),
                    "redirect_url": j.get("refs", {}).get("landing_page", "#"),
                    "salary_min": None, "salary_max": None,
                    "contract_time": "", "contract_type": "",
                    "_source": "The Muse",
                })
            if page >= data.get("page_count", 1): break
            page += 1
        except Exception:
            break
    return results

def _fetch_remoteok(title):
    try:
        tags = "+".join(t for t in title.lower().split() if len(t) > 3)
        r = requests.get(
            f"https://remoteok.com/api?tags={tags}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        jobs = [j for j in r.json() if isinstance(j, dict) and j.get("position")]
        out = []
        for j in jobs:
            out.append({
                "title": j.get("position", ""),
                "company": {"display_name": j.get("company", "")},
                "location": {"display_name": "Remote"},
                "description": _strip_html(j.get("description", "")),
                "redirect_url": j.get("url", "#"),
                "salary_min": j.get("salary_min"), "salary_max": j.get("salary_max"),
                "contract_time": "full_time", "contract_type": "",
                "_source": "RemoteOK",
            })
        return out
    except Exception:
        return []

def search_jobs(title, location, min_salary=None):
    # Fetch all three sources in parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_adzuna   = ex.submit(_fetch_adzuna, title, location, min_salary)
        f_muse     = ex.submit(_fetch_muse, title, location)
        f_remoteok = ex.submit(_fetch_remoteok, title)
        try: adzuna_jobs   = f_adzuna.result()
        except Exception: adzuna_jobs = []
        try: muse_jobs     = f_muse.result()
        except Exception: muse_jobs = []
        try: remoteok_jobs = f_remoteok.result()
        except Exception: remoteok_jobs = []

    # Adzuna goes in first — it's the primary source and has the most data.
    # Other sources only add jobs not already in Adzuna.
    seen, deduped = set(), []
    for j in adzuna_jobs:
        key = (j.get("title","").lower().strip(), j.get("company",{}).get("display_name","").lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(j)
    for j in muse_jobs + remoteok_jobs:
        key = (j.get("title","").lower().strip(), j.get("company",{}).get("display_name","").lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(j)

    return deduped


def analyze_job(title, company, description, resume_text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""Analyze this job match. Return ONLY valid JSON, no other text.

RESUME:
{resume_text}

JOB: {title} at {company}
DESCRIPTION: {description[:3000]}

{{
  "score": <integer 0-100>,
  "verdict": "Strong Match" | "Good Match" | "Partial Match" | "Weak Match",
  "strengths": ["...", "...", "..."],
  "gaps": ["...", "..."],
  "tip": "<one specific, actionable tip to improve chances for this role>"
}}"""
        }]
    )
    raw = msg.content[0].text.strip()
    import re as _re
    match = _re.search(r'\{[\s\S]*\}', raw)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def stream_cover_letter(title, company, description, resume_text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Write a professional cover letter for Stanislav Spektor applying for this role.

RESUME:
{resume_text}

ROLE: {title} at {company}
JOB DESCRIPTION: {description[:3000]}

Write 3 paragraphs. Start with "Dear Hiring Manager," — no address headers.
Reference specific achievements and numbers from the resume.
Show genuine interest in this specific company and role.
End with a clear call to action."""
        }]
    ) as stream:
        for text in stream.text_stream:
            yield text


def get_resume_tips(target_role, resume_text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{
            "role": "user",
            "content": f"""You are a professional resume coach. Review this resume targeting: {target_role}

RESUME:
{resume_text}

Provide:
## Top 3 Strengths
List what this resume does well.

## Top 5 Improvements
Specific, actionable changes to make.

## ATS Keywords to Add
List 10+ keywords that ATS systems look for in {target_role} roles that are missing or underused.

## Overall Score: X/10
Brief justification.

Be specific — reference actual content from the resume."""
        }]
    ) as stream:
        for text in stream.text_stream:
            yield text


def optimize_resume_for_job(job_title, job_description):
    """
    Rewrites Steve's v3 resume content for a specific job description using the
    locked ATS optimization prompt. Returns validated JSON matching the v3 structure.
    Format is frozen — only content changes.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        temperature=0.3,
        messages=[{
            "role": "user",
            "content": f"""You are Stanislav Spektor's personal resume strategist. Your job is to optimize
his resume for maximum ATS coverage and recruiter impact for the specific role
below — without ever compromising the quality of the language.

## BASELINE RESUME (optimize FROM this — never produce output below this quality)

{RESUME_TEXT}

## JOB DESCRIPTION

Title: {job_title}
{job_description[:4000]}

## OBJECTIVE

Rewrite the content variables so the resume reads as if Steve was written for
this specific role, while maintaining the elevated standard of the baseline above.

## RULES — NON-NEGOTIABLE

STRUCTURE (frozen — never changes):
- 3 profile bullets exactly
- 4 positions, 3 bullets each, every bullet has a main + sub
- Skills: 3 columns, 4 items per column = 12 items total
- Titles, company names, dates: never touch

OPENING VERBS:
- Every opening word across all 15 bullets (12 position + 3 profile) must be
  different — no repeated first word anywhere in the document

METRICS:
- Every number (90%, 400+, 250+, 30%, 3 days, 36, 300+, 98%) appears exactly
  once across the entire document — never twice

SUB-BULLETS:
- Each sub adds genuinely new information the main does not already contain
- The sub answers a different question than the main — it does not restate it

EXAMPLE — good vs bad sub-bullet:

  Main: "Deployed the organization's cloud billing platform end to end, authoring
         250+ UAT test cases and delivering a zero-defect go-live on schedule."

  BAD sub (restates — adds nothing new):
  "Successfully completed the billing platform deployment with zero defects and
   full test coverage across all cases."

  GOOD sub (adds new information — what permanently changed):
  "Retired the legacy billing workflow entirely, replacing it with automated
   processing that has run without a reconciliation exception since launch."

The test: if the sub could be removed and the reader loses nothing they didn't
already know from the main bullet, rewrite it.

KEYWORD PLACEMENT:
- Skills grid: explicit 1-4 word labels — ATS scanners prioritize these
- Bullets: prove the keywords through achievement, numbers, and context
- Profile: career identity — who Steve is, not what he knows
- No concept dominates more than one section
- If you cannot insert a keyword without weakening the sentence, find another
  placement or skip it — quality beats keyword density every time

VOICE PER ROLE:
- WCIRB Senior Accountant: owner and architect — strategic, systems-level impact
- WCIRB Member Services: high-precision operator — sustained accuracy under standards
- WCIRB Accounting & Compliance: infrastructure builder — foundational, institutional, durable
- East Bay Nephrology: diagnostic consultant — found problems, fixed them, earned extended trust

WCIRB THREE-ROLE STRUCTURE — READ CAREFULLY:
Positions 2 (Member Services) and 3 (Accounting & Compliance) do not display a
company header line in the rendered resume. Only position 1 (Senior Accountant)
shows the WCIRB company name. However, all three roles are at the same organization.
This means:
- The bullets for positions 2 and 3 do NOT need to introduce or name the company
- The company's context — regulatory environment, the 400+ member insurer portfolio,
  the state-designated authority status, the compliance stakes — can and should still
  be referenced WITHIN the bullet content where relevant
- Write positions 2 and 3 as continued progression within the same high-stakes
  regulatory environment, not as unrelated roles

EXISTING METRICS STAY:
- Keep 90%, 400+, 250+, 30%, 3 days, 36, 300+, 98% unless the JD provides
  something directly stronger and more relevant to replace them

LANGUAGE:
- No em dashes (—) as sentence separators — use commas or rephrase
- No hyphens as sentence separators
- Ownership-level verbs throughout

CHARACTER LIMITS (hard):
- Profile bullets: ≤150 chars
- Main bullets: ≤155 chars
- Sub-bullets: 100–150 chars (intentionally 2 lines — do not write short subs)
- Skills items: ≤30 chars each
- tech_skills string: ≤77 chars total

OUT OF SCOPE:
- If a JD requirement has no connection to Steve's actual experience, do not
  invent it — address the closest adjacent skill Steve genuinely has, or omit

## SELF-CRITIQUE — run before returning, fix anything that fails

1. Do any two bullets start with the same verb? Fix.
2. Does any metric appear more than once? Remove the duplicate.
3. Does any sub restate its main in different words? Rewrite to add new info.
4. Does any keyword feel bolted on rather than earned by the content? Reposition or remove.
5. Does any profile bullet echo language from the skills grid? Make it identity-based.
6. Does any string exceed its character limit? Trim.

## OUTPUT — valid JSON only, nothing outside it

{{
  "profile": ["bullet1", "bullet2", "bullet3"],
  "positions": {{
    "wcirb_senior":     {{"bullets": [{{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}]}},
    "wcirb_member":     {{"bullets": [{{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}]}},
    "wcirb_accounting": {{"bullets": [{{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}]}},
    "east_bay":         {{"bullets": [{{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}, {{"main":"...","sub":"..."}}]}}
  }},
  "skills_table": [
    ["...","...","...","..."],
    ["...","...","...","..."],
    ["...","...","...","..."]
  ],
  "tech_skills": "...",
  "keywords_added": ["...","..."]
}}"""
        }]
    )
    raw = msg.content[0].text.strip()
    import re as _re
    m = _re.search(r'\{[\s\S]*\}', raw)
    if m:
        raw = m.group(0)
    result = json.loads(raw)
    _validate_ats_output(result)
    return result


def _validate_ats_output(data):
    """
    Validate and normalize Claude's JSON to match the v3 structure.
    Normalizes skills_table to exactly 3 columns of 4 items regardless of
    what orientation Claude returned (it sometimes returns 4x3 instead of 3x4).
    """
    errors = []

    # Profile: exactly 3 bullets
    if len(data.get("profile", [])) != 3:
        errors.append(f"profile: expected 3 bullets, got {len(data.get('profile', []))}")

    # Positions: all 4, each with 3 main+sub bullet pairs
    for key in ["wcirb_senior", "wcirb_member", "wcirb_accounting", "east_bay"]:
        bullets = data.get("positions", {}).get(key, {}).get("bullets", [])
        if len(bullets) != 3:
            errors.append(f"{key}: expected 3 bullets, got {len(bullets)}")
        for i, b in enumerate(bullets):
            if "main" not in b or "sub" not in b:
                errors.append(f"{key}[{i}]: missing 'main' or 'sub'")

    # Skills table: normalize to 3 columns of 4 items
    # Claude sometimes returns 4 rows of 3 instead of 3 columns of 4 — flatten and reshape.
    skills = data.get("skills_table", [])
    flat = [item for col in skills for item in (col if isinstance(col, list) else [col])]
    if len(flat) < 9:
        errors.append(f"skills_table: too few items ({len(flat)}) — expected 12")
    else:
        # Pad to 12 if slightly short, truncate if longer
        flat = (flat + [""] * 12)[:12]
        data["skills_table"] = [flat[0:4], flat[4:8], flat[8:12]]

    if errors:
        raise ValueError("ATS output validation failed:\n" + "\n".join(errors))


# ── Locked resume builder — Eugene Levinson format, v3 content ────────────────
# Identical logic to build_steve_resume_v3.py. Format is frozen.
# Only the content variables (bullets, profile, skills) come from Claude's JSON.

import copy as _copy

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_IDX = {
    "name": 0, "contact": 2, "tagline": 4,
    "profile_0": 8, "profile_1": 9, "profile_2": 10, "profile_3": 11,
    "s1_header": 17, "s1_title": 18, "s1_desc": 19,
    "s1_main_0": 20, "s1_sub_0": 21, "s1_main_1": 22, "s1_sub_1": 23, "s1_main_2": 24, "s1_sub_2": 25,
    "s2_header": 27, "s2_title": 28, "s2_desc": 29,
    "s2_main_0": 30, "s2_sub_0": 31, "s2_main_1": 32, "s2_sub_1": 33, "s2_main_2": 34, "s2_sub_2": 35,
    "s3_header": 36, "s3_title": 37, "s3_desc": 38,
    "s3_main_0": 39, "s3_sub_0": 40, "s3_main_1": 41, "s3_sub_1": 42, "s3_main_2": 43, "s3_sub_2": 44,
    "s4_header": 46, "s4_title": 47, "s4_desc": 48,
    "s4_main_0": 49, "s4_sub_0": 50, "s4_main_1": 51, "s4_sub_1": 52, "s4_main_2": 53, "s4_sub_2": 54,
    "s5_paras": list(range(56, 66)),
    "blank_s3_s4": 45, "mba": 69, "tech_skills": 73, "edu_ba": 68,
}

_LOCKED = {
    "name":    "Stanislav Spektor",
    "contact": "925-639-3898  |  s.spektor93@gmail.com  |  linkedin.com/in/stanislav-spektor",
    "tagline": "Regulatory Compliance  |  Financial Close  |  ERP Systems  |  Process Engineering",
    "s1": {"company": "Workers' Compensation Insurance Rating Bureau", "date": "Jan 2022–Feb 2026",
           "title": "Senior Accountant – Membership & Assessments",
           "desc":  "Designated Statistical Agent of the California Insurance Commissioner"},
    "s2": {"suppress": True, "title": "Member Services Accounting Specialist", "date": "Aug 2019–Jan 2022"},
    "s3": {"suppress": True, "title": "Accounting and Compliance Specialist",  "date": "Oct 2017–Aug 2019"},
    "s4": {"company": "East Bay Nephrology Medical Group", "date": "Jul 2016–Aug 2017",
           "title": "Contracted Accounting Consultant",
           "desc":  "Leading Nephrology Practice in Northern California"},
    "edu": "B.A. Economics,  University of California, Davis,  2016",
}


def _rpr(p_elem):
    for run in p_elem.findall(f"{{{_W}}}r"):
        rpr = run.find(f"{{{_W}}}rPr")
        if rpr is not None:
            return _copy.deepcopy(rpr)
    return None


def _set_text(p_elem, text, rpr):
    ppr = p_elem.find(f"{{{_W}}}pPr")
    for child in list(p_elem):
        if child is not ppr:
            p_elem.remove(child)
    from docx.oxml import OxmlElement
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    p_elem.append(r)


def _set_para(doc, idx, text):
    p = doc.paragraphs[idx]
    _set_text(p._element, text, _rpr(p._element))


def _set_company_header(doc, idx, company, date):
    from docx.oxml import OxmlElement
    p = doc.paragraphs[idx]
    p_elem = p._element
    ppr = p_elem.find(f"{{{_W}}}pPr")
    ppr_rpr = ppr.find(f"{{{_W}}}rPr") if ppr is not None else None
    for child in list(p_elem):
        if child is not ppr:
            p_elem.remove(child)
    r1 = OxmlElement("w:r")
    if ppr_rpr is not None:
        r1.append(_copy.deepcopy(ppr_rpr))
    t1 = OxmlElement("w:t")
    t1.text = company
    t1.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r1.append(t1)
    p_elem.append(r1)
    r2   = OxmlElement("w:r")
    rpr2 = _copy.deepcopy(ppr_rpr) if ppr_rpr is not None else OxmlElement("w:rPr")
    for el in rpr2.findall(f"{{{_W}}}caps"):
        rpr2.remove(el)
    caps_off = OxmlElement("w:caps")
    caps_off.set(f"{{{_W}}}val", "0")
    rpr2.insert(0, caps_off)
    r2.append(rpr2)
    t2 = OxmlElement("w:t")
    t2.text = "\t" + date
    t2.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r2.append(t2)
    p_elem.append(r2)


def _set_title_with_date(doc, idx, title, date):
    from docx.oxml import OxmlElement
    p = doc.paragraphs[idx]
    p_elem = p._element
    ppr = p_elem.find(f"{{{_W}}}pPr")
    ppr_rpr = ppr.find(f"{{{_W}}}rPr") if ppr is not None else None
    for child in list(p_elem):
        if child is not ppr:
            p_elem.remove(child)
    r1 = OxmlElement("w:r")
    if ppr_rpr is not None:
        r1.append(_copy.deepcopy(ppr_rpr))
    t1 = OxmlElement("w:t")
    t1.text = title
    t1.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r1.append(t1)
    p_elem.append(r1)
    r2   = OxmlElement("w:r")
    rpr2 = _copy.deepcopy(ppr_rpr) if ppr_rpr is not None else OxmlElement("w:rPr")
    for el in rpr2.findall(f"{{{_W}}}b") + rpr2.findall(f"{{{_W}}}bCs"):
        rpr2.remove(el)
    b_off = OxmlElement("w:b")
    b_off.set(f"{{{_W}}}val", "0")
    rpr2.insert(0, b_off)
    r2.append(rpr2)
    t2 = OxmlElement("w:t")
    t2.text = "\t" + date
    t2.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r2.append(t2)
    p_elem.append(r2)


def _set_para_sz(para, sz_hp):
    from docx.oxml import OxmlElement
    p_elem = para._element
    ppr = p_elem.find(f"{{{_W}}}pPr")
    if ppr is None:
        ppr = OxmlElement("w:pPr"); p_elem.insert(0, ppr)
    rpr = ppr.find(f"{{{_W}}}rPr")
    if rpr is None:
        rpr = OxmlElement("w:rPr"); ppr.append(rpr)
    for local in ["sz", "szCs"]:
        el = rpr.find(f"{{{_W}}}{local}")
        if el is None:
            el = OxmlElement(f"w:{local}"); rpr.append(el)
        el.set(f"{{{_W}}}val", str(sz_hp))


def _del_para(para):
    para._element.getparent().remove(para._element)


def _update_skills_table(doc, skills_table):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    table = doc.tables[0]
    new_widths = [3260, 3260, 3259]
    tbl_grid = table._element.find(qn("w:tblGrid"))
    if tbl_grid is not None:
        for gc, w in zip(tbl_grid.findall(qn("w:gridCol")), new_widths):
            gc.set(qn("w:w"), str(w))
    for row in table.rows:
        for cell, w in zip(row.cells, new_widths):
            tc = cell._element
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = OxmlElement("w:tcPr"); tc.insert(0, tcPr)
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcW = OxmlElement("w:tcW"); tcPr.append(tcW)
            tcW.set(qn("w:w"), str(w)); tcW.set(qn("w:type"), "dxa")
    for col_idx, skills in enumerate(skills_table):
        cell = table.rows[0].cells[col_idx]
        for para, skill in zip(cell.paragraphs[:4], skills):
            _set_text(para._element, skill, _rpr(para._element))


def _update_tech_skills(para, software_list):
    from docx.oxml import OxmlElement
    p_elem = para._element
    plain_runs = p_elem.findall(f"{{{_W}}}r")[2:]
    plain_rpr = None
    if plain_runs:
        rpr_el = plain_runs[0].find(f"{{{_W}}}rPr")
        if rpr_el is not None:
            plain_rpr = _copy.deepcopy(rpr_el)
    for r in plain_runs:
        p_elem.remove(r)
    r = OxmlElement("w:r")
    if plain_rpr is not None:
        r.append(plain_rpr)
    t = OxmlElement("w:t")
    t.text = software_list
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    p_elem.append(r)


def build_resume_docx_locked(optimized):
    """
    Builds Steve's resume in the locked two-page format using BASE_TEMPLATE.docx.
    Format is frozen. Only the content from `optimized` (Claude's ATS JSON) changes.
    Returns the .docx file as bytes.
    """
    from docx import Document
    import io

    doc = Document(BASE_TEMPLATE_PATH)

    # Capture deletion references before any modifications
    profile_slot_4  = doc.paragraphs[_IDX["profile_3"]]
    suppress_refs   = [
        doc.paragraphs[_IDX["s2_header"]], doc.paragraphs[_IDX["s2_desc"]],
        doc.paragraphs[_IDX["s3_header"]], doc.paragraphs[_IDX["s3_desc"]],
    ]
    slot5_refs      = [doc.paragraphs[i] for i in _IDX["s5_paras"]]
    mba_ref         = doc.paragraphs[_IDX["mba"]]
    blank_s3_s4_ref = doc.paragraphs[_IDX["blank_s3_s4"]]
    tech_skills_ref = doc.paragraphs[_IDX["tech_skills"]]

    # Locked header fields
    _set_para(doc, _IDX["name"],    _LOCKED["name"])
    _set_para(doc, _IDX["contact"], _LOCKED["contact"])
    _set_para(doc, _IDX["tagline"], _LOCKED["tagline"])

    # Profile (3 bullets from Claude)
    for i, text in enumerate(optimized["profile"]):
        _set_para(doc, _IDX[f"profile_{i}"], text)

    # Positions
    slots = ["s1", "s2", "s3", "s4"]
    pos_keys = ["wcirb_senior", "wcirb_member", "wcirb_accounting", "east_bay"]
    for slot, pos_key in zip(slots, pos_keys):
        info    = _LOCKED[slot]
        bullets = optimized["positions"][pos_key]["bullets"]
        if info.get("suppress"):
            _set_title_with_date(doc, _IDX[f"{slot}_title"], info["title"], info["date"])
        else:
            _set_company_header(doc, _IDX[f"{slot}_header"], info["company"], info["date"])
            _set_para(doc, _IDX[f"{slot}_title"], info["title"])
            _set_para(doc, _IDX[f"{slot}_desc"],  info["desc"])
        for i, b in enumerate(bullets):
            _set_para(doc, _IDX[f"{slot}_main_{i}"], b["main"])
            _set_para(doc, _IDX[f"{slot}_sub_{i}"],  b["sub"])

    # Skills table and education
    _update_skills_table(doc, optimized["skills_table"])
    _set_para(doc, _IDX["edu_ba"], _LOCKED["edu"])

    # Separator between Accounting and East Bay: 8pt (locked)
    _set_para_sz(blank_s3_s4_ref, 16)

    # Deletions
    for para in [profile_slot_4] + suppress_refs + slot5_refs + [mba_ref]:
        _del_para(para)

    # Tech skills (index shifted after deletions — use pre-captured ref)
    _update_tech_skills(tech_skills_ref, optimized["tech_skills"])

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# legacy stub kept so nothing else in the file breaks
def build_resume_docx(optimized):
    from docx import Document
    import io

    template_path = os.path.join(os.path.dirname(__file__), "Stanislav_Spektor_Resume.docx")
    doc = Document(template_path)
    paras = doc.paragraphs

    def set_text(para, new_text):
        """Set paragraph text preserving run[0] formatting, clearing the rest."""
        if not para.runs:
            para.add_run(new_text)
            return
        para.runs[0].text = new_text
        for run in para.runs[1:]:
            run.text = ""

    def swap_skill(para, old_skill, new_skill):
        """Find old skill text in any run and replace it in-place."""
        for run in para.runs:
            if old_skill in run.text:
                run.text = run.text.replace(old_skill, new_skill)
                return

    # Original skills — used as search keys to find the right run
    ORIG_SKILLS = [
        "Financial Analysis & Reporting",   "Month-End Close & Reconciliation",  "ERP (Sage Intacct)",
        "Process Improvement & Documentation", "UAT & Implementation Planning",   "Compliance & Regulatory Reporting",
        "Process Automation (Macros)",      "Cross-Functional Collaboration",     "Budgeting & Forecasting",
    ]

    # Profile (paragraphs 4, 5, 6)
    for i, idx in enumerate([4, 5, 6]):
        lines = optimized.get("profile_lines", [])
        if i < len(lines):
            set_text(paras[idx], lines[i])

    # Skills — swap each skill in-place for tab-based rows (9 and 11)
    # For row 10 (space-based), copy tab stops from row 9 and rebuild with tabs
    import copy
    from docx.oxml.ns import qn

    new_skills = (optimized.get("skills", []) + [""] * 9)[:9]

    for orig, new in zip(ORIG_SKILLS[:3], new_skills[:3]):
        swap_skill(paras[9], orig, new)

    # Fix para 10: copy tab stops from para 9, then set tab-separated text
    pPr9  = paras[9]._p.get_or_add_pPr()
    pPr10 = paras[10]._p.get_or_add_pPr()
    tabs9 = pPr9.find(qn('w:tabs'))
    if tabs9 is not None:
        existing = pPr10.find(qn('w:tabs'))
        if existing is not None:
            pPr10.remove(existing)
        pPr10.append(copy.deepcopy(tabs9))
    set_text(paras[10], "\t".join(new_skills[3:6]))

    for orig, new in zip(ORIG_SKILLS[6:9], new_skills[6:9]):
        swap_skill(paras[11], orig, new)

    # WCIRB Analyst bullets (paragraphs 18–21)
    for i, idx in enumerate([18, 19, 20, 21]):
        bullets = optimized.get("wcirb_analyst_bullets", [])
        set_text(paras[idx], bullets[i] if i < len(bullets) else "")

    # WCIRB Specialist bullets (paragraphs 23–25)
    for i, idx in enumerate([23, 24, 25]):
        bullets = optimized.get("wcirb_specialist_bullets", [])
        set_text(paras[idx], bullets[i] if i < len(bullets) else "")

    # WCIRB Compliance (paragraph 27 — single paragraph)
    compliance = optimized.get("wcirb_compliance_bullets", [])
    set_text(paras[27], " ".join(compliance))

    # Nephrology (paragraph 32 — preserve "• \t" prefix in run[0])
    neph = optimized.get("nephrology_bullets", [])
    if neph:
        set_text(paras[32], "• \t" + " ".join(neph))

    # Technical Skills (paragraph 37)
    set_text(paras[37], "Software: " + optimized.get("technical_skills", ""))

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_resume_docx_v2(optimized):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io

    FONT = "Calibri"
    TEAL      = RGBColor(0x31, 0x84, 0x9B)
    BLACK     = RGBColor(0x1A, 0x1A, 0x1A)
    DARK_GREY = RGBColor(0x40, 0x40, 0x40)

    def _pPr(para):
        return para._p.get_or_add_pPr()

    def set_sp(para, before=0, after=0, line=240):
        pPr = _pPr(para)
        e = pPr.find(qn("w:spacing"))
        if e is not None: pPr.remove(e)
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:before"),   str(int(before * 20)))
        sp.set(qn("w:after"),    str(int(after  * 20)))
        sp.set(qn("w:line"),     str(line))
        sp.set(qn("w:lineRule"), "auto")
        pPr.append(sp)

    def border(para, side="bottom", color="31849B", sz=6):
        pPr = _pPr(para)
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is None:
            pBdr = OxmlElement("w:pBdr"); pPr.append(pBdr)
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "2");    el.set(qn("w:color"), color)
        pBdr.append(el)

    def rtab(para, inches=7.4):
        pPr = _pPr(para)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "right")
        t.set(qn("w:pos"), str(int(inches * 1440)))
        tabs.append(t)

    def skill_tabs(para):
        pPr = _pPr(para)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        for pos in [2.43, 4.86]:
            t = OxmlElement("w:tab")
            t.set(qn("w:val"), "left")
            t.set(qn("w:pos"), str(int(pos * 1440)))
            tabs.append(t)

    def bullet_ind(para, left=0.22, hang=0.17):
        pPr = _pPr(para)
        ind = pPr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind"); pPr.append(ind)
        ind.set(qn("w:left"),    str(int(left * 1440)))
        ind.set(qn("w:hanging"), str(int(hang * 1440)))

    def r(para, text, bold=False, italic=False, size=10, color=BLACK):
        rn = para.add_run(text)
        rn.bold = bold; rn.italic = italic
        rn.font.name = FONT; rn.font.size = Pt(size)
        rn.font.color.rgb = color
        return rn

    def sec(text):
        p = doc.add_paragraph()
        set_sp(p, before=7, after=2)
        border(p, "bottom", "31849B", 6)
        r(p, text.upper(), bold=True, size=11, color=TEAL)
        return p

    def blt(text):
        p = doc.add_paragraph()
        set_sp(p, before=0, after=2)
        bullet_ind(p)
        r(p, "\u2022  " + text, size=10, color=BLACK)
        return p

    doc = Document()
    s = doc.sections[0]
    s.top_margin = s.bottom_margin = s.left_margin = s.right_margin = Inches(0.5)
    s.bottom_margin = Inches(0.45)
    doc.styles["Normal"].font.name = FONT
    doc.styles["Normal"].font.size = Pt(10)
    doc.styles["Normal"].paragraph_format.space_before = Pt(0)
    doc.styles["Normal"].paragraph_format.space_after  = Pt(0)

    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_sp(p, before=0, after=3)
    border(p, "bottom", "31849B", 14)
    r(p, "Stanislav Spektor", bold=True, size=22, color=BLACK)

    # Contact
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_sp(p, before=4, after=0)
    r(p, "s.spektor93@gmail.com", size=10, color=DARK_GREY)
    r(p, "  \u2022  ", size=10, color=TEAL)
    r(p, "925-639-3898", size=10, color=DARK_GREY)
    r(p, "  \u2022  ", size=10, color=TEAL)
    r(p, "linkedin.com/in/stanislav-spektor", size=10, color=DARK_GREY)

    # Profile
    sec("Profile")
    for line in optimized.get("profile_lines", []):
        blt(line)

    # Skills
    sec("Skills")
    skills = (optimized.get("skills", []) + [""] * 9)[:9]
    for i in range(3):
        p = doc.add_paragraph()
        set_sp(p, before=1, after=1)
        skill_tabs(p)
        r(p, skills[i*3],   size=10, color=BLACK); r(p, "\t", size=10)
        r(p, skills[i*3+1], size=10, color=BLACK); r(p, "\t", size=10)
        r(p, skills[i*3+2], size=10, color=BLACK)

    # Experience
    sec("Professional Experience")

    p = doc.add_paragraph(); set_sp(p, before=5, after=0)
    r(p, "Workers\u2019 Compensation Insurance Rating Bureau of California", bold=True, size=10.5)
    p = doc.add_paragraph(); set_sp(p, before=0, after=0)
    r(p, "Designated Statistical Agent of the California Insurance Commissioner", italic=True, size=10, color=DARK_GREY)
    p = doc.add_paragraph(); set_sp(p, before=3, after=0)
    r(p, "Senior Accountant \u2013 Membership & Assessments (Promoted Feb 2026)", bold=True, size=10)
    p = doc.add_paragraph(); set_sp(p, before=2, after=1); rtab(p)
    r(p, "Member Services Accounting Analyst", bold=True, size=10)
    r(p, "\t", size=10); r(p, "Jan 2022 \u2013 Feb 2026", italic=True, size=10, color=DARK_GREY)
    for b in optimized.get("wcirb_analyst_bullets", []): blt(b)

    p = doc.add_paragraph(); set_sp(p, before=3, after=1); rtab(p)
    r(p, "Member Services Accounting Specialist", bold=True, size=10)
    r(p, "\t", size=10); r(p, "Aug 2019 \u2013 Jan 2022", italic=True, size=10, color=DARK_GREY)
    for b in optimized.get("wcirb_specialist_bullets", []): blt(b)

    p = doc.add_paragraph(); set_sp(p, before=3, after=1); rtab(p)
    r(p, "Accounting and Compliance Specialist", bold=True, size=10)
    r(p, "\t", size=10); r(p, "Oct 2017 \u2013 Aug 2019", italic=True, size=10, color=DARK_GREY)
    compliance = optimized.get("wcirb_compliance_bullets", [])
    blt(" ".join(compliance))

    p = doc.add_paragraph(); set_sp(p, before=5, after=0)
    r(p, "East Bay Nephrology Medical Group", bold=True, size=10.5)
    p = doc.add_paragraph(); set_sp(p, before=0, after=0)
    r(p, "Leading Nephrology Practice in Northern California", italic=True, size=10, color=DARK_GREY)
    p = doc.add_paragraph(); set_sp(p, before=3, after=1); rtab(p)
    r(p, "Contracted Accounting Consultant", bold=True, size=10)
    r(p, "\t", size=10); r(p, "Jul 2016 \u2013 Aug 2017", italic=True, size=10, color=DARK_GREY)
    neph = optimized.get("nephrology_bullets", [])
    blt(" ".join(neph))

    # Education
    sec("Education")
    p = doc.add_paragraph(); set_sp(p, before=2, after=0)
    r(p, "B.A. Economics", bold=True, size=10)
    r(p, ",  University of California, Davis  \u2022  2016", size=10, color=DARK_GREY)

    # Technical Skills
    sec("Technical Skills")
    p = doc.add_paragraph(); set_sp(p, before=2, after=0)
    r(p, "Software: ", bold=True, size=10)
    r(p, optimized.get("technical_skills", ""), size=10, color=DARK_GREY)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_resume_docx_v8(optimized):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io

    FONT = "Calibri"
    TEAL = RGBColor(0x31, 0x84, 0x9B)
    DARK = RGBColor(0x33, 0x33, 0x33)
    GREY = RGBColor(0x7F, 0x7F, 0x7F)

    def _pPr(p): return p._p.get_or_add_pPr()

    def sp(p, before=0, after=0, line=240):
        pPr = _pPr(p)
        e = pPr.find(qn("w:spacing"))
        if e is not None: pPr.remove(e)
        el = OxmlElement("w:spacing")
        el.set(qn("w:before"),   str(int(before * 20)))
        el.set(qn("w:after"),    str(int(after  * 20)))
        el.set(qn("w:line"),     str(line))
        el.set(qn("w:lineRule"), "auto")
        pPr.append(el)

    def bottom_border(p, color="31849B", sz=4):
        pPr = _pPr(p)
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is None:
            pBdr = OxmlElement("w:pBdr"); pPr.append(pBdr)
        el = OxmlElement("w:bottom")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "2");    el.set(qn("w:color"), color)
        pBdr.append(el)

    def rtab(p, pos=7.4):
        pPr = _pPr(p)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "right"); t.set(qn("w:pos"), str(int(pos * 1440)))
        tabs.append(t)

    def ind(p, left=0.2):
        pPr = _pPr(p)
        el = pPr.find(qn("w:ind"))
        if el is None:
            el = OxmlElement("w:ind"); pPr.append(el)
        el.set(qn("w:left"),    str(int(left * 1440)))
        el.set(qn("w:hanging"), str(int(left * 1440)))
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "left"); t.set(qn("w:pos"), str(int(left * 1440)))
        tabs.append(t)

    def r(p, text, bold=False, italic=False, size=8.5, color=DARK):
        rn = p.add_run(text)
        rn.bold = bold; rn.italic = italic
        rn.font.name = FONT; rn.font.size = Pt(size)
        rn.font.color.rgb = color
        return rn

    def no_border_cell(cell):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ["top","left","bottom","right","insideH","insideV"]:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "none"); el.set(qn("w:sz"), "0")
            el.set(qn("w:space"), "0"); el.set(qn("w:color"), "auto")
            tcBorders.append(el)
        tcPr.append(tcBorders)
        tcMar = OxmlElement("w:tcMar")
        for side, w in [("top","0"),("left","60"),("bottom","0"),("right","0")]:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:w"), w); el.set(qn("w:type"), "dxa")
            tcMar.append(el)
        existing = tcPr.find(qn("w:tcMar"))
        if existing is not None: tcPr.remove(existing)
        tcPr.append(tcMar)
        tcW = OxmlElement("w:tcW")
        tcW.set(qn("w:w"), "3540"); tcW.set(qn("w:type"), "dxa")
        tcPr.append(tcW)

    def no_border_table(tbl):
        tblPr = tbl._tbl.tblPr
        tblBorders = OxmlElement("w:tblBorders")
        for side in ["top","left","bottom","right","insideH","insideV"]:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "none")
            tblBorders.append(el)
        tblPr.append(tblBorders)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(int(7.5 * 1440))); tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)

    def sec(label):
        p = doc.add_paragraph()
        sp(p, before=8, after=4)
        bottom_border(p)
        r(p, label, bold=True, size=12, color=TEAL)

    def blt(text):
        p = doc.add_paragraph()
        sp(p, before=6, after=0)
        ind(p)
        r(p, "\u2022\t" + text, size=8.5, color=DARK)

    def role_line(title, date):
        p = doc.add_paragraph()
        sp(p, before=4, after=0)
        r(p, title + ":  ", bold=True, size=8.5, color=DARK)
        r(p, date, bold=True, italic=True, size=8.5, color=DARK)

    # ── Document setup ──
    doc = Document()
    s = doc.sections[0]
    s.top_margin = s.bottom_margin = s.left_margin = s.right_margin = Inches(0.5)
    s.bottom_margin = Inches(0.45)
    nm = doc.styles["Normal"]
    nm.font.name = FONT; nm.font.size = Pt(8.5)
    nm.paragraph_format.space_before = Pt(0)
    nm.paragraph_format.space_after  = Pt(0)

    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp(p, before=0, after=2)
    r(p, "Stanislav Spektor", bold=True, size=18, color=DARK)

    # Contact
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp(p, before=0, after=2)
    r(p, "s.spektor93@gmail.com  |  925-639-3898  |  linkedin.com/in/stanislav-spektor", size=8.5, color=DARK)

    # Profile
    sec("Profile")
    for line in optimized.get("profile_lines", []):
        blt(line)

    # Skills — borderless 3×3 table
    sec("Skills")
    abbrev = {
        "Process Improvement & Documentation": "Process Improvement & Docs.",
        "Compliance & Regulatory Reporting":   "Compliance & Reg. Reporting",
    }
    skills = (optimized.get("skills", []) + [""] * 9)[:9]
    skills = [abbrev.get(s, s) for s in skills]
    tbl = doc.add_table(rows=3, cols=3)
    no_border_table(tbl)
    for ri in range(3):
        for ci in range(3):
            cell = tbl.rows[ri].cells[ci]
            no_border_cell(cell)
            p = cell.paragraphs[0]
            sp(p, before=2, after=0)
            rn = p.add_run("\u2022  " + skills[ri * 3 + ci])
            rn.font.name = FONT; rn.font.size = Pt(8.5); rn.font.color.rgb = DARK

    # Professional Experience
    sec("Professional Experience")

    # WCIRB — ALL CAPS company
    p = doc.add_paragraph(); sp(p, before=6, after=0)
    r(p, "Workers\u2019 Compensation Insurance Rating Bureau of California", bold=True, size=8.5, color=DARK)
    p = doc.add_paragraph(); sp(p, before=0, after=0)
    r(p, "Designated Statistical Agent of the California Insurance Commissioner", italic=True, size=8.5, color=DARK)

    role_line("Senior Accountant \u2013 Membership & Assessments", "Jan 2022 \u2013 Feb 2026")
    for b in optimized.get("wcirb_analyst_bullets", []): blt(b)

    role_line("Member Services Accounting Specialist", "Aug 2019 \u2013 Jan 2022")
    for b in optimized.get("wcirb_specialist_bullets", []): blt(b)

    role_line("Accounting and Compliance Specialist", "Oct 2017 \u2013 Aug 2019")
    for b in optimized.get("wcirb_compliance_bullets", []): blt(b)

    # Nephrology — ALL CAPS company
    p = doc.add_paragraph(); sp(p, before=6, after=0)
    r(p, "EAST BAY NEPHROLOGY MEDICAL GROUP", bold=True, size=8.5, color=DARK)
    p = doc.add_paragraph(); sp(p, before=0, after=0)
    r(p, "Leading Nephrology Practice in Northern California", italic=True, size=8.5, color=DARK)
    role_line("Contracted Accounting Consultant", "Jul 2016 \u2013 Aug 2017")
    for b in optimized.get("nephrology_bullets", []): blt(b)

    # Education
    sec("Education")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "B.A. Economics", bold=True, size=8.5, color=DARK)
    r(p, ",  University of California, Davis  \u2022  2016", size=8.5, color=DARK)

    # Technical Skills
    sec("Technical Skills")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "Software: ", bold=True, size=8.5, color=DARK)
    tech = optimized.get("technical_skills", "").rstrip(".")
    r(p, tech + ".", size=8.5, color=DARK)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_resume_docx_v3(optimized):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io

    FONT      = "Calibri"
    TEAL      = RGBColor(0x31, 0x84, 0x9B)
    BLACK     = RGBColor(0x1A, 0x1A, 0x1A)
    GREY      = RGBColor(0x55, 0x55, 0x55)

    def _pPr(p):
        return p._p.get_or_add_pPr()

    def sp(p, before=0, after=0, line=240):
        pPr = _pPr(p)
        e = pPr.find(qn("w:spacing"))
        if e is not None: pPr.remove(e)
        el = OxmlElement("w:spacing")
        el.set(qn("w:before"),   str(int(before * 20)))
        el.set(qn("w:after"),    str(int(after  * 20)))
        el.set(qn("w:line"),     str(line))
        el.set(qn("w:lineRule"), "auto")
        pPr.append(el)

    def hborder(p, side, color="31849B", sz=6, space=2):
        pPr = _pPr(p)
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is None:
            pBdr = OxmlElement("w:pBdr"); pPr.append(pBdr)
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), str(space)); el.set(qn("w:color"), color)
        pBdr.append(el)

    def lbar(p, sz=24, space=9):
        """Thick teal left accent bar on section headers."""
        pPr = _pPr(p)
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is None:
            pBdr = OxmlElement("w:pBdr"); pPr.append(pBdr)
        el = OxmlElement("w:left")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), str(space)); el.set(qn("w:color"), "31849B")
        pBdr.append(el)

    def rtab(p, inches=7.3):
        pPr = _pPr(p)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "right"); t.set(qn("w:pos"), str(int(inches * 1440)))
        tabs.append(t)

    def ind(p, left=0.0, hang=0.0):
        pPr = _pPr(p)
        el = pPr.find(qn("w:ind"))
        if el is None:
            el = OxmlElement("w:ind"); pPr.append(el)
        if left:  el.set(qn("w:left"),    str(int(left * 1440)))
        if hang:  el.set(qn("w:hanging"), str(int(hang * 1440)))

    def r(p, text, bold=False, italic=False, size=10, color=BLACK, sc=False):
        rn = p.add_run(text)
        rn.bold = bold; rn.italic = italic
        rn.font.name = FONT; rn.font.size = Pt(size)
        rn.font.color.rgb = color
        if sc: rn.font.small_caps = True
        return rn

    def sec(label):
        p = doc.add_paragraph()
        sp(p, before=8, after=3)
        lbar(p)
        r(p, label, bold=True, size=10.5, color=TEAL, sc=True)
        return p

    def blt(text):
        p = doc.add_paragraph()
        sp(p, before=0, after=1.5)
        ind(p, left=0.18, hang=0.14)
        r(p, "\u2022  " + text, size=9.5, color=BLACK)
        return p

    # ── Document setup ─────────────────────────────────────────────────────────
    doc = Document()
    s = doc.sections[0]
    s.top_margin = s.left_margin = s.right_margin = Inches(0.5)
    s.bottom_margin = Inches(0.45)
    nm = doc.styles["Normal"]
    nm.font.name = FONT; nm.font.size = Pt(10)
    nm.paragraph_format.space_before = Pt(0)
    nm.paragraph_format.space_after  = Pt(0)

    # ── Name ───────────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    sp(p, before=0, after=2)
    hborder(p, "bottom", sz=10, space=3)
    r(p, "Stanislav Spektor", bold=True, size=20, color=BLACK)

    # ── Contact ────────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    sp(p, before=4, after=0)
    r(p, "s.spektor93@gmail.com", size=9, color=GREY)
    r(p, "   \u00b7   ", size=9, color=TEAL)
    r(p, "925-639-3898", size=9, color=GREY)
    r(p, "   \u00b7   ", size=9, color=TEAL)
    r(p, "linkedin.com/in/stanislav-spektor", size=9, color=GREY)

    # ── Profile ────────────────────────────────────────────────────────────────
    sec("Profile")
    profile_text = "  ".join(optimized.get("profile_lines", []))
    p = doc.add_paragraph()
    sp(p, before=1, after=3)
    r(p, profile_text, size=9.5, color=GREY)

    # ── Core Competencies ──────────────────────────────────────────────────────
    sec("Core Competencies")
    skills = [s for s in (optimized.get("skills", []) + [""] * 9)[:9] if s]
    p = doc.add_paragraph()
    sp(p, before=1, after=3)
    for i, skill in enumerate(skills):
        r(p, skill, size=9.5, color=BLACK)
        if i < len(skills) - 1:
            r(p, "   \u00b7   ", size=9.5, color=TEAL)

    # ── Professional Experience ────────────────────────────────────────────────
    sec("Professional Experience")

    # WCIRB
    p = doc.add_paragraph(); sp(p, before=4, after=0)
    r(p, "Workers\u2019 Compensation Insurance Rating Bureau of California", bold=True, size=10.5)
    p = doc.add_paragraph(); sp(p, before=0, after=2)
    r(p, "Designated Statistical Agent of the California Insurance Commissioner", italic=True, size=9, color=GREY)

    p = doc.add_paragraph(); sp(p, before=3, after=0)
    r(p, "Senior Accountant \u2013 Membership & Assessments  ", bold=True, size=10, color=BLACK)
    r(p, "(Promoted Feb 2026)", italic=True, size=9, color=GREY)

    p = doc.add_paragraph(); sp(p, before=2, after=1); rtab(p)
    r(p, "Member Services Accounting Analyst", bold=True, size=10, color=BLACK)
    r(p, "\t"); r(p, "Jan 2022 \u2013 Feb 2026", italic=True, size=9, color=GREY)
    for b in optimized.get("wcirb_analyst_bullets", []): blt(b)

    p = doc.add_paragraph(); sp(p, before=3, after=1); rtab(p)
    r(p, "Member Services Accounting Specialist", bold=True, size=10, color=BLACK)
    r(p, "\t"); r(p, "Aug 2019 \u2013 Jan 2022", italic=True, size=9, color=GREY)
    for b in optimized.get("wcirb_specialist_bullets", []): blt(b)

    p = doc.add_paragraph(); sp(p, before=3, after=1); rtab(p)
    r(p, "Accounting and Compliance Specialist", bold=True, size=10, color=BLACK)
    r(p, "\t"); r(p, "Oct 2017 \u2013 Aug 2019", italic=True, size=9, color=GREY)
    compliance = optimized.get("wcirb_compliance_bullets", [])
    blt(" ".join(compliance))

    # Nephrology
    p = doc.add_paragraph(); sp(p, before=5, after=0)
    r(p, "East Bay Nephrology Medical Group", bold=True, size=10.5)
    p = doc.add_paragraph(); sp(p, before=0, after=2)
    r(p, "Leading Nephrology Practice in Northern California", italic=True, size=9, color=GREY)

    p = doc.add_paragraph(); sp(p, before=3, after=1); rtab(p)
    r(p, "Contracted Accounting Consultant", bold=True, size=10, color=BLACK)
    r(p, "\t"); r(p, "Jul 2016 \u2013 Aug 2017", italic=True, size=9, color=GREY)
    blt(" ".join(optimized.get("nephrology_bullets", [])))

    # ── Education ──────────────────────────────────────────────────────────────
    sec("Education")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "B.A. Economics", bold=True, size=9.5)
    r(p, ",  University of California, Davis  \u00b7  2016", size=9.5, color=GREY)

    # ── Technical Skills ───────────────────────────────────────────────────────
    sec("Technical Skills")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "Software: ", bold=True, size=9.5)
    r(p, optimized.get("technical_skills", ""), size=9.5, color=GREY)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_resume_docx_v4(optimized):
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io

    FONT  = "Calibri"
    BLACK = RGBColor(0x1A, 0x1A, 0x1A)
    GREY  = RGBColor(0x55, 0x55, 0x55)

    def _pPr(p):
        return p._p.get_or_add_pPr()

    def sp(p, before=0, after=0, line=240):
        pPr = _pPr(p)
        e = pPr.find(qn("w:spacing"))
        if e is not None: pPr.remove(e)
        el = OxmlElement("w:spacing")
        el.set(qn("w:before"),   str(int(before * 20)))
        el.set(qn("w:after"),    str(int(after  * 20)))
        el.set(qn("w:line"),     str(line))
        el.set(qn("w:lineRule"), "auto")
        pPr.append(el)

    def dotted_rule(p):
        pPr = _pPr(p)
        pBdr = pPr.find(qn("w:pBdr"))
        if pBdr is None:
            pBdr = OxmlElement("w:pBdr"); pPr.append(pBdr)
        el = OxmlElement("w:bottom")
        el.set(qn("w:val"),   "dotted")
        el.set(qn("w:sz"),    "6")
        el.set(qn("w:space"), "1")
        el.set(qn("w:color"), "888888")
        pBdr.append(el)

    def rtab(p, pos=7.1):
        pPr = _pPr(p)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "right")
        t.set(qn("w:pos"), str(int(pos * 1440)))
        tabs.append(t)

    def skill_tab(p, pos=3.55):
        pPr = _pPr(p)
        tabs = pPr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs"); pPr.append(tabs)
        t = OxmlElement("w:tab")
        t.set(qn("w:val"), "left")
        t.set(qn("w:pos"), str(int(pos * 1440)))
        tabs.append(t)

    def ind(p, left=0.0, hang=0.0):
        pPr = _pPr(p)
        el = pPr.find(qn("w:ind"))
        if el is None:
            el = OxmlElement("w:ind"); pPr.append(el)
        if left: el.set(qn("w:left"),    str(int(left * 1440)))
        if hang: el.set(qn("w:hanging"), str(int(hang * 1440)))

    def r(p, text, bold=False, italic=False, size=10, color=BLACK):
        rn = p.add_run(text)
        rn.bold = bold; rn.italic = italic
        rn.font.name = FONT; rn.font.size = Pt(size)
        rn.font.color.rgb = color
        return rn

    def sec(label):
        p = doc.add_paragraph()
        sp(p, before=9, after=2)
        r(p, label.upper(), bold=True, size=10, color=BLACK)
        return p

    def blt(text):
        p = doc.add_paragraph()
        sp(p, before=0, after=1.5)
        ind(p, left=0.22, hang=0.17)
        r(p, "\u2022  " + text, size=10, color=BLACK)
        return p

    # ── Document setup ─────────────────────────────────────────────────────────
    doc = Document()
    s = doc.sections[0]
    s.top_margin    = Inches(0.65)
    s.bottom_margin = Inches(0.5)
    s.left_margin   = Inches(0.65)
    s.right_margin  = Inches(0.65)
    nm = doc.styles["Normal"]
    nm.font.name = FONT; nm.font.size = Pt(10)
    nm.paragraph_format.space_before = Pt(0)
    nm.paragraph_format.space_after  = Pt(0)

    # ── Name ───────────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp(p, before=0, after=3)
    r(p, "Stanislav Spektor", bold=True, size=20, color=BLACK)

    # ── Contact ────────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp(p, before=0, after=5)
    r(p, "cell: 925-639-3898", size=9.5, color=BLACK)
    r(p, "  \u2022  email: ", size=9.5, color=BLACK)
    r(p, "s.spektor93@gmail.com", size=9.5, color=BLACK)
    r(p, "  \u2022  ", size=9.5, color=BLACK)
    r(p, "linkedin.com/in/stanislav-spektor", size=9.5, color=BLACK)

    # ── Dotted rule ────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    sp(p, before=0, after=2)
    dotted_rule(p)

    # ── Professional Summary ───────────────────────────────────────────────────
    sec("Professional Summary")
    p = doc.add_paragraph()
    sp(p, before=2, after=0)
    r(p, "  ".join(optimized.get("profile_lines", [])), size=10, color=BLACK)

    # ── Skills ─────────────────────────────────────────────────────────────────
    sec("Skills")
    skills = [sk for sk in (optimized.get("skills", []) + [""] * 9)[:9] if sk]
    col2_start = (len(skills) + 1) // 2
    for row in range(col2_start):
        left_s  = skills[row] if row < len(skills) else ""
        right_s = skills[row + col2_start] if row + col2_start < len(skills) else ""
        p = doc.add_paragraph()
        sp(p, before=0, after=1.5)
        skill_tab(p)
        ind(p, left=0.22, hang=0.17)
        r(p, "\u2022  " + left_s, size=10, color=BLACK)
        if right_s:
            r(p, "\t\u2022  " + right_s, size=10, color=BLACK)

    # ── Professional Experience ────────────────────────────────────────────────
    sec("Professional Experience")

    # WCIRB – promoted title (no bullets, just the current title + company + date)
    p = doc.add_paragraph(); sp(p, before=4, after=0); rtab(p)
    r(p, "Senior Accountant \u2013 Membership & Assessments, WCIRB of California", bold=True, size=10)
    r(p, "\t"); r(p, "Feb 2026 \u2013 Present", size=10, color=GREY)

    # Analyst role
    p = doc.add_paragraph(); sp(p, before=3, after=0); rtab(p)
    r(p, "Member Services Accounting Analyst, WCIRB of California", size=10, color=BLACK)
    r(p, "\t"); r(p, "Jan 2022 \u2013 Feb 2026", size=10, color=GREY)
    for b in optimized.get("wcirb_analyst_bullets", []): blt(b)

    # Specialist role
    p = doc.add_paragraph(); sp(p, before=3, after=0); rtab(p)
    r(p, "Member Services Accounting Specialist, WCIRB of California", size=10, color=BLACK)
    r(p, "\t"); r(p, "Aug 2019 \u2013 Jan 2022", size=10, color=GREY)
    for b in optimized.get("wcirb_specialist_bullets", []): blt(b)

    # Compliance role
    p = doc.add_paragraph(); sp(p, before=3, after=0); rtab(p)
    r(p, "Accounting and Compliance Specialist, WCIRB of California", size=10, color=BLACK)
    r(p, "\t"); r(p, "Oct 2017 \u2013 Aug 2019", size=10, color=GREY)
    blt(" ".join(optimized.get("wcirb_compliance_bullets", [])))

    # Nephrology
    p = doc.add_paragraph(); sp(p, before=3, after=0); rtab(p)
    r(p, "Contracted Accounting Consultant, East Bay Nephrology Medical Group", size=10, color=BLACK)
    r(p, "\t"); r(p, "Jul 2016 \u2013 Aug 2017", size=10, color=GREY)
    blt(" ".join(optimized.get("nephrology_bullets", [])))

    # ── Education ──────────────────────────────────────────────────────────────
    sec("Education")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "B.A. Economics, University of California, Davis, 2016", size=10, color=BLACK)

    # ── Technical Skills ───────────────────────────────────────────────────────
    sec("Technical Skills")
    p = doc.add_paragraph(); sp(p, before=2, after=0)
    r(p, "Software: ", bold=True, size=10)
    r(p, optimized.get("technical_skills", ""), size=10, color=BLACK)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def get_saved_jobs_with_descriptions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, company, job_description FROM applications WHERE job_description != '' ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def save_application(title, company, location, url, salary, description):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM applications WHERE title=? AND company=?", (title, company))
    if c.fetchone():
        conn.close()
        return False
    c.execute(
        "INSERT INTO applications (title, company, location, url, salary, saved_date, job_description) VALUES (?,?,?,?,?,?,?)",
        (title, company, location, url, salary, str(date.today()), description),
    )
    conn.commit()
    conn.close()
    return True


def get_applications():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, company, location, salary, status, notes, saved_date FROM applications ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def update_application(app_id, status, notes):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE applications SET status=?, notes=? WHERE id=?", (status, notes, app_id))
    conn.commit()
    conn.close()


def delete_application(app_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM applications WHERE id=?", (app_id,))
    conn.commit()
    conn.close()


# ── App ────────────────────────────────────────────────────────────────────────

init_db()
resume_text = load_resume()

# ── Header ─────────────────────────────────────────────────────────────────────
_img_path = os.path.join(os.path.dirname(__file__), "steve_photo.jpeg")
if os.path.exists(_img_path):
    with open(_img_path, "rb") as _f:
        _b64 = base64.b64encode(_f.read()).decode()
    st.markdown(
        f'<img src="data:image/jpeg;base64,{_b64}" '
        'style="width:160px;border-radius:12px;'
        'box-shadow:0 3px 10px rgba(0,0,0,0.18);'
        'display:block;margin-bottom:10px;">',
        unsafe_allow_html=True,
    )
st.title("💼 Steve's Job Finder")
st.caption("AI-powered job search for Stanislav Spektor · Senior Accountant")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔍 Search Jobs", "📋 My Applications", "💡 Resume Tips", "📄 ATS Resume", "📊 Keyword Insights"])


# ── Tab 1: Search ──────────────────────────────────────────────────────────────
with tab1:
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        job_title = st.text_input("Job Title", value="Senior Accountant")
    with c2:
        location = st.text_input("Location", value="California")
    with c3:
        st.write("")
        st.write("")
        search_btn = st.button("Search", type="primary", use_container_width=True)

    sal_col, _ = st.columns([2, 3])
    with sal_col:
        sal_filter = st.checkbox("Filter: $120,000+ salary only", value=True,
                                 help="Only shows jobs with a listed salary at or above $120k. Uncheck to see all results including unlisted salaries.")

    if search_btn:
        with st.spinner("Searching..."):
            st.session_state.results = search_jobs(job_title, location, min_salary=120000 if sal_filter else None)

        if sal_filter:
            st.caption("ℹ️ Showing only jobs with a listed salary of $120k+. Uncheck the filter to see all results.")

    results = st.session_state.get("results", [])

    if results:
        st.write(f"**{len(results)} jobs found**")

        for i, job in enumerate(results):
            title         = job.get("title", "N/A")
            company       = job.get("company", {}).get("display_name", "N/A")
            loc           = job.get("location", {}).get("display_name", "N/A")
            desc          = job.get("description", "")
            url           = job.get("redirect_url", "#")
            s_min         = job.get("salary_min")
            s_max         = job.get("salary_max")
            contract_time = job.get("contract_time", "")
            contract_type = job.get("contract_type", "")
            salary        = f"${s_min:,.0f} – ${s_max:,.0f}" if s_min and s_max else "Salary not listed"

            desc_lower = desc.lower()
            is_remote  = any(w in desc_lower for w in ["remote", "work from home", "work-from-home", "telecommute"])
            remote_tag = "🌐 Remote" if is_remote or "remote" in loc.lower() else ""

            contract_tag = ""
            if contract_time == "part_time":   contract_tag = "⏱ Part-time"
            elif contract_time == "full_time":  contract_tag = "🕐 Full-time"
            if contract_type == "contract":     contract_tag += "  📄 Contract"
            elif contract_type == "permanent":  contract_tag += "  ✅ Permanent"

            source     = job.get("_source", "")
            source_tag = {"Adzuna": "🔵 Adzuna", "The Muse": "🟣 The Muse", "RemoteOK": "🟢 RemoteOK"}.get(source, "")
            tags   = "  |  ".join(t for t in [remote_tag, contract_tag.strip(), source_tag] if t)
            header = f"**{title}** — {company} | {loc} | {salary}"

            with st.expander(header):
                if tags:
                    st.markdown(f"**{tags}**")
                st.write(desc)
                st.markdown(f"[View full posting ↗]({url})")

                pasted = st.text_area(
                    "📋 Paste full job description here for better analysis (optional)",
                    value="",
                    height=100,
                    placeholder="Copy the complete job description from the posting and paste it here...",
                    key=f"fd{i}",
                )
                effective_desc = pasted.strip() if pasted.strip() else desc

                btn1, btn2, btn3 = st.columns(3)

                with btn1:
                    if st.button("🤖 Analyze Match", key=f"a{i}"):
                        with st.spinner("Analyzing with AI..."):
                            try:
                                st.session_state[f"analysis_{i}"] = analyze_job(title, company, effective_desc, resume_text)
                            except Exception as e:
                                st.error(f"Analysis error: {e}")

                with btn2:
                    if st.button("✉️ Cover Letter", key=f"c{i}"):
                        st.session_state[f"gen_cover_{i}"] = True

                with btn3:
                    if st.button("💾 Save Job", key=f"s{i}"):
                        if save_application(title, company, loc, url, salary, effective_desc):
                            st.success("Saved to applications!")
                        else:
                            st.info("Already saved.")

                # Analysis results
                if f"analysis_{i}" in st.session_state:
                    a = st.session_state[f"analysis_{i}"]
                    score = a.get("score", 0)
                    css = "score-high" if score >= 70 else "score-mid" if score >= 50 else "score-low"
                    st.markdown(f'<p class="{css}">{score}/100 — {a.get("verdict", "")}</p>', unsafe_allow_html=True)

                    col_s, col_g = st.columns(2)
                    with col_s:
                        st.markdown("**Strengths**")
                        for s in a.get("strengths", []):
                            st.markdown(f"✅ {s}")
                    with col_g:
                        st.markdown("**Gaps**")
                        gaps = a.get("gaps", [])
                        if gaps:
                            for g in gaps:
                                st.markdown(f"⚠️ {g}")
                        else:
                            st.markdown("None identified")
                    st.info(f"💡 **Tip:** {a.get('tip', '')}")

                # Cover letter generation
                if st.session_state.get(f"gen_cover_{i}"):
                    st.markdown("---")
                    st.markdown("**Cover Letter:**")
                    placeholder = st.empty()
                    full_text = ""
                    for chunk in stream_cover_letter(title, company, effective_desc, resume_text):
                        full_text += chunk
                        placeholder.markdown(full_text + "▌")
                    placeholder.markdown(full_text)
                    st.session_state[f"cover_text_{i}"] = full_text
                    del st.session_state[f"gen_cover_{i}"]

                if f"cover_text_{i}" in st.session_state:
                    st.download_button(
                        "⬇️ Download Cover Letter",
                        st.session_state[f"cover_text_{i}"],
                        file_name=f"cover_letter_{company.replace(' ', '_')}.txt",
                        key=f"dl{i}",
                    )


# ── Tab 2: Applications ────────────────────────────────────────────────────────
with tab2:
    st.subheader("Saved Applications")
    apps = get_applications()

    if not apps:
        st.info("No saved applications yet. Search for jobs and save the ones that look good!")
    else:
        statuses = ["Saved", "Applied", "Phone Screen", "Interview", "Offer", "Rejected"]

        # Summary stats
        status_counts = {}
        for app in apps:
            s = app[5]
            status_counts[s] = status_counts.get(s, 0) + 1

        cols = st.columns(len(status_counts))
        for col, (s, count) in zip(cols, status_counts.items()):
            col.metric(s, count)

        st.divider()

        for app in apps:
            app_id, title, company, loc, salary, status, notes, saved_date = app
            badge = {"Offer": "🟢", "Interview": "🔵", "Phone Screen": "🟡",
                     "Applied": "🟠", "Saved": "⚪", "Rejected": "🔴"}.get(status, "⚪")

            with st.expander(f"{badge} **{title}** — {company}"):
                st.write(f"📍 {loc}  |  💰 {salary}  |  📅 Saved {saved_date}")

                new_status = st.selectbox(
                    "Status", statuses,
                    index=statuses.index(status) if status in statuses else 0,
                    key=f"st_{app_id}"
                )
                new_notes = st.text_area("Notes", value=notes or "", key=f"nt_{app_id}", height=80)

                col_u, col_d = st.columns([1, 1])
                with col_u:
                    if st.button("Update", key=f"up_{app_id}", type="primary"):
                        update_application(app_id, new_status, new_notes)
                        st.success("Updated!")
                        st.rerun()
                with col_d:
                    if st.button("Delete", key=f"de_{app_id}"):
                        delete_application(app_id)
                        st.rerun()


# ── Tab 3: Resume Tips ─────────────────────────────────────────────────────────
with tab3:
    st.subheader("AI Resume Coach")
    target = st.text_input("Target role", value="Senior Accountant / Accounting Manager")

    if st.button("Analyze My Resume", type="primary"):
        st.markdown("---")
        st.write_stream(get_resume_tips(target, resume_text))


# ── Tab 4: ATS Resume Optimizer ───────────────────────────────────────────────
with tab4:
    st.subheader("ATS Resume Optimizer")
    st.write("Tailors Steve's resume to pass Applicant Tracking Systems.")

    source = st.radio("Job source", ["Paste job description", "From saved jobs"], horizontal=True)

    opt_title, opt_desc = "", ""

    if source == "Paste job description":
        opt_title = st.text_input("Job title", placeholder="e.g. Accounting Manager")
        opt_desc  = st.text_area("Paste the full job description here", height=220)
    else:
        saved_jobs = get_saved_jobs_with_descriptions()
        if not saved_jobs:
            st.info("No saved jobs with descriptions yet. Search and save jobs first.")
        else:
            options = {f"{j[1]} at {j[2]}": (j[1], j[3]) for j in saved_jobs}
            choice  = st.selectbox("Select a saved job", list(options.keys()))
            opt_title, opt_desc = options[choice]
            st.text_area("Job description preview", value=opt_desc[:800] + "...", height=150, disabled=True)

    if st.button("🎯 Optimize Resume for ATS", type="primary", disabled=not opt_desc):
        with st.spinner("AI is optimizing the resume — this takes ~20 seconds..."):
            try:
                optimized  = optimize_resume_for_job(opt_title, opt_desc)
                docx_bytes = build_resume_docx_locked(optimized)
                fname      = (
                    f"Stanislav_Spektor_{opt_title.replace(' ', '_')}_Resume.docx"
                    if opt_title else "Stanislav_Spektor_Resume_Optimized.docx"
                )
                st.session_state["ats_keywords"]   = optimized.get("keywords_added", [])
                st.session_state["ats_docx_bytes"] = docx_bytes
                st.session_state["ats_fname"]      = fname
                try:
                    _kw_conn = sqlite3.connect(DB_PATH)
                    _kw_c = _kw_conn.cursor()
                    _kw_c.execute(
                        "INSERT INTO ats_keyword_log (job_title, keywords, template, logged_date) VALUES (?, ?, ?, ?)",
                        (opt_title, ", ".join(optimized.get("keywords_added", [])), "v3_locked", date.today().strftime("%Y-%m-%d"))
                    )
                    _kw_conn.commit()
                    _kw_conn.close()
                except Exception as _kw_err:
                    st.warning(f"Keyword log failed: {_kw_err}")
            except Exception as e:
                st.error(f"Something went wrong: {e}")

    if st.session_state.get("ats_keywords"):
        st.success(f"✅ {len(st.session_state['ats_keywords'])} ATS keywords woven in: {', '.join(st.session_state['ats_keywords'])}")

    if st.session_state.get("ats_docx_bytes"):
        st.download_button(
            "⬇️ Download Optimized Resume (.docx)",
            st.session_state["ats_docx_bytes"],
            file_name=st.session_state.get("ats_fname", "resume.docx"),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


# ── Tab 5: Keyword Insights ────────────────────────────────────────────────────
with tab5:
    st.subheader("Keyword Insights")
    st.write("Every keyword the ATS optimizer has injected — ranked by how often employers ask for it.")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT job_title, keywords, logged_date FROM ats_keyword_log ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not rows:
        st.info("No keyword data yet. Run the ATS optimizer on a job and the keywords will appear here.")
    else:
        from collections import Counter

        freq: Counter = Counter()
        kw_roles: dict = {}

        for job_title, keywords_str, logged_date in rows:
            if not keywords_str:
                continue
            for kw in [k.strip() for k in keywords_str.split(",") if k.strip()]:
                freq[kw] += 1
                kw_roles.setdefault(kw, set()).add(job_title or "Unknown")

        st.markdown("### Most Requested Keywords")
        table_data = [
            {
                "Keyword": kw,
                "Times Requested": count,
                "Roles": ", ".join(sorted(kw_roles[kw])),
            }
            for kw, count in freq.most_common()
        ]
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Optimization History")
        for job_title, keywords_str, logged_date in rows:
            with st.expander(f"**{job_title or 'Untitled'}** — {logged_date}"):
                if keywords_str:
                    for kw in [k.strip() for k in keywords_str.split(",") if k.strip()]:
                        st.markdown(f"- {kw}")
                else:
                    st.write("No keywords recorded.")
