def apply_negation(triple, is_neg):
    s, r, o = triple

    if is_neg:
        r = r + "_NOT"

    return (s, r, o)
