#!/usr/bin/env python
#
# Copyright (c) 2019 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# Class to sanitize nutanix partitions.

from remote_host import (RemoteHost, module_print)

class SanitizeNode(object):
  """
  Base class to perform sanitization operations on node.
  """
  def __init__(self, options, part):
    self.options = options
    self.ntnx_part = part

  def sanitize_node(self):
    """
    Sanitizes Nutanix partition on remote host.
    Returns:
      True: Sanitization successfully completed.
      False: Sanitization Error occurred.
    Raises:
      StandardError
    """
    self.host = RemoteHost.get_instance(self.options)
    if not self.host:
      module_print("Unable to get the Remote Host type")
      return False

    import json
    try:
      with open(self.options.config, "r") as f:
        cfg = json.load(f)
    except ValueError as e:
      module_print("Invalid json data in config file: %s" % str(e))
      return False

    ret, err = self.host.sanitize_node(self.options, cfg)
    if not ret:
      module_print("Unable to sanitize node [%s] err: [%s]" %
                   (self.options.node_ip, err))
      return False

    module_print("Successfully sanitized node")
    return True
