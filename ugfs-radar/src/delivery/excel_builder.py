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

VERT_GO="92D050"; BLEU_OPEN="00B0F0"; ROUGE_NEG="FF0000"; BLANC="FFFFFF"; GRIS_HDR="D9D9D9"
THIN=Side(style="thin",color="000000")
B=Border(left=THIN,right=THIN,top=THIN,bottom=THIN)
AL=Alignment(horizontal="left",vertical="top",wrap_text=True)
AC=Alignment(horizontal="center",vertical="center",wrap_text=True)

def _days(o):
    d=getattr(o,"deadline",None)
    if not d: return None
    return (d-date.today()).days

def _dl_str(o):
    d=getattr(o,"deadline",None)
    if d: return d.strftime("%d/%m/%Y")
    return getattr(o,"deadline_text_raw",None) or "Rolling"

def _row_color(o):
    dec=(getattr(o,"client_decision","") or "").upper()
    if dec in ("NO_GO","REFUSED"): return ROUGE_NEG
    if dec in ("GO","GO_SUBMITTED","SUBMITTED"): return VERT_GO
    s=getattr(o,"score",0) or 0
    d=_days(o)
    if s>=50 or (d is not None and d>0): return BLEU_OPEN
    return BLANC

def _elig_str(o):
    s=getattr(o,"score",0) or 0
    e=getattr(o,"eligibility_summary","") or ""
    base="oui" if s>=50 else "a verifier"
    if e and e!="-": return base+"\n"+e[:150]
    return base

def _actions_str(o):
    vm=getattr(o,"vehicle_match",None) or ""
    why=getattr(o,"why_interesting","") or ""
    sc=getattr(o,"score",0) or 0
    d=_days(o)
    parts=[]
    if vm: parts.append(vm)
    if d is not None and 0<d<=21: parts.append(str(d)+"j restants - URGENT")
    if sc>=70: parts.append("PRIORITAIRE")
    if why: parts.append(why[:120])
    return "\n".join(parts) if parts else "-"

def _resp_str(o):
    dec=getattr(o,"client_decision",None) or ""
    reason=getattr(o,"client_reason",None) or ""
    parts=[dec] if dec else []
    if reason: parts.append(reason[:80])
    return "\n".join(parts) if parts else ""

def build_weekly_excel(opportunities,historical=None,output_path=None,run_date=None):
    if run_date is None: run_date=date.today()
    wb=Workbook(); ws=wb.active; ws.title="Opportunites"
    ws.sheet_view.showGridLines=False
    ws.row_dimensions[1].height=8
    ws.merge_cells("A2:E2")
    t=ws["A2"]
    t.value="OPPORTUNITES D APPEL D OFFRES - UGFS-Radar - Edition du "+run_date.strftime("%d/%m/%Y")
    t.font=Font(name="Calibri",bold=True,size=13)
    t.alignment=Alignment(horizontal="left",vertical="center")
    ws.row_dimensions[2].height=22
    ws.row_dimensions[3].height=8
    COLS=["Opportunite","Lien","Type","UGFS eligible","Appel ouvert","Deadline","Actions","Responsable / Decision UGFS"]
    for c,h in enumerate(COLS,1):
        cell=ws.cell(4,c,h)
        cell.font=Font(name="Calibri",bold=True,size=11)
        cell.alignment=AC; cell.border=B
        cell.fill=PatternFill(start_color=GRIS_HDR,end_color=GRIS_HDR,fill_type="solid")
    ws.row_dimensions[4].height=35
    opps=[o for o in (opportunities or []) if getattr(o,"status",None)!="HISTORICAL"]
    opps=sorted(opps,key=lambda o:(getattr(o,"client_decision","") in ("NO_GO",),not((_days(o) or 999)<=21 and (_days(o) or 0)>=0),-(getattr(o,"score",0) or 0)))
    if not opps and historical: opps=list(historical)[:25]
    DR=5
    for i,opp in enumerate(opps):
        r=DR+i; bg=_row_color(opp)
        def W(col,val,bold=False,link=False,_r=r,_bg=bg):
            cell=ws.cell(_r,col,val)
            cell.font=Font(name="Calibri",bold=bold,size=11,color="0563C1" if link else "000000",underline="single" if link else None)
            cell.fill=PatternFill(start_color=_bg,end_color=_bg,fill_type="solid")
            cell.alignment=AL; cell.border=B
        url=getattr(opp,"url","") or ""
        W(1,getattr(opp,"title","") or "-",bold=True)
        W(2,url,link=bool(url.startswith("http")))
        if url.startswith("http"): ws.cell(r,2).hyperlink=url
        W(3,getattr(opp,"opportunity_type","") or getattr(opp,"theme","") or "-")
        W(4,_elig_str(opp))
        d=_days(opp)
        ouvert="oui" if (d is None or d>0) else "Cloture"
        if d is not None and 0<d<=7: ouvert="oui URGENT ("+str(d)+"j)"
        W(5,ouvert); W(6,_dl_str(opp)); W(7,_actions_str(opp)); W(8,_resp_str(opp))
        cl=max(len(getattr(opp,"eligibility_summary","") or ""),len(getattr(opp,"why_interesting","") or ""))
        ws.row_dimensions[r].height=max(50,min(150,15+cl//3))
    if opps:
        last=DR+len(opps)-1
        dv=DataValidation(type="list",formula1='"GO,NO_GO,BORDERLINE,SUBMITTED,En cours"',allow_blank=True)
        ws.add_data_validation(dv); dv.add("H"+str(DR)+":H"+str(last))
        ws.auto_filter.ref="A4:H"+str(last); ws.freeze_panes="A5"
    for col,w in {"A":35.3,"B":58.9,"C":41.4,"D":27.4,"E":18.6,"F":17.0,"G":34.1,"H":23.7}.items():
        ws.column_dimensions[col].width=w
    buf=io.BytesIO(); wb.save(buf); data=buf.getvalue()
    if output_path: Path(output_path).write_bytes(data)
    logger.info("excel_built",n=len(opps),kb=round(len(data)/1024,1))
    return data

ALL_OPPS_COLUMNS=["Opportunite","Lien","Type","UGFS eligible","Appel ouvert","Deadline","Actions","Responsable / Decision UGFS"]
