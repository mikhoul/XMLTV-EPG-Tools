from lxml import etree
from datetime import datetime, timedelta
import pytz
from xmlmerge import write_xml, read_yaml_input
# Make some dummy program entries for the specified number of days
# with the channel ids, names, titles, descriptions, and optional icons
# Needs xmlmerge.py for write_xml, and read_yaml_input functions
output_path = 'cache/' # path to output file, I want to merge this with other files
output = 'dummy.xml' # output file name, .gz will be added if gzipped
input_file = 'make_dummies.yaml' # input, yaml format, description in the file
future_days = 2 # how many days worth of programs to create

def create_dummy_program(start, stop, channel_id, title, desc, categories, icon_url):
    program = etree.Element('programme')
    program.set('channel', channel_id)
    program.set('start', start.strftime('%Y%m%d%H%M%S %z'))
    program.set('stop', stop.strftime('%Y%m%d%H%M%S %z'))
    name = etree.SubElement(program, 'title')
    name.text = title
    desc_el = etree.SubElement(program, 'desc')
    desc_el.text = desc
    for category in categories:
        cat = etree.SubElement(program, 'category')
        cat.text = category
    if icon_url:
        icon = etree.SubElement(program, 'icon')
        icon.set('src', icon_url)
    return program

def future_dummies(hrs, channel_id, channel_name, title, desc, icon_url):
    global future_days
    local_timezone = pytz.timezone('America/Chicago')
    time = datetime.now(local_timezone)
    delta = timedelta(days=future_days)
    end = (time+delta).timestamp()
    delta = timedelta(hours=int(hrs))
    tv = []
    tv.append(make_channel_element(channel_id, channel_name, icon_url))
    while time.timestamp() < end:
        now = time
        time = time+delta
        tv.append(create_dummy_program(now, time,channel_id,title,desc,'Dummy',icon_url))
    return tv

def make_tree(elements):
    programs = []
    root = etree.Element('tv')
    for element in elements:
        if element.tag.strip() == 'channel':
            root.append(element)
        else:
            programs.append(element)
    for program in programs:
        root.append(program)
    return root

def make_channel_element(id, names, icon):
    chan = etree.Element('channel')
    chan.set('id',id)
    if not isinstance(names,list):
        names = [names]
    for name in names:
        dname = etree.SubElement(chan,'display-name')
        dname.text = name
    if icon:
        pic = etree.SubElement(chan,'icon')
        pic.set('src',icon)
    return chan

def make_dummies():
    global input_file, output_path, output
    elements = []
    dummies = read_yaml_input(input_file)['dummies']
    for dummy in dummies:
        hrs = dummy[0]
        channel_id = dummy[1]
        channel_name = dummy[2]
        title = dummy[3]
        desc = dummy[4]
        icon = None
        try:
            icon = dummy[5]
        except IndexError:
            icon = None
        elements = elements+(future_dummies(hrs, channel_id, channel_name, title, desc, icon))
    root = make_tree(elements)
    write_xml(output_path+output,False,root)

if __name__ == "__main__":
    make_dummies()
