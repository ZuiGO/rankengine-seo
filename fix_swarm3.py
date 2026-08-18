import re

with open("backend/tests/test_agent_swarm.py", "r") as f:
    c = f.read()

c = c.replace('"generate_suggestions"', '"run_single_page_analysis"')
c = c.replace('"competitor_gap_analysis"', '"run_competitor_audit"')
c = c.replace('"extract_seo_insights"', '"fetch_seo_insights"')
c = c.replace('"generate_report"', '"generate_pdf_report"')
c = c.replace('"schedule_audit"', '"create_schedule"')
c = c.replace('"run_technical_audit"', '"audit_technical"')

with open("backend/tests/test_agent_swarm.py", "w") as f:
    f.write(c)
