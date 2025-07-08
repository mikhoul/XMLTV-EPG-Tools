#!/usr/bin/env python3

"""
xmlmerge.py

Merge multiple XMLTV EPG sources into a single, well-formed, normalized XMLTV file.

Enhancements:
- Robust caching: handles both gzipped and plain-XML sources
- Lenient channel‐ID matching (normalizes entity encodings)
- Correct ampersand escaping for text nodes
- Cross-platform file‐path handling
- Cleaned up redundant attribute‐escaping logic
"""

import gzip
import os
import re
import sys
import yaml
import logging
import requests
import xml.sax.saxutils as saxutils
from datetime import datetime
from lxml import etree
from urllib.parse import urlparse

# --- Configuration ---
updatetime    = 4                  # hours before cache refresh
trim          = False              # drop programmes older than now
gzipped_out   = True               # gzip final output
output_path   = 'output'           # output directory
cache_path    = 'cache'            # cache directory
input_file    = 'xmlmerge.yaml'    # YAML source list
base_filename = 'merged.xml'       # output filename base

# Global data holders
output_channels = {}               # dict: normalized_id → <channel> element
output_programs = {}               # dict: channel_id → list of <programme> elements
seen_channel_ids = set()           # set of canonical channel IDs

# Regex patterns
tz_pattern   = re.compile(r'([+-])(\d{1,2}):(\d{2})$')
sci_full     = re.compile(r'(\d+\.\d+e[+-]\d+)(?:\s*([+-]\d{4}))?$', re.IGNORECASE)
amp_pattern  = re.compile(r'&(?![a-zA-Z]+;|#\d+;|#x[0-9A-Fa-f]+;)')

# --- Logging Setup ---
logging.basicConfig(
    level    = logging.INFO,
    format   = '%(asctime)s %(levelname)s %(message)s',
    datefmt  = '%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


def normalize_id(raw_id):
    """
    Convert XML escaped IDs to normalized form: unescape '&amp;' → '&', strip whitespace.
    """
    return saxutils.unescape(raw_id).strip()


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
    fname  = f"{parsed.netloc}{parsed.path}"
    return re.sub(r'[<>:"/\\\\|?*]', '_', fname) or 'default.xml'


def is_fresh(fname):
    """Return cached path if fresh (younger than updatetime), else None."""
    now = datetime.now().timestamp()
    for suffix in ('', '.gz'):
        full = os.path.join(cache_path, fname + suffix)
        if os.path.exists(full) and os.path.getmtime(full) + updatetime*3600 > now:
            return full
    return None


def fetch_to_cache(url):
    """Download URL content and cache it, logging duration."""
    start = datetime.now()
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        fname = url_to_filename(url)
        out   = os.path.join(cache_path, fname + ('.gz' if not url.lower().endswith('.gz') else ''))
        os.makedirs(cache_path, exist_ok=True)
        # Write raw content or compress based on URL extension
        if url.lower().endswith('.gz'):
            with open(out, 'wb') as f:
                f.write(resp.content)
        else:
            with gzip.open(out, 'wb') as f:
                f.write(resp.content)
        duration = (datetime.now() - start).total_seconds()
        logger.info("Fetched %s in %.2fs", url, duration)
        return gzip.open(out, 'rt', encoding='utf-8', newline=None)
    except Exception as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


def open_xml(source):
    """Open and parse XMLTV source from URL or local file, logging load time."""
    start = datetime.now()
    if source.startswith(('http://','https://')):
        fname  = url_to_filename(source)
        cached = is_fresh(fname)
        if cached:
            fh = gzip.open(cached, 'rt', encoding='utf-8', newline=None)
            logger.info("Opened cached %s", source)
        else:
            fh = fetch_to_cache(source)
        logger.info("Load time for %s: %.2fs", source, (datetime.now()-start).total_seconds())
    else:
        path = source
        if path.endswith('.gz'):
            fh = gzip.open(path, 'rt', encoding='utf-8', newline=None)
        else:
            fh = open(path, 'rt', encoding='utf-8')
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
    Builds normalized-ID map for channels and collects programmes.
    """
    start = datetime.now()
    root  = open_xml(source)
    if root is None:
        return

    new_ch = dup_ch = pr_count = 0

    for elem in root:
        if elem.tag == 'channel':
            cid     = elem.get('id')
            if cid:
                norm_c = normalize_id(cid)
                if norm_c not in output_channels:
                    output_channels[norm_c] = elem
                    seen_channel_ids.add(cid)
                    new_ch += 1
                else:
                    logger.info("Duplicate channel skipped: %s (normalized from %s)", norm_c, cid)
                    dup_ch += 1

        elif elem.tag == 'programme':
            ch = elem.get('channel')
            if not ch:
                continue
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

    duration = (datetime.now() - start).total_seconds()
    if dup_ch:
        logger.info("Parsed %s: %d new channels, %d duplicates, %d programmes in %.2fs",
                    source, new_ch, dup_ch, pr_count, duration)
    else:
        logger.info("Parsed %s: %d new channels, 0 duplicates, %d programmes in %.2fs",
                    source, new_ch, pr_count, duration)


def normalize_timezones(root):
    fixes = 0
    for prog in root.findall('programme'):
        for attr in ('start','stop'):
            ts = prog.get(attr)
            if ts:
                fixed = tz_pattern.sub(lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3)}", ts)
                if fixed != ts:
                    prog.set(attr, fixed)
                    fixes += 1
    logger.info("Applied %d timezone normalizations", fixes)


def normalize_exponents(root):
    fixes = 0
    for prog in root.findall('programme'):
        for attr in ('start','stop'):
            val = prog.get(attr,'')
            m   = sci_full.match(val)
            if m:
                ts_int = int(float(m.group(1)))
                prog.set(attr, f"{ts_int:014d}" + (m.group(2) or ''))
                fixes += 1
    logger.info("Converted %d scientific-notation timestamps", fixes)


def escape_specials(root):
    """
    Strip CDATA sections. Rely on final lxml serialization for proper escaping.
    """
    fixes = 0
    for el in root.iter():
        if isinstance(el.text, etree.CDATA):
            el.text = str(el.text)
            fixes += 1
    logger.info("Applied %d CDATA unwraps", fixes)


def fix_chronology(root):
    fixes = 0
    for prog in list(root.findall('programme')):
        try:
            s = datetime.strptime(prog.get('start'), '%Y%m%d%H%M%S %z')
            e = datetime.strptime(prog.get('stop'),  '%Y%m%d%H%M%S %z')
            if e <= s:
                root.remove(prog)
                fixes += 1
        except:
            pass
    logger.info("Removed %d inverted-time programmes", fixes)


def escape_ampersands(root):
    """
    Escape raw '&' in text nodes to '&amp;', ignoring existing entities.
    """
    fixes = 0
    for el in root.iter():
        if el.text:
            new = amp_pattern.sub('&amp;', el.text)
            if new != el.text:
                el.text = new
                fixes += 1
    logger.info("Escaped %d ampersands in text nodes", fixes)


def prune_invalid_programmes(root):
    """
    Remove programmes whose (normalized) channel ID does not map to any channel.
    Also rewrites programme channel attributes to the canonical form.
    """
    fixes = 0
    # Build normalized → canonical channel-ID map
    norm_map = { normalize_id(cid): cid for cid in seen_channel_ids }

    for prog in list(root.findall('programme')):
        raw_ch = prog.get('channel')
        norm   = normalize_id(raw_ch or '')
        if norm in norm_map:
            canonical = norm_map[norm]
            if raw_ch != canonical:
                prog.set('channel', canonical)
        else:
            title = prog.findtext('title','(no title)')
            start = prog.get('start','')
            logger.info("Pruning programme %s / %s / %s", start, raw_ch, title)
            root.remove(prog)
            fixes += 1

    logger.info("Pruned %d invalid programmes", fixes)


def final_escape(root):
    """Re-serialize to normalize all escaping via lxml."""
    xml_bytes = etree.tostring(
        root, xml_declaration=True, encoding='utf-8', pretty_print=True
    )
    return etree.fromstring(xml_bytes)


def build_merged_tree():
    """Construct <tv> root, append channels and programmes, set metadata."""
    tv = etree.Element('tv')
    tv.set('generator-info-name', 'mikhoul/XMLTV-EPG-Tools')
    tv.set('generator-info-url',  'https://github.com/mikhoul/XMLTV-EPG-Tools')
    tv.set('generated-ts',        str(int(datetime.now().timestamp())))

    # Append canonical channels
    for ch in output_channels.values():
        tv.append(ch)
    # Append programmes
    for prog_list in output_programs.values():
        for prog in prog_list:
            tv.append(prog)

    return tv


def write_output(tv):
    """Write the final EPG to disk, logging output path."""
    os.makedirs(output_path, exist_ok=True)
    filename = base_filename + ('.gz' if gzipped_out else '')
    out_file = os.path.join(output_path, filename)
    mode     = 'wb'
    opener   = gzip.open if gzipped_out else open

    with opener(out_file, mode) as f:
        etree.ElementTree(tv).write(f, xml_declaration=True, encoding='utf-8', pretty_print=True)

    logger.info("Wrote merged EPG to %s", out_file)


def xmlmerge():
    cfg = read_yaml_input(input_file)
    for src in cfg.get('files', []):
        get_channels_programs(src)

    merged = build_merged_tree()
    normalize_timezones(merged)
    normalize_exponents(merged)
    escape_specials(merged)
    fix_chronology(merged)
    prune_invalid_programmes(merged)
    escape_ampersands(merged)
    merged = final_escape(merged)
    write_output(merged)


if __name__ == '__main__':
    xmlmerge()
