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
 6. Final escape pass to ensure no raw '&' remain
"""

import gzip
import os
import re
import requests
import sys
import yaml
from datetime import datetime
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

# Regex for timezone normalization: +H:MM or +HH:MM → +HHMM
tz_pattern      = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
# Regex for scientific-notation timestamps
sci_pattern     = re.compile(r'\d+\.\d+e[+-]\d+', re.IGNORECASE)


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
    """
    Check if cached file (<fname> or <fname>.gz) is younger than updatetime.
    Returns the existing path or None.
    """
    now = datetime.now().timestamp()
    for suffix in ('', '.gz'):
        full = cache_path + fname + suffix
        if os.path.exists(full) and os.path.getmtime(full) + updatetime*3600 > now:
            return full
    return None


def fetch_to_cache(url):
    """
    Download URL and write to cache (gzipped if needed).
    Return a file handle for reading the cached content.
    """
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
    """
    Return the parsed root element of an XMLTV source.
    Supports HTTP(S) URLs (with caching) or local files.
    """
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
    Populates output_channels and output_programs globals.
    """
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
            # Optionally trim old programmes
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
    """
    Rewrite all start/stop attributes matching ±H:MM or ±HH:MM to ±HHMM.
    """
    for prog in root.findall('programme'):
        for attr in ('start', 'stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                prog.set(attr, fixed)


def escape_specials(root):
    """
    Strip CDATA sections and replace raw '&' in attributes with '&amp;'.
    """
    for el in root.iter():
        # Convert CDATA to plain text
        if isinstance(el.text, etree.CDATA):
            el.text = str(el.text)
        # Escape ampersands in attributes
        for a, v in list(el.attrib.items()):
            if '&' in v and not v.startswith('&amp;'):
                el.attrib[a] = v.replace('&', '&amp;')


def sanitize_timestamps(root):
    """
    Remove any <programme> whose start/stop uses scientific notation.
    """
    for prog in list(root.findall('programme')):
        for attr in ('start', 'stop'):
            ts = prog.get(attr, '')
            if sci_pattern.search(ts):
                root.remove(prog)
                break


def prune_invalid_programmes(root, valid_ids):
    """
    Remove any <programme> whose @channel is not in valid_ids.
    """
    for prog in list(root.findall('programme')):
        if prog.get('channel') not in valid_ids:
            root.remove(prog)


def final_escape(root):
    """
    Perform a final serialize-and-parse to force lxml to escape any
    remaining special characters in text nodes.
    """
    xml_bytes = etree.tostring(root,
                               encoding='utf-8',
                               xml_declaration=True,
                               pretty_print=True)
    return etree.fromstring(xml_bytes)


def build_merged_tree():
    """
    Create the <tv> root, append all channels then programmes,
    and set generator metadata attributes.
    """
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
    """
    Write the final <tv> tree to disk, gzipped or plain XML.
    """
    os.makedirs(output_path, exist_ok=True)
    out_file = output_path + base_filename + ('.gz' if gzipped_out else '')
    with (gzip.open(out_file, 'wb') if gzipped_out else open(out_file, 'wb')) as f:
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
    prune_invalid_programmes(merged, seen_channel_ids)
    # Final serialize-parse to enforce full escaping
    merged = final_escape(merged)
    write_output(merged)


if __name__ == '__main__':
    xmlmerge()
