from __future__ import annotations
import re, zipfile, io
from datetime import date
from typing import Sequence
from fpdf import FPDF
from fpdf.enums import XPos, YPos
try:
    from src.config.logger import get_logger
    logger = get_logger(__name__)
except Exception:
    import logging; logger = logging.getLogger(__name__)

def _s(t):
    if not t: return ''
    for a,b in {'\u2014':'-','\u2013':'-','\u2019':"'",'\u2018':"'",'\u201c':'"','\u201d':'"','\u2022':'-','\u00b0':'','\u20ac':'EUR','\u2026':'...','\u00a0':' '}.items():
        t=t.replace(a,b)
    return t.encode('latin-1',errors='replace').decode('latin-1')

def _days(o):
    d=getattr(o,'deadline',None)
    if not d: return None
    return (d-date.today()).days

def _dl(o):
    d=getattr(o,'deadline',None)
    if d: return d.strftime("%d/%m/%Y")
    return _s(getattr(o,'deadline_text_raw',None) or 'Rolling')

def _safe_name(t):
    return re.sub(r'\s+','_',re.sub(r'[^\w\s-]','',t).strip())[:60]

def _strategy(o):
    vm=(getattr(o,'vehicle_match',None) or '').upper()
    geo=', '.join(getattr(o,'geographies',[]) or [])
    if 'TGF' in vm:
        return ("VEHICULE : Tunisia Green Fund (TGF)\n\nPositionnement :\n- Expertise UGFS en finance climatique Afrique du Nord / MENA\n- Accreditation GCF et track record mobilisation capital vert\n- Partenariats strategiques : GIZ, OSS, AFD, Adaptation Fund\n- Capacite a structurer des mecanismes blended finance\n\nArguments differenciants :\n- Seul gestionnaire de fonds climatiques base en Afrique du Nord\n- Connaissance fine du contexte reglementaire tunisien et MENA\n- Pipeline de projets identifies et en cours de structuration\n- Relations etablies avec autorites locales (APIA, ministeres)")
    if 'BLUE' in vm:
        return ("VEHICULE : Blue Bond UGFS\n\nPositionnement :\n- Expertise economie bleue et ressources marines\n- Position geographique Mediterranee + cotes africaines\n- Partenariats : OSS, SIFI, institutions maritimes\n- Alignement ODD 14 et 13 (Action climatique)\n\nArguments differenciants :\n- Vision integree eau/ocean/cotes en Afrique du Nord\n- Reseau experts locaux en gestion durable ressources marines\n- Capacite mobilisation co-investisseurs europeens (EIB, AFD)")
    if 'SEED' in vm:
        return ("VEHICULE : Seed of Change\n\nPositionnement :\n- Expertise PME agritech et food security en Afrique\n- Reseau partenaires : CFYE, GIZ agri\n- Deploiement tickets early-stage (100K-5M USD)\n- Impact emploi des jeunes et securite alimentaire\n\nArguments differenciants :\n- Pipeline PME identifiees dans filieres agri prioritaires\n- Due diligence locale rapide grace au reseau MENA\n- Co-investisseurs europeens mobilisables (KfW, AFD)")
    if 'NEW' in vm or 'ERA' in vm:
        return ("VEHICULE : NEW ERA Fund\n\nPositionnement :\n- Expertise investissement numerique et innovation Afrique-Europe\n- Pont strategique Tunis-Europe (hub digital emergent)\n- Co-investissements potentiels avec fonds Horizon Europe\n\nArguments differenciants :\n- Acces ecosystemes startup africains ET europeens\n- Capacite structuration tickets mid-size (500K-15M USD)\n- Reseau mentors et experts tech en Afrique du Nord")
    return f"POSITIONNEMENT GENERAL UGFS\n\nAsset manager africain expert en finance climatique et impact investing.\nPresence en Afrique du Nord (MENA), Afrique subsaharienne et Europe.\nVehicules : TGF | Blue Bond | Seed of Change | NEW ERA\nGeographies : {geo or 'Non precisee'}"

def _guide(o):
    why=_s(getattr(o,'why_interesting','') or '')
    elig=_s(getattr(o,'eligibility_summary','') or '')
    score=getattr(o,'score',0) or 0
    partners=getattr(o,'partners_mentioned',[]) or []
    days=_days(o)
    urg=f"ATTENTION : {days} jours restants - mobiliser l'equipe maintenant!\n\n" if days is not None and 0<days<=30 else ''
    part=f"Partenaires a contacter : {', '.join(partners[:5])}\n\n" if partners else ''
    return (f"{urg}1. PRESENTATION UGFS (1 page max)\n   - Gestionnaire actifs base Tunis, specialise finance climatique et impact investing\n   - Fonds : TGF, Blue Bond, Seed of Change, NEW ERA, Musanada\n   - Partenariats : GIZ, AFD, GCF, Adaptation Fund, OSS\n\n2. ALIGNEMENT STRATEGIQUE\n   {why if why else 'A completer selon criteres de l appel'}\n\n3. ELIGIBILITE\n   {elig if elig else 'Verifier et confirmer la conformite UGFS'}\n\n4. PROPOSITION TECHNIQUE\n   - Methodologie de gestion (selection, suivi)\n   - Instruments : blended finance, equity, quasi-equity\n   - Strategie impact et KPIs (emplois, tonnes CO2...)\n   - Pipeline de projets potentiels\n\n5. EQUIPE ET REFERENCES\n   - Profils des gerants principaux\n   - References de transactions comparables\n   - Temoignages partenaires si disponibles\n\n{part}6. CHECKLIST DOCUMENTS\n   [ ] Memorandum du fonds concerne\n   [ ] Comptes audites (2-3 derniers exercices)\n   [ ] Liste des investisseurs LPs\n   [ ] Politique ESG et Impact UGFS\n   [ ] Accreditations (GCF, APIA...)\n   [ ] Deck de presentation UGFS\n   [ ] Lettres de soutien partenaires (GIZ, AFD, OSS)\n   [ ] Pipeline de projets identifies\n\n7. ARGUMENTS DIFFERENCIANTS UGFS\n   + Seul asset manager climatique base en Afrique du Nord\n   + Double presence Afrique + Europe (Tunis = hub strategique)\n   + Score UGFS-Radar : {score}/100\n   + Equipe bilingue FR/EN, maitrise contexte local\n   + Capital patient, instruments adaptes marches emergents")

def generate_opportunity_pdf(o):
    title=_s(getattr(o,'title','') or 'Opportunite')
    url=_s(getattr(o,'url','') or '')
    score=getattr(o,'score',0) or 0
    vm=_s(getattr(o,'vehicle_match',None) or 'Non specifie')
    geo=_s(', '.join(getattr(o,'geographies',[]) or []) or 'Non specifie')
    summ=_s(getattr(o,'summary_executive','') or 'Non disponible')
    why=_s(getattr(o,'why_interesting','') or '')
    elig=_s(getattr(o,'eligibility_summary','') or '')
    prelim=_s(getattr(o,'preliminary_decision','') or 'PENDING')
    days=_days(o)
    pdf=FPDF()
    pdf.set_margins(18,22,18)
    pdf.set_auto_page_break(auto=True,margin=18)
    W=pdf.epw
    pdf.add_page()
    pdf.set_fill_color(31,56,100); pdf.set_text_color(255,255,255)
    pdf.set_font('Helvetica','B',13)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(W,9,title,fill=True)
    pdf.ln(3)
    sc_r,sc_g,sc_b=(146,208,80) if score>=70 else (255,153,0) if score>=50 else (192,0,0)
    pdf.set_fill_color(sc_r,sc_g,sc_b); pdf.set_text_color(255,255,255)
    pdf.set_font('Helvetica','B',11)
    pdf.set_x(pdf.l_margin)
    pdf.cell(44,8,f"SCORE: {score}/100",fill=True,new_x=XPos.RIGHT,new_y=YPos.TOP)
    pdf.set_fill_color(0,176,240)
    pdf.cell(60,8,f"Vehicule: {vm}",fill=True,new_x=XPos.RIGHT,new_y=YPos.TOP)
    if days is not None and 0<=days<=21:
        pdf.set_fill_color(192,0,0)
        pdf.cell(W-104,8,f"URGENT: {days} jours restants!",fill=True)
    pdf.ln(10)
    pdf.set_fill_color(220,220,220); pdf.set_text_color(0,0,0)
    pdf.set_font('Helvetica','B',10)
    pdf.set_x(pdf.l_margin)
    pdf.cell(W,7,'INFORMATIONS CLES',fill=True,new_x=XPos.LMARGIN,new_y=YPos.NEXT)
    pdf.ln(1)
    def kv(key,val,wk=48):
        pdf.set_font('Helvetica','B',10); pdf.set_text_color(31,56,100)
        pdf.set_x(pdf.l_margin)
        pdf.cell(wk,6,key+':',new_x=XPos.RIGHT,new_y=YPos.TOP)
        pdf.set_font('Helvetica','',10); pdf.set_text_color(0,0,0)
        pdf.multi_cell(W-wk,6,val)
    kv('Deadline',_dl(o))
    kv('Geographies',geo)
    kv('Source',url[:75] if url else 'Non disponible')
    kv('Recommandation',prelim)
    pdf.ln(4)
    def section(t,b):
        pdf.set_fill_color(220,220,220); pdf.set_text_color(0,0,0)
        pdf.set_font('Helvetica','B',10)
        pdf.set_x(pdf.l_margin)
        pdf.cell(W,7,t,fill=True,new_x=XPos.LMARGIN,new_y=YPos.NEXT)
        pdf.ln(1)
        pdf.set_font('Helvetica','',10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(W,5,b)
        pdf.ln(3)
    section('RESUME EXECUTIF',summ)
    if why: section("POURQUOI C'EST INTERESSANT POUR UGFS",why)
    if elig: section("CRITERES D'ELIGIBILITE",elig)
    pdf.add_page()
    pdf.set_fill_color(0,176,240); pdf.set_text_color(255,255,255)
    pdf.set_font('Helvetica','B',11)
    pdf.set_x(pdf.l_margin)
    pdf.cell(W,8,'POSITIONNEMENT STRATEGIQUE UGFS',fill=True,new_x=XPos.LMARGIN,new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_text_color(0,0,0); pdf.set_font('Helvetica','',10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(W,5,_strategy(o))
    pdf.add_page()
    pdf.set_fill_color(146,208,80); pdf.set_text_color(255,255,255)
    pdf.set_font('Helvetica','B',11)
    pdf.set_x(pdf.l_margin)
    pdf.cell(W,8,"GUIDE COMPLET DE REPONSE A L'APPEL D'OFFRES",fill=True,new_x=XPos.LMARGIN,new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_text_color(0,0,0); pdf.set_font('Helvetica','',10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(W,5,_guide(o))
    pdf.set_y(-18)
    pdf.set_font('Helvetica','I',8); pdf.set_text_color(128,128,128)
    pdf.set_x(pdf.l_margin)
    pdf.cell(W,6,f"UGFS-Radar - Document confidentiel - {date.today().strftime('%d/%m/%Y')}",align='C')
    fname=_safe_name(title)+'.pdf'
    return fname, bytes(pdf.output())

def build_pdfs_zip(opportunities, run_date=None):
    if run_date is None: run_date=date.today()
    qualified=sorted([o for o in opportunities if (getattr(o,'score',0) or 0)>=50 and getattr(o,'status',None)!='HISTORICAL'],key=lambda o:-(getattr(o,'score',0) or 0))
    buf=io.BytesIO(); names=[]
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as zf:
        for o in qualified:
            try:
                fn,data=generate_opportunity_pdf(o)
                zf.writestr(fn,data); names.append(fn)
                logger.info("pdf_ok",fn=fn)
            except Exception as e:
                logger.warning("pdf_fail",title=getattr(o,'title','')[:40],err=str(e))
    zb=buf.getvalue()
    logger.info("zip_done",n=len(names),kb=round(len(zb)/1024,1))
    return zb, names
