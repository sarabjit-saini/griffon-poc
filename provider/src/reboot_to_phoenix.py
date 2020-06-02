#!/usr/bin/env python
#
# Copyright (c) 2019 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# Class to boot node into Phoenix.

from remote_host import (RemoteHost, module_print)

class RebootToPhoenix(object):
  """
  Base class to perform operations on reboot to Phoenix.
  """
  def __init__(self, options):
    self.options = options
    self.host = None

  def reboot_to_phoenix(self):
    """
    Reboots specified node into Phoenix.
    Returns:
      True: Node successfully booted into Phoenix.
      False: Error rebooting node into Phoenix.
    Raises:
      StandardError
    """
    self.host = RemoteHost.get_instance(self.options)
    if not self.host:
      module_print("Unable to get the Remote Host type")
      return False
    import json
    with open(self.options.config, "r") as f:
      cfg = json.load(f)
    ret, err = self.host.reboot_to_target(target="phoenix", config=cfg)
    if not ret:
      module_print("Unable to boot node [%s] into Phoenix err: [%s]" %
                   (self.options.node_ip, err))
      return False

    # wait for node to boot into Phoenix
    module_print("Successfully booted into Phoenix")
    return True
