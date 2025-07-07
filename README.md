# 📺 XMLTV EPG Merger & Time Shifter

[![Python](https://img.shields.io/badge/Python-3.6%2B-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![XMLTV](https://img.shields.io/badge/XMLTV-Compatible-orange.svg)](http://xmltv.org)

> **All-in-one toolkit to merge multiple XMLTV Electronic Program Guide (EPG) sources and optionally time-shift selected channels – delivered in a single, self-contained README for easy download.**

---

## 🎯 Key Features

### 🔀 XML Merger (main focus)
1. **Multi-source aggregation** – Combine any number of XMLTV or GZIP-compressed EPG feeds
2. **Smart caching** – Locally stores downloads and only refreshes when stale
3. **Duplicate handling** – Removes duplicate channels *and* colliding programmes automatically
4. **YAML driven** – Just list your feeds in `xmlmerge.yaml`, run, and relax
5. **Collision-safe merging** – Prevents overlapping programme duplicates using start-time comparison
6. **Compressed output** – Writes `merged.xml.gz` by default to save space

### ⏰ Time Shifter (utility)
Simply shift programme start/stop times east (−) or west (+) and optionally rename / re-ID channels – ideal for cross-timezone EPGs.

---

## 🚀 Quick Start
```bash
pip install lxml requests pyyaml             # ① Install deps
python xmlmerge.py                           # ② Merge feeds ➜ output/merged.xml.gz
python timeshift.py                          # ③ (Optional) Time-shift select channels ➜ cache/shift.xml
```

---

## 🛠️ Configuration

### `xmlmerge.yaml`
```yaml
files:
  - https://i.mjh.nz/PlutoTV/fr.xml.gz
  - https://i.mjh.nz/Plex/fr.xml.gz
  - https://i.mjh.nz/SamsungTVPlus/fr.xml.gz
  - https://epgshare01.online/epgshare01/epg_ripper_RAKUTEN_FR1.xml.gz
  - https://epgshare01.online/epgshare01/epg_ripper_CA1.xml.gz
```

### `timeshift.yaml`
```yaml
channels:
  "input_file.xml":
    - ["🇫🇷 TF1 décalé", "tf1.fr",  "tf1.fr.shifted",  1]   # +1 h west ➜ CET → GMT
    - ["🇨🇦 CBC décalé", "cbc.ca",  "cbc.ca.shifted", -3]   # −3 h east ➜ PT → ET
```

---

## 🧩 Directory Layout
```
.
├─ xmlmerge.py        # ⇣ main merger logic
├─ timeshift.py       # ⇣ optional time-shift helper
├─ xmlmerge.yaml      # ⇢ list of source feeds
├─ timeshift.yaml     # ⇢ channel / shift map
├─ cache/             # ⇣ downloaded & shifted XMLs
└─ output/            # ⇣ final merged EPG
```

---

## 📜 Full Source (single file copy-paste)
Below you will find **all code & config** required to run the toolkit. Copy the sections into separate files **or simply download this README** and cut along the markers. No external modules beyond `lxml`, `PyYAML`, and `requests` are needed.

<details>
<summary>📂 xmlmerge.py</summary>

```python
from lxml import etree
import gzip, requests, os, re, sys
from datetime import datetime
from urllib.parse import urlparse
import yaml

updatetime = 20        # hours until refresh
trim = False           # drop past programmes
gzipped = True         # gzip output
output_path = 'output/'
cache_path  = 'cache/'
output = 'merged.xml'  # becomes merged.xml.gz when gzipped
input_file = 'xmlmerge.yaml'

output_programs = []   # {id:[programme,…]}
output_channels = []   # [channel,…]

def read_yaml_input(file_name):
    try:
        with open(file_name, 'rt', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error opening {file_name}: {e}")
        sys.exit(e)

def get_file(file_name):
    try:
        return (gzip.open if file_name.endswith('.gz') else open)(file_name, 'rt', encoding='utf-8-sig')
    except Exception as e:
        print(f"Error opening {file_name}: {e}")
        sys.exit(e)

def url_to_filename(url):
    parsed = urlparse(url)
    return re.sub(r'[<>:"/\\|?*]', '_', f"{parsed.netloc}{parsed.path}") or 'default.xml'

def check_fresh(path):
    now = datetime.now().timestamp()
    return os.path.exists(path) and os.path.getmtime(path) + updatetime*3600 > now

def fetch_url(url):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        print(f"Error downloading {url}: {e}")
        return None

def open_xml(source, cache):
    if source.startswith('http'):  # remote
        local = cache + url_to_filename(source)
        if check_fresh(local) or check_fresh(local + '.gz'):
            fp = get_file(local if os.path.exists(local) else local + '.gz')
        else:
            data = fetch_url(source)
            if data is None:
                raise RuntimeError('Download failed')
            path = local + ('' if source.endswith('.gz') else '.gz')
            (open if not source.endswith('.gz') else open)(path, 'wb').write(data if source.endswith('.gz') else gzip.compress(data))
            fp = get_file(path)
    else:  # local path
        fp = get_file(source)
    return etree.parse(fp, etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True)).getroot()

def merge_sources(path):
    global output_programs, output_channels
    root = open_xml(path, cache_path)
    programs = {}
    for elem in root:
        if elem.tag == 'channel':
            if elem.get('id') not in {c.get('id') for c in output_channels}:
                output_channels.append(elem)
        else:  # programme
            cid = elem.get('channel')
            programs.setdefault(cid, []).append(elem)
    if not output_programs:
        output_programs = programs
    else:
        for cid, plist in programs.items():
            known_starts = {p.get('start') for p in output_programs.get(cid, [])}
            for p in plist:
                if p.get('start') not in known_starts:
                    output_programs.setdefault(cid, []).append(p)

def create_tree():
    root = etree.Element('tv', generator="xmltv-epg-merger")
    for ch in output_channels:
        root.append(ch)
    for plist in output_programs.values():
        root.extend(plist)
    return root

def write_xml(root):
    path = output_path + (output + '.gz' if gzipped else output)
    os.makedirs(output_path, exist_ok=True)
    data = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='utf-8')
    (gzip.open if gzipped else open)(path, 'wb').write(data)
    print('Wrote', path)

def xmlmerge():
    os.makedirs(cache_path, exist_ok=True)
    files = read_yaml_input(input_file)['files']
    for f in files:
        merge_sources(f)
    write_xml(create_tree())

if __name__ == '__main__':
    xmlmerge()
```
</details>

<details>
<summary>📂 timeshift.py</summary>

```python
from lxml import etree
from datetime import datetime, timedelta
from xmlmerge import open_xml, write_xml, read_yaml_input  # reuse helpers

cache_path  = 'cache/'
output_path = 'cache/'
output_file = output_path + 'shift.xml'

out_root = etree.Element('tv')
out_channels, out_programs = [], []

def modify_programs(plist, new_id, hours):
    for p in plist:
        for tag in ('start', 'stop'):
            dt = datetime.strptime(p.get(tag), '%Y%m%d%H%M%S %z') + timedelta(hours=hours)
            p.set(tag, dt.strftime('%Y%m%d%H%M%S %z'))
        p.set('channel', new_id)
    return plist

def process_file(src, maps):
    root = open_xml(src, cache_path)
    for name, cid, new_id, shift in maps:
        ch_el = root.find(f'.//channel[@id="{cid}"]')
        if ch_el is None:
            print("Channel not found:", cid)
            continue
        ch_el.set('id', new_id)
        ch_el.find('display-name').text = name
        icons = ch_el.findall('icon')
        if len(icons) > 1:
            ch_el.remove(icons[1])
        out_channels.append(ch_el)
        progs = root.findall(f'.//programme[@channel="{cid}"]')
        out_programs.append(modify_programs(progs, new_id, int(shift)))

def timeshift():
    cfg = read_yaml_input('timeshift.yaml')['channels']
    for src, maps in cfg.items():
        process_file(src, maps)
    for ch in out_channels: out_root.append(ch)
    for plist in out_programs: out_root.extend(plist)
    write_xml(output_file, False, out_root)

if __name__ == '__main__':
    timeshift()
```
</details>

<details>
<summary>⚙️ xmlmerge.yaml</summary>

```yaml
files:
  - https://i.mjh.nz/PlutoTV/fr.xml.gz
  - https://i.mjh.nz/Plex/fr.xml.gz
  - https://i.mjh.nz/SamsungTVPlus/fr.xml.gz
  - https://epgshare01.online/epgshare01/epg_ripper_RAKUTEN_FR1.xml.gz
  - https://epgshare01.online/epgshare01/epg_ripper_CA1.xml.gz
```
</details>

<details>
<summary>⚙️ timeshift.yaml (template)</summary>

```yaml
channels:
  "input_file.xml":
    - ["New Channel Name", "orig_channel_id", "new_channel_id", 3]
```
</details>

---

## 🏁 License
Released under the **MIT License** – free for personal & commercial use.

---

> Made with ❤️  •  Enjoy your unified EPG!
