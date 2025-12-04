# Exclusion Patterns - Feature Summary

## What Changed

✅ **Removed hardcoded exclusions** from docker-manager.py
✅ **Added configurable patterns** via YAML config
✅ **Two levels of control**: Global defaults + per-project overrides

## Configuration

### Global Defaults (Optional)

Applied to all projects unless overridden:

```yaml
global:
  backup:
    default_exclude_patterns:
      - "*.log"           # Log files
      - "*.sock"          # Socket files
      - "*/cache/*"       # Cache directories
      - "*/Cache/*"       # Cache (capitalized)
      - "*/logs/*"        # Log directories
      - "*/Logs/*"        # Logs (capitalized)
      - "*/tmp/*"         # Temp directories
      - "*/temp/*"        # Temp (alternate)
      - "*/.cache/*"      # Hidden cache
      - "*/lost+found/*"  # Linux artifacts
```

### Per-Project Overrides

Add project-specific exclusions (merged with global):

```yaml
projects:
  plex:
    exclude_patterns:
      - "*/Logs/*"
      - "*/Cache/*"
      - "*/Crash Reports/*"
      - "*/Diagnostics/*"
```

## Pattern Examples

### Common Patterns

```yaml
# File extensions
- "*.log"
- "*.tmp"
- "*.sock"

# Directory names (anywhere in tree)
- "*/cache/*"
- "*/logs/*"
- "*/temp/*"

# Specific paths within volumes
- "*/Plex Media Server/Cache/*"
- "*/Plex Media Server/Logs/*"

# Case-sensitive variants
- "*/cache/*"  # lowercase
- "*/Cache/*"  # capitalized
```

### Use Cases

**Plex**:
```yaml
plex:
  exclude_patterns:
    - "*/Logs/*"
    - "*/Cache/*"
    - "*/Crash Reports/*"
    # Keep Metadata (not excluded)
```

**Jellyfin**:
```yaml
jellyfin:
  exclude_volumes:
    - cache      # Entire volume
    - transcodes # Entire volume
  exclude_patterns:
    - "*/log/*"  # Additional pattern-based exclusion
```

**Database with logs**:
```yaml
postgres:
  exclude_patterns:
    - "*/pg_log/*"
    - "*.log"
```

## How It Works

1. Script reads `default_exclude_patterns` from global config
2. Script reads `exclude_patterns` from project config
3. Merges both lists
4. Passes all patterns to `tar --exclude='pattern'`

## Testing Your Patterns

Test what would be excluded:

```bash
# Dry run - see what tar would exclude
cd /opt/docker/plex
tar --exclude='*/Logs/*' --exclude='*/Cache/*' -tvf - . | less

# Check backup size with/without exclusions
du -sh /opt/docker/plex/
du -sh /opt/docker/plex/ --exclude='*/{Logs,Cache}/*'
```

## Migration from Old Config

If you had no config, **no changes needed**. The example config includes sensible defaults.

If you want the old hardcoded behavior:

```yaml
global:
  backup:
    default_exclude_patterns:
      - "*.log"
      - "*.sock"
      - "cache/*"
      - "tmp/*"
```

## Benefits

✅ **Flexible** - Control exclusions per project
✅ **Space-efficient** - Skip large cache/log directories
✅ **Configurable** - No code changes needed
✅ **Clear** - Explicit in YAML config
✅ **Layered** - Global defaults + project overrides
