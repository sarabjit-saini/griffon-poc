#!/usr/bin/env python
#
# Copyright (c) 2019 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# Class to boot node into AHV.

from remote_host import (RemoteHost, module_print)

class RebootToAhv(object):
  """
  Base class to perform operations on reboot to Ahv.
  """
  def __init__(self, options):
    self.options = options
    self.host = None

  def reboot_to_ahv(self):
    """
    Reboots specified node into Ahv.
    Returns:
      True: Node successfully booted into Ahv.
      False: Error rebooting node into Ahv.
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
    ret, err = self.host.reboot_to_target(target="ahv", config=cfg)
    if not ret:
      module_print("Unable to boot node [%s] into Ahv err: [%s]" %
                   (self.options.node_ip, err))
      return False

    # wait for node to boot into Ahv
    module_print("Successfully booted into Ahv")
    return True
