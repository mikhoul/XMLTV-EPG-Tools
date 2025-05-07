import sys
from lxml import etree
from xmlmerge import open_xml, write_xml
# Rename channel id's from jibberish to something recognizable
# from  <channel id="673247127d5da5000817b4d6">
#           <display-name>Pluto TV Trending Now</display-name>
# to <channel id="Pluto.TV.Trending.Now.pluto">
# and <programme channel="Pluto.TV.Trending.Now.pluto">

def change_pluto_ids():
    gzipped = False
# [ [input_path, suffix, output_path] ...]
    files = [ # leaving these inputs here since these were the only thing I was using this for
        ['https://i.mjh.nz/PlutoTV/us.xml.gz', '.pluto', 'i.mjh.nz_PlutoTV_us.mod.xml.gz'],
        ['https://i.mjh.nz/Roku/all.xml.gz', '.roku', 'i.mjh.nz_Roku_all.mod.xml.gz']
    ]
    cache_path = 'cache/' # path to stored input files
    output_path = 'cache/' # path to output file, I want to merge this with other files
    output_programs = []
    tree = etree.Element('tv')
    for file, suffix, outpath in files:
        root = open_xml(file, cache_path)
        try:
            channels = root.findall('channel')
            tree.extend(channels)
            for channel in channels:
                old_id = channel.get('id')
                name = channel.find('display-name')
                old_name = name.text
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
        if '.gz' in file:
            gzipped = True
        write_xml(output_path+outpath, gzipped, tree)

if __name__ == '__main__':
    change_pluto_ids()
