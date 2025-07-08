#!/usr/bin/env python3
"""
xmlmerge.py

Merge multiple XMLTV EPG sources into a single, well-formed, normalized XMLTV file.
Includes fixes for:
 1. Adding the DOCTYPE declaration for schema validation
 2. Adding the generator-info-url attribute for provenance
 3. Converting scientific-notation timestamps into fixed-width strings
 4. Other normalization and validation routines
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
updatetime     = 20               # hours before cache refresh
trim           = False            # drop programmes older than now
gzipped_out    = True             # gzip output
output_path    = 'output/'        # output directory
cache_path     = 'cache/'         # cache directory
input_file     = 'xmlmerge.yaml'  # YAML source list
base_filename  = 'merged.xml'     # output filename base

# Global data holders
output_channels = []              # list of <channel> elements
output_programs = {}              # dict: channel_id -> list of <programme>
seen_channel_ids = set()          # for deduplication

# Regex patterns
tz_pattern    = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_full      = re.compile(r'(\d+\.\d+e[+-]\d+)(?:\s*([+-]\d{4}))?$', re.IGNORECASE)
amp_pattern   = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;)')

def read_yaml_input(path):
    """Load YAML configuration file."""
    try:
        with open(path, 'rt') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        sys.exit(1)

def url_to_filename(url):
    """Convert URL to safe filename for caching."""
    parsed = urlparse(url)
    fname = f"{parsed.netloc}{parsed.path}"
    return re.sub(r'[<>:"/\\|?*]', '_', fname) or 'default.xml'

def is_fresh(fname):
    """Check if cache file is fresh based on modification time."""
    now = datetime.now().timestamp()
    for suffix in ('', '.gz'):
        full = cache_path + fname + suffix
        if os.path.exists(full) and os.path.getmtime(full) + updatetime*3600 > now:
            return full
    return None

def fetch_to_cache(url):
    """Download URL content and cache it."""
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
    """Open and parse XMLTV source from URL or local file."""
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
    """Extract channels and programmes from source, populate globals."""
    root = open_xml(source)
    if root is None:
        return
    for elem in root:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid and cid not in seen_channel_ids:
                seen_channel_ids.add(cid)
                output_channels.append(elem)
        elif elem.tag == 'programme':
            ch = elem.get('channel')
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
        for attr in ('start', 'stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                prog.set(attr, fixed)

def normalize_exponents(root):
    """Convert scientific notation timestamps to fixed-width strings."""
    for prog in root.findall('programme'):
        for attr in ('start', 'stop'):
            val = prog.get(attr, '')
            m = sci_full.match(val)
            if m:
                float_ts, offset = m.groups()
                ts_int = int(float(float_ts))
                ts_str = f"{ts_int:014d}"
                prog.set(attr, ts_str + (offset or ''))

def escape_specials(root):
    """Strip CDATA and escape '&' in attributes."""
    for el in root.iter():
        if isinstance(el.text, etree.CDATA):
            el.text = str(el.text)
        for a, v in list(el.attrib.items()):
            if '&' in v:
                el.attrib[a] = v.replace('&', '&amp;')

def fix_chronology(root):
    """Remove programmes where stop ≤ start."""
    for prog in list(root.findall('programme')):
        try:
            s = datetime.strptime(prog.get('start'), '%Y%m%d%H%M%S %z')
            e = datetime.strptime(prog.get('stop'), '%Y%m%d%H%M%S %z')
            if e <= s:
                root.remove(prog)
        except:
            continue

def escape_ampersands(root):
    """Ensure no raw '&' in text nodes."""
    for el in root.iter():
        if el.text:
            el.text = amp_pattern.sub('&amp;', el.text)

def prune_invalid_programmes(root, valid_ids):
    """Remove programmes with invalid channel references."""
    for prog in list(root.findall('programme')):
        if prog.get('channel') not in valid_ids:
            root.remove(prog)

def final_escape(root):
    """Serialize and parse to normalize escaping."""
    xml_bytes = etree.tostring(
        root,
        encoding='utf-8',
        xml_declaration=True,
        pretty_print=True
    )
    return etree.fromstring(xml_bytes)

def build_merged_tree():
    """Create <tv> root, append channels and programmes, set metadata."""
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'mikhoul/XMLTV-EPG-Tools')
    # Use integer timestamp to avoid scientific notation
    tv.set('generated-ts', str(int(datetime.now().timestamp())))
    # Add the generator-info-url attribute
    tv.set('generator-info-url', 'https://github.com/mikhoul/XMLTV-EPG-Tools')
    for ch in output_channels:
        tv.append(ch)
    for plist in output_programs.values():
        for prog in plist:
            tv.append(prog)
    return tv

def write_output(tv):
    """Write the final <tv> with DOCTYPE declaration."""
    os.makedirs(output_path, exist_ok=True)
    out_file = output_path + base_filename + ('.gz' if gzipped_out else '')
    # Write with DOCTYPE
    doctype_str = '<!DOCTYPE tv SYSTEM "xmltv.dtd">'
    with (gzip.open(out_file, 'wb') if gzipped_out else open(out_file, 'wb')) as f:
        # Use lxml's API to include DOCTYPE
        tree = etree.ElementTree(tv)
        # Write to a string with DOCTYPE
        xml_bytes = etree.tostring(tree, encoding='utf-8', pretty_print=True,
                                   xml_declaration=True)
        # Prepend DOCTYPE manually
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(doctype_str.encode('utf-8') + b'\n')
        f.write(xml_bytes)
    print(f"Wrote merged EPG: {out_file}")

def xmlmerge():
    """Main merge routine."""
    cfg = read_yaml_input(input_file)
    for src in cfg.get('files', []):
        get_channels_programs(src)
    merged = build_merged_tree()
    normalize_timezones(merged)
    normalize_exponents(merged)
    escape_specials(merged)
    fix_chronology(merged)
    prune_invalid_programmes(merged, seen_channel_ids)
    escape_ampersands(merged)
    # Add DOCTYPE declaration
    merged = final_escape(merged)
    write_output(merged)

if __name__ == '__main__':
    xmlmerge()
