import sys
from lxml import etree
from xmlmerge import open_xml, write_xml
# Rename channel id's from jibberish to something recognizable.
# This was made specifically for the xml files from 
# acidjesuz repo, and will probably break on anything else.
# Needs xmlmerge.py for open and write

# <channel id="I8.18955.schedulesdirect.org"> <- change these ids to a combo of the display names
# 	<display-name>A&amp;E Latinoamerica</display-name>
# 	<display-name>8 A&amp;E Latinoamerica</display-name> --grab this one
# 	<display-name>8</display-name>
# 	<display-name>A&amp;E</display-name> -- and append this one if it's there
# 	<icon src="https://schedulesdirect-api20141201-logos.s3.dualstack.us-east-1.amazonaws.com/stationLogos/s10035_dark_360w_270h.png" width="360" height="270" />
# </channel>
# <channel id="I827.11118.gracenote.com">
# 	<display-name>UNI</display-name>
# 	<display-name>827 UNI</display-name> --grab this one
# 	<display-name>827</display-name>
# 	<icon src="https://zap2it.tmsimg.com/h3/NowShowing/11118/s11118_ll_h15_ab.png" />
# </channel>

def change_gracenote_ids():
    gzipped = False
# leaving this input, it's the only thing it's used for
    cache_path = 'cache/' # path to stored input files
    output_path = 'cache/' # path to output file, I want to merge this with other files
    input = 'https://github.com/acidjesuz/EPGTalk/raw/refs/heads/master/guide.xml.gz' # input file
    output = 'github.com_acidjesuz_EPGTalk_raw_refs_heads_master_guide.mod.xml.gz' # output file
    output_programs = []
    tree = etree.Element('tv')
    root = open_xml(input, cache_path)
    try:
        channels = root.findall('channel')
        tree.extend(channels)
        for channel in channels:
            old_id = channel.get('id')
            names = channel.findall('display-name')
            old_name = names[1].text
            if 'gracenote' in old_id:
                suffix = '.gracenote'
            elif 'schedulesdirect' in old_id:
                suffix = '.schedules'
                try:
                    old_name = old_name + ' ' + names[3].text
                except IndexError as e:
                    pass
            id = old_name.replace(' ', '.')+suffix
            id = id.replace('&', '.and.')
            id = id.replace('..','.')
            channel.set('id', id)
            programs = root.findall(f'programme[@channel="{old_id}"]')
            for program in programs:
                program.set('channel',id)
                output_programs.append(program)
        tree.extend(output_programs)
    except Exception as e:
        sys.exit(e)
    if '.gz' in input:
        gzipped = True
    write_xml(output_path+output, gzipped, tree)

if __name__ == '__main__':
    change_gracenote_ids()
