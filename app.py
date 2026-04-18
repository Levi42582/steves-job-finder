import streamlit as st
import anthropic
import requests
import sqlite3
import json
import os
from datetime import date

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
DB_PATH = os.path.join(os.path.dirname(__file__), "applications.db")

RESUME_TEXT = """Stanislav Spektor
s.spektor93@gmail.com | 925-639-3898 | linkedin.com/in/stanislav-spektor

Profile
8+ years in financial analysis, reporting, compliance, forecasting and process improvement.
Collaborates cross-functionally to meet deadlines and deliver actionable, accurate financial reports.
Designs and tests financial systems, streamlines workflows, and handles high-volume reconciliations.

Skills
Financial Analysis & Reporting | Month-End Close & Reconciliation | ERP (Sage Intacct)
Process Improvement & Documentation | UAT & Implementation Planning | Compliance & Regulatory Reporting
Process Automation (Macros) | Cross-Functional Collaboration | Budgeting & Forecasting

Professional Experience

Workers' Compensation Insurance Rating Bureau of California
Senior Accountant – Membership & Assessments (Promoted Feb 2026)
Member Services Accounting Analyst: Jan 2022 – Feb 2026
- Provided comprehensive financial and accounting support for a large portfolio of 400+ member insurers.
- Co-led design, testing, and deployment of a cloud-based billing and assessment platform; executed 250+ test cases, delivered a zero-defect rollout.
- Lead financial reconciliation processes (AR, benefits, high-volume member accounts), completing reconciliations within 3 days post-close and reducing backlog 90%.
- Improved revenue cycle performance by reducing aging balances 50% through targeted interventions.

Member Services Accounting Specialist: Aug 2019 – Jan 2022
- Supported monthly, quarterly, and annual close activities, performing variance analysis.
- Completed AR reconciliations within 5 days post-close.
- Led UAT efforts for assessment calculation platform, achieved full team adoption within first month.

Accounting and Compliance Specialist: Oct 2017 – Aug 2019
- Managed internal control documentation, maintaining 25+ procedure documents.
- Reduced recurring discrepancies 30% through financial audits and targeted reviews.

East Bay Nephrology Medical Group
Contracted Accounting Consultant: Jul 2016 – Aug 2017
- Led daily AP/AR accounting operations, processing 300+ monthly transactions with 98% accuracy.
- Supported system migration and trained 10+ team members with zero disruption post-launch.

Education
B.A. Economics, University of California, Davis | 2016

Technical Skills
Advanced Excel (PivotTables, XLOOKUP, Power Query), Limelight, Power BI, ADP, BRiWeb, SharePoint, Sage Intacct
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
    conn.commit()
    conn.close()


def load_resume():
    return RESUME_TEXT


def search_jobs(title, location, page=1):
    url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": title,
        "where": location,
        "results_per_page": 15,
        "sort_by": "relevance",
        "content-type": "application/json",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        st.error(f"Job search failed: {e}")
        return []


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
    return json.loads(msg.content[0].text)


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
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{
            "role": "user",
            "content": f"""You are an ATS resume optimizer. Optimize Stanislav Spektor's resume for this specific job.

ORIGINAL RESUME:
{RESUME_TEXT}

TARGET JOB: {job_title}
JOB DESCRIPTION: {job_description[:3000]}

Rules:
- Keep all facts, companies, dates, and numbers EXACTLY accurate — never fabricate
- Naturally incorporate relevant ATS keywords from the job description
- Rewrite bullet points to emphasize the most relevant experience
- Keep the same number of bullet points per role
- CRITICAL: The resume must fit on ONE page — keep every bullet under 200 characters
- Profile lines must be single sentences under 120 characters each
- Skills must be 1-4 words each (short labels only, e.g. "Cost Accounting", "ERP Systems")
- Return ONLY valid JSON, no other text

Return this exact JSON structure:
{{
  "profile_lines": ["line1", "line2", "line3"],
  "skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6", "skill7", "skill8", "skill9"],
  "wcirb_analyst_bullets": ["bullet1", "bullet2", "bullet3", "bullet4"],
  "wcirb_specialist_bullets": ["bullet1", "bullet2", "bullet3"],
  "wcirb_compliance_bullets": ["bullet1", "bullet2"],
  "nephrology_bullets": ["bullet1", "bullet2"],
  "technical_skills": "comma-separated technical skills string",
  "keywords_added": ["kw1", "kw2", "kw3", "kw4", "kw5"]
}}"""
        }]
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


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

    # Skills — swap each skill in-place to preserve run/tab structure
    new_skills = (optimized.get("skills", []) + [""] * 9)[:9]
    for orig, new in zip(ORIG_SKILLS[:3], new_skills[:3]):
        swap_skill(paras[9], orig, new)
    for orig, new in zip(ORIG_SKILLS[3:6], new_skills[3:6]):
        swap_skill(paras[10], orig, new)
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

st.title("💼 Steve's Job Finder")
st.caption("AI-powered job search for Stanislav Spektor · Senior Accountant")

tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search Jobs", "📋 My Applications", "💡 Resume Tips", "📄 ATS Resume"])


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

    if search_btn:
        with st.spinner("Searching..."):
            st.session_state.results = search_jobs(job_title, location)

    results = st.session_state.get("results", [])

    if results:
        st.write(f"**{len(results)} jobs found**")

        for i, job in enumerate(results):
            title    = job.get("title", "N/A")
            company  = job.get("company", {}).get("display_name", "N/A")
            loc      = job.get("location", {}).get("display_name", "N/A")
            desc     = job.get("description", "")
            url      = job.get("redirect_url", "#")
            s_min    = job.get("salary_min")
            s_max    = job.get("salary_max")
            salary   = f"${s_min:,.0f} – ${s_max:,.0f}" if s_min and s_max else "Salary not listed"

            with st.expander(f"**{title}** — {company} | {loc} | {salary}"):
                st.write(desc[:600] + ("..." if len(desc) > 600 else ""))
                st.markdown(f"[View full posting ↗]({url})")

                btn1, btn2, btn3 = st.columns(3)

                with btn1:
                    if st.button("🤖 Analyze Match", key=f"a{i}"):
                        with st.spinner("Analyzing with AI..."):
                            try:
                                st.session_state[f"analysis_{i}"] = analyze_job(title, company, desc, resume_text)
                            except Exception as e:
                                st.error(f"Analysis error: {e}")

                with btn2:
                    if st.button("✉️ Cover Letter", key=f"c{i}"):
                        st.session_state[f"gen_cover_{i}"] = True

                with btn3:
                    if st.button("💾 Save Job", key=f"s{i}"):
                        if save_application(title, company, loc, url, salary, desc):
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
                    for chunk in stream_cover_letter(title, company, desc, resume_text):
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
    st.write("Tailors Steve's resume to pass Applicant Tracking Systems — downloads as a formatted PDF.")

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
                optimized = optimize_resume_for_job(opt_title, opt_desc)
                keywords  = optimized.get("keywords_added", [])
                if keywords:
                    st.success(f"✅ {len(keywords)} ATS keywords woven in: {', '.join(keywords)}")
                docx_bytes = build_resume_docx(optimized)
                fname = f"Stanislav_Spektor_{opt_title.replace(' ', '_')}_Resume.docx" if opt_title else "Stanislav_Spektor_Resume_Optimized.docx"
                st.download_button(
                    "⬇️ Download Optimized Resume (.docx)",
                    docx_bytes,
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            except Exception as e:
                st.error(f"Something went wrong: {e}")
