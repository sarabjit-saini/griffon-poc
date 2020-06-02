#!/usr/bin/env python
#
# Copyright (c) 2020 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# This script is used to boot node into phoenix.
import json
import os
import shutil
try:
  import wget
except ImportError:
  print("Please install wget package")
  raise SystemExit("Missing wget package")

from collections import OrderedDict
from datetime import datetime
from remote_host import RemoteHost
from remote_host import module_print
from string import Template

STAGING_DIR = "staging"
PHOENIX_STAGING_DIR = "/boot"

HOLO_KERNEL = "vmlinuz-3.10.0-1062.el7.x86_64"
HOLO_INITRD = "initramfs-3.10.0-1062.el7.x86_64.img"
AHV_KERNEL = "vmlinuz-4.19.84-2.el7.nutanix.20190916.123.x86_64"
AHV_INITRD = "initramfs-4.19.84-2.el7.nutanix.20190916.123.x86_64.img"

class LinuxHost(RemoteHost):
  """
  Perform reboot to ivu operation on remote KVM host.
  """
  def __init__(self, *args, **kwargs):
    super(LinuxHost, self).__init__(*args, **kwargs)
    self.os_type = "centos"

  def get_files_to_copy(self):
    return OrderedDict([
      ("%s/kernel" % STAGING_DIR, [PHOENIX_STAGING_DIR + "/kernel-phoenix"]),
      ("%s/initrd" % STAGING_DIR, [PHOENIX_STAGING_DIR + "/initrd-phoenix"])
    ])

  def get_boot_conf_tmpl(self):
    with open("config/grub.cfg") as fp:
      return fp.read()

  def get_phoenix_cmdline_tmpl(self):
    with open("config/phoenix_cmdline.cfg") as fp:
      return fp.read()

  def get_holo_cmdline_tmpl(self):
    with open("config/holo_cmdline.cfg") as fp:
      return fp.read()

  def get_ahv_cmdline_tmpl(self):
    with open("config/ahv_cmdline.cfg") as fp:
      return fp.read()

  def get_boot_partition(self):
    out, err, ret = self.ssh(cmd=["df", "/boot"])
    module_print("Boot partition details:\n"
                 "out %s, err %s, ret %s" %(out, err, ret))
    lines = out.splitlines()
    if lines <= 1:
      raise StandardError("Unable to find boot partition")
    return lines[1].split()[0]

  def get_home_partition(self):
    out, err, ret = self.ssh(cmd=["df", "/home"])
    module_print("Home partition details:\n"
                 "out %s, err %s, ret %s" %(out, err, ret))
    lines = out.splitlines()
    if lines <= 1:
      raise StandardError("Unable to find home partition")
    return lines[1].split()[0]

  def get_partition_uuid(self, partition):
    out, _, _ = self.ssh(cmd=["blkid", partition])
    for token in out.split():
      key, _, value = token.partition('=')
      if key.lower() == "uuid":
        return value
    raise StandardError("Unable to find uuid of partition %s" % partition)

  def get_boot_partition_uuid(self):
    """
    Returns uuid for boot partition.
    Note: This is different from PARTUUID.
    """
    partition = self.get_boot_partition()
    return self.get_partition_uuid(partition)

  def get_home_partition_uuid(self):
    """
    Returns uuid for home partition.
    Note: This is different from PARTUUID.
    """
    partition = self.get_home_partition()
    return self.get_partition_uuid(partition)

  def regenerate_grub_config(self, grubcfg):
    """
    Regenerates GRUB config
    """
    module_print("Regenerating grub config")
    cmd = "sudo grub2-mkconfig --output=%s" % grubcfg
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error updating grub configuration: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Regenerating grub config: Successful")
    return True, ""

  def get_menuentries(self, grubcfg):
    """
    Retrieve existing menuentries in grub
    """
    cmd = "awk -F\\' '$1==\"menuentry \" {print $2}' %s" % grubcfg
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error enumerating existing grub menuconfig: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    return True, out

  def in_uefi(self):
    """
    Detects whether remote host is booted in uefi or not.

    Returns: True if boot mode is uefi
    False: otherwise
    """
    cmd = ["test", "-d", "/sys/firmware/efi"]
    out, err, ret = self.ssh(cmd=cmd,
                             throw_on_error=False,
                             log_on_error=False)
    if ret:
      return False
    return True

  def get_grub_cfg(self):
    """
    Detects whether host booted in Legacy BIOS or UEFI mode
    """
    grubcfg = ""
    if self.in_uefi():
      grubcfg = "/boot/efi/EFI/centos/grub.cfg"
      module_print("Detect remote host boot mode: UEFI")
    else:
      grubcfg = "/boot/grub2/grub.cfg"
      module_print("Detect remote host boot mode: Legacy BIOS")
    return grubcfg

  def set_grub_default(self, menuentry):
    """
    Sets default grub menu entry
    """
    cmd = "sed -i 's/GRUB_DEFAULT=.*/GRUB_DEFAULT=\"%s\"/g' "\
          "/etc/default/grub" % menuentry
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error modifying defult grub entry: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Update default grub entry: Successful")
    return True, out

  def set_grub_cmdline(self, kernel, args):
    """
    Updates kernel command line args for specified kernel
    """
    k = "/boot/%s" % kernel
    module_print("Retrieving existing grub cmdline")
    cmd = "grubby --info %s" % k
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error retrieving grub cmdline: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Existing grub cmdline:\n%s" % out)

    rmargs = ""
    for line in out.strip().splitlines():
      if "args=" in line.lower():
        rmargs = line.split('=', 1)[1].strip(' \"')
    if rmargs:
      module_print("Removing existing grub cmdline arguments: %s" % rmargs)
      cmd = "grubby --remove-args=\"%s\" --update-kernel %s" % (rmargs, k)
      out, err, ret = self.ssh(cmd=cmd.split(' '))
      if ret:
        module_print("Error removing existing cmdline arguments: %s" % rmargs)
        return False, err
      module_print("Removing existing cmdline arguments: Successful")

    module_print("Adding grub cmdline options %s for %s" % (args, kernel))
    cmd = "grubby --args=\"%s\" --update-kernel %s" % (args, k)
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error updating grub cmdline: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Adding grub cmdline options for %s: Successful\n"
                 "cmd: %s, out: %s, err: %s, ret: %s" %(kernel, cmd, out, err, ret))
    return True, ""

  def generate_boot_cfg(self, config):
    """
    Generates grub for phoenix
    """
    prefix=""
    uuid = self.get_boot_partition_uuid()
    arizona_url = config["arizona_url"]
    boot_parameters = ""
    host_ip = config["host_ip"]
    phoenix_ip = config["host_ip"]
    phoenix_netmask = config["host_subnet_mask"]
    phoenix_gw = config["default_gw"]
    vlan_id = getattr(config, "svm_vlan_id", "")
    boot_script = "installer"
    type_img = "squashfs"
    griffon_ip = self.get_my_ip(host_ip)
    livefs_url = config["phoenix"]["livefs"]

    text = Template(self.get_boot_conf_tmpl()).substitute(
        foundation_ip=griffon_ip,
        foundation_port=8000,
        az_conf_url=arizona_url,
        livefs_url=livefs_url["url"],
        node_id=host_ip,
        phoenix_ip=phoenix_ip,
        phoenix_netmask=phoenix_netmask,
        phoenix_gw=phoenix_gw,
        vlan_id=vlan_id,
        boot_script=boot_script,
        session=datetime.today().strftime('%Y%m%d-%H:%M:%S'),
        bond_mode="",
        bond_uplinks="",
        bond_lacp_rate="",
        type_img=type_img,
        uuid=uuid,
        prefix=prefix,
        boot_parameters=boot_parameters
    )
    module_print("generate_boot_cfg:\n%s" % text)
    boot_cfg = os.path.join(STAGING_DIR, "grub.cfg")

    with open(boot_cfg, "w") as boot_cfg_fp:
      boot_cfg_fp.write(text)

  def generate_phoenix_cmdline(self, config):
    """
    Generates kernel command line parameters for phoenix
    """
    ahv_rootfs_part = config["partition_table"]["nutanix"]["id"]
    boot_part = self.get_boot_partition()
    boot_dev = boot_part[:-1]
    ahv_part = boot_dev + str(ahv_rootfs_part)
    cmd = "blkid %s" % ahv_part
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error checking Ahv partition UUID: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    lines = out.strip().splitlines()
    ahv_uuid = lines[0].split()[1].replace('"', '')

    prefix=""
    arizona_url = config["arizona_url"]
    boot_parameters = "NUTANIX_PART=%s" % ahv_rootfs_part

    module_print("\nDownloading arizona config....\n")
    wget.download(config["arizona_url"], "%s/arizona.conf" % STAGING_DIR)
    with open("%s/arizona.conf" % STAGING_DIR, "r") as f:
      cfg = json.load(f)
    host_ip = cfg["host_ip"]
    phoenix_ip = cfg["host_ip"]
    phoenix_netmask = cfg["host_subnet_mask"]
    phoenix_gw = cfg["default_gw"]
    vlan_id = getattr(cfg, "svm_vlan_id", "")
    boot_script = config["phoenix"]["mode"].lower()
    type_img = "squashfs"
    griffon_ip = self.get_my_ip(host_ip)
    livefs_url = config["phoenix"]["livefs"]

    text = Template(self.get_phoenix_cmdline_tmpl()).substitute(
        phx_uuid=ahv_uuid,
        foundation_ip=griffon_ip,
        foundation_port=8000,
        az_conf_url=arizona_url,
        livefs_url=livefs_url["url"],
        phoenix_ip=phoenix_ip,
        phoenix_netmask=phoenix_netmask,
        phoenix_gw=phoenix_gw,
        vlan_id=vlan_id,
        boot_script=boot_script,
        session=datetime.today().strftime('%Y%m%d-%H:%M:%S'),
        bond_mode="",
        bond_uplinks="",
        bond_lacp_rate="",
        type_img=type_img,
        prefix=prefix,
        boot_parameters=boot_parameters
    )
    module_print("\ngenerate_phoenix_cmdline:\n%s" % text.strip())
    return text.strip()

  def generate_holo_cmdline(self, config):
    """
    Generates kernel command line parameters for holo
    """
    holo_rootfs_part = config["partition_table"]["holo"]["id"]
    boot_part = self.get_boot_partition()
    boot_dev = boot_part[:-1]
    holo_part = boot_dev + str(holo_rootfs_part)
    cmd = "blkid %s" % holo_part
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error checking Holo partition UUID: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    lines = out.strip().splitlines()
    holo_uuid = lines[0].split()[1].replace('"', '')
    module_print("Holo UUID: %s" % holo_uuid)
      
    text = Template(self.get_holo_cmdline_tmpl()).substitute(
      holo_uuid=holo_uuid
    )
    module_print("generate_holo_cmdline: %s" % text.strip()) 
    return text.strip()

  def generate_ahv_cmdline(self, config=None):
    """
    Generates kernel command line parameters for ahv
    """
    ahv_rootfs_part = config["partition_table"]["nutanix"]["id"]
    boot_part = self.get_boot_partition()
    boot_dev = boot_part[:-1]
    ahv_part = boot_dev + str(ahv_rootfs_part)
    cmd = "blkid %s" % ahv_part
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error checking Ahv partition UUID: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    lines = out.strip().splitlines()
    ahv_uuid = lines[0].split()[1].replace('"', '')
    module_print("Ahv UUID: %s" % ahv_uuid)

    text = Template(self.get_ahv_cmdline_tmpl()).substitute(
      ahv_uuid=ahv_uuid
    )
    module_print("generate_ahv_cmdline: %s" % text.strip())
    return text.strip()

  def remove_from_fstab(self, partition):
    """
    Removes mountpoints on a given partition from fstab
    """
    boot_part = self.get_boot_partition()
    boot_dev = boot_part[:-1]
    part = boot_dev + str(partition)
    cmd = "blkid %s" % part
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error checking partition UUID: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("%s" % out)
    lines = out.strip().splitlines()
    target_uuid = lines[0].split()[1].replace('"', '')
    module_print("Target UUID: %s" % target_uuid)

    cmd = "cat /etc/fstab"
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error enumerating fstab entries: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Fstab entries:\n%s" % out)

    cmd = "sed -i.bak '\@^%s@d' /etc/fstab" % target_uuid
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      module_print("Error removing entry from fstab: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Fstab successfully updated")

    cmd = "cat /etc/fstab"
    out, _, ret = self.ssh(cmd=cmd.split(' '))
    if not ret:
      module_print("Fstab entries:\n%s" % out)
    return True, ""

  def revert_grub(self, grubcfg):
    """
    Reverts back the original grub file from backup
    """
    module_print("Reverting grub configuration changes")
    cmd = ["mv", "%s.backup" % grubcfg, "%s" % grubcfg]
    out, err, ret = self.ssh(cmd=cmd)
    if ret:
      module_print("Error reverting original grub configuration: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    return True, ""

  def stage_phoenix(self, config):
    """
    Stages phoenix payloads
    """
    try:
      shutil.rmtree(STAGING_DIR)
      if not os.path.exists(STAGING_DIR):
        os.mkdir(STAGING_DIR)
    except OSError:
      module_print("Error: Creating directory %s" % STAGING_DIR)

    # Download phoenix payload to staging area
    module_print("\nDownloading phoenix kernel....\n")
    wget.download(config["phoenix"]["kernel"]["url"], "%s/kernel" % STAGING_DIR)
    module_print("\nDownloading phoenix initrd....\n")
    wget.download(config["phoenix"]["initrd"]["url"], "%s/initrd" % STAGING_DIR)
    module_print("\nSuccessfully downloaded files\n")

    # Stage phoenix payload on remote host
    module_print("Staging files on host")
    files = self.get_files_to_copy()
    for src, dsts in files.items():
      for dst in dsts:
        out, err, ret = self.scp(target=dst, files=[src]) 
        if ret:
          return False, err
    module_print("Staging files on host: Successful")

    module_print("Setting execute permissions on phoenix kernel")
    cmd = "chmod +x /boot/kernel-phoenix"
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      self.revert_grub(grubcfg)
      module_print("Error setting execute permissions on phoenix kernel: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Setting execute permissions on phoenix kernel: Successful")

    module_print("Renaming base kernel and initramfs")
    cmd = "mv /boot/%s "\
          "/boot/kernel-holo && mv /boot/%s "\
          "/boot/initrd-holo && chmod +x /boot/kernel-holo" % (
          HOLO_KERNEL, HOLO_INITRD)
    out, err, ret = self.ssh(cmd=cmd.split(' '))
    if ret:
      self.revert_grub(grubcfg)
      module_print("Error renaming base kernel and initrd: "
                   "cmd: %s, out: %s, err: %s, ret: %s" %(cmd, out, err, ret))
      return False, err
    module_print("Renaming base kernel and initramfs: Successful")

    grubcfg = self.get_grub_cfg()
    module_print("Backing up grub configuration file")
    cmd = ["cp", "%s" % grubcfg, "%s.backup" % grubcfg]
    self.ssh(cmd=cmd)

    module_print("Unmount the nutanix partition and remove "
                 "entry from fstab")
    ahv_rootfs_part = config["partition_table"]["nutanix"]["id"]
    ret, err = self.remove_from_fstab(ahv_rootfs_part)
    if not ret:
      module_print("Could not remove nutanix partition mountpoint "
                   "from fstab")
      return False, err
    return True, "Stage Phoenix: Successful"
    
  def reboot_to_target(self, target, config):
    """
    Reboots host and waits for it to boot into target OS
    """
    if not isinstance(target, basestring) or \
      target.lower() not in ["holo", "phoenix", "ahv"]:
        module_print("Invalid target os %s specified" % target)
        return False, "Invalid target os %s specified" % target

    taret = target.lower()
    kernel = {"holo": "kernel-holo",
              "phoenix": "kernel-phoenix",
              "ahv": AHV_KERNEL}
    menukey = {"holo": "holo",
               "phoenix": "phoenix",
               "ahv": "nutanix"}
    try:
      grubcfg = self.get_grub_cfg()
      ret, out = self.regenerate_grub_config(grubcfg)
      if not ret:
        return False, out

      module_print("Marking %s as default in grub config" % target)
      ret, out = self.get_menuentries(grubcfg)
      if not ret:
        return False, out

      for line in out.strip().splitlines():
        if not menukey[target] in line.lower():
          continue
        else:
          module_print("Update default grub entry")
          menuentry = line
          module_print("Menuentry: %s" % menuentry)
          ret, out = self.set_grub_default(menuentry)
          if not ret:
            return False, out
          module_print("Update default grub entry: Successful")

          module_print("Updating grub config")
          ret, out = self.regenerate_grub_config(grubcfg)
          if not ret:
            return False, out
          module_print("Updating grub config: Successful")

          cmdline_fn = {
            "phoenix": self.generate_phoenix_cmdline,
            "holo": self.generate_holo_cmdline,
            "ahv": self.generate_ahv_cmdline
          }
          module_print("Update grub cmdline options for %s" % target)
          cmdline = cmdline_fn[target](config)
          ret, out = self.set_grub_cmdline(kernel=kernel[target],
                                           args=cmdline)
          if not ret:
            return False, out

      module_print("Rebooting the host")
      out, err, ret = self.ssh(cmd=["reboot", "-f"])
      err_msg = ("Reboot host returned : "
                 "out: %s, err: %s, ret: %s" % (out, err, ret))
      module_print(err_msg)

      module_print("Waiting for node to reboot into %s......" % target)
      ret, os_type = self.wait_for_host()
      if ret and os_type == target:
        module_print("Node successfully booted into %s" % target)
        return True, ""
      if ret:
        module_print("Node did not boot into %s" % target)
        return False, "Node booted into %s" % os_type
    except Exception as e:
      err_msg = ("Exception while rebooting host into target %s: "
                 "'%s'" % (target, str(e)))
      module_print(err_msg)
      return False, err_msg

  def sanitize_node(self, options, config):
    """
    Sanitizes Nutanix partitions
    """
    try:
      # Ensure the node is running AHV
      os_type = RemoteHost._detect_remote_os_type(options.node_ip)
      if os_type != "ahv":
        err_msg = ("This workflow is only supported on AHV for now. "
                   "Detected OS: %s" % os_type)
        module_print(err_msg)
        return False, err_msg
      module_print("Node %s is running AHV" % options.node_ip)
      # Reboot into HOLO
      in_holo, msg = self.reboot_to_target(target="holo", config=config)
      if not in_holo:
        err_msg = "Could not reboot into holo partition"
        module_print("err_msg")
        return False, err_msg
      else:
        # Stage the sanitize script in HOLO
        module_print("Staging santization scripts on host")
        out, err, ret = self.scp(target="/sanitize_disks.py",
                                 files=["./sanitize_disks.py"])
        if ret:
          err_msg = "Unable to stage sanitization script to node\n"\
                    "out: %s\nerr: %s\nret: %s" % (out, err, ret)
          module_print(err_msg)
          return False, err_msg
        module_print("Stages sanitization script to node: Successful\n"\
                     "out: %s\nerr: %s\nret: %s" % (out, err, ret))
        # Set execute bit of script
        cmd = "chmod +x /sanitize_disks.py"
        out, err, ret = self.ssh(cmd=cmd.split(' '))
        if ret:
          err_msg = "Unable to set execute permission for sanitization script"
          module_print(err_msg)
          return False, err_msg
        module_print("Change execute permissions on host: Successful\n"\
                     "out: %s\nerr: %s\nret: %s" % (out, err, ret))
        return True, "Dummy return from sanitize_node"
        # Execute sanitization script on host
        module_print("Executing santization scripts on host")
        cmd = "python /sanitize_disks.py -m fast "\
              "-p 1b7843342ac5e4713552a6cd1439a3e6 "\
              "--i-really-know-what-i-am-doing"
        out, err, ret = self.ssh(cmd=cmd.split(' '))
        if ret:
          err_msg = "Unable to execute sanitization script\n"\
                    "out: %s\nerr: %s\nret: %s" % (out, err, ret)
          module_print(err_msg)
          return False, err_msg
        module_print("Executing santization scripts on host: Successful\n"
                     "out: %s\nerr: %s\nret: %s" % (out, err, ret))
        return True, ""
    except Exception as e:
      err_msg = ("Failed to sanitize node '%s'" % str(e))
      module_print(err_msg)
      return False, err_msg
    return False, "Unable to locate Holo menuentry in grub" 
