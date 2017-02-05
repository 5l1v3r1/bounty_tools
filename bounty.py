#!/usr/bin/env python


import paramiko
import digitalocean
import configparser
import argparse
import time
import progressbar
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from bounty_db import Host, Base


def setup_vm(manager, config, verbose):
    droplet = digitalocean.Droplet(token=manager.token, name="recon-droplet", region="nyc1", image="ubuntu-16-04-x64",
                                   size_slug="512mb", ssh_keys=manager.get_all_sshkeys(), backups=False)
    print("Creating the droplet...")
    droplet.create()

    print("Waiting for the droplet to be active...")
    # Wait for the DO droplet to become active
    bar = progressbar.ProgressBar()
    while droplet.status != "active":
        print("Sleeping for 30 seconds to wait for the droplet to become active.")
        for i in (bar(range(30))):
            time.sleep(1)
        droplet.load()

    # Show progress
    print()
    droplet.load()
    print("Droplet has been created with the address {}".format(droplet.ip_address))

    # Setup the SSH connection
    print()
    print("Sleeping for 30 seconds to wait for SSH to be ready...")
    bar = progressbar.ProgressBar()
    for i in (bar(range(30))):
        time.sleep(1)
    ssh_key_filename = config.get("DigitalOcean", "ssh_key_filename")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("Connecting to the droplet...")
    ssh.connect(droplet.ip_address, username="root", key_filename=ssh_key_filename)

    # Configure the VM with the setup script
    print()
    print("Setting up the droplet with the configuration script...")
    _, stdout, stderr = ssh.exec_command(
        "wget -O - https://raw.githubusercontent.com/gradiuscypher/bounty_tools/master/scripts/setup_do_vm.sh | bash")

    # Print the output of configuration
    for line in iter(lambda: stdout.readline(2048), ""):
        print(line)
    print("I'm done setting up the droplet.")

    return droplet


def run_recon(manager, droplet, config, workspace, domain_list):
    # Setup SSH
    ssh_key_filename = config.get("DigitalOcean", "ssh_key_filename")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("Connecting to the droplet...")
    ssh.connect(droplet.ip_address, username="root", key_filename=ssh_key_filename)

    # Do all the stuff with recon-ng
    recon_modules = [
        "recon/domains-hosts/google_site_web",
        "recon/domains-hosts/brute_hosts",
        "recon/domains-hosts/bing_domain_web",
        "recon/domains-hosts/hackertarget",
        "recon/domains-hosts/ssl_san",
        "recon/domains-hosts/threatcrowd",
        "recon/hosts-hosts/resolve",
    ]

    # Add domains to workspace
    for domain in domain_list:
        print("Adding domain: {}".format(domain))
        _, stdout, stderr = ssh.exec_command('./recon-ng/recon-cli -w {} -C "add domains {}"'.format(workspace, domain))
        # Print the output of execution
        for line in iter(lambda: stdout.readline(2048), ""):
            print(line)
        print()

    # Execute recon-ng modules
    for module in recon_modules:
        print("Executing recon-ng module: {}".format(module))
        _, stdout, stderr = ssh.exec_command('./recon-ng/recon-cli -w {} -m "{}" -x'.format(workspace, module))
        # Print the output of execution
        for line in iter(lambda: stdout.readline(2048), ""):
            print(line)
        print()

    # Remove hosts from recon-ng db where there is no IP
    print("Removing hosts without IP addresses from the DB...")
    _, stdout, stderr = ssh.exec_command(
        './recon-ng/recon-cli -w {} -C "query delete from hosts where ip_address is null"'.format(workspace))
    # Print the output of execution
    for line in iter(lambda: stdout.readline(2048), ""):
        print(line)
    print()


def import_to_db(manager, droplet, config, workspace):
    # Setup SSH
    ssh_key_filename = config.get("DigitalOcean", "ssh_key_filename")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("Connecting to the droplet...")
    ssh.connect(droplet.ip_address, username="root", key_filename=ssh_key_filename)

    # Collect recon-ng db file
    sftp = ssh.open_sftp()
    sftp.chdir("/root/.recon-ng/workspaces/{}".format(workspace))
    sftp.get("data.db", "{}.db".format(workspace))

    # Build the DB connection and import the data
    engine = create_engine("sqlite:///recon.db")
    Base.metadata.bind = engine
    DBSession = sessionmaker(bind=engine)
    session = DBSession()

    # Iterate through recon-ng db and add host data to recon.db
    # new_host = Host(ip_address="0.0.0.0", host="testhost", source="recon")
    # session.add(new_host)
    # session.commit()


def generate_report():
    pass


def cleanup_droplet():
    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Command line tool for bounty management.")
    parser.add_argument("--config", help="Config file to use rather than the default")
    parser.add_argument("--setupvm", help="Setup recon VM", action="store_true")
    parser.add_argument("--verbose", help="Verbose logging", action="store_true")
    parser.add_argument("--fullrecon", help="Setup recon VM", action="store_true")
    parser.add_argument("--domains", help="List of domains to target", nargs='+')
    parser.add_argument("--workspace", help="Name of the workspace")
    opts = parser.parse_args()

    # Read from the config file
    config = configparser.RawConfigParser()
    if opts.config is None:
        config.read("config.conf")
    else:
        config.read(opts.config)

    # build the digital ocean manager object
    manager = digitalocean.Manager(token=config.get("DigitalOcean", "api_key"))

    if opts.setupvm:
        setup_vm(manager, config, opts.verbose)

    elif opts.fullrecon and (opts.domains is not None) and (opts.workspace is not None):
        droplet = setup_vm(manager, config, opts.verbose)
        workspace = opts.workspace
        domains = opts.domains
        run_recon(manager, droplet, config, workspace, domains)