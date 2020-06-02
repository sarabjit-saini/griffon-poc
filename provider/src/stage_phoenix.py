#!/usr/bin/env python
#
# Copyright (c) 2020 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# Class to stage phoenix payload on remote node.

from remote_host import (RemoteHost, module_print)

class StagePhoenix(object):
  """
  Base class to stage phoenix payload on remote node.
  """
  def __init__(self, options):
    self.options = options
    self.host = None

  def stage_phoenix(self):
    """
    Staged phoenix payload on remote node.
    Returns:
      True: Payload successfully staged.
      False: Error staging payload.
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
    ret, err = self.host.stage_phoenix(cfg)
    if not ret:
      module_print("Unable to stage phoenix payload "
                   "on node [%s] err: [%s]" %
                   (self.options.node_ip, err))
      return False

    # wait for ivu to come back up
    module_print("Successfully staged phoenix payload")
    return True
