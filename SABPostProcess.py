#!/usr/bin/python
import os
import json
import sys
from shutil import copytree, rmtree
from autoprocess import autoProcessTV, autoProcessMovie, autoProcessTVSR, sonarr, radarr
from readSettings import ReadSettings
from mkvtomp4 import MkvtoMp4
import logging
from logging.config import fileConfig
import fnmatch
from os.path import isdir, join

logpath = '/var/log/sickbeard_mp4_automator'
if os.name == 'nt':
    logpath = os.path.dirname(sys.argv[0])
elif not os.path.isdir(logpath):
    try:
        os.mkdir(logpath)
    except:
        logpath = os.path.dirname(sys.argv[0])
configPath = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'logging.ini')).replace("\\", "\\\\")
logPath = os.path.abspath(os.path.join(logpath, 'index.log')).replace("\\", "\\\\")
fileConfig(configPath, defaults={'logfilename': logPath})
log = logging.getLogger("SABPostProcess")

log.info("SAB post processing started.")

if len(sys.argv) < 8:
    log.error("Not enough command line parameters specified. Is this being called from SAB?")
    sys.exit()

# SABnzbd argv:
# 1 The final directory of the job (full path)
# 2 The original name of the NZB file
# 3 Clean version of the job name (no path info and ".nzb" removed)
# 4 Indexer's report number (if supported)
# 5 User-defined category
# 6 Group that the NZB was posted in e.g. alt.binaries.x
# 7 Status of post processing. 0 = OK, 1=failed verification, 2=failed unpack, 3=1+2

# Chcanged by me, use custom ini based on category
ini_file = "autoProcess-{}.ini".format(str(sys.argv[5]).lower())
log.info(ini_file)
settings = ReadSettings(
    os.path.dirname(sys.argv[0]),
    ini_file,
)

categories = [settings.SAB['sb'], settings.SAB['cp'], settings.SAB['sonarr'], settings.SAB['radarr'], settings.SAB['sr'], settings.SAB['bypass']]
category = str(sys.argv[5]).lower()
path = str(sys.argv[1])
nzb = str(sys.argv[2])

log.debug("Path: %s." % path)
log.debug("Category: %s." % category)
log.debug("Categories: %s." % categories)
log.debug("NZB: %s." % nzb)

if category.lower() not in categories:
    log.error("No valid category detected.")
    sys.exit()

if len(categories) != len(set(categories)):
    log.error("Duplicate category detected. Category names must be unique.")
    sys.exit()

# added by me - flatten dirs
for dirpath, dirnames, filenames in os.walk(path):
    for filename in filenames:
        org_file_path = os.path.join(dirpath, filename)
        dest_file_path = os.path.join(path, filename)
        if org_file_path != dest_file_path:
            if os.path.exists(dest_file_path):
                n = 1
                while True:
                    dest_file_path = os.path.join(path, "{}-{}".format(n, filename))
                    if not os.path.exists(dest_file_path):
                        break
                    n += 1
            os.rename(org_file_path, dest_file_path)
            # rm empty dirs
            if len(os.listdir(dirpath)) == 0:
                os.rmdir(dirpath)

if settings.SAB['convert']:
    log.info("Performing conversion")
    # Check for custom uTorrent output_dir
    if settings.SAB['output_dir']:
        settings.output_dir = settings.SAB['output_dir']
        log.debug("Overriding output_dir to %s." % settings.SAB['output_dir'])

    converter = MkvtoMp4(settings)
    for r, d, f in os.walk(path):
        for files in f:
            inputfile = os.path.join(r, files)
            if MkvtoMp4(settings).validSource(inputfile):
                log.info("Processing file %s." % inputfile)
                try:
                    output = converter.process(inputfile)
                except:
                    log.exception("Error converting file %s." % inputfile)
            else:
                log.debug("Ignoring file %s." % inputfile)
    if converter.output_dir:
        path = converter.output_dir
else:
    log.info("Passing without conversion.")

# Added by me, copy subs before sending to Sonarr/Radarr - because their extra import sucks (deletes some subs and doesn't keep forced tag)
def include_patterns(*patterns):
    def _ignore_patterns(path, all_names):
        keep = (name for pattern in patterns
                        for name in fnmatch.filter(all_names, pattern))
        dir_names = (name for name in all_names if isdir(join(path, name)))
        return set(all_names) - set(keep) - set(dir_names)
    return _ignore_patterns
org_path = str(sys.argv[1])
copy_path = org_path.replace('/downloads', '/subs_to_import')
# if already exists, remove old
log.info("Checking if {} already exists.".format(copy_path))
if os.path.isdir(copy_path):
    log.info("Removing {}.".format(copy_path))
    rmtree(copy_path, ignore_errors=True)
else:
    log.info("Doesn't already exist: {}.".format(copy_path))
copytree(org_path, copy_path, ignore=include_patterns('*.sub', '*.smi', '*.ssa', '*.ass', '*.vtt', '*.srt', '*.idx'))
if os.path.isdir(copy_path) and not os.listdir(copy_path):
    # If no subs found, no point having dir
    os.rmdir(copy_path)

# Send to Sickbeard
if (category == categories[0]):
    log.info("Passing %s directory to Sickbeard." % path)
    autoProcessTV.processEpisode(path, settings, nzb)
# Send to CouchPotato
elif (category == categories[1]):
    log.info("Passing %s directory to Couch Potato." % path)
    autoProcessMovie.process(path, settings, nzb, sys.argv[7])
# Send to Sonarr
elif (category == categories[2]):
    log.info("Passing %s directory to Sonarr." % path)
    sonarr.processEpisode(path, settings)
elif (category == categories[3]):
    log.info("Passing %s directory to Radarr." % path)
    radarr.processMovie(path, settings)
elif (category == categories[4]):
    log.info("Passing %s directory to Sickrage." % path)
    autoProcessTVSR.processEpisode(path, settings, nzb)
# Bypass
elif (category == categories[5]):
    log.info("Bypassing any further processing as per category.")
