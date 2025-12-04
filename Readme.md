# Docker Manager

Centralized Docker backup and update management CLI application.

## Features

- ✅ **Automated Backups** - Stop, backup, restart projects safely
- ✅ **Flexible Scheduling** - Daily, weekly, biweekly, monthly per project
- ✅ **Smart Updates** - Automatic updates after backups (configurable)
- ✅ **Retention Management** - Keep last N backups per project
- ✅ **Selective Backups** - Exclude volumes, backup only compose files
- ✅ **Multi-Host** - Manage multiple Docker hosts from one place
- ✅ **Notifications** - ntfy integration for status updates
- ✅ **SSH-based** - Secure remote execution via SSH
- ✅ **YAML Configuration** - Easy, readable configuration

## Prerequisites

- Python 3.8+
- SSH access to Docker hosts (root with SSH keys)
- NFS share mounted on all hosts and admin machine
- `pigz` installed on Docker hosts (optional, for faster compression)

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/docker-manager.git /opt/docker-manager
cd /opt/docker-manager

# Install Python dependencies
pip3 install -r requirements.txt

# Make executable
chmod +x docker-manager.py

# Create symlink (optional, for convenience)
ln -s /opt/docker-manager/docker-manager.py /usr/local/bin/docker-manager

# Create log directory
mkdir -p /var/log/docker-manager
```

## Configuration

Copy the example configuration and customize:

```bash
cp docker-manager.yml.example docker-manager.yml
nano docker-manager.yml
```

Required settings:
- `global.hosts` - Your Docker hosts with friendly names and IPs
- `global.backup.root` - Path to NFS backup directory
- `global.notifications.ntfy` - Your ntfy server credentials

Optional:
- `projects` - Per-project overrides (schedule, retention, exclusions)

See `docker-manager.yml.example` for detailed configuration options.

## Quick Start

```bash
# Test SSH connectivity to all hosts
./docker-manager.py test-ssh

# Test notifications
./docker-manager.py test-notify

# List all discovered projects
./docker-manager.py list

# Test backup a single project
./docker-manager.py backup --host docker01 vaultwarden

# Check logs
tail -f /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log
```

## Usage

### Main Operations

```bash
# Run scheduled backups and updates (respects schedule config)
docker-manager.py run

# Force run everything regardless of schedule
docker-manager.py run --force

# Run specific host or project
docker-manager.py run --host docker01
docker-manager.py run vaultwarden
```

### Backup Operations

```bash
# Backup all projects
docker-manager.py backup all

# Backup specific project on all hosts
docker-manager.py backup vaultwarden

# Backup all projects on specific host
docker-manager.py backup --host docker01

# Backup specific project on specific host
docker-manager.py backup --host docker01 vaultwarden
```

### Update Operations

```bash
# Update all projects
docker-manager.py update all

# Update specific project
docker-manager.py update vaultwarden

# Update all on specific host
docker-manager.py update --host docker02

# Update specific project on specific host
docker-manager.py update --host docker02 jellyfin
```

### Maintenance

```bash
# Clean up old backups (respects retention policy)
docker-manager.py cleanup

# List all projects
docker-manager.py list
```

### Testing

```bash
# Test SSH connectivity
docker-manager.py test-ssh

# Test notifications
docker-manager.py test-notify
```

## Automated Execution

Set up a daily cron job:

```bash
crontab -e
```

Add:
```
0 2 * * * /opt/docker-manager/docker-manager.py run
```

This runs daily at 2 AM, checking each project's schedule and backing up/updating as configured.

## Configuration

### Global Settings

```yaml
global:
  # Host definitions
  hosts:
    docker01:
      ip: 172.16.100.200
      docker_root: /opt/docker
    docker02:
      ip: 172.16.100.202
      docker_root: /opt/docker
  
  # Backup settings
  backup:
    root: /mnt/media/nfs/docker-backups
    compression: pigz  # pigz (faster) or gzip
    compression_level: 6  # 1-9
    default_retention: 4  # Keep last N backups per project
    default_schedule: daily  # daily, weekly, biweekly, monthly
    
    # Global exclusion patterns (optional)
    default_exclude_patterns:
      - "*.log"
      - "*.sock"
      - "*/cache/*"
      - "*/logs/*"
  
  # Update settings
  update:
    default_behavior: backup_then_update  # backup_then_update, backup_only, update_only
  
  # Notifications
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: your-topic
      username: your-user
      password: your-pass
```

### Project Overrides

Projects not listed use global defaults. Add per-project customization:

```yaml
projects:
  # High-value service: daily backups, keep 10
  vaultwarden:
    retention: 10
    schedule: daily
    behavior: backup_then_update
  
  # Skip backup entirely, only update
  musicbrainz:
    behavior: update_only
    schedule: weekly
  
  # Media server: weekly backups, exclude cache
  jellyfin:
    retention: 6
    schedule: weekly
    exclude_volumes:
      - cache
      - transcodes
  
  # Database: daily backup, never auto-update
  postgres:
    retention: 10
    schedule: daily
    behavior: backup_only
  
  # Only backup compose files, no volumes
  nginx:
    retention: 4
    exclude_volumes:
      - ALL  # Special keyword
```

### Configuration Options

#### Per-Project Settings

- `retention` - Keep last N backups (overrides default)
- `schedule` - `daily`, `weekly`, `biweekly`, `monthly`
- `behavior` - `backup_then_update`, `backup_only`, `update_only`
- `backup_compose` - `false` to skip compose files (default: `true`)
- `exclude_volumes` - List of volume directories to skip
  - Use `ALL` to exclude all volumes (backup only compose files)
- `exclude_patterns` - List of file/path patterns to exclude (per-project)
  - Patterns are passed to `tar --exclude`
  - Merged with `default_exclude_patterns` from global config
  - Examples: `"*/Logs/*"`, `"*.tmp"`, `"*/Cache/*"`

#### Example: Plex with Custom Exclusions

```yaml
projects:
  plex:
    retention: 4
    schedule: weekly
    exclude_patterns:
      - "*/Logs/*"           # Skip Plex logs
      - "*/Cache/*"          # Skip Plex cache
      - "*/Crash Reports/*"  # Skip crash reports
      # Metadata is backed up (not excluded)
```

## How It Works

### Backup Process

For each project:
1. Check if backup is due based on schedule and last backup timestamp
2. SSH to Docker host
3. `docker compose down` (stop containers)
4. Create compressed tar backup (excluding configured volumes)
5. `docker compose up -d` (restart containers)
6. Clean up old backups based on retention policy

### Update Process

For projects where `behavior` allows:
1. SSH to Docker host
2. Get current image digests
3. `docker compose pull`
4. Compare new vs old digests
5. If changed: `docker compose up -d` (recreate containers)

### Scheduling

Backup schedules are enforced by parsing the timestamp from existing backup filenames:
- `daily` - Backup if last backup was >24 hours ago
- `weekly` - Backup if last backup was >7 days ago
- `biweekly` - Backup if last backup was >14 days ago
- `monthly` - Backup if last backup was >30 days ago

Projects without existing backups are always backed up.

## Backup Format

Backups are named: `{hostname}-{project}-{timestamp}.tar.gz`

Examples:
```
docker01-vaultwarden-20241204-103000.tar.gz
docker01-jellyfin-20241204-103005.tar.gz
docker02-plex-20241204-103010.tar.gz
```

## Restoration

To restore a backup:

```bash
# 1. SSH to the host
ssh root@docker01

# 2. Stop the service
cd /opt/docker/vaultwarden
docker compose down

# 3. Extract backup over existing directory
cd /opt/docker
tar -xzf /mnt/media/nfs/docker-backups/docker01-vaultwarden-20241204-103000.tar.gz -C vaultwarden/

# 4. Restart service
cd vaultwarden
docker compose up -d
```

## Notifications

### Backup Summary
```
🐳 Docker Manager: 12 backups completed
━━━━━━━━━━━━━━━━━━━━
Total: 14 projects
✅ Successful: 12
❌ Failed: 2

Total Size: 3.2GB
```

### Update Summary
```
🐳 Docker Manager: 3 updates applied
━━━━━━━━━━━━━━━━━━━━
Checked: 14 projects
✅ Updated: 3
✔️ Up-to-date: 11
```

### Cleanup Notification
```
🐳 Docker Manager: Cleanup Complete
━━━━━━━━━━━━━━━━━━━━
Backups removed: 5
Space freed: 12.3GB
```

## Troubleshooting

### Dependencies Not Installed

```bash
# Install from requirements.txt
pip3 install -r requirements.txt

# Or install individually
pip3 install paramiko pyyaml requests python-dateutil
```

### SSH Connection Issues

```bash
# Test SSH manually
ssh root@172.16.100.200 "echo OK"

# Check SSH keys exist
ls -la ~/.ssh/

# Use test-ssh command
./docker-manager.py test-ssh
```

### Backups Not Running

```bash
# Check logs
tail -100 /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log

# Force run to ignore schedules
./docker-manager.py run --force

# Test specific project
./docker-manager.py backup --host docker01 vaultwarden
```

### Notifications Not Working

```bash
# Test notification
./docker-manager.py test-notify

# Check configuration
grep -A 6 "notifications:" docker-manager.yml
```

## Project Structure

```
/opt/docker-manager/
├── docker-manager.py           # Main application
├── docker-manager.yml          # Your configuration
├── docker-manager.yml.example  # Example configuration
├── requirements.txt            # Python dependencies
└── README.md                   # This file

/var/log/docker-manager/
└── docker-manager-YYYYMMDD.log  # Daily logs
```

## Development

### Adding New Features

The code is structured for easy extension:

```python
class DockerManager:
    def backup_project()   # Backup logic
    def update_project()   # Update logic
    def run()             # Main orchestration

class Notifier:
    def send()            # Send notifications
```

### Testing

```bash
# Test SSH
python3 docker-manager.py test-ssh

# Test notifications
python3 docker-manager.py test-notify

# Dry run (view discovered projects)
python3 docker-manager.py list
```

## Security

- SSH keys should be properly secured (not password-based auth)
- Protect `docker-manager.yml` as it contains ntfy credentials: `chmod 600 docker-manager.yml`
- Backups contain all project data including secrets - secure the NFS share
- Logs may contain sensitive information - review log permissions

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT

## Support

For issues, check logs at `/var/log/docker-manager/` or open an issue on GitHub.

## Configuration

Edit `/opt/docker-manager/docker-manager.yml`:

```yaml
global:
  hosts:
    docker01:
      ip: 172.16.100.200
      docker_root: /opt/docker
  
  backup:
    root: /mnt/media/nfs/docker-backups
    default_retention: 4
    default_schedule: daily
  
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: your-topic
      username: user
      password: pass

projects:
  vaultwarden:
    retention: 8
    schedule: daily
  
  jellyfin:
    exclude_volumes:
      - cache
      - transcodes
```

### Configuration Options

#### Global Settings

- `hosts` - Define Docker hosts with friendly names
- `backup.root` - NFS path for backups
- `backup.compression` - `pigz` (faster) or `gzip`
- `backup.default_retention` - Keep last N backups
- `backup.default_schedule` - `daily`, `weekly`, `biweekly`, `monthly`
- `update.default_behavior` - `backup_then_update`, `backup_only`, `update_only`

#### Project Settings

Projects not listed use global defaults. Override per project:

- `retention` - Keep last N backups for this project
- `schedule` - Backup frequency for this project
- `behavior` - Override update behavior
- `backup_compose` - Set to `false` to skip compose files
- `exclude_volumes` - List of volume directories to skip
  - Use `ALL` to exclude all volumes (backup only compose)

## Usage

### Testing

```bash
# Test SSH connectivity
docker-manager test-ssh

# Test notifications
docker-manager test-notify

# List all discovered projects
docker-manager list
```

### Backup Operations

```bash
# Backup all projects (respects schedule)
docker-manager run

# Force backup all (ignore schedule)
docker-manager run --force

# Backup specific project on all hosts
docker-manager backup vaultwarden

# Backup all projects on specific host
docker-manager backup --host docker01

# Backup specific project on specific host
docker-manager backup --host docker01 vaultwarden
```

### Update Operations

```bash
# Update all projects (respects behavior settings)
docker-manager update all

# Update specific project
docker-manager update vaultwarden

# Update all on specific host
docker-manager update --host docker02
```

### Maintenance

```bash
# Clean up old backups (respects retention)
docker-manager cleanup

# Show status (not yet implemented)
docker-manager status
```

### Cron Setup

Run daily at 2 AM:

```bash
crontab -e
```

Add:
```
0 2 * * * /usr/local/bin/docker-manager run
```

## How It Works

### Backup Process

For each project:
1. Check if backup is due based on schedule
2. SSH to host
3. `docker compose down` (stop containers)
4. Create `tar.gz` backup (with exclusions)
5. `docker compose up -d` (restart containers)
6. Enforce retention policy (delete old backups)

### Update Process

For each project (if behavior allows):
1. SSH to host
2. Get current image digests
3. `docker compose pull` (check for updates)
4. Compare new vs old digests
5. If changed: `docker compose up -d` (recreate containers)

### Scheduling Logic

When running `docker-manager run`:
- Parse last backup timestamp from filename
- Calculate days since last backup
- Compare to project schedule setting
- Backup if due, skip if not

Example:
- Project with `daily` schedule, last backup yesterday → Skip
- Project with `weekly` schedule, last backup 8 days ago → Backup
- Project with no backups → Always backup

## Backup File Format

```
{hostname}-{project}-{timestamp}.tar.gz

Examples:
docker01-vaultwarden-20241204-103000.tar.gz
docker01-jellyfin-20241204-103005.tar.gz
docker02-plex-20241204-103010.tar.gz
```

## Notifications

### Backup Summary
```
🐳 Docker Manager: 12 backups completed
━━━━━━━━━━━━━━━━━━━━
Total: 14 projects
✅ Successful: 12
❌ Failed: 2

Total Size: 3.2GB
```

### Update Summary
```
🐳 Docker Manager: 3 updates applied
━━━━━━━━━━━━━━━━━━━━
Checked: 14 projects
✅ Updated: 3
✔️ Up-to-date: 11
```

### Cleanup Notification
```
🐳 Docker Manager: Cleanup Complete
━━━━━━━━━━━━━━━━━━━━
Backups removed: 5
Space freed: 12.3GB
```

## Troubleshooting

### SSH Connection Fails

```bash
# Test SSH manually
ssh root@172.16.100.200 "echo OK"

# Check SSH keys
ls -la ~/.ssh/
```

### Dependencies Missing

```bash
# Reinstall dependencies
pip3 install -r /opt/docker-manager/requirements.txt
```

### Backups Not Running

```bash
# Check logs
tail -100 /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log

# Run with verbose output
docker-manager run --force
```

### Notifications Not Working

```bash
# Test notification
docker-manager test-notify

# Check config
cat /opt/docker-manager/docker-manager.yml | grep -A 6 notifications
```

## Examples

### Example 1: Backup Important Service Daily, Keep 10 Copies

```yaml
projects:
  postgres-db:
    retention: 10
    schedule: daily
    behavior: backup_only  # Don't auto-update
```

### Example 2: Weekly Backups, Exclude Cache

```yaml
projects:
  jellyfin:
    retention: 4
    schedule: weekly
    exclude_volumes:
      - cache
      - transcodes
```

### Example 3: Backup Compose Only (No Volumes)

```yaml
projects:
  documentation:
    retention: 2
    schedule: monthly
    exclude_volumes:
      - ALL
```

### Example 4: Skip Backups, Only Update

```yaml
projects:
  musicbrainz:
    behavior: update_only
    schedule: weekly
```

## Security Notes

- Uses root SSH keys for host access
- Stores ntfy credentials in config file (protect with `chmod 600`)
- Backups contain all project data including secrets
- Ensure NFS share has proper permissions

## Requirements

- Python 3.8+
- SSH access to Docker hosts (root with keys)
- NFS share mounted on all hosts and admin machine
- `pigz` installed on Docker hosts (optional, for faster compression)

## Project Structure

```
/opt/docker-manager/
├── docker-manager.py      # Main application
├── docker-manager.yml     # Configuration
├── requirements.txt       # Python dependencies
└── README.md             # This file

/var/log/docker-manager/
└── docker-manager-YYYYMMDD.log  # Daily logs
```

## License

MIT

## Support

Check logs at `/var/log/docker-manager/` for detailed information.
