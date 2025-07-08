#!/usr/bin/env python3
"""
xmlmerge.py

Merge multiple XMLTV EPG sources into a single, well-formed, normalized XMLTV file.

Enhancement: Structured logging emits:
  - Fetch durations
  - Parse durations
  - Counts of new vs duplicate channels
  - Counts of programmes processed
  - Counts of timezone fixes, exponent conversions, CDATA/attribute escapes,
    chronology removals, ampersand escapes
  - Logs each pruned programme for missing channels
"""

import gzip
import os
import re
import requests
import sys
import yaml
import logging
from datetime import datetime
from lxml import etree
from urllib.parse import urlparse

# --- Configuration ---
updatetime     = 4               # hours before cache refresh
trim           = False           # drop programmes older than now
gzipped_out    = True            # gzip final output
output_path    = 'output/'       # output directory
cache_path     = 'cache/'        # cache directory
input_file     = 'xmlmerge.yaml' # YAML source list
base_filename  = 'merged.xml'    # output filename base

# Global data holders
output_channels  = []            # list of <channel> elements
output_programs  = {}            # dict: channel_id → list of <programme> elements
seen_channel_ids = set()         # for channel deduplication

# Regex patterns
tz_pattern   = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_full     = re.compile(r'(\d+\.\d+e[+-]\d+)(?:\s*([+-]\d{4}))?$', re.IGNORECASE)
amp_pattern  = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;)')

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


def read_yaml_input(path):
    """Load YAML file listing XMLTV source URLs or paths."""
    try:
        with open(path, 'rt') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error("Error reading %s: %s", path, e)
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
    """Download URL content and cache it, logging duration."""
    start = datetime.now()
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        fname = cache_path + url_to_filename(url)
        out = fname + ('' if url.lower().endswith('.gz') else '.gz')
        os.makedirs(cache_path, exist_ok=True)
        with open(out, 'wb') as f:
            f.write(resp.content)
        duration = (datetime.now() - start).total_seconds()
        logger.info("Fetched %s in %.2fs", url, duration)
        return gzip.open(out, 'rt', encoding='utf-8', newline=None)
    except Exception as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


def open_xml(source):
    """Open and parse XMLTV source from URL or local file, logging load time."""
    fetch_start = datetime.now()
    if source.startswith(('http://', 'https://')):
        fname = url_to_filename(source)
        cached = is_fresh(fname)
        if cached:
            fh = gzip.open(cached, 'rt', encoding='utf-8', newline=None)
            logger.info("Opened cached %s", source)
        else:
            fh = fetch_to_cache(source)
        logger.info("Load time for %s: %.2fs",
                    source, (datetime.now() - fetch_start).total_seconds())
    else:
        if source.endswith('.gz'):
            fh = gzip.open(source, 'rt', encoding='utf-8', newline=None)
        else:
            fh = open(source, 'rt', encoding='utf-8')
        logger.info("Opened local %s", source)

    if fh is None:
        return None

    try:
        parser = etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)
        return etree.parse(fh, parser).getroot()
    except Exception as e:
        logger.error("XML parse error in %s: %s", source, e)
        return None


def get_channels_programs(source):
    """
    Extract <channel> and <programme> elements from one source.
    Logs counts, duplicates skipped, and parse duration.
    """
    parse_start = datetime.now()
    root = open_xml(source)
    if root is None:
        return

    ch_new = ch_dupes = pr_count = 0

    for elem in root:
        if elem.tag == 'channel':
            cid = elem.get('id')
            if cid:
                if cid not in seen_channel_ids:
                    seen_channel_ids.add(cid)
                    output_channels.append(elem)
                    ch_new += 1
                else:
                    logger.info("Duplicate channel skipped: %s (from %s)", cid, source)
                    ch_dupes += 1
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
            pr_count += 1

    duration = (datetime.now() - parse_start).total_seconds()
    logger.info(
        "Parsed %s: %d new channels, %d duplicate channels skipped, %d programmes in %.2fs",
        source, ch_new, ch_dupes, pr_count, duration
    )


def normalize_timezones(root):
    """Convert time-zone offsets and log count."""
    fixes = 0
    for prog in root.findall('programme'):
        for attr in ('start', 'stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                if fixed != ts:
                    prog.set(attr, fixed)
                    fixes += 1
    logger.info("Applied %d timezone normalizations", fixes)


def normalize_exponents(root):
    """Convert scientific-notation timestamps to fixed-width strings."""
    fixes = 0
    for prog in root.findall('programme'):
        for attr in ('start', 'stop'):
            val = prog.get(attr, '')
            m = sci_full.match(val)
            if m:
                float_ts, offset = m.groups()
                ts_int = int(float(float_ts))
                ts_str = f"{ts_int:014d}"
                prog.set(attr, ts_str + (offset or ''))
                fixes += 1
    logger.info("Converted %d scientific-notation timestamps", fixes)


def escape_specials(root):
    """Strip CDATA and escape ampersands in attributes."""
    fixes = 0
    for el in root.iter():
        if isinstance(el.text, etree.CDATA):
            el.text = str(el.text)
            fixes += 1
        for a, v in list(el.attrib.items()):
            if '&' in v and not v.startswith('&amp;'):
                el.attrib[a] = v.replace('&', '&amp;')
                fixes += 1
    logger.info("Applied %d CDATA/attribute escapes", fixes)


def fix_chronology(root):
    """Remove programmes where stop ≤ start, logging count."""
    fixes = 0
    for prog in list(root.findall('programme')):
        try:
            s = datetime.strptime(prog.get('start'), '%Y%m%d%H%M%S %z')
            e = datetime.strptime(prog.get('stop'), '%Y%m%d%H%M%S %z')
            if e <= s:
                root.remove(prog)
                fixes += 1
        except:
            continue
    logger.info("Removed %d inverted-time programmes", fixes)


def escape_ampersands(root):
    """Ensure no raw '&' remain in text nodes."""
    fixes = 0
    for el in root.iter():
        if el.text:
            new = amp_pattern.sub('&amp;', el.text)
            if new != el.text:
                el.text = new
                fixes += 1
    logger.info("Escaped %d ampersands in text nodes", fixes)


def prune_invalid_programmes(root, valid_ids):
    """Remove invalid-channel programmes, logging each and summary count."""
    fixes = 0
    for prog in list(root.findall('programme')):
        cid = prog.get('channel')
        if cid not in valid_ids:
            title = prog.findtext('title', default='(no title)')
            start = prog.get('start', '')
            logger.info("Pruning programme %s / %s / %s", start, cid, title)
            root.remove(prog)
            fixes += 1
    logger.info("Pruned %d invalid programmes", fixes)


def final_escape(root):
    """Serialize & parse to normalize escaping; returns new Element root."""
    xml_bytes = etree.tostring(
        root,
        encoding='utf-8',
        xml_declaration=True,
        pretty_print=True
    )
    return etree.fromstring(xml_bytes)


def build_merged_tree():
    """Construct <tv> root, append channels and programmes, set metadata."""
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'mikhoul/XMLTV-EPG-Tools')
    tv.set('generator-info-url', 'https://github.com/mikhoul/XMLTV-EPG-Tools')
    tv.set('generated-ts', str(int(datetime.now().timestamp())))
    for ch in output_channels:
        tv.append(ch)
    for plist in output_programs.values():
        for prog in plist:
            tv.append(prog)
    return tv


def write_output(tv):
    """Write the final EPG to disk, logging output path."""
    os.makedirs(output_path, exist_ok=True)
    out_file = output_path + base_filename + ('.gz' if gzipped_out else '')
    with (gzip.open(out_file, 'wb') if gzipped_out else open(out_file, 'wb')) as f:
        etree.ElementTree(tv).write(
            f,
            xml_declaration=True,
            encoding='utf-8',
            pretty_print=True
        )
    logger.info("Wrote merged EPG to %s", out_file)


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
    merged = final_escape(merged)
    write_output(merged)


if __name__ == '__main__':
    xmlmerge()
