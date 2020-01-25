#!/usr/bin/env python

import os
import re
import sys
import shutil
from shutil import copytree, rmtree
from autoprocess import autoProcessTV, autoProcessMovie, autoProcessTVSR, sonarr, radarr
from readSettings import ReadSettings
from mkvtomp4 import MkvtoMp4
import logging
from logging.config import fileConfig
import fnmatch
from os.path import isdir, join, basename, splitext

try:
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
    log = logging.getLogger("qBittorrentPostProcess")

    log.info("qBittorrent post processing started.")

    torrent_hash = sys.argv[1]
    try:
        label = sys.argv[2]
    except IndexError:
        log.info("No label - so no processing")
        sys.exit()

    # Chcanged by me, use custom ini based on category
    ini_file = "autoProcess-{}.ini".format(str(label).lower())
    log.info(ini_file)
    settings = ReadSettings(
        os.path.dirname(sys.argv[0]),
        ini_file,
    )

    categories = [settings.qBittorrent['cp'], settings.qBittorrent['sb'], settings.qBittorrent['sonarr'], settings.qBittorrent['radarr'], settings.qBittorrent['sr'], settings.qBittorrent['bypass']]

    if label not in categories:
        log.error("No valid label detected.")
        sys.exit()

    if len(categories) != len(set(categories)):
        log.error("Duplicate category detected. Category names must be unique.")
        sys.exit()

    # Import python-qbittorrent
    try:
        from qbittorrent import Client
    except ImportError:
        log.exception("Python module PYTHON-QBITTORRENT is required. Install with 'pip install python-qbittorrent' then try again.")
        sys.exit()

    qb = Client(settings.qBittorrent['host'])
    qb.login(settings.qBittorrent['username'], settings.qBittorrent['password'])
    log.info("Pausing all torrents")
    qb.pause_all()

    torrent_name = qb._get('query/torrents', params={'hashes': torrent_hash})[0]['name']
    torrent_save_path = qb.get_torrent(torrent_hash)['save_path']
    torrent_files = [f['name'] for f in qb.get_torrent_files(torrent_hash)]

    if not torrent_name:
        raise Exception("Torrent name could not be fetched")

    copy_to = "/downloads/{}".format(torrent_name)
    if os.path.exists(copy_to):
        log.info("Removing existing copy_to of {}".format(copy_to))
        rmtree(copy_to, ignore_errors=True)

    log.info("Creating copy_to of {}".format(copy_to))
    os.makedirs(copy_to)

    for torrent_file in torrent_files:
        source_path = "{}/{}".format(torrent_save_path, torrent_file)
        target_path = "{}/{}".format(copy_to, basename(torrent_file))
        if os.path.exists(target_path):
            n = 1
            while True:
                target_path = "{}/{}-{}".format(copy_to, n, basename(torrent_file))
                if not os.path.exists(target_path):
                    break
                n += 1

        if not os.path.exists(source_path) or not os.path.isfile(source_path):
            raise Exception('{} does not exist.'.format(source_path))

        if os.path.exists(target_path):
            if os.path.isfile(target_path):
                log.info("Removing existing {} as to be replaced".format(target_path))
                os.remove(target_path)
            else:
                raise Exception('{} is not a file.'.format(target_path))

        shutil.copy(source_path, target_path)

    if settings.qBittorrent['convert']:
        log.info("Performing conversion")
        # Use None to mean it converts to current (already copied) location
        settings.output_dir = None

        converter = MkvtoMp4(settings)
        for r, d, f in os.walk(copy_to):
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

    sub_copy_path = copy_to.replace('/downloads', '/subs_to_import')
    # if already exists, remove old
    log.info("Checking if {} already exists.".format(sub_copy_path))
    if os.path.isdir(sub_copy_path):
        log.info("Removing {}.".format(sub_copy_path))
        rmtree(sub_copy_path, ignore_errors=True)
    else:
        log.info("Doesn't already exist: {}.".format(sub_copy_path))
    copytree(copy_to, sub_copy_path, ignore=include_patterns('*.sub', '*.smi', '*.ssa', '*.ass', '*.vtt', '*.srt', '*.idx'))
    if os.path.isdir(sub_copy_path) and not os.listdir(sub_copy_path):
        # If no subs found, no point having dir
        os.rmdir(sub_copy_path)

    if label == categories[0]:
        log.info("Passing %s directory to Couch Potato." % copy_to)
        autoProcessMovie.process(copy_to, settings)
    elif label == categories[1]:
        log.info("Passing %s directory to Sickbeard." % copy_to)
        autoProcessTV.processEpisode(copy_to, settings)
    elif label == categories[2]:
        log.info("Passing %s directory to Sonarr." % copy_to)
        sonarr.processEpisode(copy_to, settings)
    elif label == categories[3]:
        log.info("Passing %s directory to Radarr." % copy_to)
        radarr.processMovie(copy_to, settings)
    elif label == categories[4]:
        log.info("Passing %s directory to Sickrage." % copy_to)
        autoProcessTVSR.processEpisode(copy_to, settings)
    elif label == categories[5]:
        log.info("Bypassing any further processing as per category.")

    log.info("Resuming all torrents")
    qb.resume_all()

# added by me - ensure if it fails - torrents keep seeding
except Exception as e:
    log.error("Error processing: {}".format(e))
    log.info("Resuming all torrents")
    qb.resume_all()
    raise e
