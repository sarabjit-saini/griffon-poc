#!/usr/bin/env python
#
# Copyright (c) 2019 Nutanix Inc. All rights reserved.
#
# Author: sarabjit.saini@nutanix.com
#
# This script kickstarts imaging process on remote cloud instance.

import json
import os
import socket
import sys
import time
import threading

SSH_TIMEOUT = 30
SSH_SEMA = threading.Semaphore(value=32)
MAX_BOOT_WAIT_CYCLES = 6 * 60     # 1 hour
CHECK_INTERVAL_S = 10

try:
  import paramiko
  from scp import SCPClient, SCPException
except ImportError:
  print("Please install paramiko package before running this utility")
  raise SystemExit("Required package paramiko missing")

SSH_TIMEOUT = 120
SCP_RETRIES = 3
STAGING_DIR = "/home/nutanix/phoenix"
SVM_CFG_FILE = "%s/svm_cfg.json" % STAGING_DIR
SVM_TMP_PATH = "/tmp/svm_cfg.json"

MAX_BOOT_WAIT_CYCLES = 6 * 5     # 5 minutes.
CHECK_INTERVAL_S = 10
HOST_DEFAULT_USER = "root"
CVM_USERNAME = "nutanix"

class RemoteHost(object):
  """
  Base class to perform operations on remote host.
  """
  SUPPORTED_OS = ["esx", "ahv", "centos"]

  def __init__(self, options):
    self.options = options

  @staticmethod
  def get_instance(options):
    """
    Get the Remote Host instance
    :param options:
    :return: Host instance
    """
    os_type = RemoteHost._detect_remote_os_type(options.node_ip)

    module_print("Detected remote os type [%s]" % os_type)
    if os_type == "ahv":
      from linux_host import LinuxHost
      return LinuxHost(options)
    elif os_type == "esx":
      from esx_host import EsxHost
      return EsxHost(options)
    elif os_type == "centos":
      from linux_host import LinuxHost
      return LinuxHost(options)
    elif os_type == "phoenix":
      from linux_host import LinuxHost
      return LinuxHost(options)
    else:
      module_print("OS type '%s' is not supported for this "
                   "workflow" % os_type)
      module_print("Supported OSes : [%s]" %
                   RemoteHost.SUPPORTED_OS)
      return None

  @staticmethod
  def _detect_remote_os_type(node_ip):
    """
    Detects underlying os type of remote node.
    """
    out, err, ret = RemoteHost._ssh(node_ip, command=["uname", "-a"], user="root",
                                    log_on_error=False, throw_on_error=False)
    if not ret:
      if "vmkernel" in out.lower():
        return "esx"
      elif "linux" in out.lower():
        out, _, ret = RemoteHost._ssh(node_ip, command=[
                                      "test", "-f", "/etc/nutanix-release"],
                                      user="root", log_on_error=False,
                                      throw_on_error=False)
        if not ret:
          return "ahv"
        out, _, ret = RemoteHost._ssh(node_ip, command=[
                                      "test", "-f", "/usr/bin/layout_finder.py"],
                                      user="root", log_on_error=False,
                                      throw_on_error=False)
        if not ret:
          return "phoenix"
        out, _, ret = RemoteHost._ssh(node_ip, command=[
                                      "cat", "/etc/centos-release"],
                                      user="root", log_on_error=False,
                                      throw_on_error=False)
        if not ret:
          if "Linux" in out.strip() and "7.7" in out.strip():  
            return "centos"
      else:
        module_print("Remote host seems to be a Linux-like host but "
                     "could not determine the exact flavor. "
                     "stdout: %s\nstderr: %s\n" % (out, err))
    return ""

  @staticmethod
  def is_node_up(self):
    """
    Checks if node is reachable
    """
    module_print("Checking host ip %s" % self.options.node_ip)
    out, _, ret = self.ssh(cmd=["true"])
    if ret:
      return False
    return True

  @staticmethod
  def wait_for_host(self):
    """
    Wait for node to boot up an try to detect the OS

    Return True, os_type if node has successfully booted up and OS is
           recognized.
           False, "" otherwise
    """
    # Wait until we can ssh to Holo
    for i in range(MAX_BOOT_WAIT_CYCLES):
      if self.is_node_up():
        module_print("Node is up, detecting OS")
        os_type = self._detect_remote_os_type(self.options.node_ip)
        return True, os_type
      module_print("[%s/%s] Waiting for node to boot up" % (i, MAX_BOOT_WAIT_CYCLES))
      time.sleep(CHECK_INTERVAL_S)
    return False, ""

  @staticmethod
  def get_ssh_client(*args, **kwargs):
    with SSH_SEMA:
      timeout = kwargs.get("timeout", None)
      assert timeout is None or timeout > 0, (
        "timeout cannot be negative: %s" % timeout)

      client = paramiko.SSHClient()
      client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

      # Switch to paramiko 2.2.0+?
      # see https://github.com/paramiko/paramiko/issues/869
      if timeout:
        timer = threading.Timer(timeout, client.close)
        timer.daemon = True
        timer.start()
      else:
        timer = None

      client.connect(*args, **kwargs)

      if timer:
        timer.cancel()
      return client

  @staticmethod
  def _ssh(ip, command, throw_on_error=True, user="nutanix",
           password="nutanix/4u", log_on_error=True, timeout=SSH_TIMEOUT,
           get_pty=False, **kwargs):
    """
    Execute the commands via ssh on the remote machine with given ip.
    """
    ssh_client = None
    params = {"hostname": ip, "username": user, "password": password}
    if timeout:
      params["timeout"] = timeout
    params.update(kwargs)

    try:
      client = RemoteHost.get_ssh_client(**params)
    except (paramiko.AuthenticationException, paramiko.SSHException,
            socket.error, Exception) as e:
      if log_on_error:
        module_print("Exception on executing cmd: %s" % command)
      if throw_on_error:
        raise
      else:
        return "", str(e), -1

    cmd_str = " ".join(command)
    module_print("[%s]Running command [%s]" % (ip, cmd_str))

    out, err = [], []
    # use Timer to shutdown client.exec_command, the paramiko's
    # client.exec_command doesn't really timeout when the remote ssh service or
    # command stuck. client.close will close all channels and unblock this thread
    if timeout:
      timer = threading.Timer(timeout, client.close)
      timer.daemon = True
      timer.start()
    else:
      timer = None

    try:
      stdin, stdout, stderr = client.exec_command(cmd_str, get_pty=get_pty, timeout=timeout)
      channel = stdout.channel
      while not channel.exit_status_ready():
        if channel.recv_ready():
          outbuf = channel.recv(1024)
          while outbuf:
            out.append(outbuf)
            outbuf = channel.recv(1024)
        if channel.recv_stderr_ready():
          errbuf = channel.recv_stderr(1024)
          while errbuf:
            err.append(errbuf)
            errbuf = channel.recv_stderr(1024)
      else:
        out.append(stdout.read())
        err.append(stderr.read())
      exit_status = stdout.channel.recv_exit_status()
    except (socket.timeout, paramiko.SSHException, EOFError) as e:
      # paramiko.transport.py:open_channel raises EOFError
      err.append(str(e))
      exit_status = -1
    finally:
      client.close()

    if timer:
      timer.cancel()

    out = "".join(out)
    err = "".join(err)

    # module_print("ssh: %s\n%s" % (cmd_str, out))

    if exit_status != 0:
      message = "Command '%s' returned error code %d\n" % (
                " ".join(command), exit_status)
      message += "stdout:\n%s\nstderr:\n%s" % (out, err)
      if log_on_error:
        module_print("%s" % message)
      if throw_on_error:
        raise StandardError(message)

    return out, err, exit_status

  @staticmethod
  def _scp(ip, target_path, files,
           throw_on_error=True, user="nutanix",
           password="nutanix/4u", log_on_error=True, timeout=SSH_TIMEOUT,
           recursive=False):
    """
    Transfer files via scp on the remote machine with given ip.

    Args:
      timeout: Use None for no-timeout limit , do not use -1, that means
      timeout immediately after (or before) connect.
    """
    client = None
    params = {"hostname": ip, "username": user, "password": password}
    if timeout:
      params["timeout"] = timeout

    try:
      client = RemoteHost.get_ssh_client(**params)
    except (paramiko.AuthenticationException, paramiko.SSHException,
            socket.error, Exception) as e:
      if log_on_error:
        module_print("Failed to connect to remote host %s" % ip)
      if throw_on_error:
        raise
      else:
        return "", str(e), -1

    scp_client = SCPClient(client.get_transport(), socket_timeout=timeout)
    module_print("[%s] copying files %s -> %s" % (ip, files[0], target_path))
    try:
      scp_client.put(files, target_path, recursive=recursive)
    except SCPException as e:
      if log_on_error:
        module_print("Failed to scp files %s to %s:%s" % (files, ip, target_path))
      if throw_on_error:
        raise
      return "", str(e), -1
    return "", "", 0

  @staticmethod
  def get_my_ip(dest_ip, port=80):
    """
    Find local external IP address by UDP connect.

    NOTE: dest_ip:port could be an invalid UDP address, `connect` will route
    the local socket, no packet is send in this process.

    Raises:
      socket.error(IOError) when dest_ip is not in the same subnet and default
      gateway is not set.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((dest_ip, port))
    my_ip = s.getsockname()[0]
    s.close()
    return my_ip

  def node_ip(self):
    return self.options.node_ip

  def ssh(self, cmd, ip=None, user="root", **kwargs):
    if ip is None:
      ip = self.options.node_ip
    return RemoteHost._ssh(ip=ip, command=cmd, user=user, **kwargs)

  def scp(self, target, files, user="root"):
    return RemoteHost._scp(ip=self.options.node_ip,
                           target_path=target, files=files, user=user)

  def reboot_to_phoenix(self):
    raise NotImplementedError

  def is_host_up(self):
    """
    Checks if node is reachable via ssh.

    Returns:
      True if node is reachable. False, otherwise
    """
    module_print("Checking host ip %s" % options.node_ip)
    _, _, ret = self.ssh(cmd=["true"])
    if ret:
      return False
    return True

  def is_phoenix_up(self):
    """
    Checks if node is in phoenix by checking if
    /phoenix/layout/layout_finder.py is present

    Returns:
      True if node is in Phoenix. False, otherwise
    """
    module_print("Checking host ip %s" % options.node_ip)
    _, _, ret = self.ssh(cmd=["test", "-f", "/usr/bin/layout_finder.py"])
    if ret:
      return False
    return True

  def wait_for_phoenix(self):
    """
    Wait for node to boot into phoenix.

    Return True if node has successfully booted into phoenix.
    False otherwise.
    """
    # Wait until we can ssh to Phoenix
    for i in range(MAX_BOOT_WAIT_CYCLES):
      if self.is_phoenix_up():
        module_print("Phoenix is up")
        return True
      module_print("[%s/%s] Waiting for Phoenix" % (i, MAX_BOOT_WAIT_CYCLES))
      time.sleep(CHECK_INTERVAL_S)
    return False

  def is_ahv_up(self):
    """
    Checks if node is in ahv by checking uname -a.

    Returns:
      True if node is in Ahv. False, otherwise
    """
    module_print("Checking host ip %s" % options.node_ip)
    out, err, ret = self.ssh(cmd=["uname", "-a"])
    if ret:
      module_print("Error executing command: "
                   "cmd: %s, out: %s, err: %s" % (cmd, out, err))
      return False
    if "linux" in out.lower() and ".nutanix." in out.lower():
      return True
    return False

  def wait_for_ahv(self):
    """
    Wait for node to boot into ahv.

    Return True if node has successfully booted into ahv.
    False otherwise.
    """
    # Wait until we can ssh to Phoenix
    for i in range(MAX_BOOT_WAIT_CYCLES):
      if self.is_ahv_up():
        module_print("Hypervisor is up")
        return True
      module_print("[%s/%s] Waiting for AHV" % (i, MAX_BOOT_WAIT_CYCLES))
      time.sleep(CHECK_INTERVAL_S)
    return False

def module_print(msg):
  """
  Print the message
  :param msg:
  :return:
  """
  print(msg)
