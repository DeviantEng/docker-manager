# Docker Manager - Setup Guide

Complete installation and configuration guide.

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/DeviantEng/docker-manager.git /opt/docker-manager
cd /opt/docker-manager
```

### 2. Create Virtual Environment

```bash
# Create venv
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure

```bash
# Copy example configuration
cp docker-manager.yml.example docker-manager.yml

# Edit configuration
nano docker-manager.yml
```

**Required settings:**
- `global.hosts` - Define your Docker hosts with friendly names and IPs
- `global.backup.root` - Set your NFS backup path
- `global.notifications.ntfy` - Configure ntfy credentials

**Optional:**
- `projects` - Add per-project customizations (schedule, retention, exclusions)

### 4. Create Log Directory

```bash
mkdir -p /var/log/docker-manager
```

### 5. Make Executable

```bash
chmod +x docker-manager.py
```

## Testing

```bash
# Ensure venv is activated
source venv/bin/activate

# Test SSH connectivity to all hosts
./docker-manager.py test-ssh

# Test notifications
./docker-manager.py test-notify

# List discovered projects
./docker-manager.py list

# Test backup one project
./docker-manager.py backup --host docker01 your-project
```

Check logs:
```bash
tail -f /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log
```

Check backup was created:
```bash
ls -lh /mnt/nfs/docker-backups/
```

## Setup Cron Job

```bash
crontab -e
```

Add this line to run daily at 2 AM:
```
0 2 * * * /opt/docker-manager/venv/bin/python3 /opt/docker-manager/docker-manager.py run
```

**Cron schedule examples:**
```bash
# Daily at 2 AM
0 2 * * * /opt/docker-manager/venv/bin/python3 /opt/docker-manager/docker-manager.py run

# Sundays at 2 AM only
0 2 * * 0 /opt/docker-manager/venv/bin/python3 /opt/docker-manager/docker-manager.py run

# Weekdays at 2 AM
0 2 * * 1-5 /opt/docker-manager/venv/bin/python3 /opt/docker-manager/docker-manager.py run
```

## Configuration Examples

### Minimal Configuration

```yaml
global:
  hosts:
    docker01:
      ip: 192.168.1.101
      docker_root: /opt/docker
  
  backup:
    root: /mnt/nfs/docker-backups
  
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: docker-manager
      username: user
      password: pass
```

All projects will use default settings (weekly backups, keep 4, backup then update).

### Advanced Configuration

```yaml
global:
  hosts:
    docker01:
      ip: 192.168.1.101
      docker_root: /opt/docker
    docker02:
      ip: 192.168.1.102
      docker_root: /opt/docker
  
  backup:
    root: /mnt/nfs/docker-backups
    compression: pigz
    compression_level: 6
    default_retention: 4
    default_schedule: weekly
    default_exclude_patterns:
      - "*.log"
      - "*.sock"
      - "*/cache/*"
      - "*/logs/*"
  
  update:
    default_behavior: backup_then_update
  
  log_dir: /var/log/docker-manager
  log_retention_days: 30
  
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: docker-manager
      username: user
      password: pass

projects:
  # Critical service - daily backups, keep 14
  vaultwarden:
    retention: 14
    schedule: daily
  
  # Media server - weekly, exclude cache
  jellyfin:
    schedule: weekly
    exclude_volumes:
      - cache
      - transcodes
  
  # Database service - daily, never auto-update
  postgres:
    retention: 10
    schedule: daily
    behavior: backup_only
  
  # Skip backup, only update
  musicbrainz:
    behavior: update_only
  
  # Custom exclusion patterns
  plex:
    schedule: weekly
    exclude_patterns:
      - "*/Logs/*"
      - "*/Cache/*"
      - "*/Crash Reports/*"
```

## First Run

Run manually to test:

```bash
# Activate venv
source venv/bin/activate

# Force run everything (ignore schedules)
./docker-manager.py run --force
```

Monitor:
```bash
# Watch logs
tail -f /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log

# Check backups created
ls -lh /mnt/nfs/docker-backups/

# Check notifications in ntfy app
```

## Updating Docker Manager

To update to the latest version:

```bash
cd /opt/docker-manager
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
```

## Monitoring

### Daily Checks

```bash
# Check if cron ran
ls -lt /var/log/docker-manager/ | head -5

# Review last run
tail -100 /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log

# Check backup growth
du -sh /mnt/nfs/docker-backups/

# Verify retention working
ls /mnt/nfs/docker-backups/ | wc -l
```

### After One Week

- Verify weekly projects backed up once
- Verify daily projects backed up 7 times
- Check retention cleanup is working
- Review notification history

## Troubleshooting

### Dependencies Missing

```bash
cd /opt/docker-manager
source venv/bin/activate
pip install -r requirements.txt
```

### Can't Connect to Hosts

```bash
# Test SSH manually
ssh root@192.168.1.101 "echo OK"

# Check SSH keys
ls -la ~/.ssh/

# Use built-in test
./docker-manager.py test-ssh
```

### Backups Not Running

```bash
# Check schedule - might not be due yet
./docker-manager.py run --force

# Check logs
tail -100 /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log
```

### Notifications Not Sending

```bash
# Test notification
./docker-manager.py test-notify

# Check config
cat docker-manager.yml | grep -A 6 notifications
```

### Permission Issues

```bash
# Ensure script is executable
chmod +x docker-manager.py

# Protect config file
chmod 600 docker-manager.yml

# Check log directory permissions
ls -ld /var/log/docker-manager
```

## System Requirements

- **Python**: 3.8 or higher
- **OS**: Linux (tested on Ubuntu/Debian)
- **Network**: SSH access to Docker hosts (port 22)
- **Storage**: NFS share mounted on all hosts and admin machine
- **Optional**: `pigz` on Docker hosts for faster compression

## Security Checklist

- ✅ Protect `docker-manager.yml`: `chmod 600 docker-manager.yml`
- ✅ Use SSH keys (not passwords) for host access
- ✅ Secure NFS share with proper permissions (no public access)
- ✅ Review logs before sharing (may contain sensitive info)
- ✅ `.gitignore` prevents accidentally committing credentials

## Performance Tips

- Use `pigz` instead of `gzip` for faster compression
- Adjust `compression_level` (1-9) - lower = faster, higher = smaller
- Use exclusion patterns to skip cache/logs (saves time and space)
- Run backups during low-usage hours (2 AM default)

## Next Steps

1. ✅ Complete installation
2. ✅ Test backup one project
3. ✅ Test restore procedure
4. ✅ Review and adjust schedules per project
5. ✅ Setup cron job
6. ✅ Monitor first automated run
7. ✅ Adjust retention as needed

## Support

- **Documentation**: See [README.md](README.md)
- **Exclusion Patterns**: See [EXCLUSIONS.md](EXCLUSIONS.md)
- **Issues**: https://github.com/DeviantEng/docker-manager/issues

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/docker-manager.git /opt/docker-manager
cd /opt/docker-manager
```

### 2. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Configure

```bash
# Copy example configuration
cp docker-manager.yml.example docker-manager.yml

# Edit configuration
nano docker-manager.yml
```

**Required settings:**
- `global.hosts` - Define your Docker hosts
- `global.backup.root` - Set your NFS backup path
- `global.notifications.ntfy` - Configure ntfy credentials

**Optional:**
- `projects` - Add per-project customizations

### 4. Make Executable

```bash
chmod +x docker-manager.py
```

### 5. Create Symlink (Optional)

```bash
ln -s /opt/docker-manager/docker-manager.py /usr/local/bin/docker-manager
```

This allows you to run `docker-manager` from anywhere.

### 6. Create Log Directory

```bash
mkdir -p /var/log/docker-manager
```

## Testing

```bash
# Test SSH connectivity
./docker-manager.py test-ssh

# Test notifications
./docker-manager.py test-notify

# List discovered projects
./docker-manager.py list

# Test backup one project
./docker-manager.py backup --host docker01 vaultwarden
```

## Setup Cron Job

```bash
crontab -e
```

Add this line to run daily at 2 AM:
```
0 2 * * * /opt/docker-manager/docker-manager.py run
```

Or if you created the symlink:
```
0 2 * * * /usr/local/bin/docker-manager run
```

## First Run

Run manually to test:

```bash
./docker-manager.py run --force
```

Check logs:
```bash
tail -f /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log
```

Check backups were created:
```bash
ls -lh /mnt/media/nfs/docker-backups/
```

## Configuration Examples

### Minimal Configuration

```yaml
global:
  hosts:
    docker01:
      ip: 172.16.100.200
      docker_root: /opt/docker
  
  backup:
    root: /mnt/media/nfs/docker-backups
  
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: docker-backups
      username: user
      password: pass
```

All projects will use default settings (daily backups, keep 4, backup then update).

### Advanced Configuration

```yaml
global:
  hosts:
    docker01:
      ip: 172.16.100.200
      docker_root: /opt/docker
    docker02:
      ip: 172.16.100.202
      docker_root: /opt/docker
  
  backup:
    root: /mnt/media/nfs/docker-backups
    compression: pigz
    compression_level: 6
    default_retention: 4
    default_schedule: weekly
  
  update:
    default_behavior: backup_then_update
  
  log_dir: /var/log/docker-manager
  
  notifications:
    enabled: true
    provider: ntfy
    ntfy:
      server: https://ntfy.example.com
      topic: homelab-alerts
      username: user
      password: pass

projects:
  vaultwarden:
    retention: 10
    schedule: daily
  
  jellyfin:
    schedule: weekly
    exclude_volumes:
      - cache
      - transcodes
  
  musicbrainz:
    behavior: update_only
```

## Updating

To update Docker Manager:

```bash
cd /opt/docker-manager
git pull
pip3 install -r requirements.txt --upgrade
```

## Troubleshooting

### Missing Dependencies

```bash
pip3 install -r requirements.txt
```

### Can't Connect to Hosts

```bash
# Test manually
ssh root@172.16.100.200 "echo OK"

# Check SSH keys
ls -la ~/.ssh/

# Use built-in test
./docker-manager.py test-ssh
```

### Backups Not Working

```bash
# Check logs
tail -100 /var/log/docker-manager/docker-manager-$(date +%Y%m%d).log

# Force run
./docker-manager.py run --force
```

### Notifications Not Sending

```bash
# Test notification
./docker-manager.py test-notify

# Check config
cat docker-manager.yml | grep -A 6 notifications
```

## System Requirements

- **Python**: 3.8 or higher
- **OS**: Linux (tested on Ubuntu/Debian)
- **Network**: SSH access to Docker hosts
- **Storage**: NFS share mounted on all hosts
- **Optional**: `pigz` on Docker hosts for faster compression

## Security Notes

- Protect `docker-manager.yml`: `chmod 600 docker-manager.yml`
- Use SSH keys (not passwords) for host access
- Secure your NFS share with proper permissions
- `.gitignore` prevents accidentally committing credentials

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure hosts and backup location
3. ✅ Test SSH connectivity
4. ✅ Test backup one project
5. ✅ Review logs
6. ✅ Test restore procedure
7. ✅ Add per-project customizations
8. ✅ Setup cron job
9. ✅ Monitor first automated run
