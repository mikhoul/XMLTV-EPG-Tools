#!/usr/bin/env python3
import gzip, os, re, sys, yaml, logging, requests
from datetime import datetime, timedelta, timezone
from lxml import etree
from urllib.parse import urlparse

# --- CONFIG ---
output_path   = '.'
cache_path    = 'cache'
input_file    = 'xmlmerge.yaml'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

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

def generate_daily_epg(date_target, all_channels, all_progs):
    """Generates a single XMLTV file for a specific date."""
    filename = f"{date_target.strftime('%d-%m-%Y')}.xml.gz"

    # 1. Skip if file already exists
    if os.path.exists(filename):
        logger.info(f"Skipping {filename}, already exists.")
        return
    
    logger.info(f"Generating {filename}...")
    
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'VeloTV-Daily-Splitter')
    
    # Add all channels
    for ch in all_channels.values():
        tv.append(ch)
        
    # Add programmes matching this date
    date_str = date_target.strftime('%Y%m%d')
    for ch_id in all_progs:
        for prog in all_progs[ch_id]:
            if prog.get('start')[:8] == date_str:
                tv.append(prog)

    with gzip.open(filename, 'wb', compresslevel=9) as f:
        etree.ElementTree(tv).write(f, xml_declaration=True, encoding='utf-8', pretty_print=False)

def xmlmerge():
    cfg = yaml.safe_load(open(input_file))
    all_channels = {}
    all_progs = {}

    # Load all data into memory first
    for src in cfg.get('files', []):
        root = open_xml(src)
        if root is None: continue
        for elem in root:
            if elem.tag == 'channel':
                cid = elem.get('id')
                if cid and cid not in all_channels:
                    all_channels[cid] = elem
            elif elem.tag == 'programme':
                ch = elem.get('channel')
                if ch:
                    all_progs.setdefault(ch, []).append(elem)

    # Generate files for Yesterday, Today, and Tomorrow
    now = datetime.now(timezone.utc)
    dates_to_gen = [now - timedelta(days=1), now, now + timedelta(days=1)]
    
    for d in dates_to_gen:
        generate_daily_epg(d, all_channels, all_progs)

if __name__ == '__main__':
    xmlmerge()
