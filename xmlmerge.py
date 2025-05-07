from lxml import etree
import gzip
import requests
from datetime import datetime
import os
import re
from urllib.parse import urlparse
import sys
import yaml
output_programs = [] # hold program elements to write
output_channels = [] # hold channel elements to write
updatetime = 20 # downloaded files are stale after this many hours
trim = False # cut program elements older than now
output = 'merged.xml' # output file name, .gz will be added if gzipped
gzipped=True # gzip output y/n
input_file = 'xmlmerge.yaml' # input, yaml format
output_programs = [] # hold program elements to write
output_channels = [] # hold channel elements to write

def read_input(file_name):
    try:
        with open(file_name,'rt') as f:
            return yaml.safe_load(f)['files']
    except Exception as e:
        print(f"Error opening {file_name}: {e}")
        sys.exit(e)

def get_file(file_name):
    try:
        if file_name.endswith('.gz'):
            return gzip.open(file_name, 'rt', encoding='utf-8-sig', newline=None)
        return open(file_name, 'r', encoding='utf-8-sig', newline=None)
    except Exception as e:
        print(f"Error opening {file_name}: {e}")
        sys.exit(e)

def get_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        file_name = url_to_filename(url)
        if file_name.endswith('.gz'):
            f = open(file_name, 'wb')
            f.write(response.content)
            f.close()
            return gzip.open(file_name, 'rt', encoding='utf-8', newline=None)
        else:
            file_name = file_name+'.gz'
            f = gzip.open(file_name, 'wb')
            f.write(response.content)
            f.close()
            return gzip.open(file_name, 'rt', encoding='utf-8', newline=None)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None
    except Exception as e:
        sys.exit(e)

def check_file(file_name):
    global updatetime
    timenow = datetime.now().timestamp()
    if os.path.exists(file_name) and os.path.getmtime(file_name)+(updatetime*3600) > timenow:
        return True # file is fresh
    elif os.path.exists(file_name+'.gz') and os.path.getmtime(file_name+'.gz')+(updatetime*3600) > timenow:
        return True # file is fresh
    return False # file is stale or doesn't exist

def url_to_filename(url): # make a string out of a url to use as a file name
    parsed_url = urlparse(url)
    filename = f"{parsed_url.netloc}{parsed_url.path}"
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    if not filename or filename == '/':
        filename = 'default_filename.xml'
    return filename

def open_xml(file_path):
    f = None
    if file_path.startswith('http://') or file_path.startswith('https://'):
        file_name = url_to_filename(file_path)
        if check_file(file_name):
            f = get_file(file_name)
            print(f'{file_path}: downloaded recently, using local copy')
        else:
            f = get_url(file_path)
            print(f'{file_path}: dowloaded local copy')
    else:
        f = get_file(file_path)
        print(f'{file_path}: opened local file')
    try:
        root = etree.parse(f, etree.XMLParser(recover=True, huge_tree=True, remove_blank_text=True, resolve_entities=True)).getroot()
        return root
    except etree.XMLSyntaxError as e:
        print(f'{e} - skipping')
        return None
    except Exception as e:
        print(e)
        sys.exit(e)

def get_channels_programs(file_path):
    global trim, output_channels, output_programs
    root = open_xml(file_path)
    programs = {}
    for element in root: # go through all elements
        if element.tag == 'channel': # channel elements
            id = element.get('id')
            if id not in output_channels:
                output_channels.append(element) # add channels to output list
        else:
            id = element.get('channel') # programme elements
            if not programs or id not in programs.keys():
                programs[id] = [element]
            else:
                if trim: # get rid of programs older than now
                    stop = element.get('stop')
                    if old_program(stop): continue
                programs[id].append(element)
#    for channel in root.findall('channel'): # see if any channels are missing programs
#        id = channel.get('id')
#        if id not in programs.keys():
#            print(f'{file_path} - No program data for channel: {id}')
    if len(output_programs) > 0:
        merge_xml(programs)
    else:
        output_programs = programs

def merge_xml(p): # 
    for id, plist in p.items():
        if id not in output_programs.keys():
            output_programs[id] = plist
        else:
            for program in plist:
                r = etree.Element('r')
                r.extend(output_programs[id])
                start = program.get('start')
                collision = r.xpath(f'programme[@start="{start}"]')
                if collision: continue
                else:
                    output_programs[id].append(program)

def old_program(timestr):
    prog_date = datetime.strptime(timestr, '%Y%m%d%H%M%S %z')
    now = datetime.now(tz=prog_date.tzinfo)
    if prog_date < now:
        return True
    return False

def create_xml_tree(channels, programs):
    root = etree.Element('tv')
    root.extend(channels)
    for program in programs.values():
        root.extend(program)
    return root

def write_xml(output_path, gzipped, root):
    root.set('generator-info-name', "broken-droid/xmltools")
    now = round(datetime.now().timestamp())
    root.set('generated-ts', f'{now}')
    tree = etree.ElementTree(root)
    try:
        if gzipped:
            f = gzip.open(output_path, 'wb')
        else:
            f = open(output_path, 'wb')
        tree.write(f, pretty_print=True, xml_declaration=True, encoding='utf-8')
        print(f'Wrote: {output_path}')
    except Exception as e:
        sys.exit(e)

def xmlmerge():
    files = []
    global input_file, output, gzipped, output_channels, output_programs
    files = read_input(input_file)
    if gzipped: output = output+".gz"
    for file in files:
        get_channels_programs(file)
    root = create_xml_tree(output_channels, output_programs)
    write_xml(output, gzipped, root)

if __name__ == '__main__':
    xmlmerge()