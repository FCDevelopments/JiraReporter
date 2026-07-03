"""
generate_report_pdf.py
Generates the IT Jira Dashboard project summary PDF.
Run: python generate_report_pdf.py
Output: IT_Dashboard_Report.pdf
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "IT_Dashboard_Report.pdf")

# ── Palette ──────────────────────────────────────────────────────────────────
NAVY   = colors.HexColor("#1e3a5f")
BLUE   = colors.HexColor("#2563eb")
LIGHT  = colors.HexColor("#eff6ff")
BORDER = colors.HexColor("#bfdbfe")
GREEN  = colors.HexColor("#16a34a")
AMBER  = colors.HexColor("#d97706")
DGREY  = colors.HexColor("#374151")
MGREY  = colors.HexColor("#6b7280")
LGREY  = colors.HexColor("#f3f4f6")
WHITE  = colors.white

# ── Paragraph styles ─────────────────────────────────────────────────────────
def ps(name, **kw):
    return ParagraphStyle(name, **kw)

cover_title = ps("CT", fontName="Helvetica-Bold",   fontSize=26, textColor=WHITE,          leading=32, spaceAfter=6)
cover_sub   = ps("CS", fontName="Helvetica",         fontSize=13, textColor=colors.HexColor("#bfdbfe"), leading=18, spaceAfter=4)
cover_date  = ps("CD", fontName="Helvetica",         fontSize=10, textColor=colors.HexColor("#93c5fd"), leading=14)
h1          = ps("H1", fontName="Helvetica-Bold",   fontSize=14, textColor=NAVY,           leading=18, spaceBefore=14, spaceAfter=4)
h2          = ps("H2", fontName="Helvetica-Bold",   fontSize=11, textColor=BLUE,           leading=15, spaceBefore=10, spaceAfter=4)
body        = ps("BD", fontName="Helvetica",         fontSize=10, textColor=DGREY,          leading=15, spaceAfter=4)
bul         = ps("BL", fontName="Helvetica",         fontSize=10, textColor=DGREY,          leading=15, leftIndent=16, spaceAfter=3)
note        = ps("NT", fontName="Helvetica-Oblique", fontSize=9,  textColor=MGREY,          leading=13, spaceAfter=2)
callout     = ps("CL", fontName="Helvetica-Bold",   fontSize=10, textColor=NAVY,           leading=14, leftIndent=6)
footer_s    = ps("FT", fontName="Helvetica",         fontSize=8,  textColor=MGREY,          leading=11, alignment=TA_RIGHT)

def B(text): return f"<b>{text}</b>"
def I(text): return f"<i>{text}</i>"
def C(text, hex_color): return f'<font color="{hex_color}">{text}</font>'

def p(text, style=None):   return Paragraph(text, style or body)
def sp(n=6):               return Spacer(1, n)
def hr():                  return HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceAfter=8, spaceBefore=4)
def bullet(text):          return p(f"&bull;&nbsp;&nbsp;{text}", bul)

# ── Helpers ───────────────────────────────────────────────────────────────────
def section_hdr(text):
    """Blue left-bar section block."""
    t = Table([[p(text, h1)]], colWidths=[6.5*inch])
    t.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("BACKGROUND",   (0,0), (-1,-1), LIGHT),
        ("LINEBEFORE",   (0,0), (0,-1),  4, BLUE),
    ]))
    return t

def styled_table(rows, col_widths, header=True):
    t = Table(rows, colWidths=col_widths)
    styles = [
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1,-1), [WHITE, LGREY]),
        ("GRID",           (0,0), (-1,-1), 0.4, BORDER),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",     (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ]
    if header:
        styles += [
            ("BACKGROUND", (0,0), (-1,0), NAVY),
            ("TEXTCOLOR",  (0,0), (-1,0), WHITE),
        ]
    t.setStyle(TableStyle(styles))
    return t

# ── Build story ───────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT, pagesize=letter,
    leftMargin=0.85*inch, rightMargin=0.85*inch,
    topMargin=0.75*inch,  bottomMargin=0.75*inch,
    title="IT Jira Dashboard — Project Summary",
    author="IT Department",
)
story = []

# Cover
cover = Table([
    [p("IT Jira Dashboard", cover_title)],
    [p("Project Summary &amp; Remote Access Proposal", cover_sub)],
    [p("Prepared for: Management Review &nbsp;|&nbsp; May 2026", cover_date)],
], colWidths=[6.5*inch])
cover.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,-1), NAVY),
    ("LEFTPADDING",   (0,0), (-1,-1), 22),
    ("RIGHTPADDING",  (0,0), (-1,-1), 22),
    ("TOPPADDING",    (0,0), (0, 0),  22),
    ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ("BOTTOMPADDING", (0,2), (-1, 2), 22),
]))
story += [cover, sp(18)]

# ── Section 1: What Was Built ─────────────────────────────────────────────────
story.append(section_hdr("1.  What Was Built"))
story += [sp(4), p(
    "A custom internal IT dashboard that pulls live data from Jira and presents it as an "
    "interactive, browser-based web page — no external accounts, cloud subscriptions, or "
    "additional software licenses required."
), sp(6)]

feat_rows = [
    [p(B("Ticket Visibility"), callout),
     p("Displays all IT tickets open 45+ days, grouped by assignee, with days open, "
       "last response date, and repeat-flag count.")],
    [p(B("Charts &amp; Filters"), callout),
     p("Age-distribution and assignee-breakdown charts. Filter by assignee, priority, "
       "or status. Toggle between the 45-day scoped view and all open tickets.")],
    [p(B("Approaching Tickets"), callout),
     p("Separate warning section for tickets within 7 days of the 45-day threshold.")],
    [p(B("Comment System"), callout),
     p("View, post, edit, and delete Jira comments directly from the dashboard "
       "without opening Jira.")],
    [p(B("Automated Refresh"), callout),
     p("PowerShell script pulls fresh data from Jira on a schedule; "
       "dashboard updates automatically.")],
    [p(B("No Admin Rights"), callout),
     p("Entire system — server, data refresh, and tunnel — runs under a standard "
       "user account with no elevated privileges.")],
]
feat = Table(feat_rows, colWidths=[1.75*inch, 4.75*inch])
feat.setStyle(TableStyle([
    ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("ROWBACKGROUNDS",(0,0), (-1,-1), [WHITE, LGREY]),
    ("LINEAFTER",     (0,0), (0,-1),  0.5, BORDER),
]))
story += [feat, sp(10)]

# ── Section 2: Current State ──────────────────────────────────────────────────
story.append(section_hdr("2.  Current State"))
story += [
    sp(4),
    p("The dashboard server runs on a local workstation and is accessible to anyone "
      "on the company network via a local IP address:"),
    p("&nbsp;&nbsp;&nbsp;&nbsp;" + B("http://192.0.2.10:8080")),
    sp(4),
    p("For " + B("remote access") + " — from home, while traveling, or for users on a "
      "different network segment — the team uses a " + B("Cloudflare Tunnel") + ": a free, "
      "secure HTTPS link from the internet to the local server. No inbound firewall ports "
      "are opened; the connection is outbound-only and encrypted end-to-end."),
    sp(4),
    p(B("Current limitation:") + " The tunnel URL is temporary. Each restart generates a new "
      "random address (e.g. " + I("random-words.trycloudflare.com") + ") that must be "
      "re-shared with the team."),
    sp(10),
]

# ── Section 3: Permanent URL Options ─────────────────────────────────────────
story.append(section_hdr("3.  Remote Access — Permanent URL Options"))
story += [
    sp(4),
    p("Two paths exist to give the dashboard a fixed, permanent HTTPS address. "
      "Both use the same free Cloudflare Tunnel technology already in place."),
    sp(8),
]

# Option A
story.append(p(
    "Option A — Subdomain on Existing Company Domain &nbsp;"
    + C("(Recommended · $0)", "#16a34a"), h2))
story += [
    p("If the company domain (e.g. " + I("yourcompany.com") + ") is registered anywhere — "
      "GoDaddy, Namecheap, Google Domains, etc. — a dedicated subdomain can be created "
      "at no additional cost."),
    p(B("Example permanent URL:")),
    p("&nbsp;&nbsp;&nbsp;&nbsp;" + B("https://it-dashboard.yourcompany.com")),
    sp(4),
    p(B("Steps required:")),
    bullet("Identify who manages the company domain"),
    bullet("Add one CNAME DNS record for the chosen subdomain pointing to the Cloudflare tunnel"),
    bullet("Run the one-time setup script already prepared (≈15 minutes total)"),
    sp(4),
    p(B("Cost: $0") + " — no new registrations or subscriptions required."),
    sp(10),
]

# Option B — pricing table
story.append(p(
    "Option B — Dedicated Domain Purchase &nbsp;"
    + C("(~$10–12 / year)", "#d97706"), h2))
story += [
    p("If no company domain is available or a separate identity is preferred, "
      "a domain can be registered specifically for this project. "
      "Cloudflare Registrar sells domains at cost with zero markup."),
    sp(6),
]

price_rows = [
    [p(B("Extension"), callout), p(B("Annual Cost"), callout), p(B("Example URL"), callout)],
    [p(".com", body), p("$10.44 / yr", body), p("it-dashboard.yourcompany.com", note)],
    [p(".net", body), p("$11.44 / yr", body), p("it-dashboard.yourcompany.net", note)],
    [p(".org", body), p("$10.44 / yr", body), p("it-dashboard.yourcompany.org", note)],
    [p(".dev", body), p("$12.00 / yr", body), p("it-dashboard.yourcompany.dev", note)],
]
story.append(styled_table(price_rows, [1.1*inch, 1.4*inch, 4.0*inch]))
story += [
    sp(6),
    p("Cloudflare DNS management and the tunnel service are both " + B("free") + " on any "
      "plan. The domain registration fee above is the only recurring cost.", note),
    sp(10),
]

# ── Section 4: Summary ────────────────────────────────────────────────────────
story.append(section_hdr("4.  Summary of Deliverables &amp; Next Steps"))
story.append(sp(6))

sum_rows = [
    [p(B("Item"), callout),         p(B("Status"), callout),                             p(B("Notes"), callout)],
    [p("Dashboard built & running"), p(C(B("Done"), "#16a34a")),                          p("Live on local workstation", note)],
    [p("Accessible on LAN"),         p(C(B("Done"), "#16a34a")),                          p("http://192.0.2.10:8080", note)],
    [p("Remote access (temp URL)"),  p(C(B("Working"), "#16a34a")),                       p("Cloudflare Tunnel active", note)],
    [p("Comment system (CRUD)"),     p(C(B("Done"), "#16a34a")),                          p("Post, edit, delete in Jira", note)],
    [p("Permanent remote URL"),      p(C(B("Pending"), "#d97706")),                       p("Needs subdomain or new domain", note)],
    [p("Setup time (once domain is available)"), p("~15 minutes"),                        p("Scripts already prepared", note)],
    [p("Cost — Option A (subdomain)"),           p(C(B("$0"), "#16a34a")),               p("Use existing company domain", note)],
    [p("Cost — Option B (new domain)"),          p("~$10–12 / year"),                p("Cloudflare Registrar", note)],
]
story.append(styled_table(sum_rows, [2.6*inch, 1.4*inch, 2.5*inch]))
story.append(sp(14))

# Footer
story += [
    hr(),
    p(B("Security note:") + " The Cloudflare Tunnel is outbound-only. No inbound ports are "
      "opened on the machine or company firewall. All traffic is HTTPS-encrypted. "
      "Access can be restricted to company email addresses only via Cloudflare Access "
      "(also free) if required in the future.", note),
    sp(4),
    p("Prepared by IT Department &nbsp;|&nbsp; JiraReporter Project &nbsp;|&nbsp; May 2026",
      footer_s),
]

doc.build(story)
print(f"PDF saved: {OUT}")
