<div align="center"><a href='https://ko-fi.com/X8X81ELTUM' target='_blank' class="centered-image"><img height='45' style='border:0px;height:45px;' src='https://storage.ko-fi.com/cdn/kofi5.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com'/></a></div>

# xmltools

## xmlmerge
Merge multiple xmltv files.  Opens and writes uncompressed or gzipped xml.  Remote files are saved locally, and new versions will only be pulled after a specified number of hours.
|vars| description |
|--|--|
| updatetime | get a new copy of a remote file if it's older than this many hours |
|trim|boolean - remove programs older than the current time|
|gzipped|boolean - compress output
|output| output file name
|input_file| yaml file to read

## timeshift
Pull channels and programs out of an existing xml file, change the air time for the programs, and write them to the output file.
|vars| description |
|--|--|
|channels|contains the files, associated ids to use, and other data to change|
|output|output file name

## change_pluto_ids
Changes the id names from pluto and roku xml files from i.mhj.nz.  If you only see channel ids that look like '2309340sdlfkj20' in your editor, then this will change them to something more easy to recognize, followed by .roku or .pluto suffix.  This was intended only for these specific files.
|vars|description|
|--|--|
|gzipped|boolean - compress output|
|files|files to change, along with suffix, and output file name

## change_gracenote_ids
Similar to the change_pluto_ids, but made to work with a file from the acidjesuz repo that only contains gracenote and schedulesdirect ids.  This was intended only for that specific file.
|vars|description|
|--|--|
|gzipped|boolean - compress output|
|input|input file|
|output|output file|

## make_dummies
Make dummy programs with the specified details.
|vars|description|
|--|--|
|output|output file|
|future_days|days worth of programs to create|
|dummies|details to create the dummy programs
