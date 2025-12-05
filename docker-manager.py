#!/usr/bin/env python3
"""
Docker Manager - Centralized Docker backup and update management
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Check for required dependencies
REQUIRED_PACKAGES = ['paramiko', 'yaml', 'requests', 'dateutil']
missing_packages = []

for package in REQUIRED_PACKAGES:
    try:
        __import__(package)
    except ImportError:
        missing_packages.append(package)

if missing_packages:
    print("ERROR: Missing required Python packages:")
    for pkg in missing_packages:
        print(f"  - {pkg}")
    print("\nInstall with: pip install -r requirements.txt")
    print(f"Location: {Path(__file__).parent}/requirements.txt")
    sys.exit(1)

import yaml
import paramiko
import requests
from dateutil.relativedelta import relativedelta

# Version
VERSION = "1.0.0"

# Default paths
DEFAULT_CONFIG = Path(__file__).parent / "docker-manager.yml"
DEFAULT_LOG_DIR = Path("/var/log/docker-manager")


class DockerManager:
    """Main Docker Manager class"""
    
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.config = self.load_config()
        self.logger = self.setup_logging()
        self.notifier = Notifier(self.config.get('global', {}).get('notifications', {}), self.logger)
        
    def load_config(self):
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            print(f"ERROR: Configuration file not found: {self.config_path}")
            print(f"Create a config file at: {self.config_path}")
            sys.exit(1)
        
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def setup_logging(self):
        """Setup logging"""
        log_dir = Path(self.config['global'].get('log_dir', DEFAULT_LOG_DIR))
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"docker-manager-{datetime.now().strftime('%Y%m%d')}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        return logging.getLogger(__name__)
    
    def test_ssh(self):
        """Test SSH connectivity to all hosts"""
        self.logger.info("Testing SSH connectivity to all hosts...")
        
        all_success = True
        for host_name, host_config in self.config['global']['hosts'].items():
            ip = host_config['ip']
            
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username='root', timeout=5)
                
                stdin, stdout, stderr = ssh.exec_command('echo "SSH OK"')
                result = stdout.read().decode().strip()
                
                if result == "SSH OK":
                    self.logger.info(f"✓ {host_name} ({ip}): Connected")
                else:
                    self.logger.error(f"✗ {host_name} ({ip}): Unexpected response")
                    all_success = False
                
                ssh.close()
                
            except Exception as e:
                self.logger.error(f"✗ {host_name} ({ip}): {str(e)}")
                all_success = False
        
        return all_success
    
    def discover_projects(self, target_host=None):
        """Discover all Docker projects on all hosts (or specific host if specified)"""
        projects = {}
        
        for host_name, host_config in self.config['global']['hosts'].items():
            # Skip hosts not matching target
            if target_host and host_name != target_host:
                continue
            
            ip = host_config['ip']
            docker_root = host_config['docker_root']
            
            self.logger.info(f"Discovering projects on {host_name} ({ip})...")
            
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username='root', timeout=10)
                
                # Find all directories with docker-compose.yml
                cmd = f"find {docker_root} -maxdepth 2 -name 'docker-compose.yml' -exec dirname {{}} \\;"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                
                project_paths = stdout.read().decode().strip().split('\n')
                projects[host_name] = []
                
                for path in project_paths:
                    if path:
                        project_name = Path(path).name
                        projects[host_name].append({
                            'name': project_name,
                            'path': path
                        })
                
                self.logger.info(f"  Found {len(projects[host_name])} projects on {host_name}")
                
                ssh.close()
                
            except Exception as e:
                self.logger.error(f"  Error discovering projects on {host_name}: {str(e)}")
                projects[host_name] = []
        
        return projects
    
    def get_project_config(self, project_name):
        """Get configuration for a project (merges defaults with project-specific)"""
        defaults = {
            'retention': self.config['global']['backup'].get('default_retention', 4),
            'schedule': self.config['global']['backup'].get('default_schedule', 'daily'),
            'behavior': self.config['global']['update'].get('default_behavior', 'backup_then_update'),
            'backup_compose': True,
            'exclude_volumes': []
        }
        
        project_config = self.config.get('projects', {}).get(project_name, {})
        
        # Merge configs (project overrides defaults)
        config = {**defaults, **project_config}
        
        return config
    
    def should_backup(self, host_name, project_name, project_config):
        """Determine if project should be backed up based on schedule"""
        schedule = project_config['schedule']
        behavior = project_config['behavior']
        
        # If behavior is update_only, skip backup
        if behavior == 'update_only':
            return False
        
        # Find last backup
        backup_root = Path(self.config['global']['backup']['root'])
        pattern = f"{host_name}-{project_name}-*.tar.gz"
        
        backups = sorted(backup_root.glob(pattern), reverse=True)
        
        if not backups:
            # No backup exists, do it
            return True
        
        # Parse timestamp from most recent backup
        last_backup = backups[0]
        try:
            # Remove .tar.gz extension first, then split
            # Format: docker01-joplin-20251205-020004.tar.gz
            filename_no_ext = last_backup.stem  # Removes .gz -> docker01-joplin-20251205-020004.tar
            if filename_no_ext.endswith('.tar'):
                filename_no_ext = filename_no_ext[:-4]  # Remove .tar -> docker01-joplin-20251205-020004
            
            parts = filename_no_ext.split('-')
            # Last two parts should be date and time
            timestamp_str = parts[-2] + parts[-1]  # 20251205 + 020004
            last_backup_date = datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
        except Exception as e:
            self.logger.warning(f"Could not parse backup date from {last_backup.name}: {e}, assuming backup needed")
            return True
        
        now = datetime.now()
        
        # Check schedule
        if schedule == 'daily':
            return (now - last_backup_date).days >= 1
        elif schedule == 'weekly':
            return (now - last_backup_date).days >= 7
        elif schedule == 'biweekly':
            return (now - last_backup_date).days >= 14
        elif schedule == 'monthly':
            return (now - last_backup_date).days >= 30
        else:
            self.logger.warning(f"Unknown schedule '{schedule}', defaulting to daily")
            return (now - last_backup_date).days >= 1
    
    def backup_project(self, host_name, project_name, project_path, project_config, force=False):
        """Backup a single project"""
        if not force and not self.should_backup(host_name, project_name, project_config):
            self.logger.info(f"  Skipping {project_name} - not due for backup")
            return {'status': 'skipped', 'reason': 'schedule'}
        
        host_config = self.config['global']['hosts'][host_name]
        ip = host_config['ip']
        
        self.logger.info(f"  Backing up {project_name} on {host_name}...")
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username='root', timeout=10)
            
            # Check if containers are running
            self.logger.info(f"    Checking container state...")
            stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose ps -q 2>/dev/null | wc -l")
            running_containers = int(stdout.read().decode().strip())
            was_running = running_containers > 0
            
            if was_running:
                self.logger.info(f"    Containers running: {running_containers}")
            else:
                self.logger.info(f"    No containers running")
            
            # Stop containers if they were running
            if was_running:
                self.logger.info(f"    Stopping containers...")
                stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose down")
                stdout.channel.recv_exit_status()  # Wait for completion
            
            # Build tar command with exclusions
            backup_root = self.config['global']['backup']['root']
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            backup_name = f"{host_name}-{project_name}-{timestamp}.tar.gz"
            backup_path = f"{backup_root}/{backup_name}"
            
            # Build exclude options
            exclude_opts = ""
            if project_config.get('backup_compose') == False:
                exclude_opts += " --exclude='docker-compose.yml' --exclude='docker-compose.override.yml' --exclude='.env'"
            
            exclude_volumes = project_config.get('exclude_volumes', [])
            if 'ALL' in exclude_volumes:
                # Exclude all directories, only backup compose files
                exclude_opts += " --exclude='*/'"
            else:
                for vol in exclude_volumes:
                    exclude_opts += f" --exclude='{vol}'"
            
            # Add exclusion patterns (global defaults + project-specific)
            global_patterns = self.config['global']['backup'].get('default_exclude_patterns', [])
            project_patterns = project_config.get('exclude_patterns', [])
            all_patterns = global_patterns + project_patterns
            
            for pattern in all_patterns:
                exclude_opts += f" --exclude='{pattern}'"
            
            # Determine compression command
            compression = self.config['global']['backup'].get('compression', 'pigz')
            compression_level = self.config['global']['backup'].get('compression_level', 6)
            
            if compression == 'pigz':
                compress_cmd = f"pigz -{compression_level}"
            else:
                compress_cmd = f"gzip -{compression_level}"
            
            # Create backup
            self.logger.info(f"    Creating backup...")
            tar_cmd = f"cd {project_path} && tar {exclude_opts} -cf - . | {compress_cmd} > {backup_path}"
            stdin, stdout, stderr = ssh.exec_command(tar_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error = stderr.read().decode()
                raise Exception(f"Backup failed: {error}")
            
            # Get backup size
            stdin, stdout, stderr = ssh.exec_command(f"stat -c%s {backup_path}")
            size_bytes = int(stdout.read().decode().strip())
            
            self.logger.info(f"    ✓ Backup complete: {backup_name} ({self.format_bytes(size_bytes)})")
            
            # Check if we should update before restarting (only if containers were running)
            behavior = project_config.get('behavior', self.config['global']['update'].get('default_behavior', 'backup_then_update'))
            should_update = behavior == 'backup_then_update' and was_running
            
            update_status = None
            images_updated = 0
            
            if should_update:
                # Pull updates while containers are still down
                self.logger.info(f"    Checking for updates...")
                
                # Get current image digests
                stdin, stdout, stderr = ssh.exec_command(
                    f"cd {project_path} && docker compose images -q 2>/dev/null | xargs -r docker inspect --format='{{{{.Id}}}}' 2>/dev/null | sort"
                )
                old_digests = stdout.read().decode().strip()
                
                # Pull updates
                stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose pull 2>&1")
                pull_output = stdout.read().decode()
                pull_exit = stdout.channel.recv_exit_status()
                
                # Check for errors
                if pull_exit != 0 and 'Error' in pull_output and 'must be built from source' not in pull_output:
                    self.logger.warning(f"    Pull had errors: {pull_output[:200]}")
                
                # Get new image digests
                stdin, stdout, stderr = ssh.exec_command(
                    f"cd {project_path} && docker compose images -q 2>/dev/null | xargs -r docker inspect --format='{{{{.Id}}}}' 2>/dev/null | sort"
                )
                new_digests = stdout.read().decode().strip()
                
                # Check if anything changed
                if old_digests != new_digests:
                    images_updated = pull_output.count('Downloaded newer image') + pull_output.count('Pulled')
                    self.logger.info(f"    ✓ Updates found: {images_updated} image(s) pulled")
                    update_status = 'updated'
                else:
                    self.logger.info(f"    ✓ No updates available")
                    update_status = 'up-to-date'
            elif not was_running and behavior == 'backup_then_update':
                self.logger.info(f"    Skipping updates - containers were not running")
                update_status = 'skipped'
            
            # Restart containers only if they were originally running
            if was_running:
                self.logger.info(f"    Starting containers...")
                stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose up -d")
                stdout.channel.recv_exit_status()
            else:
                self.logger.info(f"    Containers remain stopped (original state)")
            
            ssh.close()
            
            return {
                'status': 'success',
                'backup_name': backup_name,
                'size': size_bytes,
                'containers': running_containers,
                'update_status': update_status,
                'images_updated': images_updated
            }
            
        except Exception as e:
            self.logger.error(f"    ✗ Backup failed: {str(e)}")
            
            # Try to restart containers if they were stopped
            try:
                stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose up -d")
                stdout.channel.recv_exit_status()
                ssh.close()
            except:
                pass
            
            return {'status': 'failed', 'error': str(e)}
    
    def update_project(self, host_name, project_name, project_path, project_config):
        """Update a single project"""
        behavior = project_config['behavior']
        
        # Check if updates are allowed for this project
        if behavior == 'backup_only':
            self.logger.info(f"  Skipping update for {project_name} - backup_only mode")
            return {'status': 'skipped', 'reason': 'backup_only'}
        
        host_config = self.config['global']['hosts'][host_name]
        ip = host_config['ip']
        
        self.logger.info(f"  Checking for updates for {project_name} on {host_name}...")
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username='root', timeout=10)
            
            # Get current image digests
            stdin, stdout, stderr = ssh.exec_command(
                f"cd {project_path} && docker compose images -q 2>/dev/null | xargs -r docker inspect --format='{{{{.Id}}}}' 2>/dev/null | sort"
            )
            old_digests = stdout.read().decode().strip()
            
            # Pull updates
            self.logger.info(f"    Pulling updates...")
            stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose pull 2>&1")
            pull_output = stdout.read().decode()
            pull_exit = stdout.channel.recv_exit_status()
            
            # Check for errors
            if pull_exit != 0 and 'Error' in pull_output and 'must be built from source' not in pull_output:
                raise Exception(f"Pull failed: {pull_output}")
            
            # Get new image digests
            stdin, stdout, stderr = ssh.exec_command(
                f"cd {project_path} && docker compose images -q 2>/dev/null | xargs -r docker inspect --format='{{{{.Id}}}}' 2>/dev/null | sort"
            )
            new_digests = stdout.read().decode().strip()
            
            # Check if anything changed
            if old_digests == new_digests:
                self.logger.info(f"    ✓ Up-to-date - no updates needed")
                ssh.close()
                return {'status': 'up-to-date'}
            
            # Count updated images
            images_updated = pull_output.count('Downloaded newer image') + pull_output.count('Pulled')
            
            # Recreate containers
            self.logger.info(f"    Recreating containers...")
            stdin, stdout, stderr = ssh.exec_command(f"cd {project_path} && docker compose up -d 2>&1")
            up_output = stdout.read().decode()
            up_exit = stdout.channel.recv_exit_status()
            
            if up_exit != 0:
                raise Exception(f"Container restart failed: {up_output}")
            
            ssh.close()
            
            self.logger.info(f"    ✓ Updated successfully - {images_updated} image(s) pulled")
            
            return {
                'status': 'updated',
                'images_pulled': images_updated
            }
            
        except Exception as e:
            self.logger.error(f"    ✗ Update failed: {str(e)}")
            try:
                ssh.close()
            except:
                pass
            return {'status': 'failed', 'error': str(e)}
    
    def cleanup_backups(self):
        """Clean up old backups based on retention policy"""
        self.logger.info("Cleaning up old backups...")
        
        backup_root = Path(self.config['global']['backup']['root'])
        removed_count = 0
        freed_space = 0
        
        # Group backups by host-project
        backup_groups = {}
        
        for backup_file in backup_root.glob("*-*-*.tar.gz"):
            try:
                parts = backup_file.stem.split('-')
                host = parts[0]
                # Project name might have hyphens, so join everything except last 2 parts (timestamp)
                project = '-'.join(parts[1:-2])
                
                key = f"{host}-{project}"
                if key not in backup_groups:
                    backup_groups[key] = []
                backup_groups[key].append(backup_file)
            except:
                self.logger.warning(f"Could not parse backup filename: {backup_file.name}")
                continue
        
        # Clean up each group based on retention
        for key, backups in backup_groups.items():
            host, project = key.split('-', 1)
            project_config = self.get_project_config(project)
            retention = project_config['retention']
            
            # Sort by date (newest first)
            backups = sorted(backups, reverse=True)
            
            # Keep only the last N backups
            to_remove = backups[retention:]
            
            if to_remove:
                self.logger.info(f"  {project} on {host}: Removing {len(to_remove)} old backup(s)")
                
                for backup in to_remove:
                    size = backup.stat().st_size
                    backup.unlink()
                    removed_count += 1
                    freed_space += size
                    self.logger.info(f"    Removed: {backup.name}")
        
        if removed_count > 0:
            self.logger.info(f"✓ Cleanup complete: {removed_count} backup(s) removed, {self.format_bytes(freed_space)} freed")
            
            # Send notification
            if self.notifier.enabled:
                self.notifier.send_cleanup_notification(removed_count, self.format_bytes(freed_space))
        else:
            self.logger.info("✓ No old backups to remove")
        
        return removed_count, freed_space
    
    def run(self, force=False, target_host=None, target_project=None, operation='all'):
        """Run scheduled backup and update operations"""
        self.logger.info("=" * 50)
        self.logger.info(f"Docker Manager Run Started (force={force})")
        self.logger.info("=" * 50)
        
        # Discover projects (optionally filter by target_host)
        all_projects = self.discover_projects(target_host=target_host)
        
        # Statistics
        stats = {
            'total_projects': 0,
            'total_containers': 0,
            'backups_attempted': 0,
            'backups_successful': 0,
            'backups_failed': 0,
            'backups_skipped': 0,
            'updates_attempted': 0,
            'updates_successful': 0,
            'updates_failed': 0,
            'updates_skipped': 0,
            'total_backup_size': 0
        }
        
        # Process each host
        for host_name, projects in all_projects.items():
            if target_host and host_name != target_host:
                continue
            
            self.logger.info(f"Processing {host_name}...")
            
            for project in projects:
                project_name = project['name']
                project_path = project['path']
                
                if target_project and project_name != target_project:
                    continue
                
                stats['total_projects'] += 1
                project_config = self.get_project_config(project_name)
                
                self.logger.info(f"  {project_name}:")
                
                # Backup (may include update if behavior is backup_then_update)
                if operation in ['all', 'backup']:
                    stats['backups_attempted'] += 1
                    backup_result = self.backup_project(host_name, project_name, project_path, project_config, force)
                    
                    if backup_result['status'] == 'success':
                        stats['backups_successful'] += 1
                        stats['total_backup_size'] += backup_result['size']
                        stats['total_containers'] += backup_result.get('containers', 0)
                        
                        # Track update stats if backup included update check
                        update_status = backup_result.get('update_status')
                        if update_status:
                            stats['updates_attempted'] += 1
                            if update_status == 'updated':
                                stats['updates_successful'] += 1
                            elif update_status in ['up-to-date', 'skipped']:
                                stats['updates_skipped'] += 1
                    elif backup_result['status'] == 'failed':
                        stats['backups_failed'] += 1
                        # Skip standalone update if backup failed
                        continue
                    elif backup_result['status'] == 'skipped':
                        stats['backups_skipped'] += 1
                
                # Standalone update (only if not already done during backup)
                if operation in ['all', 'update']:
                    behavior = project_config.get('behavior', self.config['global']['update'].get('default_behavior', 'backup_then_update'))
                    
                    # Skip if backup already handled the update
                    if operation == 'all' and behavior == 'backup_then_update':
                        continue
                    
                    stats['updates_attempted'] += 1
                    update_result = self.update_project(host_name, project_name, project_path, project_config)
                    
                    if update_result['status'] == 'updated':
                        stats['updates_successful'] += 1
                    elif update_result['status'] == 'failed':
                        stats['updates_failed'] += 1
                    elif update_result['status'] in ['skipped', 'up-to-date']:
                        stats['updates_skipped'] += 1
        
        # Cleanup old backups
        if operation in ['all', 'backup']:
            self.cleanup_backups()
        
        # Summary
        self.logger.info("=" * 50)
        self.logger.info("Summary")
        self.logger.info("=" * 50)
        self.logger.info(f"Total Projects: {stats['total_projects']}")
        self.logger.info(f"Backups: {stats['backups_successful']} successful, {stats['backups_failed']} failed, {stats['backups_skipped']} skipped")
        self.logger.info(f"Updates: {stats['updates_successful']} successful, {stats['updates_failed']} failed, {stats['updates_skipped']} skipped")
        self.logger.info(f"Total Backup Size: {self.format_bytes(stats['total_backup_size'])}")
        
        # Send notification
        if self.notifier.enabled:
            if operation in ['all', 'backup']:
                self.notifier.send_backup_summary(stats)
            if operation in ['all', 'update']:
                self.notifier.send_update_summary(stats)
        
        return stats
    
    @staticmethod
    def format_bytes(bytes_val):
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.2f}{unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.2f}PB"


class Notifier:
    """Handle notifications"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.enabled = config.get('enabled', False)
        
        if self.enabled and config.get('provider') == 'ntfy':
            self.ntfy_config = config['ntfy']
    
    def send(self, title, message, priority='default', tags='computer'):
        """Send notification"""
        if not self.enabled:
            return
        
        try:
            # Remove emojis from title for header compatibility
            # Keep full unicode in message body
            title_clean = title.encode('ascii', 'ignore').decode('ascii').strip()
            
            url = f"{self.ntfy_config['server']}/{self.ntfy_config['topic']}"
            
            # Retry up to 3 times with a fresh connection each time
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        url,
                        data=message.encode('utf-8'),
                        headers={
                            'Title': title_clean if title_clean else 'Docker Manager',
                            'Priority': priority,
                            'Tags': tags
                        },
                        auth=(self.ntfy_config['username'], self.ntfy_config['password']),
                        timeout=10  # Add timeout
                    )
                    response.raise_for_status()
                    break  # Success, exit retry loop
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f"Notification attempt {attempt + 1} failed, retrying...")
                        import time
                        time.sleep(2)  # Wait 2 seconds before retry
                    else:
                        raise  # Last attempt failed, re-raise
            
            self.logger.info(f"Notification sent: {title}")
            
        except Exception as e:
            self.logger.error(f"Failed to send notification: {str(e)}")
    
    def send_backup_summary(self, stats):
        """Send backup summary notification"""
        total = stats['total_projects']
        success = stats['backups_successful']
        failed = stats['backups_failed']
        containers = stats.get('total_containers', 0)
        size = DockerManager.format_bytes(stats['total_backup_size'])
        
        self.logger.info(f"Sending backup notification: {total} projects, {containers} containers")
        
        if failed > 0:
            priority = 'high'
            tags = 'warning,floppy_disk,docker'
            title = f"🐳 Docker Manager: {success} backed up, {failed} failed"
        elif success > 0:
            priority = 'default'
            tags = 'white_check_mark,floppy_disk,docker'
            title = f"🐳 Docker Manager: {success} backups completed"
        else:
            priority = 'low'
            tags = 'checkmark,floppy_disk,docker'
            title = "🐳 Docker Manager: All backups up-to-date"
        
        message = f"""💾 Backup Complete
━━━━━━━━━━━━━━━━━━━━
Projects: {total} ({containers} containers)
✅ Successful: {success}
"""
        
        if failed > 0:
            message += f"❌ Failed: {failed}\n"
        
        message += f"\nTotal Size: {size}"
        
        self.send(title, message, priority, tags)
    
    def send_update_summary(self, stats):
        """Send update summary notification"""
        total = stats['total_projects']
        updated = stats['updates_successful']
        failed = stats['updates_failed']
        
        if failed > 0:
            priority = 'high'
            tags = 'warning,arrows_counterclockwise,docker'
            title = f"🐳 Docker Manager: {updated} updated, {failed} failed"
        elif updated > 0:
            priority = 'default'
            tags = 'white_check_mark,arrows_counterclockwise,docker'
            title = f"🐳 Docker Manager: {updated} updates applied"
        else:
            priority = 'low'
            tags = 'checkmark,docker'
            title = "🐳 Docker Manager: All up-to-date"
        
        message = f"""🔄 Updates Complete
━━━━━━━━━━━━━━━━━━━━
Checked: {total} projects
✅ Updated: {updated}
"""
        
        if failed > 0:
            message += f"❌ Failed: {failed}\n"
        
        up_to_date = stats['updates_skipped']
        if up_to_date > 0:
            message += f"✔️ Up-to-date: {up_to_date}"
        
        self.send(title, message, priority, tags)
    
    def send_cleanup_notification(self, removed_count, freed_space):
        """Send cleanup notification"""
        title = "🐳 Docker Manager: Cleanup Complete"
        message = f"""🧹 Old backups removed
━━━━━━━━━━━━━━━━━━━━
Backups removed: {removed_count}
Space freed: {freed_space}"""
        
        self.send(title, message, 'low', 'broom,floppy_disk')


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Docker Manager - Centralized Docker backup and update management',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--version', action='version', version=f'Docker Manager {VERSION}')
    parser.add_argument('--config', default=DEFAULT_CONFIG, help='Path to configuration file')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run scheduled backup and update operations')
    run_parser.add_argument('--force', action='store_true', help='Force run regardless of schedule')
    run_parser.add_argument('--host', help='Target specific host')
    run_parser.add_argument('project', nargs='?', help='Target specific project')
    
    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Backup operations')
    backup_parser.add_argument('target', nargs='?', default='all', help='Target (all, project name)')
    backup_parser.add_argument('--host', help='Target specific host')
    backup_parser.add_argument('project', nargs='?', help='Target specific project (when using --host)')
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Update operations')
    update_parser.add_argument('target', nargs='?', default='all', help='Target (all, project name)')
    update_parser.add_argument('--host', help='Target specific host')
    update_parser.add_argument('project', nargs='?', help='Target specific project (when using --host)')
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old backups')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show backup status')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all discovered projects')
    
    # Test commands
    test_parser = subparsers.add_parser('test-ssh', help='Test SSH connectivity')
    test_notify_parser = subparsers.add_parser('test-notify', help='Test notification')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize manager
    manager = DockerManager(args.config)
    
    # Execute command
    if args.command == 'run':
        target_host = args.host
        target_project = args.project
        manager.run(force=args.force, target_host=target_host, target_project=target_project)
    
    elif args.command == 'backup':
        target_host = args.host
        target_project = args.target if args.target != 'all' else args.project
        manager.run(force=True, target_host=target_host, target_project=target_project, operation='backup')
    
    elif args.command == 'update':
        target_host = args.host
        target_project = args.target if args.target != 'all' else args.project
        manager.run(force=True, target_host=target_host, target_project=target_project, operation='update')
    
    elif args.command == 'cleanup':
        manager.cleanup_backups()
    
    elif args.command == 'list':
        projects = manager.discover_projects()
        print("\nDiscovered Projects:")
        print("=" * 50)
        for host, host_projects in projects.items():
            print(f"\n{host}:")
            for project in host_projects:
                print(f"  - {project['name']} ({project['path']})")
        print()
    
    elif args.command == 'test-ssh':
        success = manager.test_ssh()
        sys.exit(0 if success else 1)
    
    elif args.command == 'test-notify':
        manager.notifier.send(
            "🧪 Docker Manager Test",
            "If you received this, notifications are working!",
            "low",
            "test_tube,white_check_mark"
        )


if __name__ == '__main__':
    main()
