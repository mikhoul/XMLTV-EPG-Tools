#!/usr/bin/env python3
import gzip, os, re, sys, yaml, logging, requests
import xml.sax.saxutils as saxutils
from datetime import datetime, timedelta, timezone
from lxml import etree
from urllib.parse import urlparse

# --- CONFIG ---
updatetime    = 4
gzipped_out   = True
output_path   = '.'
cache_path    = 'cache'
input_file    = 'xmlmerge.yaml'
base_filename = 'epg.xml'

# Global Holders
output_channels = {}
output_programs = {}
seen_channel_ids = set()

# Regex
tz_pattern  = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_full    = re.compile(r'(\d+\.\d+e[+-]\d+)(?:\s*([+-]\d{4}))?$', re.IGNORECASE)
amp_pattern = re.compile(r'&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def normalize_id(raw_id):
    return saxutils.unescape(raw_id).strip()

def fetch_to_cache(url):
    try:
        resp = requests.get(url, timeout=60, headers={'User-Agent': 'VeloTV-Bot/1.0'})
        resp.raise_for_status()
        fname = re.sub(r'[<>:"/\\\\|?*]', '_', urlparse(url).netloc + urlparse(url).path)
        out = os.path.join(cache_path, fname + ('.gz' if not url.lower().endswith('.gz') else ''))
        os.makedirs(cache_path, exist_ok=True)
        with open(out, 'wb') as f: f.write(resp.content)
        return gzip.open(out, 'rt', encoding='utf-8')
    except: return None

def open_xml(source):
    if source.startswith('http'):
        fh = fetch_to_cache(source)
    else:
        fh = gzip.open(source, 'rt', encoding='utf-8') if source.endswith('.gz') else open(source, 'rt', encoding='utf-8')
    if not fh: return None
    try:
        return etree.parse(fh, etree.XMLParser(recover=True, huge_tree=True)).getroot()
    except: return None

def get_channels_programs(source):
    root = open_xml(source)
    if root is None: return

    # --- THE CRITICAL WINDOW: Strike the extra days ---
    now_dt = datetime.now(timezone.utc)
    # Keeping only 12 hours past and 36 hours future (Total 48h Window)
    # This is the "sweet spot" to keep full descriptions under 100MB
    past_limit = now_dt - timedelta(hours=12)
    future_limit = now_dt + timedelta(hours=36)

    for elem in root:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid:
                norm_c = normalize_id(cid)
                if norm_c not in output_channels:
                    output_channels[norm_c] = elem
                    seen_channel_ids.add(cid)
        elif elem.tag == 'programme':
            ch = elem.get('channel')
            if not ch: continue
            try:
                st_dt = datetime.strptime(elem.get('start'), '%Y%m%d%H%M%S %z')
                if st_dt < past_limit or st_dt > future_limit:
                    continue # PRUNING BY DAY ONLY
            except: pass
            
            # NO STRIPPING HERE - Keeping desc, credits, etc.
            output_programs.setdefault(ch, []).append(elem)

def build_merged_tree():
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'VeloTV-HD-Optimizer')
    for ch in output_channels.values(): tv.append(ch)
    for prog_list in output_programs.values():
        for prog in prog_list: tv.append(prog)
    return tv

def write_output(tv):
    out_file = os.path.join(output_path, base_filename + '.gz')
    with gzip.open(out_file, 'wb', compresslevel=9) as f:
        etree.ElementTree(tv).write(f, xml_declaration=True, encoding='utf-8', pretty_print=False)
    logger.info("Final Size: %0.2f MB", os.path.getsize(out_file) / 1024 / 1024)

def xmlmerge():
    cfg = yaml.safe_load(open(input_file))
    for src in cfg.get('files', []): get_channels_programs(src)
    merged = build_merged_tree()
    write_output(merged)

if __name__ == '__main__':
    xmlmerge()