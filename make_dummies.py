from lxml import etree
from datetime import datetime, timedelta
import pytz
from xmlmerge import write_xml
# Make some dummy program entries for the specified number of
# days with the channel ids, names, titles, descriptions
# Needs xmlmerge.py for write
output = 'dummy.xml'
future_days = 2
# length(hours)|id|name|title|desc|icon
dummies = [
    '2|err-dummy|Error|No Signal.|No Signal.  Channel might be removed.|',
    '2|freenews-dummy|freenews|News only.  No Events.|Public internet feed.  News only.  No events.|',
]
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
    global dummies, output
    elements = []
    for dummy in dummies:
        dummy = dummy.split('|')
        icon_url = dummy.pop()
        desc = dummy.pop()
        title = dummy.pop()
        channel_name = dummy.pop()
        channel_id = dummy.pop()
        hrs = dummy.pop()
        elements = elements+(future_dummies(hrs, channel_id, channel_name, title, desc, icon_url))
    root = make_tree(elements)
    write_xml(output,False,root)

if __name__ == "__main__":
    make_dummies()
