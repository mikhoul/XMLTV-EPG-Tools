from xmlmerge import xmlmerge
from change_gracenote_ids import change_gracenote_ids
from change_pluto_ids import change_pluto_ids
from timeshift import timeshift
from make_dummies import make_dummies

# This is a driver script to run them all in order
# If you have your locations and configurations set up in all of these scripts,
# then you can run this script to download, modify, create your own xml,
# and finally merge it all together with xmlmerge into a single file

def main():
    change_gracenote_ids()
    change_pluto_ids()
    timeshift()
    make_dummies()
    xmlmerge()

if __name__ == '__main__':
    main()