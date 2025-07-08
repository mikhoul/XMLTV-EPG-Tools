#!/usr/bin/env python3
"""
xmlmerge.py

Merge multiple XMLTV EPG sources into a single, well-formed, normalized XMLTV file.
Implements fixes for:
 1. Correct channel de-duplication
 2. Escaping special characters (ampersands, etc.)
 3. Normalizing timezone offsets to ±HHMM
 4. Pruning programmes whose channel IDs are invalid
 5. Integrating validation hooks (placeholders for CI integration)
"""

from lxml import etree
import gzip
import requests
from datetime import datetime
import os
import re
from urllib.parse import urlparse
import sys
import yaml

# --- Configuration ---
updatetime = 20           # hours before cached files are refreshed
trim = False              # if True, drop programmes older than now
gzipped = True            # gzip output if True
output_path = 'output/'   # directory for output files
cache_path = 'cache/'     # directory for cached inputs
input_file = 'xmlmerge.yaml'
base_output = 'merged.xml'  # base name; '.gz' appended if gzipped

# Data holders
output_channels = []      # list of lxml channel elements
output_programs = {}      # dict: channel_id -> list of lxml programme elements

def read_yaml_input(file_name):
    try:
        with open(file_name, 'rt') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error opening {file_name}: {e}")
        sys.exit(1)

def url_to_filename(url):
    parsed = urlparse(url)
    fname = f"{parsed.netloc}{parsed.path}"
    # sanitize filesystem-unfriendly characters
    return re.sub(r'[<>:"/\\|?*]', '_', fname) or 'default.xml'

def get_file(path):
    try:
        if path.endswith('.gz'):
            return gzip.open(path, 'rt', encoding='utf-8-sig', newline=None)
        return open(path, 'rt', encoding='utf-8-sig', newline=None)
    except Exception as e:
        print(f"Error opening {path}: {e}")
        sys.exit(1)

def get_url(url, cache_dir):
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        fname = cache_dir + url_to_filename(url)
        # if original ends in .gz, write raw; else compress
        out_path = fname if url.lower().endswith('.gz') else fname + '.gz'
        with gzip.open(out_path, 'wb') as f:
            f.write(resp.content)
        return gzip.open(out_path, 'rt', encoding='utf-8')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def is_fresh(path):
    now = datetime.now().timestamp()
    for candidate in (path, path + '.gz'):
        full = cache_path + candidate
        if os.path.exists(full) and (os.path.getmtime(full) + updatetime*3600) > now:
            return True
    return False

def open_xml(source, cache_dir):
    """Open and parse XML from URL or local file, returning the root element."""
    if source.startswith(('http://', 'https://')):
        fname = url_to_filename(source)
        if is_fresh(fname):
            print(f"{source}: using cached copy")
            fp = get_file(cache_dir + fname + '.gz')
        else:
            print(f"{source}: downloading fresh copy")
            fp = get_url(source, cache_dir)
    else:
        print(f"{source}: opening local file")
        fp = get_file(source)
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)
        return etree.parse(fp, parser).getroot()
    except Exception as e:
        print(f"XML parse error for {source}: {e}")
        return None

# -- Fix 1: Correct channel de-duplication --
seen_channel_ids = set()

def get_channels_programs(source, cache_dir):
    """Extract channels and programmes from one source tree."""
    root = open_xml(source, cache_dir)
    if root is None:
        return
    for element in root:
        if element.tag == 'channel':
            cid = element.get('id')
            # only add if unseen
            if cid not in seen_channel_ids:
                seen_channel_ids.add(cid)
                output_channels.append(element)
        elif element.tag == 'programme':
            pid = element.get('channel')
            # optionally trim old programmes
            if trim:
                stop = element.get('stop')
                if old_program(stop):
                    continue
            # collect programmes by channel
            output_programs.setdefault(pid, []).append(element)

# -- Fix 3: Normalize timezone offsets to ±HHMM --
tz_pattern = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
def normalize_timezones(tree_root):
    for prog in tree_root.findall('programme'):
        for attr in ('start', 'stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                prog.set(attr, fixed)

# -- Fix 2: Escape special characters and strip CDATA --
def escape_specials(tree_root):
    for elem in tree_root.iter():
        # strip CDATA by casting to string
        if isinstance(elem.text, etree.CDATA):
            elem.text = str(elem.text)
        # escape ampersands etc. in attributes
        for attr, val in list(elem.attrib.items()):
            if '&' in val:
                elem.attrib[attr] = val.replace('&', '&amp;')

# -- Fix 4: Prune programmes with invalid channel references --
def prune_bad_programmes(tree_root, valid_ids):
    for prog in list(tree_root.findall('programme')):
        if prog.get('channel') not in valid_ids:
            tree_root.remove(prog)

def create_merged_tree(channels, programs):
    root = etree.Element('tv')
    for ch in channels:
        root.append(ch)
    for plist in programs.values():
        for prog in plist:
            root.append(prog)
    return root

def old_program(timestr):
    try:
        dt = datetime.strptime(timestr, '%Y%m%d%H%M%S %z')
        return dt < datetime.now(dt.tzinfo)
    except:
        return False

def write_xml(root, output_dir, base_name, gzipped_out=True):
    # add generator metadata
    now_ts = round(datetime.now().timestamp())
    root.set('generator-info-name', 'mikhoul/XMLTV-EPG-Tools')
    root.set('generated-ts', str(now_ts))

    tree = etree.ElementTree(root)
    out_name = base_name + ('.gz' if gzipped_out else '')
    full_path = output_dir + out_name
    os.makedirs(output_dir, exist_ok=True)
    with (gzip.open(full_path, 'wb') if gzipped_out else open(full_path, 'wb')) as f:
        tree.write(f, pretty_print=True, xml_declaration=True, encoding='utf-8')
    print(f"Wrote: {full_path}")

def xmlmerge():
    # load source list
    cfg = read_yaml_input(input_file)
    files = cfg.get('files', [])
    # process each source
    for src in files:
        get_channels_programs(src, cache_path)

    # build preliminary tree
    merged = create_merged_tree(output_channels, output_programs)

    # apply fixes
    normalize_timezones(merged)                          # Fix 3
    escape_specials(merged)                              # Fix 2
    prune_bad_programmes(merged, seen_channel_ids)       # Fix 4

    # placeholder: run external validator (e.g., xmllint) here for CI integration Fix 5
    # e.g., subprocess.run(["xmllint", "--noout", "--dtdvalid", "xmltv.dtd", temp_file])

    # write final output
    write_xml(merged, output_path, base_output, gzipped)

if __name__ == '__main__':
    xmlmerge()
