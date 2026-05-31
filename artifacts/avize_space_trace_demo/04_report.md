# Avize Concept Space Trace Demo

This report shows which data was pulled from which spaces and confidence values.

## Space Buckets
- attention: facts=0 avg_fact_conf=0.0 edges=3 avg_edge_conf=0.3333
- curriculum: facts=2 avg_fact_conf=0.975 edges=0 avg_edge_conf=0.0
- goal: facts=2 avg_fact_conf=0.965 edges=10 avg_edge_conf=0.234
- memory: facts=1 avg_fact_conf=0.95 edges=1 avg_edge_conf=1.0
- self: facts=0 avg_fact_conf=0.0 edges=3 avg_edge_conf=0.3333
- semantic: facts=5 avg_fact_conf=0.966 edges=14 avg_edge_conf=0.9043

## Sample Pulled Facts
- (ev, uses, avize) conf=0.95 spaces=[goal, semantic]
- (avize, used_for, aydinlatma) conf=0.98 spaces=[goal, semantic]
- (avize, contains, ampul) conf=0.96 spaces=[curriculum, semantic]
- (avize, installed_in, salon) conf=0.95 spaces=[memory, semantic]
- (science, knows_concept, avize) conf=0.99 spaces=[curriculum, semantic]
