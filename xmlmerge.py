#!/usr/bin/env python3
"""
xmlmerge.py

Merge multiple XMLTV EPG sources into a single, well-formed, normalized XMLTV file.

Includes fixes for:
 1. Correct channel de-duplication
 2. Escape special characters (ampersands, CDATA → text)
 3. Normalize timezone offsets to ±HHMM
 4. Prune programmes with invalid channel references
 5. Sanitize scientific-notation timestamps
 6. Fix chronological inversions (stop ≤ start)
 7. Final escape pass to ensure no raw '&' remain
"""

import gzip
import os
import re
import requests
import sys
import yaml
from datetime import datetime, timedelta
from lxml import etree
from urllib.parse import urlparse

# --- Configuration ---
updatetime     = 20               # hours before refreshing cache
trim           = False            # drop programmes older than now
gzipped_out    = True             # gzip final output
output_path    = 'output/'        # where to write merged file
cache_path     = 'cache/'         # where to cache inputs
input_file     = 'xmlmerge.yaml'  # YAML listing remote sources
base_filename  = 'merged.xml'     # merged file name ('.gz' appended)

# Global holders
output_channels = []              # list of <channel> elements
output_programs = {}              # dict: channel_id → list of <programme> elements
seen_channel_ids = set()          # for channel deduplication

# Regex patterns
tz_pattern   = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_pattern  = re.compile(r'\d+\.\d+e[+-]\d+', re.IGNORECASE)
amp_pattern  = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;)')

def read_yaml_input(path):
    """Load YAML file listing XMLTV source URLs or paths."""
    try:
        with open(path, 'rt') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        sys.exit(1)

def url_to_filename(url):
    """Convert a URL to a safe cache filename."""
    parsed = urlparse(url)
    fname = f"{parsed.netloc}{parsed.path}"
    return re.sub(r'[<>:"/\\|?*]', '_', fname) or 'default.xml'

def is_fresh(fname):
    """Return cached path if fresh (younger than updatetime), else None."""
    now = datetime.now().timestamp()
    for suffix in ('', '.gz'):
        full = cache_path + fname + suffix
        if os.path.exists(full) and os.path.getmtime(full) + updatetime*3600 > now:
            return full
    return None

def fetch_to_cache(url):
    """Download URL and write to cache, return file-handle for reading."""
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        fname = cache_path + url_to_filename(url)
        out = fname + ('' if url.lower().endswith('.gz') else '.gz')
        os.makedirs(cache_path, exist_ok=True)
        with open(out, 'wb') as f:
            f.write(resp.content)
        return gzip.open(out, 'rt', encoding='utf-8', newline=None)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def open_xml(source):
    """Parse and return root of XMLTV source (URL or local)."""
    if source.startswith(('http://', 'https://')):
        fname = url_to_filename(source)
        cached = is_fresh(fname)
        if cached:
            fh = gzip.open(cached, 'rt', encoding='utf-8', newline=None)
        else:
            fh = fetch_to_cache(source)
        print(f"{source} → {'cache' if cached else 'download'}")
    else:
        if source.endswith('.gz'):
            fh = gzip.open(source, 'rt', encoding='utf-8', newline=None)
        else:
            fh = open(source, 'rt', encoding='utf-8')
        print(f"Opening local {source}")
    if fh is None:
        return None
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)
        return etree.parse(fh, parser).getroot()
    except Exception as e:
        print(f"XML parse error in {source}: {e}")
        return None

def get_channels_programs(source):
    """
    Extract <channel> and <programme> elements from one source.
    Populates globals: output_channels, output_programs.
    """
    root = open_xml(source)
    if not root:
        return
    for elem in root:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid and cid not in seen_channel_ids:
                seen_channel_ids.add(cid)
                output_channels.append(elem)
        elif elem.tag == 'programme':
            ch = elem.get('channel')
            # optional trimming of old programmes
            if trim:
                stop = elem.get('stop')
                try:
                    dt = datetime.strptime(stop, '%Y%m%d%H%M%S %z')
                    if dt < datetime.now(dt.tzinfo):
                        continue
                except:
                    pass
            output_programs.setdefault(ch, []).append(elem)

def normalize_timezones(root):
    """Convert offsets ±H:MM or ±HH:MM to ±HHMM."""
    for prog in root.findall('programme'):
        for attr in ('start','stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                prog.set(attr, fixed)

def escape_specials(root):
    """Strip CDATA and escape & in attributes."""
    for el in root.iter():
        if isinstance(el.text, etree.CDATA):
            el.text = str(el.text)
        for a,v in list(el.attrib.items()):
            if '&' in v:
                el.attrib[a] = v.replace('&','&amp;')

def sanitize_timestamps(root):
    """Remove <programme> with scientific-notation timestamps."""
    for prog in list(root.findall('programme')):
        for attr in ('start','stop'):
            ts = prog.get(attr,'')
            if sci_pattern.search(ts):
                root.remove(prog)
                break

def fix_chronology(root):
    """
    Drop or adjust programmes where stop ≤ start.
    Here: remove those entries.
    """
    for prog in list(root.findall('programme')):
        try:
            s = datetime.strptime(prog.get('start'), '%Y%m%d%H%M%S %z')
            e = datetime.strptime(prog.get('stop'), '%Y%m%d%H%M%S %z')
            if e <= s:
                root.remove(prog)
        except:
            continue

def escape_ampersands(root):
    """Ensure no raw & remain in text nodes."""
    for el in root.iter():
        if el.text:
            el.text = amp_pattern.sub('&amp;', el.text)

def prune_invalid_programmes(root, valid_ids):
    """Remove programmes whose @channel not in valid channel IDs."""
    for prog in list(root.findall('programme')):
        if prog.get('channel') not in valid_ids:
            root.remove(prog)

def final_escape(root):
    """
    Serialize and parse to let lxml escape any remaining specials.
    Returns a new Element root.
    """
    xml_bytes = etree.tostring(root,
                               encoding='utf-8',
                               xml_declaration=True,
                               pretty_print=True)
    return etree.fromstring(xml_bytes)

def build_merged_tree():
    """Construct <tv> root, append channels and programmes, set metadata."""
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'mikhoul/XMLTV-EPG-Tools')
    tv.set('generated-ts', str(round(datetime.now().timestamp())))
    for ch in output_channels:
        tv.append(ch)
    for plist in output_programs.values():
        for prog in plist:
            tv.append(prog)
    return tv

def write_output(tv):
    """Write final <tv> to disk, gzipped if configured."""
    os.makedirs(output_path, exist_ok=True)
    out_file = output_path + base_filename + ('.gz' if gzipped_out else '')
    with (gzip.open(out_file,'wb') if gzipped_out else open(out_file,'wb')) as f:
        etree.ElementTree(tv).write(
            f,
            xml_declaration=True,
            encoding='utf-8',
            pretty_print=True
        )
    print(f"Wrote merged EPG: {out_file}")

def xmlmerge():
    cfg = read_yaml_input(input_file)
    for src in cfg.get('files', []):
        get_channels_programs(src)

    merged = build_merged_tree()
    normalize_timezones(merged)
    escape_specials(merged)
    sanitize_timestamps(merged)
    fix_chronology(merged)
    prune_invalid_programmes(merged, seen_channel_ids)
    escape_ampersands(merged)
    merged = final_escape(merged)
    write_output(merged)

if __name__ == '__main__':
    xmlmerge()
