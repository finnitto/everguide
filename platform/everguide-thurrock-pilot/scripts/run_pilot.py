from __future__ import annotations
import datetime as dt, json, re, zipfile
from pathlib import Path

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape, mapping
from shapely import make_valid, wkt

ROOT = Path(__file__).resolve().parents[1]
INPUTS, OUTPUTS = ROOT / 'inputs', ROOT / 'outputs'
INPUTS.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True)
ONS_QUERY = 'https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Local_Authority_Districts_DEC_2025_Boundaries_UK_BFE/FeatureServer/0/query'
THURROCK_CODE = 'E06000034'
GEOFABRIK_GPKG = 'https://download.geofabrik.de/europe/united-kingdom/england/essex-latest-free.gpkg.zip'
OVERTURE_STAC = 'https://stac.overturemaps.org/catalog.json'
HEADERS = {'User-Agent':'Everguide-Thurrock-Pilot/1.1 (independent data quality evaluation)'}
FUNERAL_RE = re.compile(r'funeral|undertak|mortuary|funeral[_ -]?(director|home|service|services|care|parlour|parlor)', re.I)
EXCLUDE_RE = re.compile(r'crematorium|cemetery|cemeteries|headstone|monument|embalming|florist|flower[_ -]?hire|stone[_ -]?cleaning|grave[_ -]?maintenance', re.I)
# Common Thurrock postcode districts. This is a screening rule, not an authoritative postcode geocoder.
THURROCK_POSTCODE_RE = re.compile(r'^(RM(?:15|16|17|18|19|20)|SS17)\b', re.I)

ADJACENT_RE = re.compile(r'celebrant|cemetery|cemeteries|crematorium|headstone|monument|embalming|florist|flower[_ -]?hire|stone[_ -]?cleaning|grave[_ -]?maintenance', re.I)
DIRECTOR_RE = re.compile(r'funeral|undertak|mortuary', re.I)

def get(url, **kwargs):
    r = requests.get(url, headers=HEADERS, timeout=(20, 180), **kwargs); r.raise_for_status(); return r

def download(url, path):
    if path.exists() and path.stat().st_size > 1024: return
    print(f'Downloading {url}')
    with get(url, stream=True) as r, path.open('wb') as f:
        for chunk in r.iter_content(1024*1024):
            if chunk: f.write(chunk)
    print(f'Downloaded {path.stat().st_size:,} bytes')

def boundary_load():
    p = INPUTS / 'thurrock_boundary.geojson'
    if p.exists():
        feat=json.loads(p.read_text(encoding='utf-8'))['features'][0]
        return make_valid(shape(feat['geometry'])), feat.get('properties',{})
    params={'where':f"LAD25CD='{THURROCK_CODE}'",'outFields':'*','returnGeometry':'true','outSR':'4326','f':'geojson'}
    data=get(ONS_QUERY,params=params).json()
    if data.get('error') or not data.get('features'): raise RuntimeError(f'ONS boundary query failed: {data}')
    feat=data['features'][0]; geom=make_valid(shape(feat['geometry']))
    p.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','properties':feat.get('properties',{}),'geometry':mapping(geom)}]}),encoding='utf-8')
    return geom,feat.get('properties',{})

def clean(v):
    if v is None: return ''
    try:
        if pd.isna(v): return ''
    except (TypeError,ValueError): pass
    s=str(v).strip()
    return '' if s.lower() in ('none','nan','null') else s

def parse_hstore(v):
    # Geofabrik GPKG may encode additional OSM tags as hstore-like text.
    s=clean(v); out={}
    if not s: return out
    for k,val in re.findall(r'"([^"\\]+)"\s*=>\s*"((?:[^"\\]|\\.)*)"',s): out[k]=val.replace('\\"','"')
    return out

def candidate_text(name, category, props):
    text=' '.join([clean(name),clean(category)] + [f'{k} {v}' for k,v in props.items()])
    text=re.sub(r'[_-]+',' ',text)
    return bool(FUNERAL_RE.search(text)) and not bool(EXCLUDE_RE.search(text))

def getval(d,*keys):
    for k in keys:
        x=clean(d.get(k))
        if x: return x
    return ''

def osm_extract(boundary):
    zpath=INPUTS/'essex-latest-free.gpkg.zip'; download(GEOFABRIK_GPKG,zpath)
    with zipfile.ZipFile(zpath) as z:
        gpkg=[n for n in z.namelist() if n.lower().endswith('.gpkg')]
        if not gpkg: raise RuntimeError('Geofabrik archive contains no GeoPackage')
        gpkg_path=INPUTS/Path(gpkg[0]).name
        if not gpkg_path.exists():
            z.extract(gpkg[0],INPUTS); extracted=INPUTS/gpkg[0]
            if extracted != gpkg_path: extracted.replace(gpkg_path)
    layer_names=gpd.list_layers(gpkg_path)['name'].tolist(); print('OSM layers:',', '.join(layer_names))
    rows=[]; diagnostics=[]
    for layer in layer_names:
        diag={'layer':layer,'records_read':0,'records_inside_thurrock':0,'named_records_inside':0,'funeral_keyword_matches':0,'excluded_adjacent_matches':0,'exported_candidates':0,'read_error':''}
        try: frame=gpd.read_file(gpkg_path,layer=layer)
        except Exception as e:
            diag['read_error']=str(e); print(f'Skipping unreadable OSM layer {layer}: {e}'); diagnostics.append(diag); continue
        diag['records_read']=len(frame)
        if frame.empty or frame.geometry.name not in frame or frame.crs is None:
            diagnostics.append(diag); continue
        frame=frame.to_crs(4326)
        try: frame=frame[frame.geometry.intersects(boundary)]
        except Exception as e:
            diag['read_error']=f'spatial filter: {e}'; print(f'Spatial filter skipped for {layer}: {e}'); diagnostics.append(diag); continue
        diag['records_inside_thurrock']=len(frame)
        for _,row in frame.iterrows():
            d=row.to_dict(); extras=parse_hstore(d.get('other_tags') or d.get('all_tags'))
            props={k:clean(v) for k,v in d.items() if k!='geometry' and clean(v)}; props.update(extras)
            name=getval(d,'name','name_en','official_name','alt_name') or extras.get('name','')
            category=getval(d,'fclass','type','shop','amenity','office','craft')
            if name: diag['named_records_inside']+=1
            alltext=' '.join([clean(name),clean(category)] + [f'{k} {v}' for k,v in props.items()])
            if DIRECTOR_RE.search(re.sub(r'[_-]+',' ',alltext)): diag['funeral_keyword_matches']+=1
            if ADJACENT_RE.search(re.sub(r'[_-]+',' ',alltext)):
                diag['excluded_adjacent_matches']+=1
                continue
            if not candidate_text(name,category,props): continue
            geom=d.get('geometry')
            if geom is None or geom.is_empty: continue
            point=geom if geom.geom_type=='Point' else geom.representative_point()
            postcode=getval(d,'addr_postcode','addr:postcode') or extras.get('addr:postcode','')
            address=' '.join(x for x in [getval(d,'addr_housenumber') or extras.get('addr:housenumber',''),getval(d,'addr_street') or extras.get('addr:street',''),getval(d,'addr_city') or extras.get('addr:city',''),postcode] if x)
            rows.append({'source':'OpenStreetMap','osm_id':getval(d,'osm_id','osm_way_id','osm_node_id','osm_relation_id'),'osm_layer':layer,'name':name,'category':category,'address':address,'postcode':postcode,'phone':getval(d,'phone','contact_phone') or extras.get('contact:phone',extras.get('phone','')),'website':getval(d,'website','contact_website') or extras.get('contact:website',extras.get('website','')),'latitude':point.y,'longitude':point.x,'tag_evidence_json':json.dumps(props,ensure_ascii=False),'licence':'OpenStreetMap contributors; ODbL 1.0; attribution required'})
            diag['exported_candidates']+=1
        diagnostics.append(diag)
    pd.DataFrame(diagnostics).to_csv(OUTPUTS/'osm_layer_diagnostics.csv',index=False)
    print('OSM diagnostic totals:', {k:sum(int(x.get(k,0) or 0) for x in diagnostics) for k in ('records_read','records_inside_thurrock','named_records_inside','funeral_keyword_matches','excluded_adjacent_matches','exported_candidates')})
    df=pd.DataFrame(rows)
    if not df.empty: df=annotate(df,'osm')
    return df

def latest_release():
    cat=get(OVERTURE_STAC).json(); return cat.get('latest') or '2026-10-21.0'

def json_load(s):
    if isinstance(s,(dict,list)): return s
    try: return json.loads(s) if clean(s) else []
    except Exception: return []

def first_value(raw,keys):
    obj=json_load(raw)
    if not isinstance(obj,list): obj=[obj]
    for item in obj:
        if isinstance(item,str) and item.strip(): return item.strip()
        if isinstance(item,dict):
            for k in keys:
                v=clean(item.get(k))
                if v: return v
            # Address objects sometimes expose components rather than freeform.
            if any(k in item for k in ('house_number','street','locality','postcode')):
                return ' '.join(clean(item.get(k)) for k in ('house_number','street','locality','postcode') if clean(item.get(k)))
    return ''

def overture_extract(boundary,release):
    minx,miny,maxx,maxy=boundary.bounds
    import duckdb
    con=duckdb.connect(); con.execute('INSTALL spatial; LOAD spatial;'); con.execute('INSTALL httpfs; LOAD httpfs;')
    # Overture's public S3 bucket can respond slowly to prefix listings.
    con.execute("SET s3_region='us-west-2';")
    con.execute('SET http_timeout=300;')
    con.execute('SET http_retries=10;')
    path=f's3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*'
    sql='''SELECT id,version,names.primary AS name,basic_category,taxonomy.primary AS taxonomy_primary,confidence,
      to_json(addresses) AS addresses_json,to_json(phones) AS phones_json,to_json(websites) AS websites_json,
      to_json(emails) AS emails_json,to_json(sources) AS sources_json,ST_AsText(geometry) AS wkt,
      ST_X(ST_PointOnSurface(geometry)) AS longitude,ST_Y(ST_PointOnSurface(geometry)) AS latitude
      FROM read_parquet(?) WHERE bbox.xmax>=? AND bbox.xmin<=? AND bbox.ymax>=? AND bbox.ymin<=?'''
    try:
        raw=con.execute(sql,[path,minx,maxx,miny,maxy]).df()
    except Exception as exc:
        con.close()
        raise RuntimeError(
            'Overture could not be read from its public S3 bucket after extended '
            'timeouts/retries. This is usually a network/proxy path issue; OSM '
            'results, if already exported, are retained. Retry with --skip-osm '
            'to run only Overture. Original error: ' + str(exc)
        ) from exc
    con.close()
    rows=[]
    for _,r in raw.iterrows():
        try:
            geom=wkt.loads(r['wkt'])
            if not geom.intersects(boundary): continue
        except Exception: continue
        name=clean(r.get('name')); cat=clean(r.get('taxonomy_primary')) or clean(r.get('basic_category'))
        # Include explicit funeral taxonomy even if the primary name is sparse.
        if not candidate_text(name,cat,{'basic_category':clean(r.get('basic_category'))}): continue
        address=first_value(r.get('addresses_json'),['freeform','address'])
        postcode=first_value(r.get('addresses_json'),['postcode'])
        rows.append({'source':'Overture Places','gers_id':clean(r.get('id')),'version':clean(r.get('version')),'name':name,'basic_category':clean(r.get('basic_category')),'taxonomy_primary':cat,'confidence':r.get('confidence'),'address':address,'postcode':postcode,'phone':first_value(r.get('phones_json'),['value','phone','number']),'website':first_value(r.get('websites_json'),['value','url','website']),'email':first_value(r.get('emails_json'),['value','email']),'latitude':r.get('latitude'),'longitude':r.get('longitude'),'addresses_json':clean(r.get('addresses_json')),'phones_json':clean(r.get('phones_json')),'websites_json':clean(r.get('websites_json')),'sources_json':clean(r.get('sources_json')),'licence_note':'Inspect sources_json and confirm applicable upstream licence before reuse'})
    df=pd.DataFrame(rows)
    if not df.empty: df=annotate(df,'overture')
    return df

def normalize_name(s): return re.sub(r'[^a-z0-9]+',' ',clean(s).lower()).strip()
def annotate(df,source):
    df=df.copy(); df['postcode_check']='missing'
    for i,row in df.iterrows():
        pc=clean(row.get('postcode')).upper().replace(' ','')
        if pc:
            outward=pc[:-3] if len(pc)>3 else pc
            df.at[i,'postcode_check']='consistent_area_prefix' if THURROCK_POSTCODE_RE.match(outward) else 'review_postcode_vs_coordinates'
    df['name_normalized']=df['name'].map(normalize_name)
    # Possible duplicate hint only; preserve all source rows.
    df['possible_duplicate_key']=df.apply(lambda r: (normalize_name(r.get('name'))+'|'+clean(r.get('postcode')).upper().replace(' ','') if clean(r.get('postcode')) else normalize_name(r.get('name'))+'|'+str(round(float(r.get('latitude') or 0),3))+'|'+str(round(float(r.get('longitude') or 0),3))),axis=1)
    df['possible_duplicate_count']=df.groupby('possible_duplicate_key')['possible_duplicate_key'].transform('count')
    df['possible_duplicate']=df['possible_duplicate_count']>1
    return df

def candidate_class(name, category, props=None):
    text=re.sub(r'[_-]+',' ',' '.join([clean(name),clean(category)] + [f'{k} {v}' for k,v in (props or {}).items()])).lower()
    if re.search(r'celebrant|cemetery|cemeteries|crematorium|headstone|monument|embalming|florist|flower hire|stone cleaning|grave maintenance',text): return 'adjacent_service_review'
    if re.search(r'funeral|undertak|mortuary',text): return 'likely_funeral_director_candidate'
    return 'other_review'

def write_candidate_class_summary(osm, ov):
    frames=[]
    for source,df in [('OpenStreetMap',osm),('Overture Places',ov)]:
        if df is None or df.empty: continue
        for _,r in df.iterrows():
            frames.append({'source':source,'name':clean(r.get('name')),'category':clean(r.get('category')) or clean(r.get('taxonomy_primary')) or clean(r.get('basic_category')),'candidate_class':candidate_class(r.get('name'),r.get('category') or r.get('taxonomy_primary') or r.get('basic_category'))})
    cols=['source','candidate_class','record_count']
    if frames:
        out=pd.DataFrame(frames).groupby(['source','candidate_class']).size().reset_index(name='record_count')
    else: out=pd.DataFrame(columns=cols)
    out.to_csv(OUTPUTS/'candidate_class_summary.csv',index=False)

def pct(series):
    if len(series)==0:return 0.0
    return round(100*series.map(lambda x:bool(clean(x))).mean(),1)
def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--skip-osm',action='store_true'); ap.add_argument('--skip-overture',action='store_true'); args=ap.parse_args()
    started=dt.datetime.now(dt.timezone.utc); print('Loading official Thurrock boundary...'); boundary,props=boundary_load(); summaries=[]; release=None
    if not args.skip_osm:
        print('Extracting OSM features...'); osm=osm_extract(boundary); osm.to_csv(OUTPUTS/'osm_candidates.csv',index=False)
        summaries.append({'source':'OpenStreetMap','candidate_records':len(osm),'address_coverage_pct':pct(osm.get('address',pd.Series(dtype=str))),'postcode_coverage_pct':pct(osm.get('postcode',pd.Series(dtype=str))),'phone_coverage_pct':pct(osm.get('phone',pd.Series(dtype=str))),'website_coverage_pct':pct(osm.get('website',pd.Series(dtype=str))),'postcode_review_count':int(osm.get('postcode_check',pd.Series(dtype=str)).eq('review_postcode_vs_coordinates').sum()),'possible_duplicate_rows':int(osm.get('possible_duplicate',pd.Series(dtype=bool)).sum())})
    if not args.skip_overture:
        release=latest_release(); print(f'Querying Overture Places release {release}...'); ov=overture_extract(boundary,release); ov.to_csv(OUTPUTS/'overture_candidates.csv',index=False)
        summaries.append({'source':'Overture Places','candidate_records':len(ov),'address_coverage_pct':pct(ov.get('address',pd.Series(dtype=str))),'postcode_coverage_pct':pct(ov.get('postcode',pd.Series(dtype=str))),'phone_coverage_pct':pct(ov.get('phone',pd.Series(dtype=str))),'website_coverage_pct':pct(ov.get('website',pd.Series(dtype=str))),'postcode_review_count':int(ov.get('postcode_check',pd.Series(dtype=str)).eq('review_postcode_vs_coordinates').sum()),'possible_duplicate_rows':int(ov.get('possible_duplicate',pd.Series(dtype=bool)).sum())})
    summary=pd.DataFrame(summaries); summary.to_csv(OUTPUTS/'source_summary.csv',index=False)
    write_candidate_class_summary(locals().get('osm',pd.DataFrame()),locals().get('ov',pd.DataFrame()))
    meta={'pilot':'Everguide Thurrock Geographic Discovery Pilot v2.6.3','started_utc':started.isoformat(),'completed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'boundary_source':'ONS Local Authority Districts December 2025 Boundaries UK BFE','boundary_code':THURROCK_CODE,'boundary_name':props.get('LAD25NM') or 'Thurrock','boundary_bbox_wgs84':boundary.bounds,'overture_release':release,'osm_extract':'Geofabrik Essex latest-free.gpkg.zip','google_places':'Not queried'}
    (OUTPUTS/'run_metadata.json').write_text(json.dumps(meta,indent=2,default=str),encoding='utf-8')
    report=['# Everguide Thurrock Geographic Discovery Pilot v2.6.3','',f"Completed: {meta['completed_utc']}",'Boundary: Thurrock (E06000034), ONS December 2025 full-resolution local-authority boundary.','','## Results','',summary.to_markdown(index=False) if not summary.empty else 'No extracts run.','','## OSM diagnostics','', 'Per-layer counts are provided in osm_layer_diagnostics.csv, including read, geographic, named, keyword and exported counts.','', '## Candidate classification','', 'candidate_class_summary.csv groups exported candidates into likely funeral director candidates and adjacent-service review records. These remain unverified.','', '## Quality controls','', '- Overture nested properties are serialized as valid JSON and flattened into address, postcode, phone and website columns.','- All records are retained; possible duplicates are flagged, not silently deleted.','- Postcode prefixes outside the common Thurrock RM15–RM20 and SS17 range are flagged for manual coordinate/postcode review. This is a screening heuristic, not definitive geocoding.','- OSM filtering normalizes underscores/hyphens and inspects both regular fields and parsed hstore tags.','','## Interpretation','', '- Candidate records are not verified providers or branches.','- OSM and Overture remain separate source datasets.','- OSM-derived data remains subject to ODbL attribution/share-alike obligations.','- Overture upstream source licences must be checked per record using sources_json.','- No Google Places data is queried, stored or used.','- No Everguide production database is accessed or changed.','','## Limitations','', '- Name/category rules can miss unusual records or include false positives.','- Postcode-area checks identify obvious anomalies but cannot validate a precise address.','- Review official provider websites and independent evidence before any provider/branch creation.']
    (OUTPUTS/'pilot_report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print('\nPilot complete. Outputs:'); [print(f' - {p.name} ({p.stat().st_size:,} bytes)') for p in sorted(OUTPUTS.iterdir())]
if __name__=='__main__': main()
