def detect_conflict(graph, new_triple):
    s_new, r_new, o_new = new_triple[:3]

    # opposite relation
    if "_NOT" in r_new:
        opposite = r_new.replace("_NOT", "")
    else:
        opposite = r_new + "_NOT"

    for triple in graph.triples:
        s, r, o = triple[:3]

        # ✅ SADECE NEGATION ÇAKIŞMASI
        if s == s_new and o == o_new:
            if r == opposite:
                return True

    return False
