#!/usr/bin/python
#
# Copyright (c) 2020 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# This script sanitizes all non boot paritions

import argparse
import os
import re
import subprocess
from glob import glob

PASSPHRASE = "1b7843342ac5e4713552a6cd1439a3e6"
ERASE_MODES = ["fast", "secure"]

rootdir_pattern = re.compile('^.*?/devices')
internal_disk_list = []

def enumerate_disks():
  """
  Enumerate non-removable disks.
  """
  for path in glob('/sys/block/*/device'):
    name = re.sub('.*/(.*?)/device', '\g<1>', path)
    with open('/sys/block/%s/device/block/%s/removable' % (name, name)) as f:
      if f.read(1) == '1':
        return
    path = rootdir_pattern.sub('', os.readlink('/sys/block/%s' % name))
    hotplug_buses = ("usb", "ieee1394", "mmc", "pcmcia", "firewire")
    for bus in hotplug_buses:
      if os.path.exists('/sys/bus/%s' % bus):
        for device_bus in os.listdir('/sys/bus/%s/devices' % bus):
          device_link = rootdir_pattern.sub('', os.readlink(
            '/sys/bus/%s/devices/%s' % (bus, device_bus)))
          if re.search(device_link, path):
            return
    internal_disk_list.append(name)

def get_boot_disk():
  ret = subprocess.Popen(["df", "/boot"],
                         stdout=subprocess.PIPE)
  out = ret.stdout.read()
  lines = out.splitlines()
  if lines <= 1:
    raise StandardError("Unable to find boot partition")
  return lines[1].split()[0][:-1]

def wipe_disk(disk, mode):
  if mode.lower() == "secure":
    cmd = ["nohup", "shred", "-n", "5", "-vz",
           "/dev/%s" % disk, "> /erase_log.txt", "2>&1 &"]
  else:
    cmd = ["dd", "if=/dev/zero", "of=/dev/%s" % disk,
           "bs=512", "count=1"]
  ret = subprocess.Popen(cmd,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
  out = ret.stdout.read()
  err = ret.stderr.read()
  print("Wipe_disk returned:\nout: %s\nerr: %s" % (out, err))

def sanitize(options):
  if options.passphrase != PASSPHRASE:
    print("Invalid passphrase")
    return
  boot_disk = get_boot_disk()
  print("Boot disk: %s" % boot_disk)
  enumerate_disks()
  for disk in internal_disk_list:
    if "/dev/%s" % disk == boot_disk:
      print("Ignoring boot disk: %s" % boot_disk)
      continue
    print("Wiping disk: %s" % disk)
    wipe_disk(disk, options.mode)

def main():
  # usage = "Usage: %prog [options]"
  parser = argparse.ArgumentParser(description="Utility to wipe all "
                                               "non-boot partitions")
  parser.add_argument("-m", "--mode", help="Erase mode",
                      action="store", dest="mode", required=True,
                      choices=ERASE_MODES)
  parser.add_argument("-p", "--passphrase", help="Secret passphrase",
                      action="store", dest="passphrase", required=True)
  parser.add_argument("--i-really-know-what-i-am-doing",
                      action="store", dest="consent", required=True)
  parser.set_defaults(func=(lambda options:
                            sanitize(options)))
  args = parser.parse_args()
  args.func(args)

if __name__ == "__main__":
  main()
