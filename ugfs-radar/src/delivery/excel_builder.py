"""
src/delivery/excel_builder.py — Rapport Excel hebdomadaire UGFS-Radar.

4 onglets :
  1. GO           — AOs score > 80 (action immédiate)
  2. A étudier    — AOs score 60-80 (à investiguer)
  3. Toutes       — Toutes les opportunités (vue complète + colonne décision)
  4. Stats RL     — Métriques d'apprentissage et historique des performances

Colonnes principales :
  A:ID(caché) B:Titre C:Score D:Lien E:Véhicule F:Éligible G:Ouvert H:Deadline
  I:Positionnement J:Décision(dropdown) K:Commentaire
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, GradientFill, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

try:
    from src.config.logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging
    logger = logging.getLogger(__name__)

# ── Palette couleurs UGFS ────────────────────────────────────────────────────
NAVY    = "1F4E79"   # Header principal
BLUE2   = "2E75B6"   # Header secondaire
VERT_GO = "92D050"   # Score > 80
VERT_LT = "E2EFDA"   # Score 60-80
ORANGE  = "FFC000"   # Urgent ≤ 14j
ORANGE_LT = "FFF2CC" # Borderline / attention
ROUGE   = "FF4D4D"   # NO-GO
ROUGE_LT = "FFE0E0"  # NO-GO light
BLEU_OPT = "BDD7EE"  # Ouvert score 40-60
BLANC   = "FFFFFF"
GRIS_LT = "F2F2F2"
GRIS_HDR = "D9D9D9"

THIN = Side(style="thin", color="BFBFBF")
MED  = Side(style="medium", color="1F4E79")
B    = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
B_MED = Border(left=MED, right=MED, top=MED, bottom=MED)
AL   = Alignment(horizontal="left",   vertical="top",    wrap_text=True)
AC   = Alignment(horizontal="center", vertical="center", wrap_text=True)
AR   = Alignment(horizontal="right",  vertical="center")

# Column layout — indices 0-based, utilisés par feedback.py
COLS = [
    "ID",                     # A  0  caché
    "Opportunite",            # B  1
    "Score /100",             # C  2
    "Lien",                   # D  3
    "Vehicule / Type",        # E  4
    "UGFS Eligible",          # F  5
    "Appel Ouvert",           # G  6
    "Deadline",               # H  7
    "Effort estime",          # I  8  ← NEW : ~Xj (low/medium/high)
    "Win prob.",              # J  9  ← NEW : 0-45%
    "Positionnement UGFS",    # K 10
    "Decision UGFS",          # L 11 ← dropdown (déplacé de J → L)
    "Commentaire interne",    # M 12 ← déplacé de K → M
]

# Exporté pour feedback.py — indices mis à jour
COL_ID       = 0
COL_TITLE    = 1
COL_SCORE    = 2
COL_URL      = 3
COL_EFFORT   = 8
COL_WINPROB  = 9
COL_DECISION = 11   # ← shift de 9 → 11
COL_REASON   = 12   # ← shift de 10 → 12

_SOCIAL = {"instagram.com", "facebook.com", "twitter.com", "tiktok.com", "youtube.com"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _days(o) -> int | None:
    d = getattr(o, "deadline", None)
    return (d - date.today()).days if d else None


def _dl_str(o) -> str:
    d = getattr(o, "deadline", None)
    if d:
        return d.strftime("%d/%m/%Y")
    return getattr(o, "deadline_text_raw", None) or "Rolling"


def _row_bg(o) -> str:
    dec = (getattr(o, "client_decision", "") or "").upper()
    if dec in ("NO_GO", "REFUSED"):
        return ROUGE_LT
    if dec in ("GO", "GO_SUBMITTED", "SUBMITTED"):
        return VERT_GO
    d = _days(o)
    s = getattr(o, "score", 0) or 0
    if d is not None and 0 < d <= 7:
        return ORANGE
    if d is not None and 0 < d <= 14:
        return ORANGE_LT
    if s >= 80:
        return VERT_GO
    if s >= 60:
        return VERT_LT
    if s >= 40:
        return BLEU_OPT
    return BLANC


def _elig_str(o) -> str:
    s = getattr(o, "score", 0) or 0
    e = getattr(o, "eligibility_summary", "") or ""
    base = "Oui" if s >= 50 else "A verifier"
    return (base + "\n" + e[:200]) if (e and e != "-") else base


def _open_str(o) -> str:
    d = _days(o)
    if d is None:
        return "Oui"
    if d <= 0:
        return "Cloture"
    if d <= 7:
        return f"⚠ URGENT ({d}j)"
    if d <= 14:
        return f"Urgent ({d}j)"
    return "Oui"


def _position_str(o) -> str:
    vm  = getattr(o, "vehicle_match", None) or ""
    why = getattr(o, "why_interesting", "") or ""
    s   = getattr(o, "score", 0) or 0
    d   = _days(o)
    parts = []
    if vm:
        parts.append(f"Vehicule : {vm}")
    if d is not None and 0 < d <= 21:
        parts.append(f"⚠ {d}j — URGENT")
    if s >= 80:
        parts.append("★★ PRIORITAIRE GO")
    elif s >= 60:
        parts.append("★ A étudier")
    if why:
        parts.append(why[:200])
    return "\n".join(parts) if parts else "-"


def _hdr(ws, row, col, value, bg=NAVY, fg="FFFFFF", size=10, bold=True):
    c = ws.cell(row, col, value)
    c.font = Font(name="Calibri", bold=bold, size=size, color=fg)
    c.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    c.alignment = AC
    c.border = B
    return c


def _cell(ws, row, col, value, bg=BLANC, bold=False, link=False):
    c = ws.cell(row, col, value)
    color = "0563C1" if link else "000000"
    c.font = Font(name="Calibri", bold=bold, size=10, color=color,
                  underline="single" if link else None)
    c.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    c.alignment = AL
    c.border = B
    return c


def _effort_str(opp) -> str:
    """Extrait effort_days + win_prob du score_breakdown."""
    br = getattr(opp, "score_breakdown", {}) or {}
    days = br.get("effort_days_estimate")
    if days is None:
        return "-"
    days = int(days)
    if days <= 4:
        level = "🟢 Faible"
    elif days <= 10:
        level = "🟡 Moyen"
    else:
        level = "🔴 Élevé"
    return f"~{days}j\n{level}"


def _winprob_str(opp) -> str:
    br = getattr(opp, "score_breakdown", {}) or {}
    p = br.get("win_probability_pct")
    if p is None:
        return "-"
    p = int(p)
    if p >= 25:
        return f"{p}%\n★★★ Forte"
    if p >= 15:
        return f"{p}%\n★★ Modérée"
    if p >= 8:
        return f"{p}%\n★ Faible"
    return f"{p}%\nTrès faible"


def _write_opp_row(ws, r, opp):
    bg = _row_bg(opp)
    opp_id = getattr(opp, "id", "") or ""
    title  = getattr(opp, "title", "") or "-"
    score  = getattr(opp, "score", 0) or 0
    url    = getattr(opp, "url", "") or ""
    vm     = getattr(opp, "vehicle_match", None) or getattr(opp, "opportunity_type", "") or "-"

    _cell(ws, r, 1,  str(opp_id),       bg=bg)
    _cell(ws, r, 2,  title,             bg=bg, bold=True)
    _cell(ws, r, 3,  score,             bg=bg)
    _cell(ws, r, 4,  url,               bg=bg, link=bool(url.startswith("http")))
    if url.startswith("http"):
        ws.cell(r, 4).hyperlink = url
    _cell(ws, r, 5,  vm,               bg=bg)
    _cell(ws, r, 6,  _elig_str(opp),   bg=bg)
    _cell(ws, r, 7,  _open_str(opp),   bg=bg)
    _cell(ws, r, 8,  _dl_str(opp),     bg=bg)
    _cell(ws, r, 9,  _effort_str(opp), bg=bg)
    _cell(ws, r, 10, _winprob_str(opp), bg=bg)
    _cell(ws, r, 11, _position_str(opp), bg=bg)
    dec = (getattr(opp, "client_decision", "") or "")
    _cell(ws, r, 12, dec,              bg=bg, bold=bool(dec))
    _cell(ws, r, 13, (getattr(opp, "client_reason", "") or ""), bg=bg)

    text_len = max(
        len(getattr(opp, "eligibility_summary", "") or ""),
        len(getattr(opp, "why_interesting", "") or ""),
    )
    ws.row_dimensions[r].height = max(40, min(150, 16 + text_len // 4))


def _add_title_row(ws, run_date, label, color=NAVY):
    ws.row_dimensions[1].height = 8
    ws.merge_cells("A2:M2")    # ← 13 cols (A→M)
    t = ws["A2"]
    t.value = f"UGFS-RADAR  ·  {label}  ·  Edition du {run_date.strftime('%d/%m/%Y')}"
    t.font = Font(name="Calibri", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 26
    ws.row_dimensions[3].height = 5


def _add_headers(ws):
    for c, h in enumerate(COLS, 1):
        # Mettre en évidence la colonne Decision UGFS (col L = 12)
        bg = BLUE2 if c == 12 else NAVY
        _hdr(ws, 4, c, h, bg=bg)
    ws.row_dimensions[4].height = 32


def _set_col_widths(ws):
    for col, w in {
        "A": 6,  "B": 36, "C": 9,  "D": 48,
        "E": 18, "F": 22, "G": 14, "H": 14,
        "I": 12, "J": 14, "K": 32, "L": 16, "M": 26,
    }.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions["A"].hidden = True


def _add_dropdown_and_filter(ws, start_row, last_row):
    if last_row < start_row:
        return
    dv = DataValidation(
        type="list",
        formula1='"GO,NO_GO,BORDERLINE,SUBMITTED,En cours"',
        allow_blank=True,
        showDropDown=False,
    )
    ws.add_data_validation(dv)
    # Decision UGFS est maintenant en col L (12e colonne)
    dv.add(f"L{start_row}:L{last_row}")
    ws.auto_filter.ref = f"A4:M{last_row}"
    ws.freeze_panes = "B5"


def _add_legend(ws, last_row):
    lr = last_row + 2
    ws.merge_cells(f"A{lr}:M{lr}")
    c = ws.cell(lr, 1,
        "LEGENDE : 🟢 GO/Soumis  ·  🟡 Score 60-80 A etudier  ·  🟠 Urgent ≤14j"
        "  ·  🔴 NO-GO  ·  🔵 Ouvert  ·  Effort : 🟢 Faible / 🟡 Moyen / 🔴 Élevé"
        "  ·  Win prob basée sur historique UGFS — "
        "Remplir colonne L (Decision) + M (Commentaire) et renvoyer a radar-feedback@ugfs-na.com"
    )
    c.font = Font(name="Calibri", italic=True, size=9, color="595959")
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[lr].height = 24


# ── Filtres ──────────────────────────────────────────────────────────────────

def _filter_opps(opportunities, min_score=40, max_rows=35, exclude_historical=True):
    opps = [
        o for o in (opportunities or [])
        if (not exclude_historical or getattr(o, "status", None) != "HISTORICAL")
        and (getattr(o, "score", 0) or 0) >= min_score
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
    return opps[:max_rows]


# ── Onglet 1 : GO (score ≥ 80) ───────────────────────────────────────────────

def _build_go_sheet(wb, opportunities, run_date):
    ws = wb.create_sheet("GO — Prioritaire")
    ws.sheet_view.showGridLines = False
    ws.tab_color = "92D050"
    _add_title_row(ws, run_date, "Opportunites GO — Score ≥ 80", color="1A7340")
    _add_headers(ws)
    _set_col_widths(ws)

    go_opps = _filter_opps(opportunities, min_score=80, max_rows=20)

    DR = 5
    for i, opp in enumerate(go_opps):
        _write_opp_row(ws, DR + i, opp)

    if go_opps:
        _add_dropdown_and_filter(ws, DR, DR + len(go_opps) - 1)
        _add_legend(ws, DR + len(go_opps) - 1)

    if not go_opps:
        ws.merge_cells("B5:M5")
        c = ws.cell(5, 2, "Aucun appel d'offres avec score ≥ 80 cette semaine.")
        c.font = Font(name="Calibri", italic=True, size=11, color="595959")
        c.alignment = AC

    return ws


# ── Onglet 2 : À étudier (score 60-79) ───────────────────────────────────────

def _build_study_sheet(wb, opportunities, run_date):
    ws = wb.create_sheet("A etudier — Score 60-79")
    ws.sheet_view.showGridLines = False
    ws.tab_color = "FFC000"
    _add_title_row(ws, run_date, "A etudier — Score 60 a 79", color="8B6000")
    _add_headers(ws)
    _set_col_widths(ws)

    study_opps = [
        o for o in _filter_opps(opportunities, min_score=60, max_rows=30)
        if (getattr(o, "score", 0) or 0) < 80
    ]

    DR = 5
    for i, opp in enumerate(study_opps):
        _write_opp_row(ws, DR + i, opp)

    if study_opps:
        _add_dropdown_and_filter(ws, DR, DR + len(study_opps) - 1)
        _add_legend(ws, DR + len(study_opps) - 1)

    if not study_opps:
        ws.merge_cells("B5:M5")
        c = ws.cell(5, 2, "Aucun appel d'offres entre 60 et 79 cette semaine.")
        c.font = Font(name="Calibri", italic=True, size=11, color="595959")
        c.alignment = AC

    return ws


# ── Onglet 3 : Toutes les opportunités ───────────────────────────────────────

def _build_all_sheet(wb, opportunities, historical, run_date):
    ws = wb.create_sheet("Toutes opportunites")
    ws.sheet_view.showGridLines = False
    ws.tab_color = "2E75B6"
    _add_title_row(ws, run_date, "Toutes les Opportunites detectees", color=NAVY)
    _add_headers(ws)
    _set_col_widths(ws)

    opps = _filter_opps(opportunities, min_score=35, max_rows=40)
    if not opps and historical:
        opps = list(historical)[:25]

    DR = 5
    for i, opp in enumerate(opps):
        _write_opp_row(ws, DR + i, opp)

    if opps:
        _add_dropdown_and_filter(ws, DR, DR + len(opps) - 1)
        _add_legend(ws, DR + len(opps) - 1)

    return ws


# ── Onglet 4 : Stats RL ───────────────────────────────────────────────────────

def _build_stats_sheet(wb, opportunities, run_date):
    ws = wb.create_sheet("Stats RL")
    ws.sheet_view.showGridLines = False
    ws.tab_color = "7030A0"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 40

    # Titre
    ws.merge_cells("A1:C1")
    t = ws["A1"]
    t.value = f"UGFS-Radar — Metriques d apprentissage  ·  {run_date.strftime('%d/%m/%Y')}"
    t.font = Font(name="Calibri", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(start_color="7030A0", end_color="7030A0", fill_type="solid")
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    all_opps = opportunities or []
    total    = len(all_opps)
    score_80 = sum(1 for o in all_opps if (getattr(o, "score", 0) or 0) >= 80)
    score_60 = sum(1 for o in all_opps if 60 <= (getattr(o, "score", 0) or 0) < 80)
    urgent   = sum(1 for o in all_opps if getattr(o, "is_urgent", False))
    go_hist  = sum(1 for o in all_opps if (getattr(o, "client_decision", "") or "").upper()
                   in ("GO", "GO_SUBMITTED"))
    nogo_hist = sum(1 for o in all_opps if (getattr(o, "client_decision", "") or "").upper()
                    == "NO_GO")

    stats = [
        ("SEMAINE EN COURS", "", ""),
        ("Opportunites detectees", total, "Total apres deduplication"),
        ("Score >= 80 (GO)", score_80, "Action immediate recommandee"),
        ("Score 60-79 (A etudier)", score_60, "Investigation recommandee"),
        ("Urgentes (deadline ≤ 7j)", urgent, "Soumission cette semaine"),
        ("", "", ""),
        ("HISTORIQUE FEEDBACK", "", ""),
        ("GO confirmes par UGFS", go_hist, "Soumissions validees"),
        ("NO-GO confirmes", nogo_hist, "Opportunites rejetees"),
        ("Taux GO/total feedbacks",
         f"{round(go_hist/(go_hist+nogo_hist)*100)}%" if (go_hist+nogo_hist) > 0 else "N/A",
         "Precision du scoring RL"),
        ("", "", ""),
        ("PARAMETRES RL", "", ""),
        ("Score minimum Excel", "35/100", "Threshold d affichage"),
        ("Score GO", "≥ 80", "Onglet GO prioritaire"),
        ("Score A etudier", "60-79", "Onglet A etudier"),
        ("Recalibration", "Mensuelle automatique", "Si ≥ 5 feedbacks recus"),
        ("Modele ML", "LogisticRegression L2", "sklearn, pas de GPU"),
        ("", "", ""),
        ("PROCHAINES ETAPES", "", ""),
        ("1. Remplir colonne J", "Decision", "GO / NO_GO / BORDERLINE / SUBMITTED"),
        ("2. Remplir colonne K", "Commentaire", "Raison courte (utile pour RL)"),
        ("3. Renvoyer le fichier", "radar-feedback@ugfs-na.com", "Integre dans le modele"),
    ]

    for r_idx, (label, value, note) in enumerate(stats, start=3):
        ws.row_dimensions[r_idx].height = 18
        if label and not value:
            # Section header
            c = ws.cell(r_idx, 1, label)
            c.font = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
            c.fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
            ws.merge_cells(f"A{r_idx}:C{r_idx}")
            c.alignment = Alignment(horizontal="left", vertical="center")
        else:
            c1 = ws.cell(r_idx, 1, label)
            c2 = ws.cell(r_idx, 2, value)
            c3 = ws.cell(r_idx, 3, note)
            for c in (c1, c2, c3):
                c.font = Font(name="Calibri", size=10)
                c.fill = PatternFill(start_color=GRIS_LT if r_idx % 2 == 0 else BLANC,
                                     end_color=GRIS_LT if r_idx % 2 == 0 else BLANC,
                                     fill_type="solid")
                c.border = B
            c1.font = Font(name="Calibri", size=10, bold=True)
            c2.alignment = Alignment(horizontal="center", vertical="center")

    return ws


# ── Fonction principale ───────────────────────────────────────────────────────

def build_weekly_excel(
    opportunities,
    historical=None,
    output_path=None,
    run_date=None,
) -> bytes:
    """
    Construit le fichier Excel complet avec 4 onglets.
    Retourne les bytes du fichier .xlsx.
    """
    if run_date is None:
        run_date = date.today()

    wb = Workbook()
    # Supprimer l'onglet par défaut
    default_sheet = wb.active
    wb.remove(default_sheet)

    all_opps = list(opportunities or [])

    # Onglet 1 — GO
    _build_go_sheet(wb, all_opps, run_date)

    # Onglet 2 — À étudier
    _build_study_sheet(wb, all_opps, run_date)

    # Onglet 3 — Toutes (avec dropdown décision pour feedback)
    _build_all_sheet(wb, all_opps, historical or [], run_date)

    # Onglet 4 — Stats RL
    _build_stats_sheet(wb, all_opps, run_date)

    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    if output_path:
        Path(output_path).write_bytes(data)

    n_go    = sum(1 for o in all_opps if (getattr(o, "score", 0) or 0) >= 80)
    n_study = sum(1 for o in all_opps if 60 <= (getattr(o, "score", 0) or 0) < 80)
    logger.info("excel_built",
                total=len(all_opps), go=n_go, study=n_study,
                kb=round(len(data) / 1024, 1))
    return data


# Compat
ALL_OPPS_COLUMNS = COLS
