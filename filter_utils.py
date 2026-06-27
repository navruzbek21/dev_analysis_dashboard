def normalize_filter_values(values):
    if not values:
        return tuple()
    by_key = {}
    for value in values:
        by_key[str(value)] = value
    return tuple(by_key[key] for key in sorted(by_key))
