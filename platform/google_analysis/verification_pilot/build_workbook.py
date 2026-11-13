"""Create a formatted Excel workbook from the pilot CSV review registers."""
from pathlib import Path
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).parent

def load_csv(name):
    with (ROOT / name).open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def add_table(ws, title, rows):
    if not rows:
        return
    headers = list(rows[0].keys())
    ws.append(headers)
    for r in rows: ws.append([r.get(h, '') for h in headers])
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='243B53')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    ws.row_dimensions[1].height = 34
    for col_idx, h in enumerate(headers, 1):
        vals = [str(ws.cell(r, col_idx).value or '') for r in range(2, min(ws.max_row, 30)+1)]
        width = min(max(14, len(h)+2, max((len(v) for v in vals), default=0)//2), 42)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    if ws.max_row >= 2:
        ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
        safe = ''.join(ch for ch in title if ch.isalnum())[:20]
        tab = Table(displayName=safe, ref=ref)
        tab.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True, showColumnStripes=False)
        ws.add_table(tab)
    ws.sheet_view.showGridLines = False

def add_dropdown(ws, column_name, values):
    headers = [c.value for c in ws[1]]
    if column_name not in headers: return
    col = get_column_letter(headers.index(column_name)+1)
    dv = DataValidation(type='list', formula1='"' + ','.join(values) + '"', allow_blank=True)
    dv.error = 'Choose a value from the list.'; dv.errorTitle = 'Invalid review status'
    dv.prompt = 'Select a review status; leave pending until evidence has been assessed.'
    ws.add_data_validation(dv); dv.add(f'{col}2:{col}1000')

wb = Workbook()
ws = wb.active; ws.title = 'Start Here'; ws.sheet_view.showGridLines = False
intro = [
 ['EVERGUIDE · THURROCK VERIFICATION PILOT'],
 ['Purpose', 'Human review of candidate providers and possible operating branches. This workbook is not a publication or import approval.'],
 ['Scope', '16 Overture candidate observations; 13 funeral-director candidate rows; 9 suggested provider groups (one held for location conflict).'],
 ['Critical rule', 'A point inside the Thurrock boundary is not proof of an operating funeral home. A source confidence score is not verification.'],
 ['Step 1', 'Resolve source licence/retention permission before operational reuse or publication of source-derived data.'],
 ['Step 2', 'Verify provider activity using the provider’s own official website and other appropriate authoritative evidence. Record every source in Evidence Log.'],
 ['Step 3', 'Verify each branch separately: real public-facing operating location, full address/postcode, current contact details and relationship to provider.'],
 ['Step 4', 'Record decisions and reasons in Decision Log. Keep unresolved conflicts as needs_more_evidence; do not guess.'],
 ['Step 5', 'Only candidates with sufficient evidence and approved source basis may move to a separately authorised provider/branch setup process.'],
 ['Not permitted', 'Do not use Google Places business details as a data source for this register. Do not automatically merge, delete, create or publish records.'],
 ['Data note', 'The original Overture quality review is retained as source context. Check upstream dataset terms and source-level licence notes before reuse.'],
 ['Statuses', 'not_checked / pending are the initial values. They are intentionally not pre-approved.'],
]
for row in intro: ws.append(row)
ws.merge_cells('A1:B1'); ws['A1'].font=Font(bold=True,size=16,color='FFFFFF'); ws['A1'].fill=PatternFill('solid',fgColor='243B53'); ws['A1'].alignment=Alignment(vertical='center')
ws.row_dimensions[1].height=32
for r in range(2,ws.max_row+1):
    ws.cell(r,1).font=Font(bold=True,color='243B53')
    ws.cell(r,1).fill=PatternFill('solid',fgColor='EAF0F6')
    ws.cell(r,2).alignment=Alignment(wrap_text=True,vertical='top')
    ws.row_dimensions[r].height=42
ws.column_dimensions['A'].width=22; ws.column_dimensions['B'].width=115

for name, title in [('Provider Review','ProviderReview'),('Branch Review','BranchReview'),('Evidence Log','EvidenceLog'),('Decision Log','DecisionLog')]:
    datafile = {'Provider Review':'provider_verification_register.csv','Branch Review':'branch_verification_register.csv','Evidence Log':'evidence_log.csv','Decision Log':'decision_log.csv'}[name]
    sh = wb.create_sheet(name)
    rows = load_csv(datafile)
    if rows: add_table(sh, title, rows)
    else:
        with (ROOT/datafile).open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
        sh.append(headers)
        for c in sh[1]:
            c.font = Font(bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor='243B53')
            c.alignment = Alignment(wrap_text=True, vertical='center')
        sh.freeze_panes = 'A2'
        sh.auto_filter.ref = sh.dimensions
        for idx, h in enumerate(headers, 1):
            sh.column_dimensions[get_column_letter(idx)].width = min(max(16, len(h)+2), 38)
    if name == 'Provider Review':
        add_dropdown(sh,'source_licence_status',['pending_review','approved_for_internal_review','approved_for_operational_use','not_permitted','unclear_seek_advice'])
        add_dropdown(sh,'service_activity_status',['not_checked','confirmed_funeral_director','related_service_only','not_funeral_director','unclear'])
        add_dropdown(sh,'trading_status',['not_checked','appears_trading','confirmed_trading','ceased_or_dissolved','unclear'])
        add_dropdown(sh,'provider_identity_status',['not_checked','confirmed','possible_parent_or_group','conflicting_identity','unclear'])
        add_dropdown(sh,'official_website_status',['not_checked','confirmed_official','not_official','unavailable','unclear'])
        add_dropdown(sh,'provider_decision',['pending','verified_ready_for_setup','needs_more_evidence','reject_not_funeral_director','reject_not_trading','exclude_source_licence'])
    elif name == 'Branch Review':
        add_dropdown(sh,'branch_operating_status',['not_checked','confirmed_public_branch','registered_office_only','mailing_or_admin_address','closed','unclear'])
        add_dropdown(sh,'address_verification_status',['not_checked','confirmed_official_source','confirmed_independent_source','conflicting','not_found'])
        add_dropdown(sh,'postcode_verification_status',['not_checked','confirmed','conflict','invalid_or_missing'])
        add_dropdown(sh,'telephone_verification_status',['not_checked','confirmed_official_source','confirmed_by_call','conflicting','not_found'])
        add_dropdown(sh,'branch_identity_status',['not_checked','confirmed_linked_to_provider','possible_branch','different_provider','unclear'])
        add_dropdown(sh,'branch_decision',['pending','verified_operating_branch','needs_more_evidence','reject_not_operating_branch','duplicate_observation','address_conflict'])
    elif name == 'Evidence Log':
        add_dropdown(sh,'entity_type',['provider','branch','source_licence'])
        add_dropdown(sh,'evidence_type',['official_provider_website','official_branch_page','companies_house','direct_phone_confirmation','local_authority_or_ons','postcode_address_reference','independent_reputable_source','source_licence_terms','other'])
        add_dropdown(sh,'strength',['strong','moderate','weak','conflicting'])
    elif name == 'Decision Log':
        add_dropdown(sh,'entity_type',['provider','branch','source_licence'])
        add_dropdown(sh,'decision',['verified','needs_more_evidence','rejected','duplicate_observation','excluded_due_to_licence','deferred'])
    sh.sheet_view.showGridLines = False

standards = wb.create_sheet('Evidence Standards'); standards.sheet_view.showGridLines=False
standards.append(['Claim to verify','Preferred evidence','Insufficient on its own','Record / caution'])
standards_rows = [
 ['Funeral director activity','Provider’s own current website describing funeral arranging/director services; corroborating direct confirmation where needed','Broad taxonomy label, business name, Overture confidence score','Separate funeral directing from celebrants, cemeteries, memorial/masonry and comparison directories'],
 ['Currently trading','Current official site/contact details plus recent direct confirmation or other credible current evidence','Companies House active status alone; an old directory page','Record date checked; do not infer from a functioning domain alone'],
 ['Provider identity','Official website legal/trading identity, Companies House details where applicable, consistent official contact details','Shared domain alone or a name similarity score','Distinguish parent/group from trading name and local operator'],
 ['Operating branch','Official branch/location page or direct confirmation that the address is a public-facing funeral home','Registered office, PO box, cemetery, residence, map pin alone','Branch is separate from provider; verify each address individually'],
 ['Address and postcode','Official branch source plus reliable postcode/address reference; reconcile coordinates if used','Point-in-polygon alone or postcode prefix alone','Record all conflicts; do not silently correct source values'],
 ['Telephone','Official branch contact page or direct call confirmation','Number copied from a third-party aggregator','Preserve raw and normalized number; record verification date'],
 ['Source licence','Upstream dataset terms and source-specific licence metadata; permission record if needed','Assuming open access from the word “Overture” or from the presence of a licence_note field','No external publication/reuse until cleared'],
]
for r in standards_rows: standards.append(r)
for c in standards[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='243B53'); c.alignment=Alignment(wrap_text=True)
for row in standards.iter_rows(min_row=2):
    for c in row: c.alignment=Alignment(wrap_text=True,vertical='top')
for col,w in {'A':28,'B':70,'C':58,'D':64}.items(): standards.column_dimensions[col].width=w
for i in range(2,standards.max_row+1): standards.row_dimensions[i].height=72
standards.freeze_panes='A2'; standards.auto_filter.ref=standards.dimensions

out = ROOT / 'thurrock_verification_workbook.xlsx'
wb.save(out)
print(out)
