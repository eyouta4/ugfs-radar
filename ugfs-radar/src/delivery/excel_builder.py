from __future__ import annotations
import io
from datetime import date
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
try:
    from src.config.logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging; logger = logging.getLogger(__name__)

VERT_GO   = "92D050"
ORANGE_BP = "FFC000"
BLEU_OPEN = "BDD7EE"
ROUGE_NEG = "FF9999"
BLANC     = "FFFFFF"
GRIS_HDR  = "1F4E79"
GRIS_HDR2 = "2E75B6"

THIN = Side(style="thin", color="BFBFBF")
B    = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
AL   = Alignment(horizontal="left", vertical="top", wrap_text=True)
AC   = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Column layout — MUST stay in sync with COL_* constants in feedback.py
COLS = [
    "ID",                          # A  col 1  — hidden, used by feedback ingestion
    "Opportunite",                 # B  col 2
    "Score /100",                  # C  col 3
    "Lien",                        # D  col 4
    "Type / Vehicule UGFS",        # E  col 5
    "UGFS eligible",               # F  col 6
    "Appel ouvert",                # G  col 7
    "Deadline",                    # H  col 8
    "Positionnement UGFS",         # I  col 9
    "Decision UGFS",               # J  col 10  ← dropdown
    "Commentaire interne",         # K  col 11  ← free text raison
]

# Exported constant used by feedback.py for column indices (0-based)
COL_ID       = 0   # A
COL_TITLE    = 1   # B
COL_SCORE    = 2   # C
COL_URL      = 3   # D
COL_DECISION = 9   # J
COL_REASON   = 10  # K


def _days(o):
    d = getattr(o, "deadline", None)
    if not d:
        return None
    return (d - date.today()).days


def _dl_str(o):
    d = getattr(o, "deadline", None)
    if d:
        return d.strftime("%d/%m/%Y")
    return getattr(o, "deadline_text_raw", None) or "Rolling"


def _row_color(o):
    dec = (getattr(o, "client_decision", "") or "").upper()
    if dec in ("NO_GO", "REFUSED"):
        return ROUGE_NEG
    if dec in ("GO", "GO_SUBMITTED", "SUBMITTED"):
        return VERT_GO
    d = _days(o)
    if d is not None and 0 < d <= 14:
        return ORANGE_BP
    s = getattr(o, "score", 0) or 0
    if s >= 50:
        return BLEU_OPEN
    return BLANC


def _elig_str(o):
    s = getattr(o, "score", 0) or 0
    e = getattr(o, "eligibility_summary", "") or ""
    base = "Oui" if s >= 50 else "A verifier"
    if e and e != "-":
        return base + "\n" + e[:200]
    return base


def _position_str(o):
    vm  = getattr(o, "vehicle_match", None) or ""
    why = getattr(o, "why_interesting", "") or ""
    sc  = getattr(o, "score", 0) or 0
    d   = _days(o)
    parts = []
    if vm:
        parts.append(f"Vehicule : {vm}")
    if d is not None and 0 < d <= 21:
        parts.append(f"⚠ {d}j restants — URGENT")
    if sc >= 70:
        parts.append("★ PRIORITAIRE")
    if why:
        parts.append(why[:180])
    return "\n".join(parts) if parts else "-"


def _hdr(ws, row, col, value, bg=GRIS_HDR, fg="FFFFFF", size=11):
    cell = ws.cell(row, col, value)
    cell.font = Font(name="Calibri", bold=True, size=size, color=fg)
    cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    cell.alignment = AC
    cell.border = B
    return cell


def _cell(ws, row, col, value, bg=BLANC, bold=False, link=False, wrap=True):
    cell = ws.cell(row, col, value)
    color = "0563C1" if link else "000000"
    cell.font = Font(name="Calibri", bold=bold, size=10, color=color,
                     underline="single" if link else None)
    cell.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    cell.alignment = Alignment(horizontal="left", vertical="top",
                                wrap_text=wrap)
    cell.border = B
    return cell


_SOCIAL = {"instagram.com", "facebook.com", "twitter.com", "tiktok.com", "youtube.com"}


def build_weekly_excel(opportunities, historical=None, output_path=None, run_date=None):
    if run_date is None:
        run_date = date.today()

    wb = Workbook()
    ws = wb.active
    ws.title = "Toutes opportunites"
    ws.sheet_view.showGridLines = False

    # ── Title row ──────────────────────────────────────────────────────────
    ws.row_dimensions[1].height = 8
    ws.merge_cells("A2:K2")
    t = ws["A2"]
    t.value = (
        "UGFS-RADAR — Appels d'offres & Opportunites de financement"
        f"  ·  Edition du {run_date.strftime('%d/%m/%Y')}"
    )
    t.font = Font(name="Calibri", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(start_color=GRIS_HDR, end_color=GRIS_HDR, fill_type="solid")
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 6

    # ── Header row ─────────────────────────────────────────────────────────
    for c, h in enumerate(COLS, 1):
        bg = GRIS_HDR if c != 10 else GRIS_HDR2   # highlight Decision col
        _hdr(ws, 4, c, h, bg=bg)
    ws.row_dimensions[4].height = 36

    # ── Filter & sort opportunities ────────────────────────────────────────
    opps = [
        o for o in (opportunities or [])
        if getattr(o, "status", None) != "HISTORICAL"
        and (getattr(o, "score", 0) or 0) >= 40
        and not any(p in (getattr(o, "url", "") or "").lower() for p in _SOCIAL)
    ]
    opps = sorted(
        opps,
        key=lambda o: (
            (getattr(o, "client_decision", "") or "").upper() in ("NO_GO",),
            not ((_days(o) or 999) <= 21 and (_days(o) or 0) >= 0),
            -(getattr(o, "score", 0) or 0),
        ),
    )
    opps = opps[:35]

    if not opps and historical:
        opps = list(historical)[:25]

    DR = 5   # data start row
    for i, opp in enumerate(opps):
        r  = DR + i
        bg = _row_color(opp)

        opp_id  = getattr(opp, "id",    "") or ""
        title   = getattr(opp, "title", "") or "-"
        score   = getattr(opp, "score", 0)  or 0
        url     = getattr(opp, "url",   "") or ""
        vm      = getattr(opp, "vehicle_match", None) or getattr(opp, "opportunity_type", "") or "-"
        d       = _days(opp)
        ouvert  = "Oui" if (d is None or d > 0) else "Cloture"
        if d is not None and 0 < d <= 7:
            ouvert = f"⚠ URGENT ({d}j)"
        elif d is not None and 0 < d <= 14:
            ouvert = f"Urgent ({d}j)"

        _cell(ws, r, 1,  str(opp_id),          bg=bg)
        _cell(ws, r, 2,  title,                 bg=bg, bold=True)
        _cell(ws, r, 3,  score,                 bg=bg, wrap=False)
        _cell(ws, r, 4,  url,                   bg=bg, link=bool(url.startswith("http")))
        if url.startswith("http"):
            ws.cell(r, 4).hyperlink = url
        _cell(ws, r, 5,  vm,                    bg=bg)
        _cell(ws, r, 6,  _elig_str(opp),        bg=bg)
        _cell(ws, r, 7,  ouvert,                bg=bg, wrap=False)
        _cell(ws, r, 8,  _dl_str(opp),          bg=bg, wrap=False)
        _cell(ws, r, 9,  _position_str(opp),    bg=bg)
        dec_val = (getattr(opp, "client_decision", "") or "")
        _cell(ws, r, 10, dec_val,               bg=bg, bold=bool(dec_val))
        _cell(ws, r, 11, (getattr(opp, "client_reason", "") or ""), bg=bg)

        text_len = max(
            len(getattr(opp, "eligibility_summary", "") or ""),
            len(getattr(opp, "why_interesting", "") or ""),
        )
        ws.row_dimensions[r].height = max(45, min(160, 18 + text_len // 4))

    if opps:
        last = DR + len(opps) - 1
        dv = DataValidation(
            type="list",
            formula1='"GO,NO_GO,BORDERLINE,SUBMITTED,En cours"',
            allow_blank=True,
            showDropDown=False,
        )
        ws.add_data_validation(dv)
        dv.add(f"J{DR}:J{last}")
        ws.auto_filter.ref = f"A4:K{last}"
        ws.freeze_panes = "A5"

    # ── Column widths ───────────────────────────────────────────────────────
    for col, w in {
        "A": 6,    "B": 38, "C": 9,  "D": 50,
        "E": 20,   "F": 22, "G": 14, "H": 14,
        "I": 36,   "J": 18, "K": 28,
    }.items():
        ws.column_dimensions[col].width = w

    # Hide ID column (A) — still readable by feedback parser
    ws.column_dimensions["A"].hidden = True

    # ── Legend row ──────────────────────────────────────────────────────────
    legend_row = DR + len(opps) + 2
    ws.merge_cells(f"A{legend_row}:K{legend_row}")
    leg = ws.cell(legend_row, 1,
        "LEGENDE : 🟢 GO/Soumis  ·  🔵 Ouvert (score ≥ 50)  ·  🟠 Urgent ≤ 14j"
        "  ·  🔴 NO-GO  ·  ⬜ A evaluer"
        "  — Remplir colonne J (Decision) + K (Commentaire), renvoyer a radar-feedback@ugfs-na.com"
    )
    leg.font = Font(name="Calibri", italic=True, size=9, color="595959")
    leg.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[legend_row].height = 28

    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(data)
    logger.info("excel_built", n=len(opps), kb=round(len(data) / 1024, 1))
    return data


# Column name list — kept for backward compat imports
ALL_OPPS_COLUMNS = COLS
