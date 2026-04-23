#!/usr/bin/env python3

"""
xmlmerge.py - Optimized for VeloTV
- Prunes data outside a 3-day window.
- Strips heavy metadata (desc, actors, producers) to stay under GitHub limits.
- Outputs directly to merged.xml.gz.
"""

import gzip
import os
import re
import sys
import yaml
import logging
import requests
import xml.sax.saxutils as saxutils
from datetime import datetime, timedelta, timezone
from lxml import etree
from urllib.parse import urlparse

# --- Configuration ---
updatetime    = 4                  # hours before cache refresh
trim          = True               # Set to True to enable date pruning
gzipped_out   = True               # Output should be gzipped
output_path   = '.'                # Root directory for easier GitHub Action access
cache_path    = 'cache'            # Cache directory
input_file    = 'xmlmerge.yaml'    # YAML source list
base_filename = 'epg.xml'          # Base filename

# Global data holders
output_channels = {}               
output_programs = {}               
seen_channel_ids = set()           

# Regex patterns
tz_pattern   = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_full     = re.compile(r'(\d+\.\d+e[+-]\d+)(?:\s*([+-]\d{4}))?$', re.IGNORECASE)
amp_pattern  = re.compile(r'&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def normalize_id(raw_id):
    return saxutils.unescape(raw_id).strip()

def read_yaml_input(path):
    try:
        with open(path, 'rt') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error("Error reading %s: %s", path, e); sys.exit(1)

def url_to_filename(url):
    parsed = urlparse(url)
    fname  = f"{parsed.netloc}{parsed.path}"
    return re.sub(r'[<>:"/\\\\|?*]', '_', fname) or 'default.xml'

def is_fresh(fname):
    now = datetime.now().timestamp()
    for suffix in ('', '.gz'):
        full = os.path.join(cache_path, fname + suffix)
        if os.path.exists(full) and os.path.getmtime(full) + updatetime*3600 > now:
            return full
    return None

def fetch_to_cache(url):
    try:
        resp = requests.get(url, timeout=60, headers={'User-Agent': 'VeloTV-Bot/1.0'})
        resp.raise_for_status()
        fname = url_to_filename(url)
        out = os.path.join(cache_path, fname + ('.gz' if not url.lower().endswith('.gz') else ''))
        os.makedirs(cache_path, exist_ok=True)
        with open(out, 'wb') as f:
            f.write(resp.content)
        return gzip.open(out, 'rt', encoding='utf-8', newline=None)
    except Exception as e:
        logger.error("Error fetching %s: %s", url, e); return None

def open_xml(source):
    if source.startswith(('http://','https://')):
        fname = url_to_filename(source)
        cached = is_fresh(fname)
        fh = gzip.open(cached, 'rt', encoding='utf-8', newline=None) if cached else fetch_to_cache(source)
    else:
        fh = gzip.open(source, 'rt', encoding='utf-8', newline=None) if source.endswith('.gz') else open(source, 'rt', encoding='utf-8')
    if fh is None: return None
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)
        return etree.parse(fh, parser).getroot()
    except Exception as e:
        logger.error("XML parse error in %s: %s", source, e); return None

def get_channels_programs(source):
    root = open_xml(source)
    if root is None: return
    
    # Pruning Window: Yesterday to +2 Days
    now_dt = datetime.now(timezone.utc)
    past_limit = now_dt - timedelta(days=1)
    future_limit = now_dt + timedelta(days=2)

    new_ch = pr_count = 0
    for elem in root:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid:
                norm_c = normalize_id(cid)
                if norm_c not in output_channels:
                    output_channels[norm_c] = elem
                    seen_channel_ids.add(cid)
                    new_ch += 1
        elif elem.tag == 'programme':
            ch = elem.get('channel')
            if not ch: continue
            
            # Prune by date
            try:
                st_dt = datetime.strptime(elem.get('start'), '%Y%m%d%H%M%S %z')
                if st_dt < past_limit or st_dt > future_limit: continue
            except: pass

            # Heavy Weight Loss: Remove non-essential tags
            for tag in ['desc', 'icon', 'actor', 'director', 'producer', 'category', 'episode-num']:
                for sub in elem.findall(tag):
                    elem.remove(sub)

            output_programs.setdefault(ch, []).append(elem)
            pr_count += 1
    logger.info("Processed %s: %d channels, %d programs", source, new_ch, pr_count)

def build_merged_tree():
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'VeloTV-Optimizer-2026')
    tv.set('generated-ts', str(int(datetime.now().timestamp())))
    for ch in output_channels.values(): tv.append(ch)
    for prog_list in output_programs.values():
        for prog in prog_list: tv.append(prog)
    return tv

def write_output(tv):
    out_file = os.path.join(output_path, base_filename + '.gz')
    # Write gzipped with high compression
    with gzip.open(out_file, 'wb', compresslevel=9) as f:
        etree.ElementTree(tv).write(f, xml_declaration=True, encoding='utf-8', pretty_print=False)
    logger.info("Final Size: %0.2f MB", os.path.getsize(out_file) / (1024*1024))

def xmlmerge():
    cfg = read_yaml_input(input_file)
    for src in cfg.get('files', []):
        get_channels_programs(src)
    merged = build_merged_tree()
    # Basic Cleanups
    for el in merged.iter():
        if isinstance(el.text, etree.CDATA): el.text = str(el.text)
        if el.text: el.text = amp_pattern.sub('&amp;', el.text)
    write_output(merged)

if __name__ == '__main__':
    xmlmerge()