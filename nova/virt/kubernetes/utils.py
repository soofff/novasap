def k8s_unit_to_mb(unit_str) -> int:
    """Convert Kubernetes memory unit string to MB."""
    unit_str = unit_str.lower()
    if unit_str.endswith('ki'):
        return int(int(unit_str[:-2]) / 1024)
    elif unit_str.endswith('mi'):
        return int(unit_str[:-2])
    elif unit_str.endswith('gi'):
        return int(unit_str[:-2]) * 1024
    elif unit_str.endswith('ti'):
        return int(unit_str[:-2]) * 1024 * 1024
    elif unit_str.endswith('k'):
        return int(int(unit_str[:-1]) / (1024 * 1024))
    elif unit_str.endswith('m'):
        return int(int(unit_str[:-1]) / 1024)
    elif unit_str.endswith('g'):
        return int(int(unit_str[:-1]) * 1024)
    elif unit_str.endswith('t'):
        return int(int(unit_str[:-1]) * 1024 * 1024)
    else:
        return int(int(unit_str) / (1024 * 1024))