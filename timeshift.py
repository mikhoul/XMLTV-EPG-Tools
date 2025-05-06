from xmlmerge import open_xml, write_xml
from lxml import etree
from datetime import datetime, timedelta
# pull out channels/programs with matching ids from an xml file and timeshift the specified hours
# write those channels/programs to 'output' with altered name and id
# needs xmlmerge.py for open and write

# { file/url : [list of New Name|id|new_id|shift_hours], ... }
# ex: channels = {'https://epgshare01.online/epgshare01/epg_ripper_US1.xml.gz': [
#    'Animal Planet West|Animal.Planet.US.-.East.us|Animal.Planet.West.shift|3'
# ] }

channels = { # edit this
}
output = 'shift.xml' # file to write, edit this
output_root = etree.Element('tv') # root node for output
output_programs = [] # hold program elements to write
output_channels = [] # hold channel elements to write

def timeshift():
    for fname, data in channels.items():
        process_file(fname, data)
    finish_and_write()

def modify_programs(id, plist, new_id, shift_hours):
    for program in plist:
        start = program.get('start')
        stop = program.get('stop')
        start = datetime.strptime(start, '%Y%m%d%H%M%S %z')
        stop = datetime.strptime(stop, '%Y%m%d%H%M%S %z')
        start = start + timedelta(hours=shift_hours)
        stop = stop + timedelta(hours=shift_hours)
        start = start.strftime('%Y%m%d%H%M%S %z')
        stop = stop.strftime('%Y%m%d%H%M%S %z')
        program.set('start', start)
        program.set('stop', stop)
        program.set('channel', new_id)
    return plist

def finish_and_write():
    global output_root, output_programs, output
    for channel in output_channels:
        output_root.append(channel)
    for prog_list in output_programs:
        output_root.extend(prog_list)
    write_xml(output, False, output_root)

def process_file(input, data):
    global output_root, output_channels, output_programs
    input_root = open_xml(input)
    for channel in data:
        channel = channel.split('|')
        channel_name = channel[0]
        channel_id = channel[1]
        new_id = channel[2]
        channel_shift = int(channel[3])
        channel_el = input_root.find(f'.//channel[@id="{channel_id}"]')
        channel_el.set('id', new_id)
        disp_name = channel_el.find('display-name')
        disp_name.text = channel_name
        icons = channel_el.findall('icon')
        if len(icons) > 1:
            channel_el.remove(icons[1])
        output_channels.append(channel_el)
        input_programs = input_root.findall(f'.//programme[@channel="{channel_id}"]')
        modify_programs(channel_id, input_programs, new_id, channel_shift)
        output_programs.append(input_programs)

if __name__ == '__main__':
    timeshift()
