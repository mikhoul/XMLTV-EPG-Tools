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

## 🏁 License
Released under the **MIT License** – free for personal & commercial use.

---

> Made with ❤️  •  Enjoy your unified EPG!
